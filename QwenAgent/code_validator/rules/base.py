"""
Base classes for the rule-based validation system.

A Rule is a single, focused check that runs in-process (no subprocesses).
RuleRunner applies a list of rules to a piece of code and returns
ValidationScore objects compatible with the Candidate data model.
"""

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional

logger = logging.getLogger(__name__)


class RuleSeverity(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class RuleResult:
    """Output of a single rule check."""

    rule_name: str
    passed: bool
    score: float  # 0.0 (worst) to 1.0 (perfect)
    severity: RuleSeverity = RuleSeverity.INFO
    messages: List[str] = field(default_factory=list)
    duration: float = 0.0

    @property
    def errors(self) -> List[str]:
        if not self.passed:
            return self.messages
        return []

    @property
    def warnings(self) -> List[str]:
        if self.passed and self.messages:
            return self.messages
        return []


class Rule(ABC):
    """
    Abstract base for all validation rules.

    Subclasses implement `check(code) -> RuleResult`.
    Rules must be:
        - Fast (< 100ms)
        - Deterministic
        - Side-effect-free
    """

    name: str = "unnamed_rule"
    severity: RuleSeverity = RuleSeverity.ERROR
    weight: float = 1.0  # default importance

    @abstractmethod
    def check(self, code: str) -> RuleResult:
        """Run the rule against *code* and return a result."""
        ...

    def _ok(self, score: float = 1.0, messages: Optional[List[str]] = None) -> RuleResult:
        """Shortcut for a passing result."""
        return RuleResult(
            rule_name=self.name,
            passed=True,
            score=score,
            severity=self.severity,
            messages=messages or [],
        )

    def _fail(self, score: float = 0.0, messages: Optional[List[str]] = None) -> RuleResult:
        """Shortcut for a failing result."""
        return RuleResult(
            rule_name=self.name,
            passed=False,
            score=score,
            severity=self.severity,
            messages=messages or [],
        )


class RuleRunner:
    """
    Applies a list of Rules to code and collects results.

    Usage:
        runner = RuleRunner([ASTSyntaxRule(), DocstringRule(), ...])
        results = runner.run(code)
        # results is List[RuleResult]
    """

    def __init__(self, rules: Optional[List[Rule]] = None):
        self.rules: List[Rule] = rules or []

    def add(self, rule: Rule) -> "RuleRunner":
        self.rules.append(rule)
        return self

    def run(self, code: str, fail_fast: bool = False) -> List[RuleResult]:
        """
        Run all rules against *code*.

        Args:
            code: Python source code string.
            fail_fast: Stop after the first CRITICAL failure.

        Returns:
            List of RuleResult, one per rule.
        """
        results: List[RuleResult] = []

        for rule in self.rules:
            t0 = time.perf_counter()
            try:
                result = rule.check(code)
            except Exception as exc:
                logger.error("Rule %s crashed: %s", rule.name, exc)
                result = RuleResult(
                    rule_name=rule.name,
                    passed=False,
                    score=0.0,
                    severity=RuleSeverity.CRITICAL,
                    messages=[f"Rule crashed: {exc}"],
                )

            result.duration = time.perf_counter() - t0
            results.append(result)

            if (
                fail_fast
                and not result.passed
                and result.severity == RuleSeverity.CRITICAL
            ):
                logger.info("fail_fast: stopping after %s", rule.name)
                break

        return results
