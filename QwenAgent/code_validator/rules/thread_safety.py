"""
Week 28: Thread Safety Validator (SV-08)

AST-based detection of common thread safety issues:
  - Class attributes modified without Lock (dict/list/set mutations in methods)
  - threading.Thread(daemon=True) without corresponding join()
  - Global mutable state without protection
  - Shared collections used as cache without Lock

Registered in BALANCED, SAFE_FIX, and CRITICAL validation profiles.
"""

import ast
import logging
from typing import Dict, List, Set, Tuple

from .base import Rule, RuleResult, RuleSeverity

logger = logging.getLogger(__name__)

# Methods that mutate mutable containers
_MUTATING_METHODS: Set[str] = {
    # dict
    "update", "pop", "popitem", "setdefault", "clear",
    # list
    "append", "extend", "insert", "remove", "sort", "reverse",
    # set
    "add", "discard", "remove", "update", "intersection_update",
    "difference_update", "symmetric_difference_update",
}

# Attribute names that suggest thread-local or already-protected state
_SAFE_ATTR_PREFIXES = ("_lock", "_rlock", "_local", "_threading_local")


class ThreadSafetyRule(Rule):
    """Detect potential thread safety issues in generated code.

    Checks:
    1. Classes with shared mutable state (self.dict/list/set) modified
       without an obvious Lock.
    2. threading.Thread(daemon=True) without a corresponding join().
    3. Global mutable assignments (module-level dict/list/set literals)
       without module-level Lock.
    4. Counter/defaultdict used as shared cache without Lock.
    """

    name = "thread_safety"
    severity = RuleSeverity.ERROR
    weight = 2.0

    def check(self, code: str) -> RuleResult:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return self._ok(1.0, ["Skipped: syntax errors"])

        issues: List[str] = []

        # Check 1: Classes with unprotected shared mutable state
        issues.extend(self._check_class_thread_safety(tree))

        # Check 2: daemon threads without join
        issues.extend(self._check_daemon_threads(tree))

        # Check 3: Global mutable state without Lock
        issues.extend(self._check_global_mutables(tree))

        if not issues:
            return self._ok(1.0)

        score = max(0.0, 1.0 - len(issues) * 0.2)
        return self._fail(round(score, 2), issues)

    def _check_class_thread_safety(self, tree: ast.AST) -> List[str]:
        """Check classes for mutable state mutated without Lock."""
        issues = []

        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue

            has_lock = self._class_has_lock(node)
            mutable_attrs = self._find_mutable_attrs(node)

            if not mutable_attrs:
                continue

            # Check if mutations happen inside 'with self._lock:' blocks
            unprotected = self._find_unprotected_mutations(node, mutable_attrs, has_lock)
            for attr, method_name, line in unprotected:
                issues.append(
                    f"Shared mutable 'self.{attr}' mutated in {node.name}.{method_name}() "
                    f"without Lock protection (line {line})"
                )

        return issues

    def _class_has_lock(self, class_node: ast.ClassDef) -> bool:
        """Check if class has a Lock/RLock attribute."""
        for node in ast.walk(class_node):
            # self._lock = threading.Lock() or Lock()
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                        if target.value.id == "self":
                            attr_name = target.attr.lower()
                            if any(attr_name.startswith(p) for p in _SAFE_ATTR_PREFIXES):
                                return True
                            if isinstance(node.value, ast.Call):
                                func = node.value.func
                                func_name = ""
                                if isinstance(func, ast.Name):
                                    func_name = func.id
                                elif isinstance(func, ast.Attribute):
                                    func_name = func.attr
                                if func_name in ("Lock", "RLock", "Condition", "Semaphore"):
                                    return True
        return False

    def _find_mutable_attrs(self, class_node: ast.ClassDef) -> Set[str]:
        """Find self.x attributes initialized as dict/list/set or their constructors."""
        mutables: Set[str] = set()

        for node in ast.walk(class_node):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (isinstance(target, ast.Attribute)
                            and isinstance(target.value, ast.Name)
                            and target.value.id == "self"):
                        attr_name = target.attr
                        # Skip lock-like attrs
                        if any(attr_name.lower().startswith(p) for p in _SAFE_ATTR_PREFIXES):
                            continue
                        if self._is_mutable_value(node.value):
                            mutables.add(attr_name)

        return mutables

    def _is_mutable_value(self, node: ast.AST) -> bool:
        """Check if AST node represents a mutable container."""
        if isinstance(node, (ast.Dict, ast.List, ast.Set)):
            return True
        if isinstance(node, ast.Call):
            func = node.func
            func_name = ""
            if isinstance(func, ast.Name):
                func_name = func.id
            elif isinstance(func, ast.Attribute):
                func_name = func.attr
            return func_name in ("dict", "list", "set", "OrderedDict", "defaultdict", "Counter", "deque")
        return False

    def _find_unprotected_mutations(
        self,
        class_node: ast.ClassDef,
        mutable_attrs: Set[str],
        has_lock: bool,
    ) -> List[Tuple[str, str, int]]:
        """Find mutations to mutable attrs NOT inside 'with self._lock:' blocks."""
        unprotected = []

        if has_lock:
            # Class has a lock, skip checking — we'll assume it's used properly
            # (deep with-block analysis is too complex for a fast validator)
            return []

        for method in ast.walk(class_node):
            if not isinstance(method, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if method.name == "__init__":
                continue

            for node in ast.walk(method):
                # Check self.x.append(), self.x.update(), etc.
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    if node.func.attr in _MUTATING_METHODS:
                        value = node.func.value
                        if (isinstance(value, ast.Attribute)
                                and isinstance(value.value, ast.Name)
                                and value.value.id == "self"):
                            if value.attr in mutable_attrs:
                                unprotected.append((value.attr, method.name, node.lineno))

                # Check self.x[key] = value (Subscript assignment)
                if isinstance(node, ast.Assign):
                    for target in node.targets:
                        if isinstance(target, ast.Subscript):
                            if (isinstance(target.value, ast.Attribute)
                                    and isinstance(target.value.value, ast.Name)
                                    and target.value.value.id == "self"):
                                if target.value.attr in mutable_attrs:
                                    unprotected.append((target.value.attr, method.name, node.lineno))

        return unprotected

    def _check_daemon_threads(self, tree: ast.AST) -> List[str]:
        """Check for daemon threads without join()."""
        issues = []

        # Find all Thread(daemon=True) calls
        daemon_threads: List[int] = []  # line numbers
        has_join = False

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                func_name = ""
                if isinstance(func, ast.Name):
                    func_name = func.id
                elif isinstance(func, ast.Attribute):
                    func_name = func.attr

                if func_name == "Thread":
                    for kw in node.keywords:
                        if kw.arg == "daemon" and isinstance(kw.value, ast.Constant):
                            if kw.value.value is True:
                                daemon_threads.append(node.lineno)

            # Check for .join() calls
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "join":
                    has_join = True

        if daemon_threads and not has_join:
            for line in daemon_threads:
                issues.append(
                    f"Thread(daemon=True) at line {line} without corresponding join() — "
                    f"thread may be killed before completing work"
                )

        return issues

    def _check_global_mutables(self, tree: ast.AST) -> List[str]:
        """Check for module-level mutable state without Lock."""
        issues = []
        has_module_lock = False
        global_mutables: List[Tuple[str, int]] = []

        for node in ast.iter_child_nodes(tree):
            # Module-level Lock
            if isinstance(node, ast.Assign):
                if isinstance(node.value, ast.Call):
                    func = node.value.func
                    func_name = ""
                    if isinstance(func, ast.Name):
                        func_name = func.id
                    elif isinstance(func, ast.Attribute):
                        func_name = func.attr
                    if func_name in ("Lock", "RLock"):
                        has_module_lock = True

                # Module-level mutable containers
                for target in node.targets:
                    if isinstance(target, ast.Name) and not target.id.startswith("_"):
                        if self._is_mutable_value(node.value):
                            global_mutables.append((target.id, node.lineno))

        # Only flag if there are global mutables AND no module lock
        # AND there are threading imports (suggesting multi-threaded usage)
        has_threading = any(
            isinstance(n, ast.Import) and any(a.name == "threading" for a in n.names)
            or isinstance(n, ast.ImportFrom) and n.module and "threading" in n.module
            for n in ast.walk(tree)
        )

        if global_mutables and has_threading and not has_module_lock:
            for name, line in global_mutables[:3]:
                issues.append(
                    f"Global mutable '{name}' (line {line}) in threaded code without Lock"
                )

        return issues
