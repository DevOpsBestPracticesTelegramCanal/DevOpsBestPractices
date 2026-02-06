"""
Pluggable Rule-Based Validators for Multi-Candidate scoring.

Each rule returns a ValidationScore that feeds into the CandidateSelector.
Rules are lightweight and fast (no LLM, no subprocess).
"""

from .base import Rule, RuleResult, RuleSeverity, RuleRunner
from .python_validators import (
    ASTSyntaxRule,
    NoForbiddenImportsRule,
    DocstringRule,
    TypeHintRule,
    ComplexityRule,
    CodeLengthRule,
)

__all__ = [
    "Rule",
    "RuleResult",
    "RuleSeverity",
    "RuleRunner",
    "ASTSyntaxRule",
    "NoForbiddenImportsRule",
    "DocstringRule",
    "TypeHintRule",
    "ComplexityRule",
    "CodeLengthRule",
]
