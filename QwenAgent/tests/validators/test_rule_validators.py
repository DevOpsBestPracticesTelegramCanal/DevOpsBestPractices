"""Tests for rule-based Python validators."""

import pytest
from code_validator.rules.base import RuleRunner, RuleSeverity
from code_validator.rules.python_validators import (
    ASTSyntaxRule,
    NoForbiddenImportsRule,
    NoEvalExecRule,
    DocstringRule,
    TypeHintRule,
    ComplexityRule,
    CodeLengthRule,
    default_python_rules,
)


# ---------------------------------------------------------------------------
# AST Syntax
# ---------------------------------------------------------------------------

class TestASTSyntax:
    def test_valid_code(self):
        r = ASTSyntaxRule().check("def f(): return 1")
        assert r.passed
        assert r.score == 1.0

    def test_syntax_error(self):
        r = ASTSyntaxRule().check("def f(: return")
        assert not r.passed
        assert r.score == 0.0
        assert "SyntaxError" in r.messages[0]

    def test_empty_code(self):
        r = ASTSyntaxRule().check("")
        assert r.passed  # empty is valid Python

    def test_multiline(self):
        code = "x = 1\ny = 2\nz = x + y"
        r = ASTSyntaxRule().check(code)
        assert r.passed


# ---------------------------------------------------------------------------
# Forbidden Imports
# ---------------------------------------------------------------------------

class TestForbiddenImports:
    def test_clean_code(self):
        r = NoForbiddenImportsRule().check("import json\nimport math")
        assert r.passed

    def test_os_import(self):
        r = NoForbiddenImportsRule().check("import os")
        assert not r.passed
        assert any("os" in m for m in r.messages)

    def test_from_subprocess(self):
        r = NoForbiddenImportsRule().check("from subprocess import run")
        assert not r.passed

    def test_nested_import(self):
        r = NoForbiddenImportsRule().check("import os.path")
        assert not r.passed

    def test_custom_forbidden(self):
        rule = NoForbiddenImportsRule(forbidden={"requests"})
        r = rule.check("import requests")
        assert not r.passed

    def test_syntax_error_skipped(self):
        r = NoForbiddenImportsRule().check("def f(: import os")
        assert r.passed  # skipped because AST fails


# ---------------------------------------------------------------------------
# No eval/exec
# ---------------------------------------------------------------------------

class TestNoEvalExec:
    def test_clean_code(self):
        r = NoEvalExecRule().check("x = int('42')")
        assert r.passed

    def test_eval_detected(self):
        r = NoEvalExecRule().check("result = eval('1+1')")
        assert not r.passed
        assert any("eval" in m for m in r.messages)

    def test_exec_detected(self):
        r = NoEvalExecRule().check("exec('print(1)')")
        assert not r.passed

    def test_compile_detected(self):
        r = NoEvalExecRule().check("c = compile('pass', '<>', 'exec')")
        assert not r.passed

    def test_eval_as_variable_ok(self):
        # Using 'eval' as a variable name (not a call) is fine
        r = NoEvalExecRule().check("eval_result = 42")
        assert r.passed


# ---------------------------------------------------------------------------
# Docstrings
# ---------------------------------------------------------------------------

class TestDocstring:
    def test_all_documented(self):
        code = '''
def hello():
    """Say hello."""
    return "hi"

class Foo:
    """A class."""
    pass
'''
        r = DocstringRule().check(code)
        assert r.passed
        assert r.score == 1.0

    def test_none_documented(self):
        code = "def f(): pass\ndef g(): pass"
        r = DocstringRule().check(code)
        assert not r.passed
        assert r.score == 0.0

    def test_partial_documented(self):
        code = '''
def f():
    """Has one."""
    pass

def g():
    pass
'''
        r = DocstringRule().check(code)
        assert r.passed  # 50% → passes threshold
        assert r.score == 0.5

    def test_no_functions(self):
        r = DocstringRule().check("x = 42")
        assert r.passed
        assert r.score == 1.0


