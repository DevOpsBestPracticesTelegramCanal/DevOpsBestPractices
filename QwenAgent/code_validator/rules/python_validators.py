"""
Python-specific validation rules.

All rules are in-process only (no subprocess calls) for speed.
They complement the existing 5-level CodeValidator pipeline by providing
fast, fine-grained scoring that feeds the Multi-Candidate selector.
"""

import ast
import re
from typing import List, Optional, Set

from .base import Rule, RuleResult, RuleSeverity


# ---------------------------------------------------------------------------
# 1. AST Syntax — the most critical rule
# ---------------------------------------------------------------------------

class ASTSyntaxRule(Rule):
    """Code must parse as valid Python."""

    name = "ast_syntax"
    severity = RuleSeverity.CRITICAL
    weight = 10.0

    def check(self, code: str) -> RuleResult:
        try:
            ast.parse(code)
            return self._ok(1.0)
        except SyntaxError as exc:
            msg = f"SyntaxError at line {exc.lineno}: {exc.msg}"
            return self._fail(0.0, [msg])


# ---------------------------------------------------------------------------
# 2. Forbidden Imports
# ---------------------------------------------------------------------------

class NoForbiddenImportsRule(Rule):
    """No dangerous module imports (os, subprocess, socket, etc.)."""

    name = "no_forbidden_imports"
    severity = RuleSeverity.ERROR
    weight = 5.0

    DEFAULT_FORBIDDEN: Set[str] = {
        "os", "sys", "subprocess", "shutil",
        "socket", "ctypes", "pickle", "marshal",
    }

    def __init__(self, forbidden: Optional[Set[str]] = None):
        self.forbidden = forbidden or self.DEFAULT_FORBIDDEN

    def check(self, code: str) -> RuleResult:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            # AST rule will catch this — don't double-count
            return self._ok(1.0, ["Skipped: code has syntax errors"])

        found: List[str] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    root_mod = alias.name.split(".")[0]
                    if root_mod in self.forbidden:
                        found.append(f"import {alias.name} (line {node.lineno})")

            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    root_mod = node.module.split(".")[0]
                    if root_mod in self.forbidden:
                        found.append(f"from {node.module} import ... (line {node.lineno})")

        if found:
            return self._fail(0.0, [f"Forbidden import: {f}" for f in found])
        return self._ok(1.0)


# ---------------------------------------------------------------------------
# 3. Docstrings
# ---------------------------------------------------------------------------

class DocstringRule(Rule):
    """
    Functions and classes should have docstrings.

    Score = ratio of documented / total definitions.
    """

    name = "docstring"
    severity = RuleSeverity.WARNING
    weight = 0.5

    def check(self, code: str) -> RuleResult:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return self._ok(1.0, ["Skipped: syntax errors"])

        total = 0
        documented = 0
        missing: List[str] = []

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                total += 1
                docstring = ast.get_docstring(node)
                if docstring:
                    documented += 1
                else:
                    missing.append(f"{node.name} (line {node.lineno})")

        if total == 0:
            return self._ok(1.0, ["No functions/classes found"])

        ratio = documented / total
        passed = ratio >= 0.5  # at least half documented

        msgs = [f"Missing docstring: {m}" for m in missing] if missing else []
        return RuleResult(
            rule_name=self.name,
            passed=passed,
            score=round(ratio, 2),
            severity=self.severity,
            messages=msgs,
        )


# ---------------------------------------------------------------------------
# 4. Type Hints
# ---------------------------------------------------------------------------

class TypeHintRule(Rule):
    """
    Functions should have return type annotations.

    Score = ratio of annotated / total functions.
    """

    name = "type_hints"
    severity = RuleSeverity.WARNING
    weight = 1.0

    def check(self, code: str) -> RuleResult:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return self._ok(1.0, ["Skipped: syntax errors"])

        total = 0
        annotated = 0
        missing: List[str] = []

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                # Skip private helpers (but keep public-facing ones)
                if node.name.startswith("_") and not node.name.startswith("__"):
                    continue
                # __init__ never needs a return annotation
                if node.name == "__init__":
                    continue
                total += 1
                if node.returns is not None:
                    annotated += 1
                else:
                    missing.append(f"{node.name} (line {node.lineno})")

        if total == 0:
            return self._ok(1.0, ["No functions found"])

        ratio = annotated / total
        passed = ratio >= 0.3  # lenient threshold

        msgs = [f"No return annotation: {m}" for m in missing[:5]] if missing else []
        return RuleResult(
            rule_name=self.name,
            passed=passed,
            score=round(ratio, 2),
            severity=self.severity,
            messages=msgs,
        )


# ---------------------------------------------------------------------------
# 5. Cyclomatic Complexity (simple approximation)
# ---------------------------------------------------------------------------

