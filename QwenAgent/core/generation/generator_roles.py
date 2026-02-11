"""
Week 21: Role-Specialized Generator Prompts

Instead of only varying temperature, each candidate gets a distinct
'role' system prompt that biases toward a different quality dimension.

This produces structurally different solutions:
  - correctness_agent: input validation, edge cases, error handling
  - security_agent: OWASP, no eval/exec, parameterized queries
  - readability_agent: clean code, docstrings, type hints, PEP 8
  - performance_agent: efficient algorithms, memory, data structures

Usage:
    role = get_role_for_candidate(index=0, n=3, complexity="MODERATE")
    system_prompt = build_role_system_prompt(role, base_prompt)
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


@dataclass
class GeneratorRole:
    """A specialized generator persona."""

    name: str
    system_prefix: str
    temperature: float
    priority_validators: List[str]


# ---------------------------------------------------------------------------
# Role definitions
# ---------------------------------------------------------------------------

GENERATOR_ROLES: Dict[str, GeneratorRole] = {
    "correctness": GeneratorRole(
        name="correctness",
        system_prefix=(
            "You are a meticulous code generator focused on CORRECTNESS. "
            "Always add input validation, handle edge cases (empty input, None, "
            "negative numbers), and prefer explicit error handling over assumptions. "
            "Every function must handle its failure modes gracefully."
        ),
        temperature=0.2,
        priority_validators=["ast_syntax", "no_eval_exec", "type_hints"],
    ),
    "security": GeneratorRole(
        name="security",
        system_prefix=(
            "You are a security-focused code generator. Always sanitize inputs, "
            "avoid eval/exec/compile, use parameterized queries for databases, "
            "validate file paths, never hardcode credentials, and follow OWASP "
            "guidelines. Prefer safe defaults over convenience."
        ),
        temperature=0.3,
        priority_validators=["no_eval_exec", "no_forbidden_imports", "ast_syntax"],
    ),
    "readability": GeneratorRole(
        name="readability",
        system_prefix=(
            "You are a code generator focused on READABILITY and MAINTAINABILITY. "
            "Write clean, well-documented code with descriptive variable names, "
            "Google-style docstrings, type hints on every parameter, and logical "
            "structure. Follow PEP 8. Use guard clauses and early returns."
        ),
        temperature=0.4,
        priority_validators=["docstring", "type_hints", "complexity"],
    ),
    "performance": GeneratorRole(
        name="performance",
        system_prefix=(
            "You are a performance-oriented code generator. Use efficient algorithms "
            "and optimal data structures (sets for lookups, deque for queues). "
            "Minimize memory allocation, prefer generators over lists for large data, "
            "and document time/space complexity in docstrings."
        ),
        temperature=0.5,
        priority_validators=["complexity", "ast_syntax"],
    ),
}

# Default role order for each candidate slot
DEFAULT_ROLE_ORDER: List[str] = [
    "correctness",
    "readability",
    "security",
    "performance",
]


# ---------------------------------------------------------------------------
# Complexity → role mapping
# ---------------------------------------------------------------------------

# Which roles to activate based on task complexity
_COMPLEXITY_ROLES: Dict[str, List[str]] = {
    "TRIVIAL": ["correctness"],
    "SIMPLE": ["readability"],
    "MODERATE": ["correctness", "readability"],
    "COMPLEX": ["correctness", "security", "readability"],
    "CRITICAL": ["correctness", "security", "performance"],
}

# Override by task type (optional)
_TASK_TYPE_ROLES: Dict[str, List[str]] = {
    "infrastructure": ["security", "correctness", "readability"],
    "bug_fix": ["correctness", "security"],
    "refactoring": ["readability", "performance"],
    "code_generation": ["correctness", "readability", "security"],
}


def get_roles_for_task(
    n_candidates: int,
    complexity: Optional[str] = None,
    task_type: Optional[str] = None,
) -> List[GeneratorRole]:
    """Select which roles to use for this generation run.

    Args:
        n_candidates: How many candidates will be generated.
        complexity: CodegenComplexity name (TRIVIAL..CRITICAL).
        task_type: TaskType value (code_generation, infrastructure, etc.).

    Returns:
        List of GeneratorRole objects, one per candidate.
    """
    # Determine role names from task type (if available) or complexity
    if task_type and task_type in _TASK_TYPE_ROLES:
        role_names = _TASK_TYPE_ROLES[task_type]
    elif complexity and complexity in _COMPLEXITY_ROLES:
        role_names = _COMPLEXITY_ROLES[complexity]
    else:
        role_names = DEFAULT_ROLE_ORDER

    # Cycle through roles if n_candidates > len(role_names)
    roles = []
    for i in range(n_candidates):
        name = role_names[i % len(role_names)]
        roles.append(GENERATOR_ROLES[name])

    return roles


def get_role_for_candidate(
    index: int,
    n: int,
    complexity: Optional[str] = None,
    task_type: Optional[str] = None,
) -> GeneratorRole:
    """Get the role for a specific candidate index."""
    roles = get_roles_for_task(n, complexity, task_type)
    return roles[index % len(roles)]


def build_role_system_prompt(role: GeneratorRole, base_prompt: str) -> str:
    """Prepend role-specific instructions to the base system prompt.

    The role prefix comes BEFORE the base prompt so the model sees the
    persona first, then the task-type requirements and quality prompts.
    """
    return f"{role.system_prefix}\n\n{base_prompt}"