# ---------------------------------------------------------------------------
# Type Hints
# ---------------------------------------------------------------------------

class TestTypeHints:
    def test_all_annotated(self):
        code = "def f(x: int) -> str: return str(x)"
        r = TypeHintRule().check(code)
        assert r.passed
        assert r.score == 1.0

    def test_none_annotated(self):
        code = "def f(x): return str(x)\ndef g(y): return y"
        r = TypeHintRule().check(code)
        assert not r.passed

    def test_private_methods_skipped(self):
        code = "def _helper(): pass"
        r = TypeHintRule().check(code)
        assert r.passed  # private methods are skipped

    def test_init_not_skipped(self):
        code = '''
class Foo:
    def __init__(self):
        pass
'''
        r = TypeHintRule().check(code)
        assert r.passed  # __init__ doesn't need return type


# ---------------------------------------------------------------------------
# Complexity
# ---------------------------------------------------------------------------

class TestComplexity:
    def test_simple_function(self):
        r = ComplexityRule().check("def f(): return 1")
        assert r.passed
        assert r.score >= 0.9

    def test_complex_function(self):
        code = """
def complex():
    if a:
        if b:
            if c:
                for x in range(10):
                    while y:
                        if z:
                            try:
                                pass
                            except A:
                                pass
                            except B:
                                pass
                            except C:
                                pass
                            except D:
                                pass
                            except E:
                                pass
                            except F:
                                pass
                            except G:
                                pass
                            except H:
                                pass
"""
        r = ComplexityRule(max_complexity=10).check(code)
        assert not r.passed

    def test_no_functions(self):
        r = ComplexityRule().check("x = 1")
        assert r.passed


# ---------------------------------------------------------------------------
# Code Length
# ---------------------------------------------------------------------------

class TestCodeLength:
    def test_normal_length(self):
        code = "\n".join([f"x_{i} = {i}" for i in range(50)])
        r = CodeLengthRule().check(code)
        assert r.passed
        assert r.score == 1.0

    def test_empty_code(self):
        r = CodeLengthRule().check("")
        assert not r.passed

    def test_too_long(self):
        code = "\n".join([f"x_{i} = {i}" for i in range(600)])
        r = CodeLengthRule().check(code)
        assert not r.passed

    def test_very_short(self):
        r = CodeLengthRule().check("x = 1")
        assert r.passed
        assert r.score < 1.0  # slight penalty


# ---------------------------------------------------------------------------
# RuleRunner
# ---------------------------------------------------------------------------

class TestRuleRunner:
    def test_run_all_rules(self):
        runner = RuleRunner(default_python_rules())
        code = '''
def hello() -> str:
    """Return greeting."""
    return "world"
'''
        results = runner.run(code)
        assert len(results) == 8  # 8 default rules (incl. OSSPatternRule)
        assert all(r.passed for r in results)

    def test_fail_fast_stops_early(self):
        runner = RuleRunner([
            ASTSyntaxRule(),      # CRITICAL
            DocstringRule(),      # WARNING — should not run
        ])
        results = runner.run("def f(: invalid", fail_fast=True)
        assert len(results) == 1  # stopped after AST failure

    def test_crash_protection(self):
        """Rules that raise are caught and reported."""

        class CrashingRule:
            name = "crasher"
            severity = RuleSeverity.ERROR
            weight = 1.0

            def check(self, code):
                raise ZeroDivisionError("boom")

        runner = RuleRunner([CrashingRule()])
        results = runner.run("x = 1")
        assert len(results) == 1
        assert not results[0].passed
        assert "crashed" in results[0].messages[0].lower()

    def test_add_fluent(self):
        runner = RuleRunner()
        runner.add(ASTSyntaxRule()).add(DocstringRule())
        assert len(runner.rules) == 2

    def test_duration_recorded(self):
        runner = RuleRunner([ASTSyntaxRule()])
        results = runner.run("x = 1")
        assert results[0].duration >= 0