class ComplexityRule(Rule):
    """
    Approximate cyclomatic complexity per function.

    Counts branching nodes: if, for, while, except, with, and, or, assert.
    Score = 1.0 if all functions ≤ threshold, degrades for higher values.
    """

    name = "complexity"
    severity = RuleSeverity.WARNING
    weight = 1.5

    BRANCH_NODES = (
        ast.If, ast.For, ast.While, ast.ExceptHandler,
        ast.With, ast.Assert,
    )

    def __init__(self, max_complexity: int = 15):
        self.max_complexity = max_complexity

    def check(self, code: str) -> RuleResult:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return self._ok(1.0, ["Skipped: syntax errors"])

        high: List[str] = []
        max_seen = 0

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                cc = self._function_complexity(node)
                max_seen = max(max_seen, cc)
                if cc > self.max_complexity:
                    high.append(
                        f"{node.name}: complexity {cc} > {self.max_complexity} "
                        f"(line {node.lineno})"
                    )

        if not high:
            # Scale score: 0 branches → 1.0, at threshold → 0.7
            if max_seen == 0:
                score = 1.0
            else:
                score = max(0.3, 1.0 - (max_seen / self.max_complexity) * 0.3)
            return self._ok(round(score, 2))

        score = max(0.0, 1.0 - len(high) * 0.3)
        return RuleResult(
            rule_name=self.name,
            passed=False,
            score=round(score, 2),
            severity=self.severity,
            messages=high,
        )

    def _function_complexity(self, func_node: ast.AST) -> int:
        """Count branching statements inside a function."""
        count = 1  # base path
        for node in ast.walk(func_node):
            if isinstance(node, self.BRANCH_NODES):
                count += 1
            elif isinstance(node, ast.BoolOp):
                # and/or add branches
                count += len(node.values) - 1
        return count


# ---------------------------------------------------------------------------
# 6. Code Length
# ---------------------------------------------------------------------------

class CodeLengthRule(Rule):
    """
    Code should not be empty or excessively long.

    Reasonable range: 1 – 500 lines for a single generation.
    """

    name = "code_length"
    severity = RuleSeverity.ERROR
    weight = 2.0

    def __init__(self, min_lines: int = 1, max_lines: int = 500):
        self.min_lines = min_lines
        self.max_lines = max_lines

    def check(self, code: str) -> RuleResult:
        lines = code.strip().splitlines()
        n = len(lines)

        if n < self.min_lines:
            return self._fail(0.0, [f"Code is empty or too short ({n} lines)"])

        if n > self.max_lines:
            score = max(0.2, 1.0 - (n - self.max_lines) / self.max_lines)
            return self._fail(
                round(score, 2),
                [f"Code too long: {n} lines (max {self.max_lines})"],
            )

        # Score gently: very short code is slightly penalized
        if n < 3:
            return self._ok(0.7, [f"Very short code ({n} lines)"])

        return self._ok(1.0)


# ---------------------------------------------------------------------------
# 7. OSS Pattern Alignment
# ---------------------------------------------------------------------------

class OSSPatternRule(Rule):
    """Score code based on alignment with OSS pattern consensus.

    Checks for common patterns found in top open-source Python projects:
    type hints, docstrings, error handling, logging, async patterns,
    dataclasses, and pathlib usage.

    Advisory only — doesn't block, only influences selection scoring.
    """

    name = "oss_patterns"
    severity = RuleSeverity.INFO
    weight = 1.5

    _POSITIVE_PATTERNS = {
        "type_hints": r"def\s+\w+\([^)]*:\s*\w+",          # type annotations
        "docstrings": r'""".*?"""',                           # docstrings
        "error_handling": r"try:\s*\n",                       # try/except
        "logging": r"import logging|logger\s*=",              # logging setup
        "async_patterns": r"async\s+def",                     # async code
        "dataclass": r"@dataclass",                           # dataclasses
        "pathlib": r"from pathlib|Path\(",                    # pathlib over os.path
    }

    def check(self, code: str) -> RuleResult:
        found = sum(1 for p in self._POSITIVE_PATTERNS.values()
                    if re.search(p, code, re.DOTALL))
        total = len(self._POSITIVE_PATTERNS)
        # 40% coverage = perfect score (not every snippet needs all patterns)
        score = min(found / max(total * 0.4, 1), 1.0)
        return self._ok(
            round(score, 2),
            [f"OSS alignment: {found}/{total} patterns detected"],
        )


# ---------------------------------------------------------------------------
# 8. No eval/exec
# ---------------------------------------------------------------------------

class NoEvalExecRule(Rule):
    """No use of eval() or exec() — security rule."""

    name = "no_eval_exec"
    severity = RuleSeverity.CRITICAL
    weight = 8.0

    DANGEROUS = {"eval", "exec", "compile", "__import__"}

    def check(self, code: str) -> RuleResult:
        try:
            tree = ast.parse(code)
        except SyntaxError:
            return self._ok(1.0, ["Skipped: syntax errors"])

        found: List[str] = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func_name = None
                if isinstance(node.func, ast.Name):
                    func_name = node.func.id
                elif isinstance(node.func, ast.Attribute):
                    func_name = node.func.attr

                if func_name and func_name in self.DANGEROUS:
                    found.append(f"{func_name}() at line {node.lineno}")

        if found:
            return self._fail(0.0, [f"Dangerous call: {f}" for f in found])
        return self._ok(1.0)


# ---------------------------------------------------------------------------
# Default rule set
# ---------------------------------------------------------------------------

def default_python_rules() -> list[Rule]:
    """Return the standard set of Python rules."""
    return [
        ASTSyntaxRule(),
        NoForbiddenImportsRule(),
        NoEvalExecRule(),
        CodeLengthRule(),
        ComplexityRule(),
        DocstringRule(),
        TypeHintRule(),
        OSSPatternRule(),
    ]
