"""
Week 16: DevOps External Validators.

Extends the validation system to cover Kubernetes manifests, Terraform configs,
GitHub Actions workflows, and generic YAML — using kubeval, kube-linter, tflint,
checkov, yamllint, and actionlint.

All validators follow the ExternalRule pattern from external_validators.py:
graceful skip when tool is not installed, 10-second timeout, temp-file lifecycle.
"""

import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
from typing import Dict, List, Optional

from .base import Rule, RuleResult, RuleSeverity
from .external_validators import ExternalRule, SUBPROCESS_TIMEOUT

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Content type detection
# ---------------------------------------------------------------------------

_TERRAFORM_RE = re.compile(
    r'^\s*(?:resource|variable|provider|terraform|module|data|output|locals)\s',
    re.MULTILINE,
)
_DOCKERFILE_RE = re.compile(r'^\s*FROM\s', re.MULTILINE)
_KUBERNETES_RE_API = re.compile(r'^\s*apiVersion\s*:', re.MULTILINE)
_KUBERNETES_RE_KIND = re.compile(r'^\s*kind\s*:', re.MULTILINE)
_GITHUB_ACTIONS_RE_ON = re.compile(r'^\s*on\s*:', re.MULTILINE)
_GITHUB_ACTIONS_RE_JOBS = re.compile(r'^\s*jobs\s*:', re.MULTILINE)
_ANSIBLE_RE_HOSTS = re.compile(r'^\s*-?\s*hosts\s*:', re.MULTILINE)
_ANSIBLE_RE_TASKS = re.compile(r'^\s*tasks\s*:', re.MULTILINE)
_ANSIBLE_RE_GATHER = re.compile(r'^\s*gather_facts\s*:', re.MULTILINE)
_ANSIBLE_RE_BUILTIN = re.compile(r'ansible\.builtin', re.MULTILINE)
_YAML_RE = re.compile(r'^\s*\w[\w\-]*\s*:', re.MULTILINE)
_PYTHON_RE = re.compile(
    r'^\s*(?:def |class |import |from \S+ import )',
    re.MULTILINE,
)


def detect_content_type(code: str) -> str:
    """Detect the type of code/config content via regex heuristics.

    Returns one of: "terraform", "dockerfile", "kubernetes",
    "github_actions", "ansible", "yaml", "python", "unknown".
    """
    if not code or not code.strip():
        return "unknown"

    # Terraform: resource/variable/provider/terraform/module/data/output/locals
    if _TERRAFORM_RE.search(code):
        return "terraform"

    # Dockerfile: starts with FROM
    if _DOCKERFILE_RE.search(code):
        return "dockerfile"

    # Kubernetes: has both apiVersion: and kind:
    if _KUBERNETES_RE_API.search(code) and _KUBERNETES_RE_KIND.search(code):
        return "kubernetes"

    # GitHub Actions: has both on: and jobs:
    if _GITHUB_ACTIONS_RE_ON.search(code) and _GITHUB_ACTIONS_RE_JOBS.search(code):
        return "github_actions"

    # Ansible: hosts/tasks/gather_facts/ansible.builtin
    if (_ANSIBLE_RE_HOSTS.search(code) or _ANSIBLE_RE_GATHER.search(code)
            or _ANSIBLE_RE_BUILTIN.search(code)
            or (_ANSIBLE_RE_TASKS.search(code) and _YAML_RE.search(code))):
        return "ansible"

    # Python: def/class/import/from
    if _PYTHON_RE.search(code):
        return "python"

    # Generic YAML: key-value patterns
    if _YAML_RE.search(code):
        return "yaml"

    return "unknown"


# ---------------------------------------------------------------------------
# yamllint — generic YAML linter
# ---------------------------------------------------------------------------

class YamllintValidator(ExternalRule):
    """Runs ``yamllint -f parsable`` on YAML content."""

    name = "yamllint"
    weight = 1.5

    def _file_suffix(self) -> str:
        return ".yaml"

    def _build_command(self, filepath: str) -> List[str]:
        return ["yamllint", "-f", "parsable", filepath]

    def _parse_output(self, stdout: str, stderr: str, returncode: int) -> RuleResult:
        if returncode == 0:
            return self._ok(1.0)

        lines = [l.strip() for l in stdout.splitlines() if l.strip()]
        errors = [l for l in lines if "[error]" in l]
        warnings = [l for l in lines if "[warning]" in l]

        if not errors and not warnings:
            return self._ok(0.9, [f"yamllint: exit {returncode}, no parseable issues"])

        score = max(0.1, 1.0 - len(errors) * 0.15 - len(warnings) * 0.05)
        passed = len(errors) == 0
        msgs = errors[:5] + warnings[:3]

        return RuleResult(
            rule_name=self.name,
            passed=passed,
            score=round(score, 2),
            severity=RuleSeverity.ERROR if not passed else RuleSeverity.WARNING,
            messages=msgs,
        )


# ---------------------------------------------------------------------------
# kubeval — Kubernetes manifest schema validator
# ---------------------------------------------------------------------------

