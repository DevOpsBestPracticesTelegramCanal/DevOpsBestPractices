"""
Уровень 0: Превалидация кода без выполнения.

Проверяет:
- Синтаксическую корректность (ast.parse)
- Запрещённые конструкции (import os, eval, exec и т.д.)
- Потенциально опасные паттерны
- Ограничения по размеру кода
"""

import ast
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class Severity(Enum):
    """Уровень серьёзности проблемы."""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class Issue:
    """Найденная проблема в коде."""
    severity: Severity
    message: str
    line: int | None = None
    column: int | None = None
    code: str = ""  # Код правила, например "PV001"
    
    def __str__(self) -> str:
        location = f"[{self.line}:{self.column}]" if self.line else ""
        return f"{self.severity.value.upper()} {self.code} {location}: {self.message}"


@dataclass
class PrevalidationResult:
    """Результат превалидации."""
    is_valid: bool
    issues: list[Issue] = field(default_factory=list)
    ast_tree: ast.AST | None = None
    
    @property
    def has_critical(self) -> bool:
        return any(i.severity == Severity.CRITICAL for i in self.issues)
    
    @property
    def has_errors(self) -> bool:
        return any(i.severity in (Severity.ERROR, Severity.CRITICAL) for i in self.issues)


# Запрещённые модули по умолчанию
DEFAULT_FORBIDDEN_IMPORTS = frozenset({
    "os", "sys", "subprocess", "shutil", "pathlib",
    "socket", "requests", "urllib", "http",
    "ctypes", "multiprocessing", "threading",
    "pickle", "shelve", "marshal",
    "importlib", "runpy", "__builtin__", "builtins",
    "code", "codeop", "compileall",
})

# Запрещённые встроенные функции
DEFAULT_FORBIDDEN_BUILTINS = frozenset({
    "eval", "exec", "compile", "open", "input",
    "__import__", "globals", "locals", "vars",
    "getattr", "setattr", "delattr", "hasattr",
    "breakpoint", "help", "exit", "quit",
})

# Запрещённые атрибуты (dunder-методы для обхода ограничений)
DEFAULT_FORBIDDEN_ATTRIBUTES = frozenset({
    "__code__", "__globals__", "__builtins__",
    "__subclasses__", "__bases__", "__mro__",
    "__class__", "__dict__", "__module__",
    "__import__", "__loader__", "__spec__",
})


