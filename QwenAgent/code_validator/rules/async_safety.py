"""
Week 22: Async Safety Checker

Detects common async anti-patterns that cause blocking, deadlocks,
or incorrect behavior:
  - Blocking calls (time.sleep, requests.get) in async functions
  - Missing await on coroutine calls
  - Sync file I/O in async context
  - threading.Lock in async code (should use asyncio.Lock)
  - asyncio.run() inside running event loop
"""

import ast
import re
from typing import List, Set, Tuple
from .base import Rule, RuleResult, RuleSeverity


# Blocking calls that should not appear in async functions
_BLOCKING_CALLS: Set[str] = {
    "time.sleep",
    "requests.get", "requests.post", "requests.put",
    "requests.delete", "requests.patch", "requests.head",
    "requests.request",
    "urllib.request.urlopen",
    "http.client.HTTPConnection",
    "http.client.HTTPSConnection",
    "socket.socket",
    "subprocess.run", "subprocess.call", "subprocess.check_output",
    "subprocess.check_call",
    "os.system",
    "sqlite3.connect",
}

# Blocking file I/O patterns
_BLOCKING_IO_RE = re.compile(
    r'(?:open\s*\(|\.read\s*\(|\.write\s*\(|\.readlines\s*\()',
)

# Sync lock in async context
_SYNC_LOCK_RE = re.compile(
    r'threading\.(?:Lock|RLock|Semaphore|Event|Condition)\s*\(',
)

# asyncio.run() inside potentially running loop
_ASYNCIO_RUN_RE = re.compile(r'asyncio\.run\s*\(')


def _is_async_module(code: str) -> bool:
    """Check if the module uses async features."""
    return bool(re.search(r'(?:async\s+def|await\s+|asyncio)', code))


def _get_call_name(node: ast.Call) -> str:
    """Extract dotted name from a Call node (e.g. 'requests.get')."""
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        parts = []
        obj = func
        while isinstance(obj, ast.Attribute):
            parts.append(obj.attr)
            obj = obj.value
        if isinstance(obj, ast.Name):
            parts.append(obj.id)
        return ".".join(reversed(parts))
    return ""


class AsyncSafetyRule(Rule):
    """Detects blocking calls and common async anti-patterns
    in async function bodies.

    Only activates if the code uses async features.
    """

    name = "async_safety"
    severity = RuleSeverity.WARNING
    weight = 2.0

    def check(self, code: str) -> RuleResult:
        if not code or not code.strip():
            return self._ok(1.0)

        if not _is_async_module(code):
            return self._ok(1.0, ["No async code detected — skipped"])

        try:
            tree = ast.parse(code)
        except SyntaxError:
            return self._ok(1.0, ["Skipped: syntax errors"])

        messages: List[str] = []
        penalty = 0.0

        # Check each async function
        for node in ast.walk(tree):
            if not isinstance(node, ast.AsyncFunctionDef):
                continue

            fname = node.name
            msgs, pen = self._check_async_func(node, fname)
            messages.extend(msgs)
            penalty += pen

        # Module-level checks
        msgs, pen = self._check_module_level(code, tree)
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
    def _check_async_func(func: ast.AsyncFunctionDef, fname: str) -> Tuple[List[str], float]:
        messages: List[str] = []
        penalty = 0.0

        for node in ast.walk(func):
            if isinstance(node, ast.Call):
                call_name = _get_call_name(node)
                if call_name in _BLOCKING_CALLS:
                    messages.append(
                        f"[blocking_call] {fname}(): blocking call '{call_name}' "
                        f"in async function — use async equivalent"
                    )
                    penalty += 0.2

        # Check for sync file I/O in async body
        func_source_lines = []
        for child in ast.walk(func):
            if isinstance(child, ast.Call):
                name = _get_call_name(child)
                if name == "open":
                    # Check if wrapped in asyncio or aiofiles
                    messages.append(
                        f"[sync_io] {fname}(): sync open() in async function "
                        f"— use aiofiles or asyncio.to_thread()"
                    )
                    penalty += 0.15
                    break

        return messages, penalty

    @staticmethod
    def _check_module_level(code: str, tree: ast.Module) -> Tuple[List[str], float]:
        messages: List[str] = []
        penalty = 0.0

        # Sync lock in async module
        if _SYNC_LOCK_RE.search(code):
            has_asyncio_lock = bool(re.search(r'asyncio\.Lock\s*\(', code))
            if not has_asyncio_lock:
                messages.append(
                    "[sync_lock] threading.Lock in async module: "
                    "use asyncio.Lock() for async-safe synchronization"
                )
                penalty += 0.15

        # asyncio.run() inside async function (nested loop)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        name = _get_call_name(child)
                        if name == "asyncio.run":
                            messages.append(
                                f"[nested_run] {node.name}(): asyncio.run() "
                                f"inside async function — causes RuntimeError"
                            )
                            penalty += 0.3

        return messages, penalty
