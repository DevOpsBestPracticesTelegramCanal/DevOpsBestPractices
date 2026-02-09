"""
External subprocess validators (ruff, mypy, hadolint).

These run real CLI tools via subprocess.run() and parse their output.
If a tool is not installed, the rule passes with an INFO message (graceful skip).
Timeout: 10 seconds per invocation.

Unlike the in-process Python rules, these are slower (~1-3s each) but catch
issues that static AST analysis cannot (linting style, type errors, Dockerfile best practices).
"""

import json
import logging
import os
import subprocess
import tempfile
from abc import abstractmethod
from typing import List, Optional

from .base import Rule, RuleResult, RuleSeverity

logger = logging.getLogger(__name__)

SUBPROCESS_TIMEOUT = 10  # seconds


class ExternalRule(Rule):
    """
    Base class for validators that shell out to an external CLI tool.

    Subclasses must implement:
        - _build_command(filepath) -> List[str]
        - _parse_output(stdout, stderr, returncode) -> RuleResult
        - _file_suffix() -> str  (e.g. ".py")

    Per-rule timeout: set ``timeout`` class attribute to override the default.
    Week 17: configurable per-rule timeouts (fast=2s, medium=5s, slow=15s).
    """

    severity = RuleSeverity.WARNING
    weight = 1.0
    timeout: int = SUBPROCESS_TIMEOUT  # per-rule override (seconds)

    def check(self, code: str) -> RuleResult:
        suffix = self._file_suffix()
        fd, path = tempfile.mkstemp(suffix=suffix, prefix="qwen_val_")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(code)
            return self._run(path)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass

    @property
    def effective_timeout(self) -> int:
        """Return the timeout this rule uses (per-rule or global default)."""
        return self.timeout

    def _run(self, filepath: str) -> RuleResult:
        cmd = self._build_command(filepath)
        t = self.effective_timeout
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=t,
            )
            return self._parse_output(proc.stdout, proc.stderr, proc.returncode)
        except FileNotFoundError:
            return self._ok(1.0, [f"{self.name}: tool not installed (skipped)"])
        except subprocess.TimeoutExpired:
            return self._fail(0.5, [f"{self.name}: timed out after {t}s"])

    @abstractmethod
    def _build_command(self, filepath: str) -> List[str]:
        ...

    @abstractmethod
    def _parse_output(self, stdout: str, stderr: str, returncode: int) -> RuleResult:
        ...

    def _file_suffix(self) -> str:
        return ".txt"


# ---------------------------------------------------------------------------
# Ruff — fast Python linter
# ---------------------------------------------------------------------------

class RuffValidator(ExternalRule):
    """Runs ``ruff check`` and reports errors/warnings."""

    name = "ruff"
    weight = 2.0

    def _file_suffix(self) -> str:
        return ".py"

    def _build_command(self, filepath: str) -> List[str]:
        return ["ruff", "check", "--output-format=json", "--no-fix", filepath]

    def _parse_output(self, stdout: str, stderr: str, returncode: int) -> RuleResult:
        if returncode == 0:
            return self._ok(1.0)

        try:
            issues = json.loads(stdout) if stdout.strip() else []
        except json.JSONDecodeError:
            return self._fail(0.5, [f"ruff: non-zero exit ({returncode}), unparseable output"])

        errors = [
            f"{i['code']}: {i['message']} (line {i['location']['row']})"
            for i in issues
            if i.get("fix") is None  # unfixable = real error
        ]
        warnings = [
            f"{i['code']}: {i['message']} (line {i['location']['row']})"
            for i in issues
            if i.get("fix") is not None
        ]

        total = len(errors) + len(warnings)
        if total == 0:
            return self._ok(0.9)

        score = max(0.1, 1.0 - len(errors) * 0.15 - len(warnings) * 0.05)
        passed = len(errors) == 0
        msgs = [f"Errors: {e}" for e in errors[:5]] + [f"Warnings: {w}" for w in warnings[:3]]

        return RuleResult(
            rule_name=self.name,
            passed=passed,
            score=round(score, 2),
            severity=RuleSeverity.ERROR if not passed else RuleSeverity.WARNING,
            messages=msgs,
        )


# ---------------------------------------------------------------------------
# Mypy — Python type checker
# ---------------------------------------------------------------------------

class MypyValidator(ExternalRule):
    """Runs ``mypy`` and reports type errors."""

    name = "mypy"
    weight = 1.5

    def _file_suffix(self) -> str:
        return ".py"

    def _build_command(self, filepath: str) -> List[str]:
        return [
            "mypy",
            "--no-error-summary",
            "--show-error-codes",
            "--ignore-missing-imports",
            filepath,
        ]

    def _parse_output(self, stdout: str, stderr: str, returncode: int) -> RuleResult:
        if returncode == 0:
            return self._ok(1.0)

        lines = [l for l in stdout.splitlines() if l.strip()]
        errors = [l for l in lines if ": error" in l]
        notes = [l for l in lines if ": note" in l]

        if not errors:
            return self._ok(0.9, [f"mypy: {len(notes)} notes"])

        score = max(0.1, 1.0 - len(errors) * 0.2)
        msgs = [e.split("/")[-1] if "/" in e else e for e in errors[:5]]

        return RuleResult(
            rule_name=self.name,
            passed=False,
            score=round(score, 2),
            severity=RuleSeverity.WARNING,
            messages=msgs,
        )


# ---------------------------------------------------------------------------
# Hadolint — Dockerfile linter
# ---------------------------------------------------------------------------

class HadolintValidator(ExternalRule):
    """Runs ``hadolint`` on Dockerfile content."""

    name = "hadolint"
    weight = 2.0

    def _file_suffix(self) -> str:
        return ".Dockerfile"

    def _build_command(self, filepath: str) -> List[str]:
        return ["hadolint", "--format", "json", filepath]

    def _parse_output(self, stdout: str, stderr: str, returncode: int) -> RuleResult:
        if returncode == 0:
            return self._ok(1.0)

        try:
            issues = json.loads(stdout) if stdout.strip() else []
        except json.JSONDecodeError:
            return self._fail(0.5, [f"hadolint: unparseable output"])

        errors = [i for i in issues if i.get("level") == "error"]
        warnings = [i for i in issues if i.get("level") == "warning"]
        infos = [i for i in issues if i.get("level") == "info"]

        if not errors and not warnings:
            return self._ok(0.9, [f"hadolint: {len(infos)} info messages"])

        score = max(0.1, 1.0 - len(errors) * 0.2 - len(warnings) * 0.1)
        passed = len(errors) == 0
        msgs = (
            [f"{e['code']}: {e['message']} (line {e['line']})" for e in errors[:3]]
            + [f"{w['code']}: {w['message']} (line {w['line']})" for w in warnings[:3]]
        )

        return RuleResult(
            rule_name=self.name,
            passed=passed,
            score=round(score, 2),
            severity=RuleSeverity.ERROR if not passed else RuleSeverity.WARNING,
            messages=msgs,
        )


# ---------------------------------------------------------------------------
# Convenience
# ---------------------------------------------------------------------------

def default_external_rules() -> List[Rule]:
    """Return the standard set of external validators."""
    return [
        RuffValidator(),
        MypyValidator(),
        HadolintValidator(),
    ]


def python_external_rules() -> List[Rule]:
    """Return only Python-relevant external validators (no hadolint)."""
    return [
        RuffValidator(),
        MypyValidator(),
    ]
