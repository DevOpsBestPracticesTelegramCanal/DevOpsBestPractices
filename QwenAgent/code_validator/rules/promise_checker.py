"""
Week 22: Promise Checker — Docstring vs Implementation Verifier

Detects mismatches between what a function's docstring *promises* and what
the implementation actually *does*.

Common failure modes caught:
  - Docstring says "Returns list of ..." but function returns None
  - Docstring says "Raises ValueError" but no raise statement exists
  - Docstring mentions parameters that don't exist in the signature
  - Function has no body (just pass/...) but a detailed docstring
"""

import ast
import re
from typing import List, Optional, Set, Tuple
from .base import Rule, RuleResult, RuleSeverity


# Patterns to extract docstring promises
_RETURNS_RE = re.compile(
    r'(?:Returns?|Yields?):\s*\n?\s*(.+)',
    re.IGNORECASE,
)
_RAISES_RE = re.compile(
    r'Raises?:\s*\n?\s*(\w+(?:Error|Exception|Warning))',
    re.IGNORECASE,
)
_ARGS_RE = re.compile(
    r'Args?:\s*\n((?:\s+\w+.*\n?)+)',
    re.IGNORECASE,
)
_ARG_NAME_RE = re.compile(r'^\s+(\w+)\s*(?:\(|:)', re.MULTILINE)


def _get_docstring(node: ast.AST) -> Optional[str]:
    """Extract docstring from a function/class node."""
    return ast.get_docstring(node) or None


def _has_return_value(func: ast.FunctionDef) -> bool:
    """Check if function has a non-None return statement."""
    for node in ast.walk(func):
        if isinstance(node, ast.Return) and node.value is not None:
            return True
    return False


def _has_yield(func: ast.FunctionDef) -> bool:
    """Check if function has a yield/yield from statement."""
    for node in ast.walk(func):
        if isinstance(node, (ast.Yield, ast.YieldFrom)):
            return True
    return False


def _get_raised_exceptions(func: ast.FunctionDef) -> Set[str]:
    """Get set of exception names raised in the function."""
    raised = set()
    for node in ast.walk(func):
        if isinstance(node, ast.Raise) and node.exc is not None:
            if isinstance(node.exc, ast.Call):
                if isinstance(node.exc.func, ast.Name):
                    raised.add(node.exc.func.id)
                elif isinstance(node.exc.func, ast.Attribute):
                    raised.add(node.exc.func.attr)
            elif isinstance(node.exc, ast.Name):
                raised.add(node.exc.id)
    return raised


def _get_param_names(func: ast.FunctionDef) -> Set[str]:
    """Get parameter names from function signature (excluding self/cls)."""
    names = set()
    for arg in func.args.args:
        if arg.arg not in ("self", "cls"):
            names.add(arg.arg)
    for arg in func.args.kwonlyargs:
        names.add(arg.arg)
    if func.args.vararg:
        names.add(func.args.vararg.arg)
    if func.args.kwarg:
        names.add(func.args.kwarg.arg)
    return names


def _is_stub_body(func: ast.FunctionDef) -> bool:
    """Check if function body is just pass/... /raise NotImplementedError."""
    body = func.body
    # Skip docstring node
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        body = body[1:]
    if not body:
        return True
    if len(body) == 1:
        stmt = body[0]
        if isinstance(stmt, ast.Pass):
            return True
        if isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant):
            if stmt.value.value is Ellipsis:
                return True
        if isinstance(stmt, ast.Raise):
            if isinstance(stmt.exc, ast.Call):
                if isinstance(stmt.exc.func, ast.Name):
                    if stmt.exc.func.id == "NotImplementedError":
                        return True
    return False


class PromiseCheckerRule(Rule):
    """Verifies that docstring promises match the implementation.

    Checks:
      1. Returns promise vs actual return statements
      2. Raises promise vs actual raise statements
      3. Args promise vs actual parameters
      4. Stub body with detailed docstring (promise without delivery)
    """

    name = "promise_checker"
    severity = RuleSeverity.WARNING
    weight = 1.5

    def check(self, code: str) -> RuleResult:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return self._ok(1.0, ["Skipped: syntax errors"])

        messages: List[str] = []
        checks_total = 0
        checks_passed = 0

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue

            doc = _get_docstring(node)
            if not doc:
                continue

            fname = node.name

            # Check 1: Returns promise vs implementation
            returns_match = _RETURNS_RE.search(doc)
            if returns_match:
                checks_total += 1
                returns_text = returns_match.group(1).strip().lower()
                has_return = _has_return_value(node)
                has_yield_val = _has_yield(node)

                if "yield" in returns_text or "generator" in returns_text:
                    if has_yield_val:
                        checks_passed += 1
                    else:
                        messages.append(
                            f"{fname}(): docstring promises yield/generator "
                            f"but no yield found"
                        )
                elif "none" not in returns_text:
                    if has_return or has_yield_val:
                        checks_passed += 1
                    elif _is_stub_body(node):
                        messages.append(
                            f"{fname}(): docstring promises return value "
                            f"but body is a stub (pass/...)"
                        )
                    else:
                        messages.append(
                            f"{fname}(): docstring promises '{returns_text[:60]}' "
                            f"but no return statement found"
                        )
                else:
                    checks_passed += 1

            # Check 2: Raises promise vs implementation
            raises_matches = _RAISES_RE.findall(doc)
            if raises_matches:
                checks_total += 1
                raised = _get_raised_exceptions(node)
                promised = set(raises_matches)
                missing = promised - raised
                if missing and not _is_stub_body(node):
                    messages.append(
                        f"{fname}(): docstring promises to raise "
                        f"{', '.join(sorted(missing))} but they are not raised"
                    )
                else:
                    checks_passed += 1

            # Check 3: Args promise vs parameters
            args_match = _ARGS_RE.search(doc)
            if args_match:
                checks_total += 1
                doc_args = set(_ARG_NAME_RE.findall(args_match.group(1)))
                actual_params = _get_param_names(node)
                phantom = doc_args - actual_params
                if phantom:
                    messages.append(
                        f"{fname}(): docstring describes args "
                        f"{', '.join(sorted(phantom))} "
                        f"that don't exist in signature"
                    )
                else:
                    checks_passed += 1

            # Check 4: Detailed docstring but stub body
            if len(doc) > 50 and _is_stub_body(node):
                checks_total += 1
                messages.append(
                    f"{fname}(): detailed docstring ({len(doc)} chars) "
                    f"but body is a stub — promise without delivery"
                )

        if checks_total == 0:
            return self._ok(1.0, ["No docstring promises to verify"])

        score = checks_passed / checks_total if checks_total > 0 else 1.0
        passed = score >= 0.5

        if not messages:
            return self._ok(score)
        return RuleResult(
            rule_name=self.name,
            passed=passed,
            score=round(score, 2),
            severity=self.severity,
            messages=messages,
        )
