# -*- coding: utf-8 -*-
"""
Tests for core/static_analyzer.py — StaticAnalyzer stub.
"""

import pytest
from core.static_analyzer import StaticAnalyzer


class TestStaticAnalyzer:
    def test_default_no_ruff(self):
        sa = StaticAnalyzer()
        assert sa.use_ruff is False

    def test_enable_ruff(self):
        sa = StaticAnalyzer(use_ruff=True)
        assert sa.use_ruff is True

    def test_analyze_returns_dict(self):
        sa = StaticAnalyzer()
        result = sa.analyze("x = 1")
        assert isinstance(result, dict)

    def test_analyze_success_true(self):
        sa = StaticAnalyzer()
        result = sa.analyze("x = 1")
        assert result["success"] is True

    def test_analyze_issues_empty(self):
        sa = StaticAnalyzer()
        result = sa.analyze("x = 1")
        assert result["issues"] == []

    def test_analyze_language_default(self):
        sa = StaticAnalyzer()
        result = sa.analyze("x = 1")
        assert result["language"] == "python"

    def test_analyze_language_custom(self):
        sa = StaticAnalyzer()
        result = sa.analyze("fn main() {}", language="rust")
        assert result["language"] == "rust"

    def test_analyze_empty_code(self):
        sa = StaticAnalyzer()
        result = sa.analyze("")
        assert result["success"] is True

    def test_analyze_multiline_code(self):
        code = "def foo():\n    return 42\n"
        sa = StaticAnalyzer()
        result = sa.analyze(code)
        assert result["success"] is True

    def test_analyze_javascript(self):
        sa = StaticAnalyzer()
        result = sa.analyze("const x = 1;", language="javascript")
        assert result["language"] == "javascript"
