"""
Week 25: Decorator Red-Flags Validator

AST-based checks for decorator-specific anti-patterns that slip past
general-purpose validators:

  - bare_retry_loop: while True: try/except without backoff or max-retries
  - signal_in_decorator: signal.alarm() inside decorator body (not thread-safe)
  - cache_outside_retry: @cache applied before @retry (caches exceptions)
  - missing_wraps: decorator function without @functools.wraps
  - unhashable_cache_key: dict/list parameter default with @lru_cache
  - missing_timeout_cancel: timeout via thread spawn without join/cancel
"""

import ast
import logging
from typing import List, Optional

from .base import Rule, RuleResult, RuleSeverity

logger = logging.getLogger(__name__)


class DecoratorRedFlagsRule(Rule):
    """Catch decorator-specific anti-patterns via AST analysis."""

    name = "decorator_red_flags"
    severity = RuleSeverity.ERROR
    weight = 2.5

    def check(self, code: str) -> RuleResult:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return self._ok(score=1.0, messages=["Cannot parse; skipping decorator checks"])

        issues: List[str] = []

        issues.extend(self._check_bare_retry(tree))
        issues.extend(self._check_signal_in_decorator(tree))
        issues.extend(self._check_cache_outside_retry(tree))
        issues.extend(self._check_missing_wraps(tree))
        issues.extend(self._check_unhashable_cache_key(tree))
        issues.extend(self._check_missing_timeout_cancel(tree))
        issues.extend(self._check_fake_timeout(tree))
        issues.extend(self._check_thread_unsafe_cache(tree, code))
        issues.extend(self._check_silent_retry_failure(tree))

        if issues:
            score = max(0.0, 1.0 - 0.2 * len(issues))
            return self._fail(score=score, messages=issues)
        return self._ok(score=1.0)

    # ------------------------------------------------------------------
    # Individual checks
    # ------------------------------------------------------------------

    def _check_bare_retry(self, tree: ast.AST) -> List[str]:
        """Detect while True: try/except without backoff or max-retries."""
        issues: List[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.While):
                continue
            # Check for `while True`
            if not (isinstance(node.test, ast.Constant) and node.test.value is True):
                continue
            # Look for a try/except inside
            has_try = any(isinstance(child, ast.Try) for child in ast.walk(node))
            if not has_try:
                continue
            # Check if there's a sleep/backoff call (heuristic for backoff)
            body_src = ast.dump(node)
            has_backoff = ("sleep" in body_src or "backoff" in body_src
                           or "jitter" in body_src)
            # Check for a retry counter / max_retries guard
            has_counter = False
            for child in ast.walk(node):
                if isinstance(child, ast.Compare):
                    has_counter = True
                    break
                if isinstance(child, ast.AugAssign):
                    has_counter = True
                    break
            if not has_backoff and not has_counter:
                line = getattr(node, "lineno", "?")
                issues.append(
                    f"Line {line}: bare retry loop (while True + try/except) "
                    f"without backoff or max-retries guard"
                )
        return issues

    def _check_signal_in_decorator(self, tree: ast.AST) -> List[str]:
        """Detect signal.alarm() usage inside decorator functions."""
        issues: List[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if not self._is_decorator_function(node):
                continue
            for child in ast.walk(node):
                if (isinstance(child, ast.Call)
                        and isinstance(child.func, ast.Attribute)
                        and child.func.attr == "alarm"
                        and isinstance(child.func.value, ast.Name)
                        and child.func.value.id == "signal"):
                    line = getattr(child, "lineno", "?")
                    issues.append(
                        f"Line {line}: signal.alarm() inside decorator is not "
                        f"thread-safe; use concurrent.futures or asyncio.wait_for"
                    )
        return issues

    def _check_cache_outside_retry(self, tree: ast.AST) -> List[str]:
        """Detect @cache applied before @retry (wrong order caches errors)."""
        issues: List[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.decorator_list:
                continue
            decorators = [self._decorator_name(d) for d in node.decorator_list]
            cache_idx = None
            retry_idx = None
            for i, name in enumerate(decorators):
                if name and ("cache" in name.lower()):
                    cache_idx = i
                if name and ("retry" in name.lower()):
                    retry_idx = i
            # Decorators are applied bottom-up; the last decorator in source
            # is the innermost (applied first).  @cache above @retry means
            # cache wraps retry → caches exceptions from failed retries.
            if cache_idx is not None and retry_idx is not None:
                if cache_idx < retry_idx:
                    line = getattr(node, "lineno", "?")
                    issues.append(
                        f"Line {line}: @cache is above @retry — cache will "
                        f"store failed retry results; swap the order"
                    )
        return issues

    def _check_missing_wraps(self, tree: ast.AST) -> List[str]:
        """Detect decorator functions that don't use @functools.wraps."""
        issues: List[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if not self._is_decorator_function(node):
                continue
            # Find the inner wrapper function
            wrapper = self._find_wrapper_function(node)
            if wrapper is None:
                continue
            # Check if wrapper has @functools.wraps or @wraps decorator
            has_wraps = False
            for dec in wrapper.decorator_list:
                name = self._decorator_name(dec)
                if name and "wraps" in name.lower():
                    has_wraps = True
                    break
            if not has_wraps:
                line = getattr(wrapper, "lineno", "?")
                issues.append(
                    f"Line {line}: inner wrapper function missing "
                    f"@functools.wraps(func) — will break __name__/__doc__"
                )
        return issues

    def _check_unhashable_cache_key(self, tree: ast.AST) -> List[str]:
        """Detect @lru_cache on functions with dict/list default args."""
        issues: List[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            # Check if decorated with lru_cache or cache
            has_lru = False
            for dec in node.decorator_list:
                name = self._decorator_name(dec)
                if name and ("lru_cache" in name or name == "cache"):
                    has_lru = True
                    break
            if not has_lru:
                continue
            # Check for dict/list/set default values
            for default in node.args.defaults + node.args.kw_defaults:
                if default is None:
                    continue
                if isinstance(default, (ast.Dict, ast.List, ast.Set)):
                    line = getattr(node, "lineno", "?")
                    issues.append(
                        f"Line {line}: @lru_cache on function with mutable "
                        f"default (dict/list/set) — unhashable args will raise TypeError"
                    )
                    break
        return issues

    def _check_missing_timeout_cancel(self, tree: ast.AST) -> List[str]:
        """Detect timeout via Thread without join timeout or cancel."""
        issues: List[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if not self._is_decorator_function(node):
                continue
            # Look for Thread() creation inside decorator
            has_thread_start = False
            has_join_or_cancel = False
            for child in ast.walk(node):
                # Thread().start()
                if (isinstance(child, ast.Call)
                        and isinstance(child.func, ast.Attribute)
                        and child.func.attr == "start"):
                    # Check if it's Thread-like
                    val = child.func.value
                    if isinstance(val, ast.Call):
                        fname = self._call_name(val)
                        if fname and "thread" in fname.lower():
                            has_thread_start = True
                # .join( with timeout keyword
                if (isinstance(child, ast.Call)
                        and isinstance(child.func, ast.Attribute)
                        and child.func.attr == "join"):
                    if child.keywords or child.args:
                        has_join_or_cancel = True
                    # bare .join() without timeout is also a problem,
                    # but at least they're waiting — skip for now
                    else:
                        has_join_or_cancel = True
                # Event / cancel / kill patterns
                if (isinstance(child, ast.Call)
                        and isinstance(child.func, ast.Attribute)
                        and child.func.attr in ("cancel", "set", "kill")):
                    has_join_or_cancel = True

            if has_thread_start and not has_join_or_cancel:
                line = getattr(node, "lineno", "?")
                issues.append(
                    f"Line {line}: decorator spawns Thread but never "
                    f"joins/cancels it — potential thread leak"
                )
        return issues

    # ------------------------------------------------------------------
    # Week 27: New checks for codegen quality gate
    # ------------------------------------------------------------------

    def _check_fake_timeout(self, tree: ast.AST) -> List[str]:
        """Detect timeout decorators that don't actually enforce timeout.

        A real timeout needs concurrent.futures, signal.alarm, asyncio.wait_for,
        or threading with join(timeout=).  A try/except wrapper does NOT
        interrupt a running function.
        """
        issues: List[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            # Heuristic: function named *timeout* that is a decorator
            if "timeout" not in node.name.lower():
                continue
            if not self._is_decorator_function(node):
                continue

            # Search entire decorator subtree for real timeout mechanisms
            src = ast.dump(node)
            has_real_timeout = any(kw in src for kw in (
                "ThreadPoolExecutor",
                "ProcessPoolExecutor",
                "submit",             # futures.submit
                "wait_for",           # asyncio.wait_for
                "alarm",              # signal.alarm
                "Timer",              # threading.Timer
            ))

            # Also check for thread.join(timeout=...)
            for child in ast.walk(node):
                if (isinstance(child, ast.Call)
                        and isinstance(child.func, ast.Attribute)
                        and child.func.attr == "join"
                        and child.keywords):
                    for kw in child.keywords:
                        if kw.arg == "timeout":
                            has_real_timeout = True

            if not has_real_timeout:
                line = getattr(node, "lineno", "?")
                issues.append(
                    f"Line {line}: timeout decorator '{node.name}' has no real "
                    f"timeout mechanism (needs concurrent.futures, signal, or "
                    f"threading.Timer); try/except alone cannot interrupt a "
                    f"running function"
                )
        return issues

    def _check_thread_unsafe_cache(self, tree: ast.AST, code: str) -> List[str]:
        """Detect global dict used as cache without thread-safety."""
        issues: List[str] = []
        # Find module-level dict assignments (CACHE = {})
        global_dicts: List[str] = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (isinstance(target, ast.Name)
                            and isinstance(node.value, ast.Dict)):
                        global_dicts.append(target.id)

        if not global_dicts:
            return issues

        # Check if any function writes to these dicts
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            for child in ast.walk(node):
                if isinstance(child, ast.Subscript):
                    if (isinstance(child.value, ast.Name)
                            and child.value.id in global_dicts):
                        # Dict is accessed inside a function — check for Lock
                        has_lock = any(kw in code for kw in (
                            "Lock()", "RLock()", "threading.Lock",
                            "threading.RLock", "lock.acquire",
                            "with lock", "with self.lock",
                            "with self._lock",
                        ))
                        if not has_lock:
                            line = getattr(child, "lineno", "?")
                            issues.append(
                                f"Line {line}: global dict '{child.value.id}' "
                                f"used as cache without threading.Lock — "
                                f"thread-unsafe in concurrent code"
                            )
                            # Only report once per dict
                            global_dicts.remove(child.value.id)
                        break
        return issues

    def _check_silent_retry_failure(self, tree: ast.AST) -> List[str]:
        """Detect retry loops that silently return None on exhaustion."""
        issues: List[str] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            if "retry" not in node.name.lower():
                continue
            if not self._is_decorator_function(node):
                continue

            wrapper = self._find_wrapper_function(node)
            if wrapper is None:
                continue

            # Check: does the wrapper have a for-loop with try/except?
            for child in ast.walk(wrapper):
                if not isinstance(child, ast.For):
                    continue
                has_try = any(isinstance(c, ast.Try) for c in ast.walk(child))
                if not has_try:
                    continue

                # Check what happens AFTER the for loop — is there a raise?
                # The for loop is a child of wrapper.body; check statements
                # that come after it.
                for_idx = None
                for i, stmt in enumerate(wrapper.body):
                    if stmt is child:
                        for_idx = i
                        break

                if for_idx is not None:
                    after_for = wrapper.body[for_idx + 1:]
                    has_raise_after = any(
                        isinstance(s, ast.Raise) for s in after_for
                    )
                    # Also check for-else clause
                    has_raise_in_else = False
                    if child.orelse:
                        has_raise_in_else = any(
                            isinstance(s, ast.Raise) for s in child.orelse
                        )

                    if not has_raise_after and not has_raise_in_else:
                        line = getattr(wrapper, "lineno", "?")
                        issues.append(
                            f"Line {line}: retry wrapper returns None "
                            f"silently after exhausting all attempts — "
                            f"should raise the last exception"
                        )
        return issues

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_decorator_function(node: ast.FunctionDef) -> bool:
        """Heuristic: a function is a decorator factory/decorator if it
        contains an inner function that it returns."""
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef):
                # Check if parent returns the inner function
                for stmt in ast.walk(node):
                    if (isinstance(stmt, ast.Return)
                            and isinstance(stmt.value, ast.Name)
                            and stmt.value.id == child.name):
                        return True
        return False

    @staticmethod
    def _find_wrapper_function(node: ast.FunctionDef) -> Optional[ast.FunctionDef]:
        """Find the innermost wrapper function inside a decorator."""
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.FunctionDef):
                # Recurse one level (decorator factory pattern)
                for grandchild in ast.iter_child_nodes(child):
                    if isinstance(grandchild, ast.FunctionDef):
                        return grandchild
                return child
        return None

    @staticmethod
    def _decorator_name(dec: ast.expr) -> Optional[str]:
        """Extract decorator name as string (best-effort)."""
        if isinstance(dec, ast.Name):
            return dec.id
        if isinstance(dec, ast.Attribute):
            parts = []
            node = dec
            while isinstance(node, ast.Attribute):
                parts.append(node.attr)
                node = node.value
            if isinstance(node, ast.Name):
                parts.append(node.id)
            return ".".join(reversed(parts))
        if isinstance(dec, ast.Call):
            return DecoratorRedFlagsRule._decorator_name(dec.func)
        return None

    @staticmethod
    def _call_name(node: ast.Call) -> Optional[str]:
        """Extract function call name as string (best-effort)."""
        return DecoratorRedFlagsRule._decorator_name(node.func)