class KubevalValidator(ExternalRule):
    """Runs ``kubeval --strict --output json`` on Kubernetes manifests."""

    name = "kubeval"
    weight = 2.0

    def _file_suffix(self) -> str:
        return ".yaml"

    def _build_command(self, filepath: str) -> List[str]:
        return ["kubeval", "--strict", "--output", "json", filepath]

    def _parse_output(self, stdout: str, stderr: str, returncode: int) -> RuleResult:
        if returncode == 0:
            # kubeval may still output JSON with status "valid"
            return self._ok(1.0)

        try:
            results = json.loads(stdout) if stdout.strip() else []
        except json.JSONDecodeError:
            return self._fail(0.5, [f"kubeval: unparseable output (exit {returncode})"])

        if not isinstance(results, list):
            results = [results]

        errors = []
        for item in results:
            status = item.get("status", "")
            if status == "invalid":
                for err in item.get("errors", []):
                    errors.append(f"{item.get('filename', '?')}: {err}")

        if not errors:
            return self._ok(0.9)

        score = max(0.1, 1.0 - len(errors) * 0.2)
        msgs = errors[:5]

        return RuleResult(
            rule_name=self.name,
            passed=False,
            score=round(score, 2),
            severity=RuleSeverity.ERROR,
            messages=msgs,
        )


# ---------------------------------------------------------------------------
# kube-linter — Kubernetes best-practice linter
# ---------------------------------------------------------------------------

class KubeLinterValidator(ExternalRule):
    """Runs ``kube-linter lint --format json`` on Kubernetes manifests."""

    name = "kube-linter"
    weight = 1.5

    def _file_suffix(self) -> str:
        return ".yaml"

    def _build_command(self, filepath: str) -> List[str]:
        return ["kube-linter", "lint", "--format", "json", filepath]

    def _parse_output(self, stdout: str, stderr: str, returncode: int) -> RuleResult:
        if returncode == 0:
            return self._ok(1.0)

        try:
            data = json.loads(stdout) if stdout.strip() else {}
        except json.JSONDecodeError:
            return self._fail(0.5, [f"kube-linter: unparseable output (exit {returncode})"])

        reports = data.get("Reports", []) if isinstance(data, dict) else []
        if not reports:
            return self._ok(0.9)

        msgs = []
        for r in reports[:5]:
            check = r.get("Check", "unknown")
            message = r.get("Diagnostic", {}).get("Message", r.get("Message", ""))
            msgs.append(f"{check}: {message}")

        score = max(0.1, 1.0 - len(reports) * 0.1)

        return RuleResult(
            rule_name=self.name,
            passed=False,
            score=round(score, 2),
            severity=RuleSeverity.WARNING,
            messages=msgs,
        )


# ---------------------------------------------------------------------------
# tflint — Terraform linter
# ---------------------------------------------------------------------------

class TflintValidator(ExternalRule):
    """Runs ``tflint --format json`` on Terraform files."""

    name = "tflint"
    weight = 2.0

    def _file_suffix(self) -> str:
        return ".tf"

    def check(self, code: str) -> RuleResult:
        """Override to use --chdir with a temp directory (tflint requirement)."""
        tmpdir = tempfile.mkdtemp(prefix="qwen_tflint_")
        filepath = os.path.join(tmpdir, "main.tf")
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(code)
            return self._run_in_dir(tmpdir)
        finally:
            try:
                shutil.rmtree(tmpdir)
            except OSError:
                pass

    def _run_in_dir(self, dirpath: str) -> RuleResult:
        cmd = ["tflint", "--format", "json", "--chdir", dirpath]
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=SUBPROCESS_TIMEOUT,
            )
            return self._parse_output(proc.stdout, proc.stderr, proc.returncode)
        except FileNotFoundError:
            return self._ok(1.0, [f"{self.name}: tool not installed (skipped)"])
        except subprocess.TimeoutExpired:
            return self._fail(0.5, [f"{self.name}: timed out after {SUBPROCESS_TIMEOUT}s"])

    def _build_command(self, filepath: str) -> List[str]:
        # Not used directly — overridden in check()
        return ["tflint", "--format", "json", filepath]

    def _parse_output(self, stdout: str, stderr: str, returncode: int) -> RuleResult:
        if returncode == 0:
            return self._ok(1.0)

        try:
            data = json.loads(stdout) if stdout.strip() else {}
        except json.JSONDecodeError:
            return self._fail(0.5, [f"tflint: unparseable output (exit {returncode})"])

        issues = data.get("issues", []) if isinstance(data, dict) else []
        if not issues:
            return self._ok(0.9)

        errors = [i for i in issues if i.get("rule", {}).get("severity", "") == "error"]
        warnings = [i for i in issues if i.get("rule", {}).get("severity", "") != "error"]

        msgs = []
        for i in (errors + warnings)[:5]:
            rule_name = i.get("rule", {}).get("name", "unknown")
            message = i.get("message", "")
            msgs.append(f"{rule_name}: {message}")

        score = max(0.1, 1.0 - len(errors) * 0.2 - len(warnings) * 0.05)
        passed = len(errors) == 0

        return RuleResult(
            rule_name=self.name,
            passed=passed,
            score=round(score, 2),
            severity=RuleSeverity.ERROR if not passed else RuleSeverity.WARNING,
            messages=msgs,
        )


