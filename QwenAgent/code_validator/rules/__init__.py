"""
Pluggable Rule-Based Validators for Multi-Candidate scoring.

In-process rules are lightweight and fast (no subprocess).
External rules shell out to CLI tools (ruff, mypy, hadolint) for deeper checks.
DevOps rules (Week 16) cover Kubernetes, Terraform, GitHub Actions, and YAML.
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
from .devops_validators import (
    YamllintValidator,
    KubevalValidator,
    KubeLinterValidator,
    TflintValidator,
    CheckovValidator,
    ActionlintValidator,
    detect_content_type,
    devops_external_rules,
    kubernetes_rules,
    terraform_rules,
    ansible_rules,
    github_actions_rules,
    yaml_rules,
    rules_for_content_type,
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
    # devops (Week 16)
    "YamllintValidator",
    "KubevalValidator",
    "KubeLinterValidator",
    "TflintValidator",
    "CheckovValidator",
    "ActionlintValidator",
    "detect_content_type",
    "devops_external_rules",
    "kubernetes_rules",
    "terraform_rules",
    "ansible_rules",
    "github_actions_rules",
    "yaml_rules",
    "rules_for_content_type",
]
