# -*- coding: utf-8 -*-
"""
Tests for parallel RuleRunner (code_validator/rules/base.py).

Tests cover:
- Parallel execution produces same results as sequential
- Order is preserved in parallel mode
- fail_fast disables parallelism
- Crash protection works in parallel
- Timing: parallel is faster (or equal) for multiple rules
- Single rule fallback
"""

import os
import sys
import time
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from code_validator.rules.base import Rule, RuleRunner, RuleResult, RuleSeverity
from code_validator.rules.python_validators import (
    ASTSyntaxRule,
    DocstringRule,
    NoForbiddenImportsRule,
    TypeHintRule,
    ComplexityRule,
    CodeLengthRule,
    NoEvalExecRule,
    default_python_rules,
)


GOOD_CODE = '''
def hello() -> str:
    """Return greeting."""
    return "world"
'''

BAD_SYNTAX = "def f(: invalid"


class SlowRule(Rule):
    """A rule that takes a fixed amount of time (for timing tests)."""

    name = "slow_rule"
    severity = RuleSeverity.INFO
    weight = 1.0

    def __init__(self, delay: float = 0.05, rule_name: str = "slow_rule"):
        self.delay = delay
        self.name = rule_name

    def check(self, code: str) -> RuleResult:
        time.sleep(self.delay)
        return self._ok(score=1.0)


class CrashingRule(Rule):
    """A rule that crashes."""

    name = "crasher"
    severity = RuleSeverity.ERROR
    weight = 1.0

    def check(self, code: str) -> RuleResult:
        raise ZeroDivisionError("boom")


class CriticalFailRule(Rule):
    """A rule that always fails with CRITICAL severity."""

    name = "critical_fail"
    severity = RuleSeverity.CRITICAL
    weight = 1.0

    def check(self, code: str) -> RuleResult:
        return self._fail(score=0.0, messages=["Critical failure"])


# ===========================================================================
# Parallel correctness
# ===========================================================================

class TestParallelCorrectness:
    """Verify parallel produces same results as sequential."""

    def test_parallel_same_results_as_sequential(self):
        """Parallel and sequential produce identical results."""
        rules = default_python_rules()
        runner = RuleRunner(rules)

        seq_results = runner.run(GOOD_CODE, parallel=False)
        par_results = runner.run(GOOD_CODE, parallel=True)

        assert len(seq_results) == len(par_results)
        for s, p in zip(seq_results, par_results):
            assert s.rule_name == p.rule_name
            assert s.passed == p.passed
            assert s.score == p.score

    def test_parallel_order_preserved(self):
        """Results maintain rule order in parallel mode."""
        rules = [
            SlowRule(delay=0.05, rule_name="rule_A"),
            SlowRule(delay=0.01, rule_name="rule_B"),  # finishes first
            SlowRule(delay=0.03, rule_name="rule_C"),
        ]
        runner = RuleRunner(rules)
        results = runner.run("x = 1", parallel=True)

        assert [r.rule_name for r in results] == ["rule_A", "rule_B", "rule_C"]

    def test_parallel_all_pass_good_code(self):
        """All validators pass on good code (parallel)."""
        runner = RuleRunner(default_python_rules())
        results = runner.run(GOOD_CODE, parallel=True)
        assert all(r.passed for r in results)

    def test_parallel_detects_bad_syntax(self):
        """AST failure detected in parallel mode."""
        runner = RuleRunner(default_python_rules())
        results = runner.run(BAD_SYNTAX, parallel=True)
        ast_result = next(r for r in results if r.rule_name == "ast_syntax")
        assert not ast_result.passed

    def test_parallel_crash_protection(self):
        """Crashing rule is caught in parallel mode."""
        runner = RuleRunner([ASTSyntaxRule(), CrashingRule()])
        results = runner.run("x = 1", parallel=True)

        assert len(results) == 2
        assert results[0].passed  # AST passes
        assert not results[1].passed  # crasher fails
        assert "crashed" in results[1].messages[0].lower()


# ===========================================================================
# Timing
# ===========================================================================

class TestParallelTiming:
    """Verify parallel is faster than sequential."""

    def test_parallel_faster_than_sequential(self):
        """Parallel with 5 slow rules is faster than sequential."""
        rules = [SlowRule(delay=0.05, rule_name=f"slow_{i}") for i in range(5)]
        runner = RuleRunner(rules)

        # Sequential: ~250ms (5 * 50ms)
        t0 = time.perf_counter()
        runner.run("x = 1", parallel=False)
        seq_time = time.perf_counter() - t0

        # Parallel: ~50ms (all concurrent)
        t0 = time.perf_counter()
        runner.run("x = 1", parallel=True)
        par_time = time.perf_counter() - t0

        # Parallel should be at least 2x faster
        assert par_time < seq_time * 0.7, (
            f"Parallel ({par_time:.3f}s) not faster than sequential ({seq_time:.3f}s)"
        )

    def test_duration_recorded_parallel(self):
        """Each rule has duration recorded in parallel mode."""
        runner = RuleRunner(default_python_rules())
        results = runner.run(GOOD_CODE, parallel=True)
        for r in results:
            assert r.duration >= 0


# ===========================================================================
# fail_fast behavior
# ===========================================================================

class TestFailFast:
    """fail_fast forces sequential mode."""

    def test_fail_fast_stops_early(self):
        """fail_fast=True stops after first CRITICAL failure."""
        runner = RuleRunner([
            CriticalFailRule(),
            SlowRule(delay=0.05, rule_name="should_not_run"),
        ])
        results = runner.run("x = 1", fail_fast=True, parallel=True)
        # fail_fast overrides parallel → sequential → stops after first
        assert len(results) == 1
        assert results[0].rule_name == "critical_fail"

    def test_fail_fast_false_runs_all(self):
        """fail_fast=False runs all rules even with failures."""
        runner = RuleRunner([CriticalFailRule(), ASTSyntaxRule()])
        results = runner.run("x = 1", fail_fast=False, parallel=True)
        assert len(results) == 2


# ===========================================================================
# Edge cases
# ===========================================================================

class TestEdgeCases:
    """Edge cases for parallel runner."""

    def test_empty_rules(self):
        """Empty rule list returns empty results."""
        runner = RuleRunner([])
        assert runner.run("x = 1", parallel=True) == []

    def test_single_rule_works(self):
        """Single rule doesn't use parallelism but still works."""
        runner = RuleRunner([ASTSyntaxRule()])
        results = runner.run(GOOD_CODE, parallel=True)
        assert len(results) == 1
        assert results[0].passed

    def test_parallel_default_is_true(self):
        """Default parallel parameter is True."""
        runner = RuleRunner(default_python_rules())
        # Just verify it works with default args
        results = runner.run(GOOD_CODE)
        assert len(results) == 8  # 8 default rules (incl. OSSPatternRule)
        assert all(r.passed for r in results)