# ---------------------------------------------------------------------------
# checkov — Terraform/IaC security scanner
# ---------------------------------------------------------------------------

class CheckovValidator(ExternalRule):
    """Runs ``checkov -f FILE --output json --quiet --compact`` on IaC files."""

    name = "checkov"
    weight = 2.5
    severity = RuleSeverity.ERROR

    def _file_suffix(self) -> str:
        return ".tf"

    def _build_command(self, filepath: str) -> List[str]:
        return ["checkov", "-f", filepath, "--output", "json", "--quiet", "--compact"]

    def _parse_output(self, stdout: str, stderr: str, returncode: int) -> RuleResult:
        if returncode == 0:
            return self._ok(1.0)

        try:
            data = json.loads(stdout) if stdout.strip() else {}
        except json.JSONDecodeError:
            return self._fail(0.5, [f"checkov: unparseable output (exit {returncode})"])

        # checkov output can be a dict or list of dicts
        if isinstance(data, list):
            data = data[0] if data else {}

        results = data.get("results", {})
        failed = results.get("failed_checks", []) if isinstance(results, dict) else []

        if not failed:
            return self._ok(0.9)

        msgs = []
        for check in failed[:5]:
            check_id = check.get("check_id", "?")
            name = check.get("check_name", check.get("name", "?"))
            msgs.append(f"{check_id}: {name}")

        score = max(0.1, 1.0 - len(failed) * 0.15)

        return RuleResult(
            rule_name=self.name,
            passed=False,
            score=round(score, 2),
            severity=RuleSeverity.ERROR,
            messages=msgs,
        )


# ---------------------------------------------------------------------------
# actionlint — GitHub Actions workflow linter
# ---------------------------------------------------------------------------

class ActionlintValidator(ExternalRule):
    """Runs ``actionlint`` on GitHub Actions workflow files."""

    name = "actionlint"
    weight = 2.0

    def _file_suffix(self) -> str:
        return ".yaml"

    def _build_command(self, filepath: str) -> List[str]:
        return ["actionlint", "-format", "{{json .}}", filepath]

    def _parse_output(self, stdout: str, stderr: str, returncode: int) -> RuleResult:
        if returncode == 0:
            return self._ok(1.0)

        # actionlint outputs one JSON object per line
        errors = []
        for line in stdout.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                msg = obj.get("message", str(obj))
                lnum = obj.get("line", "?")
                errors.append(f"line {lnum}: {msg}")
            except json.JSONDecodeError:
                if line:
                    errors.append(line)

        if not errors:
            return self._fail(0.5, [f"actionlint: exit {returncode}, no parseable errors"])

        score = max(0.1, 1.0 - len(errors) * 0.2)
        msgs = errors[:5]

        return RuleResult(
            rule_name=self.name,
            passed=False,
            score=round(score, 2),
            severity=RuleSeverity.ERROR,
            messages=msgs,
        )


# ---------------------------------------------------------------------------
# Factory functions
# ---------------------------------------------------------------------------

def devops_external_rules() -> List[Rule]:
    """Return all DevOps external validators."""
    return [
        YamllintValidator(),
        KubevalValidator(),
        KubeLinterValidator(),
        TflintValidator(),
        CheckovValidator(),
        ActionlintValidator(),
    ]


def kubernetes_rules() -> List[Rule]:
    """Return validators relevant to Kubernetes manifests."""
    return [
        YamllintValidator(),
        KubevalValidator(),
        KubeLinterValidator(),
    ]


def terraform_rules() -> List[Rule]:
    """Return validators relevant to Terraform configs."""
    return [
        TflintValidator(),
        CheckovValidator(),
    ]


def github_actions_rules() -> List[Rule]:
    """Return validators relevant to GitHub Actions workflows."""
    return [
        YamllintValidator(),
        ActionlintValidator(),
    ]


def ansible_rules() -> List[Rule]:
    """Return validators relevant to Ansible playbooks (yamllint for now)."""
    return [
        YamllintValidator(),
    ]


def yaml_rules() -> List[Rule]:
    """Return validators relevant to generic YAML."""
    return [
        YamllintValidator(),
    ]


def rules_for_content_type(content_type: str) -> List[Rule]:
    """Return the appropriate validators for a detected content type."""
    _CONTENT_TYPE_RULES = {
        "kubernetes": kubernetes_rules,
        "terraform": terraform_rules,
        "github_actions": github_actions_rules,
        "ansible": ansible_rules,
        "yaml": yaml_rules,
        "dockerfile": lambda: [],  # hadolint is in external_validators.py
    }
    factory = _CONTENT_TYPE_RULES.get(content_type)
    if factory is not None:
        return factory()
    return []
