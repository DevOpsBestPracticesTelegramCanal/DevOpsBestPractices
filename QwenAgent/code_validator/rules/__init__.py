"""
Pluggable Rule-Based Validators for Multi-Candidate scoring.

In-process rules are lightweight and fast (no subprocess).
External rules shell out to CLI tools (ruff, mypy, hadolint) for deeper checks.
"""

from .base import Rule, RuleResult, RuleSeverity, RuleRunner
from .python_validators import (
    ASTSyntaxRule,
    NoForbiddenImportsRule,
    NoEvalExecRule,
    DocstringRule,
    TypeHintRule,
    ComplexityRule,
    CodeLengthRule,
    default_python_rules,
)
from .external_validators import (
    ExternalRule,
    RuffValidator,
    MypyValidator,
    HadolintValidator,
    default_external_rules,
    python_external_rules,
)

__all__ = [
    # base
    "Rule",
    "RuleResult",
    "RuleSeverity",
    "RuleRunner",
    # in-process
    "ASTSyntaxRule",
    "NoForbiddenImportsRule",
    "NoEvalExecRule",
    "DocstringRule",
    "TypeHintRule",
    "ComplexityRule",
    "CodeLengthRule",
    "default_python_rules",
    # external
    "ExternalRule",
    "RuffValidator",
    "MypyValidator",
    "HadolintValidator",
    "default_external_rules",
    "python_external_rules",
]
