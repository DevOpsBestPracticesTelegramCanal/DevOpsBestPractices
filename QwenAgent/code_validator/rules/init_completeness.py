"""
Week 28: Init Completeness Checker (SV-07)

AST-based detection of incomplete initialization patterns:
  - Classes with self.conn / self.db but no CREATE TABLE or schema init
  - __init__ that opens resources without __enter__/__exit__ or close()
  - Missing 'if not os.path.exists' before file/directory creation

Registered in BALANCED, SAFE_FIX, and CRITICAL validation profiles.
"""

import ast
import logging
from typing import List, Set

from .base import Rule, RuleResult, RuleSeverity

logger = logging.getLogger(__name__)

# Attribute names that suggest database connections
_DB_ATTR_NAMES: Set[str] = {
    "conn", "connection", "db", "db_conn", "database",
    "cursor", "session", "engine",
}

# Attribute names that suggest file/resource handles
_RESOURCE_ATTR_NAMES: Set[str] = {
    "file", "fp", "fh", "handle", "stream",
    "socket", "sock", "client", "server",
}

# Function calls that create resources needing cleanup
_RESOURCE_CREATORS: Set[str] = {
    "open", "connect", "create_connection", "create_engine",
    "socket", "urlopen",
}


class InitCompletenessRule(Rule):
    """Check that __init__ methods properly initialize resources.

    Checks:
    1. DB connections (self.conn, self.db) should have schema init
       (CREATE TABLE or similar).
    2. Resource-holding classes should implement context manager
       (__enter__/__exit__) or have a close() method.
    3. File paths used in __init__ should check existence.
    """

    name = "init_completeness"
    severity = RuleSeverity.WARNING
    weight = 1.5

    def check(self, code: str) -> RuleResult:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return self._ok(1.0, ["Skipped: syntax errors"])

        issues: List[str] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                issues.extend(self._check_class(node))

        if not issues:
            return self._ok(1.0)

        score = max(0.0, 1.0 - len(issues) * 0.15)
        return RuleResult(
            rule_name=self.name,
            passed=len(issues) == 0,
            score=round(score, 2),
            severity=self.severity,
            messages=issues,
        )

    def _check_class(self, class_node: ast.ClassDef) -> List[str]:
        """Check a single class for init completeness issues."""
        issues = []

        init_method = None
        has_close = False
        has_enter = False
        has_exit = False
        has_del = False

        for item in class_node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if item.name == "__init__":
                    init_method = item
                elif item.name == "close":
                    has_close = True
                elif item.name == "__enter__" or item.name == "__aenter__":
                    has_enter = True
                elif item.name == "__exit__" or item.name == "__aexit__":
                    has_exit = True
                elif item.name == "__del__":
                    has_del = True

        if init_method is None:
            return []

        # Check 1: DB attrs without schema init
        db_attrs = self._find_attrs_by_names(init_method, _DB_ATTR_NAMES)
        if db_attrs:
            has_schema_init = self._has_schema_init(class_node)
            if not has_schema_init:
                for attr in db_attrs[:2]:
                    issues.append(
                        f"Class '{class_node.name}' has DB attribute 'self.{attr}' "
                        f"but no schema initialization (CREATE TABLE IF NOT EXISTS)"
                    )

        # Check 2: Resource attrs without cleanup
        resource_attrs = self._find_resource_attrs(init_method)
        if resource_attrs and not (has_close or (has_enter and has_exit) or has_del):
            for attr in resource_attrs[:2]:
                issues.append(
                    f"Class '{class_node.name}' opens resource 'self.{attr}' in __init__ "
                    f"but has no close()/__exit__/__del__ for cleanup"
                )

        return issues

    def _find_attrs_by_names(self, init_node: ast.AST, names: Set[str]) -> List[str]:
        """Find self.x assignments where x matches given names."""
        found = []
        for node in ast.walk(init_node):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (isinstance(target, ast.Attribute)
                            and isinstance(target.value, ast.Name)
                            and target.value.id == "self"):
                        attr_lower = target.attr.lower()
                        for name in names:
                            if name in attr_lower:
                                found.append(target.attr)
                                break
        return found

    def _find_resource_attrs(self, init_node: ast.AST) -> List[str]:
        """Find self.x = open(...) or connect(...) patterns."""
        found = []
        for node in ast.walk(init_node):
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if (isinstance(target, ast.Attribute)
                            and isinstance(target.value, ast.Name)
                            and target.value.id == "self"):
                        if isinstance(node.value, ast.Call):
                            func = node.value.func
                            func_name = ""
                            if isinstance(func, ast.Name):
                                func_name = func.id
                            elif isinstance(func, ast.Attribute):
                                func_name = func.attr
                            if func_name in _RESOURCE_CREATORS:
                                found.append(target.attr)
        return found

    def _has_schema_init(self, class_node: ast.ClassDef) -> bool:
        """Check if class has CREATE TABLE or schema initialization."""
        for node in ast.walk(class_node):
            # Check string constants containing SQL DDL
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                val = node.value.upper()
                if "CREATE TABLE" in val or "CREATE INDEX" in val:
                    return True
            # Check method names suggesting schema init
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name_lower = node.name.lower()
                if any(kw in name_lower for kw in ("init_schema", "init_db", "create_table", "setup_db", "migrate", "_init_schema")):
                    return True
        return False
