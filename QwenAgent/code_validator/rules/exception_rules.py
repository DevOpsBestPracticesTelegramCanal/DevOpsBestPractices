"""
Week 22: Exception Hierarchy Checker

Validates exception handling patterns:
  - Custom exceptions should inherit from specific bases (not bare Exception)
  - Exception messages should be informative
  - No swallowed exceptions (except: pass)
  - Exception chaining (raise ... from ...)
  - Overly broad except clauses
"""

import ast
from typing import List, Set, Tuple
from .base import Rule, RuleResult, RuleSeverity


# Exception base classes that are too broad
_BROAD_EXCEPTIONS: Set[str] = {"Exception", "BaseException"}

# Acceptable broad catches (often valid)
_ACCEPTABLE_BROAD_CONTEXTS = {"main", "__main__", "run", "start", "worker"}


class ExceptionHierarchyRule(Rule):
    """Validates exception handling quality and custom exception hierarchy.

    Checks:
      1. Custom exception classes inherit from specific bases
      2. No swallowed exceptions (except: pass / except Exception: pass)
      3. Exception chaining used where appropriate
      4. Overly broad except clauses
    """

    name = "exception_hierarchy"
    severity = RuleSeverity.WARNING
    weight = 1.0

    def check(self, code: str) -> RuleResult:
        if not code or not code.strip():
            return self._ok(1.0)

        try:
            tree = ast.parse(code)
        except SyntaxError:
            return self._ok(1.0, ["Skipped: syntax errors"])

        messages: List[str] = []
        penalty = 0.0

        # Check 1: Custom exception hierarchy
        msgs, pen = self._check_custom_exceptions(tree)
        messages.extend(msgs)
        penalty += pen

        # Check 2: Swallowed exceptions
        msgs, pen = self._check_swallowed(tree)
        messages.extend(msgs)
        penalty += pen

        # Check 3: Broad except clauses
        msgs, pen = self._check_broad_except(tree)
        messages.extend(msgs)
        penalty += pen

        # Check 4: Exception chaining
        msgs, pen = self._check_chaining(tree)
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
    def _check_custom_exceptions(tree: ast.Module) -> Tuple[List[str], float]:
        """Check that custom exception classes inherit from specific exception types."""
        messages: List[str] = []
        penalty = 0.0

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            # Is this an exception class?
            name = node.name
            if not (name.endswith("Error") or name.endswith("Exception")
                    or name.endswith("Warning")):
                continue

            # Check bases
            for base in node.bases:
                base_name = ""
                if isinstance(base, ast.Name):
                    base_name = base.id
                elif isinstance(base, ast.Attribute):
                    base_name = base.attr

                if base_name == "Exception":
                    messages.append(
                        f"[broad_base] {name} inherits from bare Exception: "
                        f"use a more specific base (ValueError, TypeError, RuntimeError, etc.)"
                    )
                    penalty += 0.1
                elif base_name == "BaseException":
                    messages.append(
                        f"[base_exception] {name} inherits from BaseException: "
                        f"use Exception instead (BaseException catches SystemExit, KeyboardInterrupt)"
                    )
                    penalty += 0.15

        return messages, penalty

    @staticmethod
    def _check_swallowed(tree: ast.Module) -> Tuple[List[str], float]:
        """Check for swallowed exceptions (except: pass)."""
        messages: List[str] = []
        penalty = 0.0

        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue

            # Check if body is just 'pass'
            body = node.body
            if len(body) == 1 and isinstance(body[0], ast.Pass):
                exc_name = "bare except" if node.type is None else ast.dump(node.type)
                if isinstance(node.type, ast.Name):
                    exc_name = node.type.id
                messages.append(
                    f"[swallowed] except {exc_name}: pass — "
                    f"silently swallowing exceptions hides bugs"
                )
                penalty += 0.2

        return messages, penalty

    @staticmethod
    def _check_broad_except(tree: ast.Module) -> Tuple[List[str], float]:
        """Check for overly broad except clauses."""
        messages: List[str] = []
        penalty = 0.0

        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if node.type is None:
                # Bare except — already caught by antipattern_rules
                continue

            exc_name = ""
            if isinstance(node.type, ast.Name):
                exc_name = node.type.id

            if exc_name not in _BROAD_EXCEPTIONS:
                continue

            # Check context: in a main/worker function it's often acceptable
            parent_func = None
            for parent in ast.walk(tree):
                if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    for child in ast.walk(parent):
                        if child is node:
                            parent_func = parent.name
                            break

            if parent_func and parent_func in _ACCEPTABLE_BROAD_CONTEXTS:
                continue

            # Check if it at least logs or re-raises
            body_has_log = False
            body_has_raise = False
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    if isinstance(child.func, ast.Attribute):
                        if child.func.attr in ("error", "exception", "warning", "critical"):
                            body_has_log = True
                if isinstance(child, ast.Raise):
                    body_has_raise = True

            if not body_has_log and not body_has_raise:
                messages.append(
                    f"[broad_catch] except {exc_name} without logging or re-raise: "
                    f"use specific exception types or at least log the error"
                )
                penalty += 0.15

        return messages, penalty

    @staticmethod
    def _check_chaining(tree: ast.Module) -> Tuple[List[str], float]:
        """Check for missing exception chaining (raise X from Y)."""
        messages: List[str] = []
        penalty = 0.0

        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue

            # Look for 'raise NewException(...)' inside except handler
            # without 'from' clause
            for child in ast.walk(node):
                if not isinstance(child, ast.Raise):
                    continue
                if child.exc is None:
                    continue  # bare 'raise' (re-raise) is fine

                # Check if this is a new exception (not just re-raise)
                is_new_exception = isinstance(child.exc, ast.Call)
                if is_new_exception and child.cause is None:
                    # New exception raised without 'from' — loses traceback
                    exc_cls = ""
                    if isinstance(child.exc.func, ast.Name):
                        exc_cls = child.exc.func.id
                    if exc_cls:
                        messages.append(
                            f"[no_chain] raise {exc_cls}(...) without 'from': "
                            f"use 'raise {exc_cls}(...) from err' to preserve traceback"
                        )
                        penalty += 0.1

        return messages, penalty
