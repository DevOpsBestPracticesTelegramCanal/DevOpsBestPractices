"""
Week 22: Anti-Pattern Detector

Catches critical code anti-patterns that bypass basic lint/syntax checks:
  - Regex-based SQL construction (SQL injection risk)
  - Direct TOTP/HOTP implementation (use pyotp instead)
  - Hardcoded secrets/passwords/tokens
  - Bare except clauses
  - Mutable default arguments
  - Global state mutation
  - Unrestricted pickle/yaml.load usage
"""

import ast
import re
from typing import List, Tuple
from .base import Rule, RuleResult, RuleSeverity


# ---------------------------------------------------------------------------
# Pattern definitions: (name, regex, severity_weight, message)
# ---------------------------------------------------------------------------

_ANTIPATTERNS: List[Tuple[str, re.Pattern, float, str]] = [
    # SQL Injection via string formatting
    (
        "sql_injection",
        re.compile(
            r'''(?:execute|cursor\.execute|\.raw|\.extra)\s*\(\s*'''
            r'''(?:f["\']|["\'].*?%s.*?%|["\'].*?\{.*?\}|.*?\+\s*(?:str\(|user|request|input))''',
            re.IGNORECASE | re.MULTILINE,
        ),
        0.4,
        "Potential SQL injection: use parameterized queries instead of string formatting",
    ),
    # Hardcoded secrets
    (
        "hardcoded_secret",
        re.compile(
            r'''(?:password|secret|api_key|token|auth|credential)\s*=\s*["\'][^"\']{8,}["\']''',
            re.IGNORECASE,
        ),
        0.3,
        "Hardcoded secret detected: use environment variables or a secret manager",
    ),
    # Direct TOTP/HOTP implementation
    (
        "direct_totp",
        re.compile(
            r'''(?:hmac\.new\s*\(.*?(?:sha1|sha256).*?(?:time|counter)|'''
            r'''struct\.pack.*?(?:time|counter).*?hmac)''',
            re.IGNORECASE | re.DOTALL,
        ),
        0.25,
        "Direct TOTP/HOTP implementation: use pyotp library for RFC 6238/4226 compliance",
    ),
    # Unrestricted yaml.load (RCE risk)
    (
        "unsafe_yaml",
        re.compile(
            r'''yaml\.load\s*\([^)]*(?!\bLoader\s*=\s*(?:yaml\.)?SafeLoader)''',
        ),
        0.3,
        "Unsafe yaml.load(): use yaml.safe_load() or yaml.load(data, Loader=SafeLoader)",
    ),
    # Unrestricted pickle.loads (RCE risk)
    (
        "unsafe_pickle",
        re.compile(r'''pickle\.loads?\s*\('''),
        0.25,
        "Unsafe pickle usage: pickle can execute arbitrary code on deserialization",
    ),
    # Debug mode in production
    (
        "debug_production",
        re.compile(
            r'''(?:debug\s*=\s*True|DEBUG\s*=\s*True|app\.run\s*\([^)]*debug\s*=\s*True)''',
        ),
        0.2,
        "Debug mode enabled: disable debug=True for production code",
    ),
    # Shell injection via os.system/subprocess with string
    (
        "shell_injection",
        re.compile(
            r'''(?:os\.system|os\.popen|subprocess\.(?:call|run|Popen))\s*\(\s*'''
            r'''(?:f["\']|["\'].*?\{|.*?\+\s*(?:str\(|user|request|input))''',
            re.IGNORECASE,
        ),
        0.35,
        "Potential shell injection: use subprocess with list args, avoid string interpolation",
    ),
]

# AST-based anti-patterns
_BARE_EXCEPT_MSG = "Bare 'except:' clause catches all exceptions including SystemExit/KeyboardInterrupt"
_MUTABLE_DEFAULT_MSG = "Mutable default argument: use None and create inside function body"


class AntiPatternRule(Rule):
    """Detects critical code anti-patterns that are security risks
    or common sources of bugs.

    Combines regex-based detection (for string patterns) with
    AST-based detection (for structural anti-patterns).
    """

    name = "antipattern"
    severity = RuleSeverity.ERROR
    weight = 3.0

    def check(self, code: str) -> RuleResult:
        if not code or not code.strip():
            return self._ok(1.0)

        messages: List[str] = []
        total_penalty = 0.0

        # Phase 1: Regex-based detection
        for pattern_name, regex, weight, msg in _ANTIPATTERNS:
            matches = regex.findall(code)
            if matches:
                messages.append(f"[{pattern_name}] {msg} ({len(matches)} occurrence(s))")
                total_penalty += weight

        # Phase 2: AST-based detection
        try:
            tree = ast.parse(code)
            ast_messages, ast_penalty = self._check_ast(tree)
            messages.extend(ast_messages)
            total_penalty += ast_penalty
        except SyntaxError:
            pass  # Skip AST checks if code doesn't parse

        score = max(0.0, 1.0 - total_penalty)
        passed = score >= 0.4  # Generous threshold — warnings don't block

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
    def _check_ast(tree: ast.Module) -> Tuple[List[str], float]:
        """AST-based anti-pattern detection."""
        messages: List[str] = []
        penalty = 0.0

        for node in ast.walk(tree):
            # Bare except
            if isinstance(node, ast.ExceptHandler):
                if node.type is None:
                    messages.append(f"[bare_except] {_BARE_EXCEPT_MSG}")
                    penalty += 0.15

            # Mutable default arguments
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for default in node.args.defaults + node.args.kw_defaults:
                    if default is None:
                        continue
                    if isinstance(default, (ast.List, ast.Dict, ast.Set)):
                        messages.append(
                            f"[mutable_default] {node.name}(): {_MUTABLE_DEFAULT_MSG}"
                        )
                        penalty += 0.1
                        break  # One per function is enough

            # Global state mutation (assigning to module-level mutable)
            if isinstance(node, ast.Global):
                for name in node.names:
                    messages.append(
                        f"[global_mutation] 'global {name}' — avoid global state mutation"
                    )
                    penalty += 0.1

        return messages, penalty