class ForbiddenPatternVisitor(ast.NodeVisitor):
    """AST-визитор для поиска запрещённых паттернов."""
    
    def __init__(
        self,
        forbidden_imports: frozenset[str] = DEFAULT_FORBIDDEN_IMPORTS,
        forbidden_builtins: frozenset[str] = DEFAULT_FORBIDDEN_BUILTINS,
        forbidden_attributes: frozenset[str] = DEFAULT_FORBIDDEN_ATTRIBUTES,
    ):
        self.forbidden_imports = forbidden_imports
        self.forbidden_builtins = forbidden_builtins
        self.forbidden_attributes = forbidden_attributes
        self.issues: list[Issue] = []
    
    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            module_name = alias.name.split('.')[0]
            if module_name in self.forbidden_imports:
                self.issues.append(Issue(
                    severity=Severity.CRITICAL,
                    message=f"Запрещённый импорт: {alias.name}",
                    line=node.lineno,
                    column=node.col_offset,
                    code="PV001",
                ))
        self.generic_visit(node)
    
    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module:
            module_name = node.module.split('.')[0]
            if module_name in self.forbidden_imports:
                self.issues.append(Issue(
                    severity=Severity.CRITICAL,
                    message=f"Запрещённый импорт из модуля: {node.module}",
                    line=node.lineno,
                    column=node.col_offset,
                    code="PV001",
                ))
        self.generic_visit(node)
    
    def visit_Call(self, node: ast.Call) -> None:
        # Проверка вызовов запрещённых функций
        if isinstance(node.func, ast.Name):
            if node.func.id in self.forbidden_builtins:
                self.issues.append(Issue(
                    severity=Severity.CRITICAL,
                    message=f"Запрещённая функция: {node.func.id}()",
                    line=node.lineno,
                    column=node.col_offset,
                    code="PV002",
                ))
        self.generic_visit(node)
    
    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr in self.forbidden_attributes:
            self.issues.append(Issue(
                severity=Severity.CRITICAL,
                message=f"Запрещённый атрибут: {node.attr}",
                line=node.lineno,
                column=node.col_offset,
                code="PV003",
            ))
        self.generic_visit(node)
    
    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        # Предупреждение о рекурсии без базового случая (эвристика)
        self._check_recursion(node)
        self.generic_visit(node)
    
    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._check_recursion(node)
        self.generic_visit(node)
    
    def _check_recursion(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """Эвристическая проверка на потенциально бесконечную рекурсию."""
        func_name = node.name
        has_return = False
        has_self_call = False
        
        for child in ast.walk(node):
            if isinstance(child, ast.Return) and child.value is not None:
                has_return = True
            if isinstance(child, ast.Call):
                if isinstance(child.func, ast.Name) and child.func.id == func_name:
                    has_self_call = True
        
        if has_self_call and not has_return:
            self.issues.append(Issue(
                severity=Severity.WARNING,
                message=f"Функция '{func_name}' вызывает себя без явного return — возможна бесконечная рекурсия",
                line=node.lineno,
                column=node.col_offset,
                code="PV004",
            ))
    
    def visit_While(self, node: ast.While) -> None:
        # Проверка while True без break
        if isinstance(node.test, ast.Constant) and node.test.value is True:
            has_break = any(isinstance(n, ast.Break) for n in ast.walk(node))
            if not has_break:
                self.issues.append(Issue(
                    severity=Severity.WARNING,
                    message="Цикл 'while True' без break — возможен бесконечный цикл",
                    line=node.lineno,
                    column=node.col_offset,
                    code="PV005",
                ))
        self.generic_visit(node)


class Prevalidator:
    """Превалидатор Python-кода."""
    
    def __init__(
        self,
        max_code_length: int = 50_000,
        max_lines: int = 1000,
        max_complexity: int = 50,  # Максимальная вложенность
        forbidden_imports: frozenset[str] | None = None,
        forbidden_builtins: frozenset[str] | None = None,
        forbidden_attributes: frozenset[str] | None = None,
        custom_validators: list[Callable[[ast.AST], list[Issue]]] | None = None,
    ):
        self.max_code_length = max_code_length
        self.max_lines = max_lines
        self.max_complexity = max_complexity
        self.forbidden_imports = forbidden_imports or DEFAULT_FORBIDDEN_IMPORTS
        self.forbidden_builtins = forbidden_builtins or DEFAULT_FORBIDDEN_BUILTINS
        self.forbidden_attributes = forbidden_attributes or DEFAULT_FORBIDDEN_ATTRIBUTES
        self.custom_validators = custom_validators or []
    
    def validate(self, code: str) -> PrevalidationResult:
        """Выполнить полную превалидацию кода."""
        issues: list[Issue] = []
        
        # 1. Проверка размера
        issues.extend(self._check_size(code))
        if any(i.severity == Severity.CRITICAL for i in issues):
            return PrevalidationResult(is_valid=False, issues=issues)
        
        # 2. Проверка на опасные строковые паттерны (до парсинга)
        issues.extend(self._check_string_patterns(code))
        
        # 3. Парсинг AST
        try:
            tree = ast.parse(code)
        except SyntaxError as e:
            issues.append(Issue(
                severity=Severity.CRITICAL,
                message=f"Синтаксическая ошибка: {e.msg}",
                line=e.lineno,
                column=e.offset,
                code="PV000",
            ))
            return PrevalidationResult(is_valid=False, issues=issues)
        
        # 4. Проверка глубины вложенности
        issues.extend(self._check_nesting_depth(tree))
        
        # 5. Поиск запрещённых паттернов через AST
        visitor = ForbiddenPatternVisitor(
            self.forbidden_imports,
            self.forbidden_builtins,
            self.forbidden_attributes,
        )
        visitor.visit(tree)
        issues.extend(visitor.issues)
        
        # 6. Кастомные валидаторы
        for validator in self.custom_validators:
            issues.extend(validator(tree))
        
        is_valid = not any(i.severity in (Severity.CRITICAL, Severity.ERROR) for i in issues)
        return PrevalidationResult(is_valid=is_valid, issues=issues, ast_tree=tree)
    
    def _check_size(self, code: str) -> list[Issue]:
        """Проверка ограничений по размеру."""
        issues = []
        
        if len(code) > self.max_code_length:
            issues.append(Issue(
                severity=Severity.CRITICAL,
                message=f"Код слишком большой: {len(code)} символов (макс: {self.max_code_length})",
                code="PV010",
            ))
        
        lines = code.count('\n') + 1
        if lines > self.max_lines:
            issues.append(Issue(
                severity=Severity.CRITICAL,
                message=f"Слишком много строк: {lines} (макс: {self.max_lines})",
                code="PV011",
            ))
        
        return issues
    
    def _check_string_patterns(self, code: str) -> list[Issue]:
        """Проверка опасных паттернов в строках (до парсинга AST)."""
        issues = []
        
        # Паттерны обхода sandbox через строки
        dangerous_patterns = [
            (r'__\w+__', "PV020", "Обнаружен dunder-паттерн в строке"),
            (r'\bos\s*\.\s*system', "PV021", "Вызов os.system"),
            (r'\bsubprocess', "PV022", "Использование subprocess"),
            (r'chr\s*\(\s*\d+\s*\)', "PV023", "Потенциальное формирование строки через chr()"),
        ]
        
        for pattern, code_id, message in dangerous_patterns:
            matches = list(re.finditer(pattern, code))
            for match in matches[:3]:  # Ограничиваем количество отчётов
                line_num = code[:match.start()].count('\n') + 1
                issues.append(Issue(
                    severity=Severity.WARNING,
                    message=f"{message}: '{match.group()}'",
                    line=line_num,
                    code=code_id,
                ))
        
        return issues
    
    def _check_nesting_depth(self, tree: ast.AST) -> list[Issue]:
        """Проверка глубины вложенности."""
        issues = []
        
        def get_depth(node: ast.AST, current_depth: int = 0) -> int:
            max_depth = current_depth
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, 
                                     ast.ClassDef, ast.For, ast.While, 
                                     ast.If, ast.With, ast.Try)):
                    child_depth = get_depth(child, current_depth + 1)
                    max_depth = max(max_depth, child_depth)
                else:
                    child_depth = get_depth(child, current_depth)
                    max_depth = max(max_depth, child_depth)
            return max_depth
        
        depth = get_depth(tree)
        if depth > self.max_complexity:
            issues.append(Issue(
                severity=Severity.ERROR,
                message=f"Слишком глубокая вложенность: {depth} уровней (макс: {self.max_complexity})",
                code="PV012",
            ))
        
        return issues


def prevalidate(code: str, **kwargs) -> PrevalidationResult:
    """Функция-обёртка для быстрой превалидации."""
    validator = Prevalidator(**kwargs)
    return validator.validate(code)
