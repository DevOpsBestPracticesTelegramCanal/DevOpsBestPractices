"""
Week 22: Engineer 10x Prompt Generator

Generates optimized system prompts that incorporate:
  - "7 deadly sins" of code generation (anti-patterns to avoid)
  - Domain-specific quality requirements
  - Production readiness checklist
  - Security-first principles

Integrates with the existing GeneratorRole system — can be used as
an additional role or as a prompt enhancer applied on top of any role.

Usage:
    from core.generation.engineer_10x import build_10x_prompt, ENGINEER_10X_ROLE

    # As a standalone role
    system = build_role_system_prompt(ENGINEER_10X_ROLE, base_prompt)

    # As a prompt enhancer (add to any system prompt)
    enhanced = build_10x_prompt(base_system_prompt, task_type="python")
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .generator_roles import GeneratorRole

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# 7 Deadly Sins of Code Generation
# ---------------------------------------------------------------------------

DEADLY_SINS = [
    "NEVER return search results, links, or 'see documentation' instead of code.",
    "NEVER use string formatting for SQL queries — always use parameterized queries.",
    "NEVER hardcode secrets, passwords, API keys, or tokens.",
    "NEVER use eval(), exec(), or pickle.loads() on untrusted data.",
    "NEVER ignore error handling — every external call must have try/except.",
    "NEVER use mutable default arguments (def f(items=[])).",
    "NEVER leave TODO/pass stubs — implement the full logic.",
]

# ---------------------------------------------------------------------------
# Domain-specific quality checklists
# ---------------------------------------------------------------------------

_DOMAIN_CHECKLISTS: Dict[str, List[str]] = {
    "python": [
        "Type hints on all parameters and return values",
        "Google-style docstrings with Args/Returns/Raises",
        "Guard clauses for None/empty/invalid inputs",
        "Named constants instead of magic numbers",
        "Logging via logging module, not print()",
    ],
    "fastapi": [
        "response_model on every route",
        "Depends() for dependency injection",
        "Pydantic models for request/response validation",
        "Proper HTTP status codes (201, 400, 404, 409)",
        "OAuth2 with scopes for authentication",
    ],
    "kubernetes": [
        "Stable API versions (apps/v1, not v1beta1)",
        "Resource requests AND limits on every container",
        "Liveness and readiness probes",
        "No :latest image tags — pin specific versions",
        "SecurityContext with drop ALL capabilities",
    ],
    "terraform": [
        "Provider version constraints (required_providers)",
        "Separate resources for S3 bucket configuration (not inline)",
        "Variable validation blocks",
        "Meaningful output descriptions",
        "Tags on all resources",
    ],
    "dockerfile": [
        "Multi-stage build to minimize image size",
        "Non-root USER for security",
        "Specific image tags (not :latest)",
        "HEALTHCHECK instruction",
        "Combined RUN commands to reduce layers",
    ],
    "database": [
        "Parameterized queries ONLY — never string concatenation",
        "Connection pooling (pool_size, max_overflow)",
        "Explicit transaction management",
        "Indexes on frequently queried columns",
        "Migration support (Alembic/Django)",
    ],
}

# ---------------------------------------------------------------------------
# Engineer 10x Role
# ---------------------------------------------------------------------------

ENGINEER_10X_ROLE = GeneratorRole(
    name="engineer_10x",
    system_prefix=(
        "You are an elite 10x engineer generating production-grade code. "
        "Your code is reviewed by senior staff engineers. "
        "Priorities: (1) correctness over cleverness, (2) security by default, "
        "(3) full error handling, (4) type hints and docstrings on everything, "
        "(5) no shortcuts, no stubs, no TODOs. "
        "Write code that ships to production on the first review."
    ),
    temperature=0.25,
    priority_validators=[
        "ast_syntax", "no_eval_exec", "antipattern",
        "promise_checker", "search_guard",
    ],
)


# ---------------------------------------------------------------------------
# Prompt builder
# ---------------------------------------------------------------------------

def build_10x_prompt(
    base_prompt: str,
    task_type: Optional[str] = None,
    include_sins: bool = True,
    include_checklist: bool = True,
) -> str:
    """Enhance a system prompt with 10x engineer quality requirements.

    Args:
        base_prompt: The existing system prompt to enhance.
        task_type: Domain for checklist (python, fastapi, kubernetes, etc.).
        include_sins: Whether to include the 7 deadly sins.
        include_checklist: Whether to include domain checklist.

    Returns:
        Enhanced system prompt string.
    """
    parts = [ENGINEER_10X_ROLE.system_prefix, "", base_prompt]

    if include_sins:
        sins_block = "\n## CRITICAL RULES (violations = automatic rejection):\n"
        for i, sin in enumerate(DEADLY_SINS, 1):
            sins_block += f"{i}. {sin}\n"
        parts.append(sins_block)

    if include_checklist and task_type:
        domain = task_type.lower()
        checklist = _DOMAIN_CHECKLISTS.get(domain)
        if checklist:
            check_block = f"\n## Quality checklist ({domain}):\n"
            for item in checklist:
                check_block += f"- [ ] {item}\n"
            parts.append(check_block)

    return "\n".join(parts)


def get_10x_role() -> GeneratorRole:
    """Return the Engineer 10x role for use in MultiCandidateGenerator."""
    return ENGINEER_10X_ROLE


def should_use_10x(
    complexity: Optional[str] = None,
    task_type: Optional[str] = None,
    risk_level: Optional[str] = None,
) -> bool:
    """Determine if the 10x engineer profile should be activated.

    Activates for:
      - CRITICAL or COMPLEX complexity
      - Infrastructure task type
      - HIGH or CRITICAL risk level

    Args:
        complexity: TRIVIAL, SIMPLE, MODERATE, COMPLEX, CRITICAL
        task_type: TaskType value string
        risk_level: RiskLevel value string

    Returns:
        True if 10x profile should be used.
    """
    if complexity and complexity.upper() in ("CRITICAL", "COMPLEX"):
        return True
    if task_type and task_type.lower() in ("infrastructure", "infra"):
        return True
    if risk_level and risk_level.lower() in ("high", "critical"):
        return True
    return False
