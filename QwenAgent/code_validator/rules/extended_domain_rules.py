"""
Week 22: Extended Domain Rules

Domain-specific validation for common frameworks and patterns:
  - FastAPI: OAuth2 scopes, dependency injection, response_model
  - Dockerfile: multi-stage builds, non-root user, HEALTHCHECK
  - REST API: pagination, proper status codes, input validation
  - Database: connection pooling, transaction management
"""

import re
from typing import Dict, List, Tuple
from .base import Rule, RuleResult, RuleSeverity


# ---------------------------------------------------------------------------
# Domain detection
# ---------------------------------------------------------------------------

def _detect_domain(code: str) -> str:
    """Detect the primary domain of the code."""
    lower = code.lower()

    if "fastapi" in lower or "from fastapi" in lower:
        return "fastapi"
    if lower.lstrip().startswith("from ") and "dockerfile" not in lower:
        pass  # continue checking
    if re.search(r'^\s*FROM\s+\w', code, re.MULTILINE):
        return "dockerfile"
    if "flask" in lower or "from flask" in lower:
        return "flask"
    if "sqlalchemy" in lower or "from sqlalchemy" in lower:
        return "database"
    if "django" in lower or "from django" in lower:
        return "django"
    return "generic"


# ---------------------------------------------------------------------------
# Per-domain checks
# ---------------------------------------------------------------------------

_FASTAPI_CHECKS: List[Tuple[str, re.Pattern, float, str]] = [
    (
        "missing_response_model",
        re.compile(r'@app\.(?:get|post|put|patch|delete)\s*\(\s*["\'][^"\']+["\']\s*\)'),
        0.15,
        "FastAPI route without response_model: add response_model=Schema for validation",
    ),
    (
        "no_depends",
        re.compile(r'def\s+\w+\([^)]*\)\s*(?:->|:)'),
        0.0,  # Only flagged if no Depends() found anywhere
        "FastAPI: consider using Depends() for dependency injection",
    ),
    (
        "oauth2_no_scopes",
        re.compile(r'OAuth2PasswordBearer\s*\('),
        0.1,
        "OAuth2PasswordBearer without scopes: add scopes for fine-grained access control",
    ),
]

_DOCKERFILE_CHECKS: List[Tuple[str, re.Pattern, float, str, re.Pattern]] = [
    (
        "no_multistage",
        re.compile(r'^\s*FROM\s+', re.MULTILINE),
        0.15,
        "Dockerfile without multi-stage build: use 'FROM ... AS builder' to reduce image size",
        re.compile(r'FROM\s+\S+\s+AS\s+', re.IGNORECASE | re.MULTILINE),
    ),
    (
        "no_user",
        re.compile(r'^\s*FROM\s+', re.MULTILINE),
        0.15,
        "Dockerfile runs as root: add 'USER nonroot' for security",
        re.compile(r'^\s*USER\s+(?!root)', re.MULTILINE),
    ),
    (
        "latest_tag",
        re.compile(r'FROM\s+\S+:latest\b', re.MULTILINE),
        0.2,
        "Dockerfile uses :latest tag: pin to a specific version for reproducibility",
        None,  # No positive pattern; presence of regex = fail
    ),
    (
        "no_healthcheck",
        re.compile(r'^\s*FROM\s+', re.MULTILINE),
        0.1,
        "Dockerfile without HEALTHCHECK: add health monitoring",
        re.compile(r'^\s*HEALTHCHECK\s+', re.MULTILINE),
    ),
]

_REST_CHECKS: List[Tuple[str, re.Pattern, float, str]] = [
    (
        "no_pagination",
        re.compile(r'\.(?:get|route)\s*\(\s*["\'].*(?:list|all|index)'),
        0.1,
        "List endpoint without pagination: add page/per_page parameters",
    ),
    (
        "generic_500",
        re.compile(r'(?:status_code\s*=\s*500|raise\s+HTTPException\s*\(\s*500)'),
        0.1,
        "Returning 500 directly: use specific status codes (400, 404, 409) for client errors",
    ),
]


