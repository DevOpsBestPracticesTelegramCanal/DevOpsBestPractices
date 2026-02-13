"""
Week 22: Production Readiness Checker

Validates that generated code includes production-essential patterns:
  - Health check endpoints (for web services)
  - Structured logging (not just print())
  - Environment-based configuration (not hardcoded values)
  - Graceful shutdown handling
  - Error response structure

Only applies to code that looks like a web service or application entry point.
"""

import re
from typing import List, Tuple
from .base import Rule, RuleResult, RuleSeverity


def _is_web_service(code: str) -> bool:
    """Detect if code is a web service / application."""
    indicators = [
        r'(?:from\s+)?(?:fastapi|flask|django|starlette|sanic|tornado)',
        r'app\s*=\s*(?:FastAPI|Flask|Django|Sanic)',
        r'uvicorn\.run|app\.run\(',
        r'@app\.(?:route|get|post|put|delete)',
        r'if\s+__name__\s*==\s*["\']__main__["\']',
    ]
    for pattern in indicators:
        if re.search(pattern, code, re.IGNORECASE):
            return True
    return False


def _is_application(code: str) -> bool:
    """Detect if code is an application entry point (not just a library)."""
    return bool(re.search(r'if\s+__name__\s*==\s*["\']__main__["\']', code))


class ProductionReadyRule(Rule):
    """Checks production readiness patterns for web services and applications.

    Only activates for code that looks like a web service or application
    entry point. Library code is not penalized.
    """

    name = "production_ready"
    severity = RuleSeverity.WARNING
    weight = 1.5

    def check(self, code: str) -> RuleResult:
        if not code or not code.strip():
            return self._ok(1.0)

        is_web = _is_web_service(code)
        is_app = _is_application(code)

        # Only check production readiness for services/apps
        if not is_web and not is_app:
            return self._ok(1.0, ["Not a web service or application — skipped"])

        messages: List[str] = []
        penalty = 0.0

        if is_web:
            msgs, pen = self._check_web_service(code)
            messages.extend(msgs)
            penalty += pen

        if is_app or is_web:
            msgs, pen = self._check_general(code)
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
    def _check_web_service(code: str) -> Tuple[List[str], float]:
        messages: List[str] = []
        penalty = 0.0

        # Health endpoint
        has_health = bool(re.search(
            r'''(?:/health|/ready|/live|/status|healthcheck|health_check)''',
            code, re.IGNORECASE,
        ))
        if not has_health:
            messages.append(
                "[no_health] No health check endpoint: add /health or /ready for orchestrators"
            )
            penalty += 0.15

        # CORS configuration (if it's a web API)
        has_routes = bool(re.search(r'@app\.(?:get|post|route)', code))
        has_cors = bool(re.search(r'(?:CORS|CORSMiddleware|cors)', code))
        if has_routes and not has_cors:
            messages.append(
                "[no_cors] No CORS configuration: add CORSMiddleware for cross-origin access"
            )
            penalty += 0.1

        # Debug mode in run
        if re.search(r'\.run\s*\([^)]*debug\s*=\s*True', code):
            messages.append(
                "[debug_mode] debug=True in production: use env variable for debug flag"
            )
            penalty += 0.15

        return messages, penalty

    @staticmethod
    def _check_general(code: str) -> Tuple[List[str], float]:
        messages: List[str] = []
        penalty = 0.0

        # Logging vs print
        has_logging = bool(re.search(
            r'(?:import\s+logging|logging\.getLogger|logger\s*=)',
            code,
        ))
        has_print = bool(re.search(r'\bprint\s*\(', code))
        if has_print and not has_logging:
            messages.append(
                "[print_not_log] Using print() instead of logging: "
                "use logging module for production observability"
            )
            penalty += 0.1

        # Environment config
        has_env = bool(re.search(
            r'(?:os\.environ|os\.getenv|environ\.get|\.env|dotenv|settings\.\w+)',
            code,
        ))
        has_hardcoded = bool(re.search(
            r'''(?:host\s*=\s*["\']\d+\.\d+|port\s*=\s*\d{4}|'''
            r'''(?:db_url|database_url|connection_string)\s*=\s*["\'])''',
            code, re.IGNORECASE,
        ))
        if has_hardcoded and not has_env:
            messages.append(
                "[hardcoded_config] Hardcoded host/port/db_url: use environment variables"
            )
            penalty += 0.1

        # Graceful shutdown (for apps with event loops)
        has_signal = bool(re.search(
            r'(?:signal\.signal|atexit\.register|on_shutdown|lifespan|shutdown_event)',
            code,
        ))
        has_loop = bool(re.search(r'(?:asyncio\.run|uvicorn\.run|app\.run)', code))
        if has_loop and not has_signal:
            messages.append(
                "[no_shutdown] No graceful shutdown handler: "
                "add signal handler or lifespan for clean resource cleanup"
            )
            penalty += 0.1

        return messages, penalty
