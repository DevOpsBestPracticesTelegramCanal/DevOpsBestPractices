"""
Week 28: Self-Review Step (CR-01)

After code generation but before validation, this module builds a
self-review prompt that asks the model to review and fix its own code.

Activated for COMPLEX+ complexity tasks only to avoid latency on simple tasks.
The self-review prompt focuses on the most common post-generation issues:
  - Missing error handling on external calls
  - Incomplete implementations (TODO/pass/stub)
  - SQL injection via string formatting
  - Thread safety issues with shared state

Usage:
    from core.generation.self_review import build_self_review_prompt, should_self_review

    if should_self_review(complexity="COMPLEX"):
        review_prompt = build_self_review_prompt(code, original_query)
        # Send review_prompt to LLM, get corrected code back
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

SELF_REVIEW_PROMPT = '''Review the code you just generated for the following task:
"{task_description}"

Check for these issues and fix them IN-PLACE:
1. Missing error handling: every external call (DB, HTTP, file I/O) needs try/except with specific exceptions
2. Incomplete implementations: replace any TODO, pass, NotImplementedError, or "..." stubs with real logic
3. SQL injection: replace any f-string or .format() SQL with parameterized queries (? placeholders)
4. Thread safety: if dict/list/set is shared across threads, add threading.Lock protection
5. Resource leaks: ensure all files, connections, and cursors use context managers (with statement)
6. Missing type hints: add return type annotations to all public functions

Here is the code to review:
```python
{code}
```

Output ONLY the corrected Python source code. No explanations, no markdown fences.'''


def build_self_review_prompt(
    code: str,
    task_description: str = "",
) -> str:
    """Build a self-review prompt for the given generated code.

    Args:
        code: The generated code to review.
        task_description: Original task/query for context.

    Returns:
        A prompt string to send to the LLM for self-review.
    """
    return SELF_REVIEW_PROMPT.format(
        task_description=task_description[:500],
        code=code,
    )


def should_self_review(
    complexity: Optional[str] = None,
    risk_level: Optional[str] = None,
    code_length: int = 0,
) -> bool:
    """Determine if self-review should be applied.

    Self-review adds latency (one extra LLM call), so it's only activated
    for complex or high-risk tasks where the benefit outweighs the cost.

    Args:
        complexity: TRIVIAL, SIMPLE, MODERATE, COMPLEX, CRITICAL.
        risk_level: LOW, MEDIUM, HIGH, CRITICAL.
        code_length: Number of lines in generated code.

    Returns:
        True if self-review should be applied.
    """
    # Always review COMPLEX+ tasks
    if complexity and complexity.upper() in ("COMPLEX", "CRITICAL"):
        return True

    # Review HIGH+ risk regardless of complexity
    if risk_level and risk_level.upper() in ("HIGH", "CRITICAL"):
        return True

    # Review long code (>100 lines) even if moderate complexity
    if code_length > 100 and complexity and complexity.upper() != "TRIVIAL":
        return True

    return False
