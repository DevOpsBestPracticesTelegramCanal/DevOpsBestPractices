"""
Tests for external subprocess validators (ruff, mypy, hadolint).

All subprocess calls are mocked — no real tools needed.
"""

import json
import subprocess
import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from code_validator.rules.external_validators import (
    RuffValidator,
    MypyValidator,
    HadolintValidator,
    default_external_rules,
    python_external_rules,
)
from code_validator.rules.base import RuleSeverity


CLEAN_PYTHON = 'def hello() -> str:\n    """Say hello."""\n    return "hello"\n'


# -----------------------------------------------------------------------
# Ruff
# -----------------------------------------------------------------------

class TestRuffValidator:

    def test_clean_code(self, monkeypatch):
        """Ruff returns 0 — all good."""
        proc = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = RuffValidator().check(CLEAN_PYTHON)
        assert result.passed is True
        assert result.score == 1.0

    def test_with_errors(self, monkeypatch):
        """Ruff finds unfixable errors."""
        issues = [
            {"code": "E501", "message": "Line too long", "location": {"row": 1}, "fix": None},
            {"code": "W291", "message": "Trailing whitespace", "location": {"row": 2}, "fix": {"edits": []}},
        ]
        proc = subprocess.CompletedProcess(
            args=[], returncode=1, stdout=json.dumps(issues), stderr=""
        )
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = RuffValidator().check(CLEAN_PYTHON)
        assert result.passed is False
        assert result.score < 1.0
        assert len(result.messages) >= 1

    def test_all_fixable(self, monkeypatch):
        """Ruff finds only auto-fixable warnings — passes."""
        issues = [
            {"code": "W291", "message": "Trailing whitespace", "location": {"row": 1}, "fix": {"edits": []}},
        ]
        proc = subprocess.CompletedProcess(
            args=[], returncode=1, stdout=json.dumps(issues), stderr=""
        )
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = RuffValidator().check(CLEAN_PYTHON)
        assert result.passed is True  # only warnings, no errors

    def test_not_installed(self, monkeypatch):
        """Ruff not installed — graceful skip."""
        def raise_fnf(*a, **kw):
            raise FileNotFoundError("ruff not found")
        monkeypatch.setattr(subprocess, "run", raise_fnf)

        result = RuffValidator().check(CLEAN_PYTHON)
        assert result.passed is True
        assert "not installed" in result.messages[0]

    def test_timeout(self, monkeypatch):
        """Ruff hangs — timeout handled."""
        def raise_timeout(*a, **kw):
            raise subprocess.TimeoutExpired(cmd="ruff", timeout=10)
        monkeypatch.setattr(subprocess, "run", raise_timeout)

        result = RuffValidator().check(CLEAN_PYTHON)
        assert result.passed is False
        assert "timed out" in result.messages[0]

    def test_bad_json(self, monkeypatch):
        """Ruff outputs garbage — handled gracefully."""
        proc = subprocess.CompletedProcess(args=[], returncode=1, stdout="not json!", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = RuffValidator().check(CLEAN_PYTHON)
        assert result.passed is False
        assert "unparseable" in result.messages[0]


# -----------------------------------------------------------------------
# Mypy
# -----------------------------------------------------------------------

class TestMypyValidator:

    def test_clean_code(self, monkeypatch):
        proc = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = MypyValidator().check(CLEAN_PYTHON)
        assert result.passed is True
        assert result.score == 1.0

    def test_type_errors(self, monkeypatch):
        stdout = (
            "/tmp/qwen_val_abc.py:3: error: Incompatible return [return-value]\n"
            "/tmp/qwen_val_abc.py:5: error: Missing arg [call-arg]\n"
        )
        proc = subprocess.CompletedProcess(args=[], returncode=1, stdout=stdout, stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = MypyValidator().check(CLEAN_PYTHON)
        assert result.passed is False
        assert len(result.messages) == 2

    def test_notes_only(self, monkeypatch):
        """Notes are not errors — passes."""
        stdout = "/tmp/qwen_val_abc.py:1: note: See docs for help\n"
        proc = subprocess.CompletedProcess(args=[], returncode=1, stdout=stdout, stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = MypyValidator().check(CLEAN_PYTHON)
        assert result.passed is True

    def test_not_installed(self, monkeypatch):
        def raise_fnf(*a, **kw):
            raise FileNotFoundError("mypy not found")
        monkeypatch.setattr(subprocess, "run", raise_fnf)

        result = MypyValidator().check(CLEAN_PYTHON)
        assert result.passed is True
        assert "not installed" in result.messages[0]


# -----------------------------------------------------------------------
# Hadolint
# -----------------------------------------------------------------------

DOCKERFILE = "FROM ubuntu:latest\nRUN apt-get update && apt-get install -y curl\n"


class TestHadolintValidator:

    def test_clean_dockerfile(self, monkeypatch):
        proc = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = HadolintValidator().check(DOCKERFILE)
        assert result.passed is True

    def test_with_warnings(self, monkeypatch):
        issues = [
            {"code": "DL3008", "message": "Pin versions", "level": "warning", "line": 2},
        ]
        proc = subprocess.CompletedProcess(
            args=[], returncode=1, stdout=json.dumps(issues), stderr=""
        )
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = HadolintValidator().check(DOCKERFILE)
        assert result.passed is True  # warnings only
        assert result.score < 1.0

    def test_with_errors(self, monkeypatch):
        issues = [
            {"code": "DL3006", "message": "Always tag FROM", "level": "error", "line": 1},
        ]
        proc = subprocess.CompletedProcess(
            args=[], returncode=1, stdout=json.dumps(issues), stderr=""
        )
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: proc)

        result = HadolintValidator().check(DOCKERFILE)
        assert result.passed is False

    def test_not_installed(self, monkeypatch):
        def raise_fnf(*a, **kw):
            raise FileNotFoundError("hadolint not found")
        monkeypatch.setattr(subprocess, "run", raise_fnf)

        result = HadolintValidator().check(DOCKERFILE)
        assert result.passed is True


# -----------------------------------------------------------------------
# Factory functions
# -----------------------------------------------------------------------

def test_default_external_rules():
    rules = default_external_rules()
    assert len(rules) == 3
    names = {r.name for r in rules}
    assert names == {"ruff", "mypy", "hadolint"}


def test_python_external_rules():
    rules = python_external_rules()
    assert len(rules) == 2
    names = {r.name for r in rules}
    assert names == {"ruff", "mypy"}
