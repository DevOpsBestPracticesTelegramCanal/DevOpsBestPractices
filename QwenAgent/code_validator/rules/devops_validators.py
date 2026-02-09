"""
Week 16-17: DevOps External Validators.

Extends the validation system to cover Kubernetes manifests, Terraform configs,
GitHub Actions workflows, Ansible playbooks, Helm charts, Bash scripts,
Docker Compose files, and generic YAML.

Week 16: kubeval, kube-linter, tflint, checkov, yamllint, actionlint.
Week 17: ansible-lint, shellcheck, helm lint, docker-compose validation,
         per-rule timeout configuration.

All validators follow the ExternalRule pattern from external_validators.py:
graceful skip when tool is not installed, configurable timeout, temp-file lifecycle.
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
# Week 17: Helm chart templates
_HELM_RE_VALUES = re.compile(r'\{\{.*\.Values\.', re.MULTILINE)
_HELM_RE_RELEASE = re.compile(r'\{\{.*\.Release\.', re.MULTILINE)
_HELM_RE_CHART = re.compile(r'\{\{.*\.Chart\.', re.MULTILINE)
_HELM_RE_CAPABILITIES = re.compile(r'\{\{.*\.Capabilities\.', re.MULTILINE)
_HELM_RE_INCLUDE = re.compile(r'\{\{-?\s*include\s+', re.MULTILINE)
_HELM_RE_RANGE = re.compile(r'\{\{-?\s*range\s+', re.MULTILINE)
_HELM_RE_TOYAML = re.compile(r'\{\{-?\s*toYaml\s+', re.MULTILINE)
# Week 17: Bash/shell scripts
_BASH_RE_SHEBANG = re.compile(r'^#!\s*/(?:usr/)?bin/(?:ba)?sh', re.MULTILINE)
_BASH_RE_FUNCTION = re.compile(r'^\s*function\s+\w+', re.MULTILINE)
_BASH_RE_IF_BRACKET = re.compile(r'^\s*if\s+\[\[', re.MULTILINE)
_BASH_RE_FOR_IN = re.compile(r'^\s*for\s+\w+\s+in\s', re.MULTILINE)
_BASH_RE_CASE = re.compile(r'^\s*case\s+.*\s+in\s*$', re.MULTILINE)
_BASH_RE_PARAM_EXP = re.compile(r'\$\{[A-Za-z_]\w*', re.MULTILINE)
# Week 17: Docker Compose
_COMPOSE_RE_SERVICES = re.compile(r'^\s*services\s*:', re.MULTILINE)
_COMPOSE_RE_IMAGE = re.compile(r'^\s+image\s*:', re.MULTILINE)
_COMPOSE_RE_BUILD = re.compile(r'^\s+build\s*:', re.MULTILINE)
_COMPOSE_RE_VOLUMES = re.compile(r'^\s*volumes\s*:', re.MULTILINE)
_YAML_RE = re.compile(r'^\s*\w[\w\-]*\s*:', re.MULTILINE)
_PYTHON_RE = re.compile(
    r'^\s*(?:def |class |import |from \S+ import )',
    re.MULTILINE,
)


def detect_content_type(code: str) -> str:
    """Detect the type of code/config content via regex heuristics.

    Returns one of: "terraform", "dockerfile", "helm", "kubernetes",
    "github_actions", "ansible", "bash", "docker_compose",
    "yaml", "python", "unknown".
    """
    if not code or not code.strip():
        return "unknown"

    # Terraform: resource/variable/provider/terraform/module/data/output/locals
    if _TERRAFORM_RE.search(code):
        return "terraform"

    # Dockerfile: starts with FROM
    if _DOCKERFILE_RE.search(code):
        return "dockerfile"

    # Bash/Shell: shebang or strong bash patterns (before YAML checks)
    if _BASH_RE_SHEBANG.search(code):
        return "bash"

    # Helm templates: {{ .Values. }}, {{ .Release. }}, etc. (before K8s check)
    helm_matches = sum(1 for rx in (
        _HELM_RE_VALUES, _HELM_RE_RELEASE, _HELM_RE_CHART,
        _HELM_RE_CAPABILITIES, _HELM_RE_INCLUDE, _HELM_RE_RANGE,
        _HELM_RE_TOYAML,
    ) if rx.search(code))
    if helm_matches >= 1:
        return "helm"

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

    # Docker Compose: services: + (image: or build:)
    if (_COMPOSE_RE_SERVICES.search(code)
            and (_COMPOSE_RE_IMAGE.search(code) or _COMPOSE_RE_BUILD.search(code))):
        return "docker_compose"

    # Bash patterns (weaker heuristic — function/if/for/case + param expansion)
    bash_score = sum(1 for rx in (
        _BASH_RE_FUNCTION, _BASH_RE_IF_BRACKET,
        _BASH_RE_FOR_IN, _BASH_RE_CASE,
    ) if rx.search(code))
    if bash_score >= 2 or (bash_score >= 1 and _BASH_RE_PARAM_EXP.search(code)):
        return "bash"

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
# Week 17: ansible-lint — specialized Ansible linter
# ---------------------------------------------------------------------------

class AnsibleLintValidator(ExternalRule):
    """Runs ``ansible-lint --parseable`` on Ansible playbooks.

    Catches 20+ Ansible-specific issues that yamllint cannot detect:
    E208 (file permissions), E301 (commands), E403 (package latest), etc.
    """

    name = "ansible-lint"
    weight = 2.0
    timeout = 15  # ansible-lint is slow (loads rules)

    def _file_suffix(self) -> str:
        return ".yml"

    def _build_command(self, filepath: str) -> List[str]:
        return ["ansible-lint", "--parseable", "--nocolor", "-q", filepath]

    def _parse_output(self, stdout: str, stderr: str, returncode: int) -> RuleResult:
        if returncode == 0:
            return self._ok(1.0)

        # ansible-lint parseable format:
        # filename:line: [EXXXX] message
        lines = [l.strip() for l in (stdout + stderr).splitlines() if l.strip()]
        errors = []
        warnings = []
        for line in lines:
            match = re.match(r'.*:(\d+):\s*\[([EW]\d+)\]\s*(.*)', line)
            if match:
                lineno, code, msg = match.groups()
                entry = f"Line {lineno}: [{code}] {msg}"
                if code.startswith("E"):
                    errors.append(entry)
                else:
                    warnings.append(entry)
            elif line and not line.startswith("WARNING"):
                # Non-standard lines — treat as warnings
                warnings.append(line)

        if not errors and not warnings:
            return self._ok(0.9, [f"ansible-lint: exit {returncode}, no parseable issues"])

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
# Week 17: shellcheck — Bash/Shell script linter
# ---------------------------------------------------------------------------

class ShellCheckValidator(ExternalRule):
    """Runs ``shellcheck -f json`` on Bash/Shell scripts.

    Catches quoting errors (SC2086), deprecated syntax (SC2006),
    unused variables, and 100+ other shell scripting issues.
    """

    name = "shellcheck"
    weight = 2.0
    timeout = 5  # shellcheck is fast

    def _file_suffix(self) -> str:
        return ".sh"

    def _build_command(self, filepath: str) -> List[str]:
        return ["shellcheck", "-f", "json", filepath]

    def _parse_output(self, stdout: str, stderr: str, returncode: int) -> RuleResult:
        if returncode == 0:
            return self._ok(1.0)

        try:
            issues = json.loads(stdout) if stdout.strip() else []
        except json.JSONDecodeError:
            return self._fail(0.5, [f"shellcheck: unparseable output (exit {returncode})"])

        if not isinstance(issues, list):
            return self._fail(0.5, [f"shellcheck: unexpected output format"])

        errors = [i for i in issues if i.get("level") == "error"]
        warnings = [i for i in issues if i.get("level") == "warning"]
        infos = [i for i in issues if i.get("level") in ("info", "style")]

        if not errors and not warnings:
            if infos:
                return self._ok(0.9, [f"shellcheck: {len(infos)} style suggestions"])
            return self._ok(0.9, [f"shellcheck: exit {returncode}, no issues"])

        msgs = []
        for i in (errors + warnings)[:5]:
            sc_code = i.get("code", "?")
            msg = i.get("message", "?")
            line = i.get("line", "?")
            msgs.append(f"Line {line}: SC{sc_code} - {msg}")

        score = max(0.1, 1.0 - len(errors) * 0.2 - len(warnings) * 0.1)
        passed = len(errors) == 0

        return RuleResult(
            rule_name=self.name,
            passed=passed,
            score=round(score, 2),
            severity=RuleSeverity.ERROR if not passed else RuleSeverity.WARNING,
            messages=msgs,
        )


# ---------------------------------------------------------------------------
# Week 17: helm lint — Helm chart template validator
# ---------------------------------------------------------------------------

class HelmLintValidator(ExternalRule):
    """Runs ``helm lint --strict`` on Helm chart templates.

    Creates a minimal chart structure in a temp directory,
    writes the template, and validates with helm lint.
    """

    name = "helm-lint"
    weight = 1.5
    timeout = 15  # helm lint can be slow (template rendering)

    def _file_suffix(self) -> str:
        return ".yaml"

    def check(self, code: str) -> RuleResult:
        """Override to create minimal Helm chart structure."""
        tmpdir = tempfile.mkdtemp(prefix="qwen_helm_")
        try:
            chart_dir = os.path.join(tmpdir, "chart")
            templates_dir = os.path.join(chart_dir, "templates")
            os.makedirs(templates_dir, exist_ok=True)

            # Minimal Chart.yaml
            chart_yaml = os.path.join(chart_dir, "Chart.yaml")
            with open(chart_yaml, "w", encoding="utf-8") as f:
                f.write("apiVersion: v2\nname: qwen-test\nversion: 0.1.0\n")

            # Write user template
            template_file = os.path.join(templates_dir, "template.yaml")
            with open(template_file, "w", encoding="utf-8") as f:
                f.write(code)

            # Empty values.yaml
            values_file = os.path.join(chart_dir, "values.yaml")
            with open(values_file, "w", encoding="utf-8") as f:
                f.write("{}\n")

            return self._run_helm_lint(chart_dir)
        finally:
            try:
                shutil.rmtree(tmpdir)
            except OSError:
                pass

    def _run_helm_lint(self, chart_dir: str) -> RuleResult:
        cmd = ["helm", "lint", "--strict", chart_dir]
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
        return ["helm", "lint", filepath]

    def _parse_output(self, stdout: str, stderr: str, returncode: int) -> RuleResult:
        if returncode == 0:
            # Check for warnings in successful output
            combined = stdout + stderr
            warn_lines = [l for l in combined.splitlines()
                          if "[WARNING]" in l or "[INFO]" in l]
            if warn_lines:
                return self._ok(0.9, warn_lines[:3])
            return self._ok(1.0)

        combined = stdout + stderr
        lines = [l.strip() for l in combined.splitlines() if l.strip()]
        errors = [l for l in lines if "[ERROR]" in l]
        warnings = [l for l in lines if "[WARNING]" in l]

        if not errors and not warnings:
            return self._fail(0.5, [f"helm lint: exit {returncode}, no parseable issues"])

        score = max(0.1, 1.0 - len(errors) * 0.2 - len(warnings) * 0.05)
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
# Week 17: docker-compose — Docker Compose config validation
# ---------------------------------------------------------------------------

class DockerComposeValidator(ExternalRule):
    """Runs ``docker compose config -q`` to validate Docker Compose files.

    Returns errors for invalid services, missing images, bad volume mounts, etc.
    Falls back to ``docker-compose`` (v1) if ``docker compose`` (v2) not found.
    """

    name = "docker-compose"
    weight = 1.5
    timeout = 10  # docker compose config is moderate speed

    def _file_suffix(self) -> str:
        return ".yaml"

    def _build_command(self, filepath: str) -> List[str]:
        return ["docker", "compose", "-f", filepath, "config", "-q"]

    def check(self, code: str) -> RuleResult:
        """Try docker compose v2 first, fall back to docker-compose v1."""
        suffix = self._file_suffix()
        fd, path = tempfile.mkstemp(suffix=suffix, prefix="qwen_compose_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(code)

            # Try v2 first
            cmd_v2 = ["docker", "compose", "-f", path, "config", "-q"]
            try:
                proc = subprocess.run(
                    cmd_v2,
                    capture_output=True,
                    text=True,
                    timeout=SUBPROCESS_TIMEOUT,
                )
                return self._parse_output(proc.stdout, proc.stderr, proc.returncode)
            except FileNotFoundError:
                pass

            # Fall back to v1
            cmd_v1 = ["docker-compose", "-f", path, "config", "-q"]
            try:
                proc = subprocess.run(
                    cmd_v1,
                    capture_output=True,
                    text=True,
                    timeout=SUBPROCESS_TIMEOUT,
                )
                return self._parse_output(proc.stdout, proc.stderr, proc.returncode)
            except FileNotFoundError:
                return self._ok(1.0, [f"{self.name}: tool not installed (skipped)"])
            except subprocess.TimeoutExpired:
                return self._fail(0.5, [f"{self.name}: timed out after {SUBPROCESS_TIMEOUT}s"])
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    def _parse_output(self, stdout: str, stderr: str, returncode: int) -> RuleResult:
        if returncode == 0:
            return self._ok(1.0)

        # docker compose config outputs errors to stderr
        error_lines = [l.strip() for l in stderr.splitlines() if l.strip()]
        if not error_lines:
            error_lines = [l.strip() for l in stdout.splitlines() if l.strip()]

        if not error_lines:
            return self._fail(0.5, [f"docker-compose: exit {returncode}, no details"])

        msgs = error_lines[:5]
        score = max(0.1, 1.0 - len(msgs) * 0.2)

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
        AnsibleLintValidator(),
        ShellCheckValidator(),
        HelmLintValidator(),
        DockerComposeValidator(),
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
    """Return validators relevant to Ansible playbooks."""
    return [
        YamllintValidator(),
        AnsibleLintValidator(),
    ]


def helm_rules() -> List[Rule]:
    """Return validators relevant to Helm chart templates."""
    return [
        HelmLintValidator(),
    ]


def bash_rules() -> List[Rule]:
    """Return validators relevant to Bash/Shell scripts."""
    return [
        ShellCheckValidator(),
    ]


def docker_compose_rules() -> List[Rule]:
    """Return validators relevant to Docker Compose files."""
    return [
        YamllintValidator(),
        DockerComposeValidator(),
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
        "helm": helm_rules,
        "bash": bash_rules,
        "docker_compose": docker_compose_rules,
        "yaml": yaml_rules,
        "dockerfile": lambda: [],  # hadolint is in external_validators.py
    }
    factory = _CONTENT_TYPE_RULES.get(content_type)
    if factory is not None:
        return factory()
    return []