class ExtendedDomainRule(Rule):
    """Domain-specific validation for FastAPI, Dockerfile, REST patterns.

    Auto-detects the domain from code content and applies relevant checks.
    """

    name = "extended_domain"
    severity = RuleSeverity.WARNING
    weight = 1.5

    def check(self, code: str) -> RuleResult:
        if not code or not code.strip():
            return self._ok(1.0)

        domain = _detect_domain(code)
        messages: List[str] = []
        penalty = 0.0

        if domain == "fastapi":
            msgs, pen = self._check_fastapi(code)
            messages.extend(msgs)
            penalty += pen
        elif domain == "dockerfile":
            msgs, pen = self._check_dockerfile(code)
            messages.extend(msgs)
            penalty += pen

        # REST checks apply to fastapi, flask, django
        if domain in ("fastapi", "flask", "django"):
            msgs, pen = self._check_rest(code)
            messages.extend(msgs)
            penalty += pen

        # Database checks
        if domain == "database":
            msgs, pen = self._check_database(code)
            messages.extend(msgs)
            penalty += pen

        score = max(0.0, 1.0 - penalty)
        passed = score >= 0.5

        if not messages:
            return self._ok(1.0)
        return RuleResult(
            rule_name=self.name,
            passed=passed,
            score=round(score, 2),
            severity=self.severity,
            messages=messages,
        )

    @staticmethod
    def _check_fastapi(code: str) -> Tuple[List[str], float]:
        messages: List[str] = []
        penalty = 0.0

        for name, pattern, weight, msg in _FASTAPI_CHECKS:
            if name == "no_depends":
                # Only flag if routes exist but no Depends() at all
                has_routes = re.search(r'@app\.(?:get|post|put|patch|delete)', code)
                has_depends = "Depends(" in code
                if has_routes and not has_depends and len(code.splitlines()) > 20:
                    messages.append(f"[{name}] {msg}")
                    penalty += 0.1
                continue

            if name == "oauth2_no_scopes":
                if pattern.search(code) and "scopes" not in code:
                    messages.append(f"[{name}] {msg}")
                    penalty += weight
                continue

            if name == "missing_response_model":
                matches = pattern.findall(code)
                with_model = len(re.findall(r'response_model\s*=', code))
                if matches and with_model == 0:
                    messages.append(f"[{name}] {msg}")
                    penalty += weight
                continue

        return messages, penalty

    @staticmethod
    def _check_dockerfile(code: str) -> Tuple[List[str], float]:
        messages: List[str] = []
        penalty = 0.0

        for name, trigger, weight, msg, positive in _DOCKERFILE_CHECKS:
            if not trigger.search(code):
                continue
            if positive is not None:
                # Positive pattern = good practice. Missing = problem.
                if not positive.search(code):
                    messages.append(f"[{name}] {msg}")
                    penalty += weight
            else:
                # No positive pattern: trigger itself is the problem
                messages.append(f"[{name}] {msg}")
                penalty += weight

        return messages, penalty

    @staticmethod
    def _check_rest(code: str) -> Tuple[List[str], float]:
        messages: List[str] = []
        penalty = 0.0

        for name, pattern, weight, msg in _REST_CHECKS:
            if pattern.search(code):
                messages.append(f"[{name}] {msg}")
                penalty += weight

        return messages, penalty

    @staticmethod
    def _check_database(code: str) -> Tuple[List[str], float]:
        messages: List[str] = []
        penalty = 0.0

        # Check for raw SQL string concatenation
        if re.search(r'execute\s*\(\s*f["\']', code):
            messages.append(
                "[sql_format] f-string in execute(): use parameterized queries"
            )
            penalty += 0.3

        # Check for missing connection pooling
        if "create_engine" in code and "pool_size" not in code:
            messages.append(
                "[no_pool] create_engine without pool_size: add pool_size for production"
            )
            penalty += 0.1

        return messages, penalty
