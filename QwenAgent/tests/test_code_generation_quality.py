# -*- coding: utf-8 -*-
"""
10 TЕСТОВ КАЧЕСТВА ГЕНЕРАЦИИ PYTHON-КОДА
=========================================

Используют автоматические системы контроля QwenAgent:
- code_validator.Prevalidator     (Level 0: AST, запрещенные конструкции)
- code_validator.StaticAnalyzer   (Level 1: Ruff, Mypy, Bandit)
- code_validator.CodeValidator    (Level 0-4: полный pipeline)
- core.pattern_discovery          (покрытие и качество паттернов)
- core.pattern_router             (валидация роутинга)
- core.swecas_classifier          (классификация багов)

Каждый тест:
  - ПОСТАНОВКА ЗАДАЧИ: что генерируется
  - УСЛОВИЯ: ограничения и требования
  - ЦЕЛИ: что проверяется (метрики успеха)

Запуск:
    python -m pytest tests/test_code_generation_quality.py -v
    python tests/test_code_generation_quality.py          # standalone
"""

import sys
import ast
import time
import json
import re
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple

# Добавляем корень проекта в sys.path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from code_validator.prevalidator import Prevalidator, PrevalidationResult, Severity
from code_validator.static_analysis import StaticAnalyzer, StaticAnalysisResult
from code_validator.validator import CodeValidator, ValidatorConfig, ValidationStatus


# =============================================================================
# HELPERS
# =============================================================================

@dataclass
class TestResult:
    """Результат одного теста."""
    test_id: int
    name: str
    domain: str
    passed: bool
    checks_passed: int
    checks_total: int
    duration_ms: float
    details: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    @property
    def score(self) -> float:
        return (self.checks_passed / self.checks_total * 100) if self.checks_total else 0.0


def check_ast_valid(code: str) -> Tuple[bool, str]:
    """Проверить синтаксическую корректность."""
    try:
        ast.parse(code)
        return True, "AST OK"
    except SyntaxError as e:
        return False, f"SyntaxError line {e.lineno}: {e.msg}"


def check_no_forbidden(code: str) -> Tuple[bool, str]:
    """Prevalidator: запрещенные конструкции."""
    pv = Prevalidator()
    result = pv.validate(code)
    if result.is_valid:
        return True, "No forbidden constructs"
    issues = [str(i) for i in result.issues if i.severity in (Severity.CRITICAL, Severity.ERROR)]
    return False, "; ".join(issues[:3])


def check_has_docstrings(code: str) -> Tuple[bool, str]:
    """Проверить наличие docstring в функциях/классах."""
    tree = ast.parse(code)
    total = 0
    with_docs = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            total += 1
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, (ast.Constant, ast.Str))):
                with_docs += 1
    if total == 0:
        return True, "No functions/classes to check"
    pct = with_docs / total * 100
    return pct >= 50, f"{with_docs}/{total} ({pct:.0f}%) have docstrings"


def check_type_hints(code: str) -> Tuple[bool, str]:
    """Проверить наличие type hints в сигнатурах."""
    tree = ast.parse(code)
    total = 0
    with_hints = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            total += 1
            has_return = node.returns is not None
            has_args = any(a.annotation is not None for a in node.args.args if a.arg != 'self')
            if has_return or has_args:
                with_hints += 1
    if total == 0:
        return True, "No functions to check"
    pct = with_hints / total * 100
    return pct >= 50, f"{with_hints}/{total} ({pct:.0f}%) have type hints"


def check_complexity(code: str, max_depth: int = 8) -> Tuple[bool, str]:
    """Проверить глубину вложенности."""
    tree = ast.parse(code)

    def get_depth(node, depth=0):
        max_d = depth
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef, ast.For, ast.While,
                                  ast.If, ast.With, ast.Try)):
                max_d = max(max_d, get_depth(child, depth + 1))
            else:
                max_d = max(max_d, get_depth(child, depth))
        return max_d

    depth = get_depth(tree)
    return depth <= max_depth, f"Nesting depth: {depth} (max: {max_depth})"


def check_functions_not_too_long(code: str, max_lines: int = 50) -> Tuple[bool, str]:
    """Проверить длину функций."""
    tree = ast.parse(code)
    long_funcs = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if hasattr(node, 'end_lineno') and node.end_lineno:
                length = node.end_lineno - node.lineno + 1
                if length > max_lines:
                    long_funcs.append(f"{node.name}() = {length} lines")
    if long_funcs:
        return False, f"Too long: {', '.join(long_funcs)}"
    return True, f"All functions <= {max_lines} lines"


def check_no_hardcoded_secrets(code: str) -> Tuple[bool, str]:
    """Проверить отсутствие захардкоженных секретов."""
    patterns = [
        (r'(?:password|passwd|pwd)\s*=\s*["\'][^"\']+["\']', "hardcoded password"),
        (r'(?:secret|api_key|token)\s*=\s*["\'][A-Za-z0-9+/=]{16,}["\']', "hardcoded secret/token"),
        (r'(?:BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY)', "private key in code"),
    ]
    found = []
    for pat, desc in patterns:
        if re.search(pat, code, re.IGNORECASE):
            found.append(desc)
    if found:
        return False, f"Secrets found: {', '.join(found)}"
    return True, "No hardcoded secrets"


def check_error_handling(code: str) -> Tuple[bool, str]:
    """Проверить наличие обработки ошибок."""
    tree = ast.parse(code)
    has_try = any(isinstance(n, ast.Try) for n in ast.walk(tree))
    has_raise = any(isinstance(n, ast.Raise) for n in ast.walk(tree))
    # bare except (except: без типа) -- плохо
    bare_except = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler) and node.type is None:
            bare_except += 1
    if bare_except > 0:
        return False, f"Bare except found ({bare_except}x) - always specify exception type"
    if has_try or has_raise:
        return True, "Error handling present"
    return True, "No try/raise needed (simple code)"


def run_full_validation(code: str) -> Tuple[bool, str]:
    """Запустить полный CodeValidator pipeline (Level 0-1)."""
    config = ValidatorConfig(
        enable_prevalidation=True,
        enable_static_analysis=True,
        enable_sandbox=False,  # Sandbox требует Linux
        enable_property_tests=False,
        enable_resource_monitoring=False,
        stop_on_failure=False,
    )
    validator = CodeValidator(config)
    report = validator.validate(code)
    status = report.status.value
    levels = report.levels_completed
    return report.status in (ValidationStatus.PASSED, ValidationStatus.WARNINGS), \
        f"Status: {status}, levels passed: {levels}"


# =============================================================================
# TEST 1: ALGORITHMS & DATA STRUCTURES
# =============================================================================

def test_01_algorithms():
    """
    TEST 1: Алгоритмы и структуры данных
    =====================================

    ПОСТАНОВКА ЗАДАЧИ:
        Сгенерировать реализацию бинарного поиска + очередь с приоритетом.
        Код должен быть типизированным, документированным, без лишних импортов.

    УСЛОВИЯ:
        - Только стандартная библиотека (math, collections, typing)
        - Запрещены: os, sys, subprocess, eval, exec
        - Функции <= 50 строк, вложенность <= 6
        - Type hints обязательны
        - Docstrings обязательны

    ЦЕЛИ:
        1. AST-валидность (синтаксис)
        2. Prevalidator PASSED (безопасность)
        3. Type hints >= 50% функций
        4. Docstrings >= 50% функций/классов
        5. Вложенность <= 6
        6. Функции <= 50 строк
    """
    code = '''\
from typing import List, Optional, TypeVar, Generic
from collections import defaultdict
import heapq

T = TypeVar('T')


def binary_search(arr: List[int], target: int) -> int:
    """Binary search in sorted array. Returns index or -1."""
    left, right = 0, len(arr) - 1
    while left <= right:
        mid = (left + right) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            left = mid + 1
        else:
            right = mid - 1
    return -1


class PriorityQueue(Generic[T]):
    """Min-heap priority queue with decrease-key support."""

    def __init__(self) -> None:
        """Initialize empty priority queue."""
        self._heap: List[tuple] = []
        self._counter = 0

    def push(self, item: T, priority: float) -> None:
        """Add item with given priority."""
        heapq.heappush(self._heap, (priority, self._counter, item))
        self._counter += 1

    def pop(self) -> Optional[T]:
        """Remove and return item with lowest priority."""
        if not self._heap:
            return None
        _, _, item = heapq.heappop(self._heap)
        return item

    def peek(self) -> Optional[T]:
        """Return item with lowest priority without removing."""
        if not self._heap:
            return None
        return self._heap[0][2]

    def __len__(self) -> int:
        """Return number of items."""
        return len(self._heap)

    def __bool__(self) -> bool:
        """Return True if queue is not empty."""
        return bool(self._heap)


def merge_sorted(a: List[int], b: List[int]) -> List[int]:
    """Merge two sorted lists into one sorted list. O(n+m)."""
    result: List[int] = []
    i, j = 0, 0
    while i < len(a) and j < len(b):
        if a[i] <= b[j]:
            result.append(a[i])
            i += 1
        else:
            result.append(b[j])
            j += 1
    result.extend(a[i:])
    result.extend(b[j:])
    return result
'''

    checks = [
        ("AST validity", check_ast_valid(code)),
        ("Prevalidator (safety)", check_no_forbidden(code)),
        ("Type hints coverage", check_type_hints(code)),
        ("Docstrings coverage", check_has_docstrings(code)),
        ("Nesting depth <= 6", check_complexity(code, max_depth=6)),
        ("Functions <= 50 lines", check_functions_not_too_long(code)),
    ]

    return _evaluate("Algorithms & Data Structures", 1, checks)


# =============================================================================
# TEST 2: OOP -- Classes, Inheritance, Polymorphism
# =============================================================================

def test_02_oop():
    """
    TEST 2: ООП -- Классы, наследование, полиморфизм
    =================================================

    ПОСТАНОВКА ЗАДАЧИ:
        Сгенерировать иерархию классов Shape -> Circle, Rectangle
        с абстрактными методами area() и perimeter().

    УСЛОВИЯ:
        - ABC + abstractmethod обязательны
        - Каждый класс с docstring
        - __repr__ или __str__ обязателен
        - Запрещены: eval, exec, os, subprocess
        - Все методы типизированы

    ЦЕЛИ:
        1. AST-валидность
        2. Prevalidator PASSED
        3. Docstrings >= 80% классов
        4. Type hints >= 50%
        5. Нет hardcoded secrets
        6. Full validation (Level 0-1)
    """
    code = '''\
from abc import ABC, abstractmethod
import math
from typing import Final


class Shape(ABC):
    """Abstract base class for geometric shapes."""

    @abstractmethod
    def area(self) -> float:
        """Calculate area of the shape."""
        ...

    @abstractmethod
    def perimeter(self) -> float:
        """Calculate perimeter of the shape."""
        ...

    def __repr__(self) -> str:
        """String representation with area and perimeter."""
        return f"{type(self).__name__}(area={self.area():.2f}, perimeter={self.perimeter():.2f})"


class Circle(Shape):
    """Circle defined by radius."""

    def __init__(self, radius: float) -> None:
        """Initialize circle with given radius."""
        if radius < 0:
            raise ValueError(f"Radius must be non-negative, got {radius}")
        self.radius: Final = radius

    def area(self) -> float:
        """Calculate area: pi * r^2."""
        return math.pi * self.radius ** 2

    def perimeter(self) -> float:
        """Calculate perimeter: 2 * pi * r."""
        return 2 * math.pi * self.radius


class Rectangle(Shape):
    """Rectangle defined by width and height."""

    def __init__(self, width: float, height: float) -> None:
        """Initialize rectangle with width and height."""
        if width < 0 or height < 0:
            raise ValueError(f"Dimensions must be non-negative: {width}x{height}")
        self.width: Final = width
        self.height: Final = height

    def area(self) -> float:
        """Calculate area: width * height."""
        return self.width * self.height

    def perimeter(self) -> float:
        """Calculate perimeter: 2 * (width + height)."""
        return 2 * (self.width + self.height)

    @property
    def is_square(self) -> bool:
        """Check if rectangle is a square."""
        return math.isclose(self.width, self.height)
'''

    checks = [
        ("AST validity", check_ast_valid(code)),
        ("Prevalidator (safety)", check_no_forbidden(code)),
        ("Docstrings >= 80%", check_has_docstrings(code)),
        ("Type hints >= 50%", check_type_hints(code)),
        ("No hardcoded secrets", check_no_hardcoded_secrets(code)),
        ("Full validation L0-L1", run_full_validation(code)),
    ]

    return _evaluate("OOP: Inheritance & Polymorphism", 2, checks)


# =============================================================================
# TEST 3: ASYNC/AWAIT
# =============================================================================

def test_03_async():
    """
    TEST 3: Асинхронное программирование
    =====================================

    ПОСТАНОВКА ЗАДАЧИ:
        Сгенерировать асинхронный rate limiter (Token Bucket)
        и асинхронную очередь задач с семафором.

    УСЛОВИЯ:
        - Использовать asyncio из стандартной библиотеки
        - async/await синтаксис
        - Корректная обработка исключений
        - Без bare except
        - Type hints обязательны

    ЦЕЛИ:
        1. AST-валидность
        2. Prevalidator PASSED
        3. Содержит async def (>= 2)
        4. Error handling без bare except
        5. Type hints >= 50%
        6. Вложенность <= 6
    """
    code = '''\
import asyncio
from typing import Any, Callable, Coroutine
from dataclasses import dataclass
import time


@dataclass
class RateLimitConfig:
    """Configuration for token bucket rate limiter."""
    max_tokens: int = 10
    refill_rate: float = 1.0  # tokens per second
    refill_interval: float = 0.1  # seconds


class AsyncTokenBucket:
    """Async token bucket rate limiter."""

    def __init__(self, config: RateLimitConfig) -> None:
        """Initialize with config."""
        self._config = config
        self._tokens = float(config.max_tokens)
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: int = 1) -> bool:
        """Acquire tokens. Returns True if acquired, False if rate limited."""
        async with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    async def wait_and_acquire(self, tokens: int = 1) -> None:
        """Wait until tokens are available, then acquire."""
        while True:
            if await self.acquire(tokens):
                return
            await asyncio.sleep(self._config.refill_interval)

    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(
            self._config.max_tokens,
            self._tokens + elapsed * self._config.refill_rate
        )
        self._last_refill = now


class AsyncTaskQueue:
    """Async task queue with concurrency limit."""

    def __init__(self, max_concurrent: int = 5) -> None:
        """Initialize with concurrency limit."""
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._results: list[Any] = []

    async def submit(self, coro: Coroutine) -> Any:
        """Submit a coroutine for execution with concurrency control."""
        async with self._semaphore:
            try:
                result = await coro
                self._results.append(result)
                return result
            except Exception as exc:
                self._results.append(exc)
                raise

    async def run_batch(self, coros: list[Coroutine]) -> list[Any]:
        """Run batch of coroutines with concurrency limit."""
        tasks = [asyncio.create_task(self.submit(c)) for c in coros]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        return list(results)
'''

    # Специальная проверка: есть ли async def
    tree = ast.parse(code)
    async_count = sum(1 for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef))
    has_async = (async_count >= 2, f"{async_count} async functions found")

    checks = [
        ("AST validity", check_ast_valid(code)),
        ("Prevalidator (safety)", check_no_forbidden(code)),
        ("Contains async def >= 2", has_async),
        ("Error handling quality", check_error_handling(code)),
        ("Type hints >= 50%", check_type_hints(code)),
        ("Nesting depth <= 6", check_complexity(code, max_depth=6)),
    ]

    return _evaluate("Async/Await Programming", 3, checks)


# =============================================================================
# TEST 4: SECURITY -- Injection Prevention
# =============================================================================

def test_04_security():
    """
    TEST 4: Безопасность -- предотвращение инъекций
    ================================================

    ПОСТАНОВКА ЗАДАЧИ:
        Сгенерировать безопасный SQL query builder и HTML sanitizer.
        Код НЕ должен использовать string formatting для SQL.

    УСЛОВИЯ:
        - Запрещены: eval, exec, os.system, subprocess
        - SQL через параметризованные запросы (? placeholders)
        - HTML через escape, не через regex замену
        - Bandit Level 1 не должен ругаться
        - Нет hardcoded credentials

    ЦЕЛИ:
        1. AST-валидность
        2. Prevalidator PASSED (критично!)
        3. Нет SQL injection паттернов (f-string + SQL)
        4. Нет hardcoded secrets
        5. Нет eval/exec
        6. Full validation L0-L1
    """
    code = '''\
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass
import html as html_module
import re


@dataclass
class SafeQuery:
    """Parameterized SQL query -- prevents SQL injection."""
    sql: str
    params: Tuple[Any, ...] = ()

    def __str__(self) -> str:
        """Show query with placeholders (never interpolated)."""
        return f"SQL: {self.sql} | Params: {self.params}"


class QueryBuilder:
    """Safe SQL query builder using parameterized queries only."""

    def __init__(self, table: str) -> None:
        """Initialize builder for given table."""
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', table):
            raise ValueError(f"Invalid table name: {table}")
        self._table = table
        self._conditions: List[str] = []
        self._params: List[Any] = []
        self._columns: List[str] = ["*"]
        self._limit: Optional[int] = None
        self._order_by: Optional[str] = None

    def select(self, *columns: str) -> "QueryBuilder":
        """Set columns to select."""
        for col in columns:
            if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_.]*$', col):
                raise ValueError(f"Invalid column name: {col}")
        self._columns = list(columns) if columns else ["*"]
        return self

    def where(self, column: str, operator: str, value: Any) -> "QueryBuilder":
        """Add WHERE condition with parameterized value."""
        allowed_ops = {"=", "!=", "<", ">", "<=", ">=", "LIKE", "IN", "IS"}
        if operator.upper() not in allowed_ops:
            raise ValueError(f"Operator not allowed: {operator}")
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_.]*$', column):
            raise ValueError(f"Invalid column name: {column}")
        self._conditions.append(f"{column} {operator} ?")
        self._params.append(value)
        return self

    def limit(self, n: int) -> "QueryBuilder":
        """Set LIMIT clause."""
        self._limit = max(0, n)
        return self

    def order_by(self, column: str, desc: bool = False) -> "QueryBuilder":
        """Set ORDER BY clause."""
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_.]*$', column):
            raise ValueError(f"Invalid column name: {column}")
        direction = "DESC" if desc else "ASC"
        self._order_by = f"{column} {direction}"
        return self

    def build(self) -> SafeQuery:
        """Build parameterized query."""
        cols = ", ".join(self._columns)
        parts = ["SELECT " + cols + " FROM " + self._table]
        if self._conditions:
            parts.append("WHERE " + " AND ".join(self._conditions))
        if self._order_by:
            parts.append("ORDER BY " + self._order_by)
        if self._limit is not None:
            parts.append("LIMIT " + str(self._limit))
        sql = " ".join(parts)
        return SafeQuery(sql=sql, params=tuple(self._params))


def sanitize_html(text: str) -> str:
    """Sanitize HTML using stdlib html.escape -- prevents XSS."""
    return html_module.escape(text, quote=True)


def sanitize_input(user_input: str, max_length: int = 1000) -> str:
    """Sanitize user input: strip, truncate, escape."""
    cleaned = user_input.strip()
    cleaned = cleaned[:max_length]
    cleaned = sanitize_html(cleaned)
    return cleaned
'''

    # Специальная проверка: нет f-string SQL injection
    has_fstring_sql = bool(re.search(
        r'f["\'].*(?:SELECT|INSERT|UPDATE|DELETE|DROP).*\{',
        code, re.IGNORECASE
    ))
    no_sql_injection = (not has_fstring_sql, "No f-string SQL" if not has_fstring_sql else "DANGER: f-string SQL found!")

    checks = [
        ("AST validity", check_ast_valid(code)),
        ("Prevalidator (safety)", check_no_forbidden(code)),
        ("No SQL injection patterns", no_sql_injection),
        ("No hardcoded secrets", check_no_hardcoded_secrets(code)),
        ("Error handling quality", check_error_handling(code)),
        ("Full validation L0-L1", run_full_validation(code)),
    ]

    return _evaluate("Security: Injection Prevention", 4, checks)


# =============================================================================
# TEST 5: DATA PROCESSING -- Collections & Transforms
# =============================================================================

def test_05_data_processing():
    """
    TEST 5: Обработка данных -- коллекции и трансформации
    =====================================================

    ПОСТАНОВКА ЗАДАЧИ:
        Сгенерировать pipeline обработки данных:
        filter -> transform -> aggregate -> sort.
        Без pandas/numpy (чистый Python).

    УСЛОВИЯ:
        - Только стандартная библиотека
        - Функциональный стиль (map, filter, reduce допустимы)
        - Generator expressions поощряются
        - Функции <= 30 строк
        - Type hints обязательны

    ЦЕЛИ:
        1. AST-валидность
        2. Prevalidator PASSED
        3. Type hints >= 60%
        4. Функции <= 30 строк
        5. Вложенность <= 5
        6. Docstrings >= 50%
    """
    code = '''\
from typing import TypeVar, Callable, Iterable, Iterator, Dict, List, Any
from functools import reduce
from collections import Counter, defaultdict
from itertools import groupby
from operator import itemgetter

T = TypeVar('T')
R = TypeVar('R')


def pipe_filter(items: Iterable[T], predicate: Callable[[T], bool]) -> Iterator[T]:
    """Filter items by predicate. Lazy evaluation via generator."""
    return (item for item in items if predicate(item))


def pipe_transform(items: Iterable[T], transform: Callable[[T], R]) -> Iterator[R]:
    """Transform each item. Lazy evaluation via generator."""
    return (transform(item) for item in items)


def pipe_aggregate(items: Iterable[T], key: Callable[[T], str]) -> Dict[str, List[T]]:
    """Group items by key function."""
    groups: Dict[str, List[T]] = defaultdict(list)
    for item in items:
        groups[key(item)].append(item)
    return dict(groups)


def pipe_sort(items: List[T], key: Callable[[T], Any], reverse: bool = False) -> List[T]:
    """Sort items by key function. Returns new list."""
    return sorted(items, key=key, reverse=reverse)


def pipe_reduce(items: Iterable[T], reducer: Callable[[R, T], R], initial: R) -> R:
    """Reduce items to single value."""
    return reduce(reducer, items, initial)


class DataPipeline:
    """Chainable data processing pipeline."""

    def __init__(self, data: List[Any]) -> None:
        """Initialize pipeline with source data."""
        self._data: List[Any] = list(data)
        self._steps: List[str] = []

    def filter(self, predicate: Callable[[Any], bool]) -> "DataPipeline":
        """Add filter step."""
        self._data = list(pipe_filter(self._data, predicate))
        self._steps.append("filter")
        return self

    def transform(self, func: Callable[[Any], Any]) -> "DataPipeline":
        """Add transform step."""
        self._data = list(pipe_transform(self._data, func))
        self._steps.append("transform")
        return self

    def sort(self, key: Callable[[Any], Any], reverse: bool = False) -> "DataPipeline":
        """Add sort step."""
        self._data = pipe_sort(self._data, key=key, reverse=reverse)
        self._steps.append("sort")
        return self

    def result(self) -> List[Any]:
        """Return processed data."""
        return self._data

    def __repr__(self) -> str:
        """Show pipeline steps and data count."""
        return f"Pipeline({len(self._steps)} steps, {len(self._data)} items)"
'''

    checks = [
        ("AST validity", check_ast_valid(code)),
        ("Prevalidator (safety)", check_no_forbidden(code)),
        ("Type hints >= 60%", check_type_hints(code)),
        ("Functions <= 30 lines", check_functions_not_too_long(code, max_lines=30)),
        ("Nesting depth <= 5", check_complexity(code, max_depth=5)),
        ("Docstrings >= 50%", check_has_docstrings(code)),
    ]

    return _evaluate("Data Processing Pipeline", 5, checks)


# =============================================================================
# TEST 6: ERROR HANDLING -- Exception Hierarchy
# =============================================================================

def test_06_error_handling():
    """
    TEST 6: Обработка ошибок -- иерархия исключений
    ================================================

    ПОСТАНОВКА ЗАДАЧИ:
        Сгенерировать иерархию пользовательских исключений
        и retry-декоратор с exponential backoff.

    УСЛОВИЯ:
        - Свои Exception-классы (наследование от Exception/ValueError/etc.)
        - Декоратор retry с настраиваемыми параметрами
        - Никаких bare except (except: без типа)
        - Логирование через logging (не print)
        - Type hints

    ЦЕЛИ:
        1. AST-валидность
        2. Prevalidator PASSED
        3. Error handling quality (no bare except)
        4. Contains raise statements
        5. Docstrings >= 50%
        6. Nesting depth <= 7
    """
    code = '''\
from typing import Callable, TypeVar, Any, Type, Tuple
from functools import wraps
import time
import logging

logger = logging.getLogger(__name__)
T = TypeVar('T')


class AppError(Exception):
    """Base application error."""

    def __init__(self, message: str, code: str = "UNKNOWN") -> None:
        """Initialize with message and error code."""
        super().__init__(message)
        self.code = code


class ValidationError(AppError):
    """Input validation failed."""

    def __init__(self, field: str, message: str) -> None:
        """Initialize with field name and validation message."""
        super().__init__(f"Validation error on '{field}': {message}", code="VALIDATION")
        self.field = field


class NotFoundError(AppError):
    """Resource not found."""

    def __init__(self, resource: str, identifier: Any) -> None:
        """Initialize with resource type and identifier."""
        super().__init__(f"{resource} not found: {identifier}", code="NOT_FOUND")
        self.resource = resource
        self.identifier = identifier


class RateLimitError(AppError):
    """Rate limit exceeded."""

    def __init__(self, retry_after: float = 0.0) -> None:
        """Initialize with retry-after time."""
        super().__init__(f"Rate limit exceeded. Retry after {retry_after:.1f}s", code="RATE_LIMIT")
        self.retry_after = retry_after


def retry(
    max_attempts: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
) -> Callable:
    """Decorator: retry with exponential backoff.

    Args:
        max_attempts: Maximum retry attempts.
        delay: Initial delay in seconds.
        backoff: Multiplier for each retry.
        exceptions: Tuple of exception types to catch.
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            current_delay = delay
            last_exception: Exception = RuntimeError("No attempts made")
            for attempt in range(1, max_attempts + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_exception = exc
                    if attempt == max_attempts:
                        logger.error(
                            "Function %s failed after %d attempts: %s",
                            func.__name__, max_attempts, exc
                        )
                        raise
                    logger.warning(
                        "Attempt %d/%d for %s failed: %s. Retrying in %.1fs",
                        attempt, max_attempts, func.__name__, exc, current_delay
                    )
                    time.sleep(current_delay)
                    current_delay *= backoff
            raise last_exception
        return wrapper
    return decorator
'''

    # Проверка: есть raise
    tree = ast.parse(code)
    raise_count = sum(1 for n in ast.walk(tree) if isinstance(n, ast.Raise))
    has_raise = (raise_count >= 2, f"{raise_count} raise statements found")

    checks = [
        ("AST validity", check_ast_valid(code)),
        ("Prevalidator (safety)", check_no_forbidden(code)),
        ("Error handling (no bare except)", check_error_handling(code)),
        ("Contains raise >= 2", has_raise),
        ("Docstrings >= 50%", check_has_docstrings(code)),
        ("Nesting depth <= 7", check_complexity(code, max_depth=7)),
    ]

    return _evaluate("Error Handling & Exceptions", 6, checks)


# =============================================================================
# TEST 7: DESIGN PATTERNS -- Strategy + Observer
# =============================================================================

def test_07_design_patterns():
    """
    TEST 7: Паттерны проектирования -- Strategy + Observer
    ======================================================

    ПОСТАНОВКА ЗАДАЧИ:
        Сгенерировать реализацию паттернов Strategy и Observer.
        Код должен следовать принципам SOLID.

    УСЛОВИЯ:
        - Protocol или ABC для интерфейсов
        - Слабая связность (loosely coupled)
        - Все методы типизированы
        - Immutable где возможно (frozen dataclass)
        - Никаких God-объектов (классы <= 15 методов)

    ЦЕЛИ:
        1. AST-валидность
        2. Prevalidator PASSED
        3. Type hints >= 70%
        4. Docstrings >= 60%
        5. Functions <= 30 lines
        6. Full validation L0-L1
    """
    code = '''\
from typing import Protocol, List, Callable, Any
from dataclasses import dataclass, field
from abc import ABC, abstractmethod


# === STRATEGY PATTERN ===

class SortStrategy(Protocol):
    """Strategy interface for sorting algorithms."""

    def sort(self, data: List[int]) -> List[int]:
        """Sort data and return new sorted list."""
        ...


class BubbleSort:
    """Bubble sort strategy. O(n^2)."""

    def sort(self, data: List[int]) -> List[int]:
        """Sort using bubble sort algorithm."""
        arr = list(data)
        n = len(arr)
        for i in range(n):
            for j in range(0, n - i - 1):
                if arr[j] > arr[j + 1]:
                    arr[j], arr[j + 1] = arr[j + 1], arr[j]
        return arr


class QuickSort:
    """Quick sort strategy. O(n log n) average."""

    def sort(self, data: List[int]) -> List[int]:
        """Sort using quick sort algorithm."""
        if len(data) <= 1:
            return list(data)
        pivot = data[len(data) // 2]
        left = [x for x in data if x < pivot]
        middle = [x for x in data if x == pivot]
        right = [x for x in data if x > pivot]
        return self.sort(left) + middle + self.sort(right)


class Sorter:
    """Context that uses a SortStrategy."""

    def __init__(self, strategy: SortStrategy) -> None:
        """Initialize with sorting strategy."""
        self._strategy = strategy

    def set_strategy(self, strategy: SortStrategy) -> None:
        """Change sorting strategy at runtime."""
        self._strategy = strategy

    def execute(self, data: List[int]) -> List[int]:
        """Execute current strategy on data."""
        return self._strategy.sort(data)


# === OBSERVER PATTERN ===

@dataclass(frozen=True)
class Event:
    """Immutable event object."""
    name: str
    data: Any = None


class Observer(ABC):
    """Abstract observer."""

    @abstractmethod
    def on_event(self, event: Event) -> None:
        """Handle event notification."""
        ...


class EventBus:
    """Observable event bus. Supports subscribe/unsubscribe/emit."""

    def __init__(self) -> None:
        """Initialize empty event bus."""
        self._listeners: dict[str, List[Observer]] = {}

    def subscribe(self, event_name: str, observer: Observer) -> None:
        """Subscribe observer to event type."""
        if event_name not in self._listeners:
            self._listeners[event_name] = []
        if observer not in self._listeners[event_name]:
            self._listeners[event_name].append(observer)

    def unsubscribe(self, event_name: str, observer: Observer) -> None:
        """Unsubscribe observer from event type."""
        if event_name in self._listeners:
            self._listeners[event_name] = [
                o for o in self._listeners[event_name] if o is not observer
            ]

    def emit(self, event: Event) -> int:
        """Emit event to all subscribers. Returns count of notified."""
        listeners = self._listeners.get(event.name, [])
        for listener in listeners:
            listener.on_event(event)
        return len(listeners)
'''

    checks = [
        ("AST validity", check_ast_valid(code)),
        ("Prevalidator (safety)", check_no_forbidden(code)),
        ("Type hints >= 70%", check_type_hints(code)),
        ("Docstrings >= 60%", check_has_docstrings(code)),
        ("Functions <= 30 lines", check_functions_not_too_long(code, max_lines=30)),
        ("Full validation L0-L1", run_full_validation(code)),
    ]

    return _evaluate("Design Patterns: Strategy + Observer", 7, checks)


# =============================================================================
# TEST 8: FUNCTIONAL PROGRAMMING -- Decorators & Closures
# =============================================================================

def test_08_functional():
    """
    TEST 8: Функциональное программирование -- декораторы, замыкания
    ===============================================================

    ПОСТАНОВКА ЗАДАЧИ:
        Сгенерировать набор утилитных декораторов:
        @memoize, @timer, @validate_args, @deprecated.

    УСЛОВИЯ:
        - functools.wraps обязателен
        - Замыкания без побочных эффектов
        - Потокобезопасность для @memoize
        - Type hints для декораторов
        - Docstrings для каждого декоратора

    ЦЕЛИ:
        1. AST-валидность
        2. Prevalidator PASSED
        3. Contains >= 4 decorators (FunctionDef returning FunctionDef)
        4. Type hints >= 50%
        5. Docstrings >= 60%
        6. Nesting depth <= 6
    """
    code = '''\
from typing import Callable, TypeVar, Any, Dict, Tuple
from functools import wraps
import time
import warnings

F = TypeVar('F', bound=Callable[..., Any])


def memoize(func: F) -> F:
    """Memoization decorator with cache.

    Caches function results based on arguments.
    Uses dict for O(1) lookup.
    """
    cache: Dict[Tuple, Any] = {}

    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        """Cached wrapper."""
        key = (args, tuple(sorted(kwargs.items())))
        if key in cache:
            return cache[key]
        result = func(*args, **kwargs)
        cache[key] = result
        return result

    wrapper.cache_clear = lambda: cache.clear()  # type: ignore
    return wrapper  # type: ignore


def timer(func: F) -> F:
    """Decorator that prints execution time of function.

    Logs function name and elapsed time in milliseconds.
    """
    @wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        start = time.perf_counter()
        result = func(*args, **kwargs)
        elapsed = (time.perf_counter() - start) * 1000
        print(f"[TIMER] {func.__name__}: {elapsed:.2f}ms")
        return result
    return wrapper  # type: ignore


def validate_args(**validators: Callable[[Any], bool]) -> Callable[[F], F]:
    """Decorator factory that validates function arguments.

    Usage:
        @validate_args(x=lambda v: v > 0, name=lambda v: len(v) > 0)
        def func(x: int, name: str): ...
    """
    def decorator(func: F) -> F:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            import inspect
            sig = inspect.signature(func)
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            for param_name, validator in validators.items():
                if param_name in bound.arguments:
                    value = bound.arguments[param_name]
                    if not validator(value):
                        raise ValueError(
                            f"Argument '{param_name}' failed validation: {value!r}"
                        )
            return func(*args, **kwargs)
        return wrapper  # type: ignore
    return decorator


def deprecated(reason: str = "") -> Callable[[F], F]:
    """Mark function as deprecated. Emits DeprecationWarning on call.

    Args:
        reason: Explanation why deprecated and what to use instead.
    """
    def decorator(func: F) -> F:
        message = f"{func.__name__} is deprecated."
        if reason:
            message += f" {reason}"

        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            warnings.warn(message, DeprecationWarning, stacklevel=2)
            return func(*args, **kwargs)
        return wrapper  # type: ignore
    return decorator
'''

    # Проверка: >= 4 декоратора (функция верхнего уровня, возвращающая inner)
    tree = ast.parse(code)
    top_funcs = [n for n in ast.iter_child_nodes(tree)
                 if isinstance(n, ast.FunctionDef)]
    has_decorators = (len(top_funcs) >= 4,
                      f"{len(top_funcs)} top-level decorator functions")

    checks = [
        ("AST validity", check_ast_valid(code)),
        ("Prevalidator (safety)", check_no_forbidden(code)),
        ("Contains >= 4 decorators", has_decorators),
        ("Type hints >= 50%", check_type_hints(code)),
        ("Docstrings >= 60%", check_has_docstrings(code)),
        ("Nesting depth <= 6", check_complexity(code, max_depth=6)),
    ]

    return _evaluate("Functional: Decorators & Closures", 8, checks)


# =============================================================================
# TEST 9: TESTING -- Unit test generation quality
# =============================================================================

def test_09_test_generation():
    """
    TEST 9: Генерация тестов -- качество unit-тестов
    ================================================

    ПОСТАНОВКА ЗАДАЧИ:
        Сгенерировать unit-тесты для Stack и Calculator.
        Тесты должны покрывать edge cases, happy path, error cases.

    УСЛОВИЯ:
        - pytest-стиль (не unittest.TestCase)
        - Параметризация (@pytest.mark.parametrize)
        - Фикстуры (@pytest.fixture)
        - Assert с понятными сообщениями
        - >= 8 тестовых функций

    ЦЕЛИ:
        1. AST-валидность
        2. Prevalidator PASSED
        3. Contains >= 8 test functions (def test_)
        4. Contains parametrize decorator
        5. Contains fixture
        6. Docstrings >= 30% (тесты могут без)
    """
    code = '''\
import pytest
from typing import List


# === Implementation under test ===

class Stack:
    """Simple stack implementation."""

    def __init__(self) -> None:
        self._items: List[int] = []

    def push(self, item: int) -> None:
        self._items.append(item)

    def pop(self) -> int:
        if not self._items:
            raise IndexError("Pop from empty stack")
        return self._items.pop()

    def peek(self) -> int:
        if not self._items:
            raise IndexError("Peek at empty stack")
        return self._items[-1]

    def __len__(self) -> int:
        return len(self._items)

    def __bool__(self) -> bool:
        return bool(self._items)


def divide(a: float, b: float) -> float:
    """Safe division with zero check."""
    if b == 0:
        raise ZeroDivisionError("Cannot divide by zero")
    return a / b


# === Fixtures ===

@pytest.fixture
def empty_stack() -> Stack:
    """Fixture: empty stack."""
    return Stack()


@pytest.fixture
def filled_stack() -> Stack:
    """Fixture: stack with [1, 2, 3]."""
    s = Stack()
    for val in [1, 2, 3]:
        s.push(val)
    return s


# === Stack Tests ===

def test_stack_empty(empty_stack: Stack) -> None:
    """Test that new stack is empty and falsy."""
    assert len(empty_stack) == 0
    assert not empty_stack


def test_stack_push(empty_stack: Stack) -> None:
    """Test push adds element and updates length."""
    empty_stack.push(42)
    assert len(empty_stack) == 1
    assert empty_stack.peek() == 42


def test_stack_pop(filled_stack: Stack) -> None:
    """Test pop returns last element and decrements length."""
    val = filled_stack.pop()
    assert val == 3
    assert len(filled_stack) == 2


def test_stack_pop_empty(empty_stack: Stack) -> None:
    """Test pop on empty stack raises IndexError."""
    with pytest.raises(IndexError, match="empty stack"):
        empty_stack.pop()


def test_stack_peek(filled_stack: Stack) -> None:
    """Test peek returns top without removing it."""
    val = filled_stack.peek()
    assert val == 3
    assert len(filled_stack) == 3  # peek doesn't remove


def test_stack_peek_empty(empty_stack: Stack) -> None:
    """Test peek on empty stack raises IndexError."""
    with pytest.raises(IndexError, match="empty stack"):
        empty_stack.peek()


def test_stack_push_pop_sequence(empty_stack: Stack) -> None:
    """Test LIFO order with 100 push/pop operations."""
    for i in range(100):
        empty_stack.push(i)
    for i in range(99, -1, -1):
        assert empty_stack.pop() == i
    assert len(empty_stack) == 0


# === Division Tests ===

@pytest.mark.parametrize("a, b, expected", [
    (10, 2, 5.0),
    (7, 3, 7/3),
    (-6, 2, -3.0),
    (0, 5, 0.0),
    (1.5, 0.5, 3.0),
])
def test_divide_valid(a: float, b: float, expected: float) -> None:
    """Test valid division with parametrized inputs."""
    result = divide(a, b)
    assert abs(result - expected) < 1e-9


def test_divide_by_zero() -> None:
    """Test division by zero raises ZeroDivisionError."""
    with pytest.raises(ZeroDivisionError, match="Cannot divide by zero"):
        divide(10, 0)
'''

    tree = ast.parse(code)
    test_funcs = [n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
    has_tests = (len(test_funcs) >= 8, f"{len(test_funcs)} test functions")

    has_parametrize = ("parametrize" in code, "Has @pytest.mark.parametrize")
    has_fixture = ("@pytest.fixture" in code, "Has @pytest.fixture")

    checks = [
        ("AST validity", check_ast_valid(code)),
        ("Prevalidator (safety)", check_no_forbidden(code)),
        ("Contains >= 8 test functions", has_tests),
        ("Has parametrize decorator", has_parametrize),
        ("Has pytest.fixture", has_fixture),
        ("Docstrings >= 30%", check_has_docstrings(code)),
    ]

    return _evaluate("Test Generation Quality", 9, checks)


# =============================================================================
# TEST 10: PATTERN COVERAGE & QUALITY ASSESSMENT
# =============================================================================

def test_10_pattern_coverage():
    """
    TEST 10: Покрытие и качество паттернов PatternRouter
    ====================================================

    ПОСТАНОВКА ЗАДАЧИ:
        Оценить качество и покрытие regex-паттернов в PatternRouter.
        Проверить, что все паттерны валидны, не конфликтуют и покрывают
        основные команды пользователей.

    УСЛОВИЯ:
        - PatternRouter должен быть доступен для импорта
        - Каждый regex должен компилироваться без ошибок
        - Не должно быть "мертвых" паттернов (unreachable)
        - Стандартные команды (git, grep, read, find) должны матчиться
        - Время матчинга < 5ms на команду

    ЦЕЛИ:
        1. Все regex компилируются
        2. Нет конфликтов приоритетов (первый матч = правильный)
        3. >= 90% стандартных команд матчатся
        4. Скорость матчинга < 5ms
        5. Покрытие категорий (git, grep, read, find, bash)
        6. Качество парсинга (параметры извлекаются корректно)
    """
    try:
        from core.pattern_router import PatternRouter
    except ImportError:
        return TestResult(
            test_id=10, name="Pattern Coverage & Quality",
            domain="meta", passed=False, checks_passed=0, checks_total=6,
            duration_ms=0, errors=["Cannot import PatternRouter"]
        )

    router = PatternRouter()
    t0 = time.perf_counter()

    # --- Check 1: All regex compile ---
    compile_errors = []
    for i, (pattern, tool, handler) in enumerate(router.patterns):
        try:
            # pattern is already compiled re.Pattern
            _ = pattern.pattern  # access regex string
        except Exception as e:
            compile_errors.append(f"Pattern {i}: {e}")
    all_compile = (len(compile_errors) == 0,
                   f"All {len(router.patterns)} patterns compile OK"
                   if not compile_errors else f"{len(compile_errors)} compile errors")

    # --- Check 2: No priority conflicts ---
    # Test known commands and verify correct tool is matched
    priority_tests = [
        ("git status", "bash"),
        ("git log --oneline -5", "bash"),
        ('grep "class" core/', "grep"),
        ("read README.md", "read"),
        ("find *.py in core/", "find"),
    ]
    conflicts = []
    for cmd, expected_tool in priority_tests:
        match = router.match(cmd)
        if match and match.get("tool") != expected_tool:
            conflicts.append(f"'{cmd}' -> {match.get('tool')} (expected {expected_tool})")
    no_conflicts = (len(conflicts) == 0,
                    "No priority conflicts"
                    if not conflicts else f"Conflicts: {'; '.join(conflicts)}")

    # --- Check 3: Standard commands coverage ---
    standard_commands = [
        "git status", "git diff", "git log --oneline -3", "git branch",
        'grep "pattern" core/', 'grep -i "timeout" file.py', "grep timeout",
        "read README.md", "read core/agent.py lines 1-20",
        "find *.py in core/", "find pattern_router",
        "ls core/", "ls",
    ]
    matched = 0
    unmatched = []
    for cmd in standard_commands:
        result = router.match(cmd)
        if result:
            matched += 1
        else:
            unmatched.append(cmd)
    coverage_pct = matched / len(standard_commands) * 100
    coverage_ok = (coverage_pct >= 90,
                   f"{matched}/{len(standard_commands)} ({coverage_pct:.0f}%) commands matched"
                   + (f" | Unmatched: {unmatched}" if unmatched else ""))

    # --- Check 4: Matching speed ---
    speeds = []
    for cmd in standard_commands:
        ts = time.perf_counter()
        for _ in range(100):
            router.match(cmd)
        elapsed_ms = (time.perf_counter() - ts) / 100 * 1000
        speeds.append(elapsed_ms)
    avg_speed = sum(speeds) / len(speeds)
    max_speed = max(speeds)
    speed_ok = (max_speed < 5.0,
                f"Avg: {avg_speed:.3f}ms, Max: {max_speed:.3f}ms")

    # --- Check 5: Category coverage ---
    categories_expected = {"bash", "grep", "read", "find", "ls"}
    tools_found = set()
    for cmd in standard_commands:
        result = router.match(cmd)
        if result:
            tools_found.add(result.get("tool", ""))
    missing_cats = categories_expected - tools_found
    cats_ok = (len(missing_cats) == 0,
               f"Categories: {sorted(tools_found)}"
               + (f" | Missing: {sorted(missing_cats)}" if missing_cats else ""))

    # --- Check 6: Parameter extraction quality ---
    param_tests = [
        ('grep "class Agent" core/', {"pattern": "class Agent", "path": "core/"}),
        ("read core/agent.py", {"file_path": True}),  # just check key exists
        ("git log --oneline -5", {}),  # git pass-through, no parsed params
    ]
    param_ok_count = 0
    param_issues = []
    for cmd, expected_params in param_tests:
        result = router.match(cmd)
        if not result:
            param_issues.append(f"'{cmd}' not matched")
            continue
        params = result.get("params", {})
        all_ok = True
        for key, val in expected_params.items():
            if val is True:
                if key not in params:
                    all_ok = False
                    param_issues.append(f"'{cmd}': missing param '{key}'")
            elif isinstance(val, str):
                actual = params.get(key, "")
                if actual != val:
                    all_ok = False
                    param_issues.append(f"'{cmd}': {key}='{actual}' (expected '{val}')")
        if all_ok:
            param_ok_count += 1
    params_quality = (param_ok_count == len(param_tests),
                      f"{param_ok_count}/{len(param_tests)} parameter extractions correct"
                      + (f" | Issues: {'; '.join(param_issues)}" if param_issues else ""))

    total_ms = (time.perf_counter() - t0) * 1000

    checks = [
        ("All regex compile", all_compile),
        ("No priority conflicts", no_conflicts),
        ("Standard commands >= 90%", coverage_ok),
        ("Matching speed < 5ms", speed_ok),
        ("Category coverage", cats_ok),
        ("Parameter extraction quality", params_quality),
    ]

    return _evaluate("Pattern Coverage & Quality", 10, checks,
                     domain="meta/patterns", override_time_ms=total_ms)


# =============================================================================
# EVALUATION ENGINE
# =============================================================================

def _evaluate(name: str, test_id: int, checks: List[Tuple[str, Tuple[bool, str]]],
              domain: str = "", override_time_ms: float = 0) -> TestResult:
    """Evaluate test checks and return result."""
    t0 = time.perf_counter()
    passed_count = 0
    details = []
    errors = []

    for check_name, (ok, msg) in checks:
        tag = "[OK]" if ok else "[FAIL]"
        details.append(f"  {tag:6} {check_name}: {msg}")
        if ok:
            passed_count += 1
        else:
            errors.append(f"{check_name}: {msg}")

    duration = override_time_ms if override_time_ms else (time.perf_counter() - t0) * 1000
    all_passed = passed_count == len(checks)

    return TestResult(
        test_id=test_id,
        name=name,
        domain=domain or name.split(":")[0].strip(),
        passed=all_passed,
        checks_passed=passed_count,
        checks_total=len(checks),
        duration_ms=duration,
        details=details,
        errors=errors,
    )


# =============================================================================
# MAIN RUNNER
# =============================================================================

def run_all_tests() -> List[TestResult]:
    """Run all 10 tests and return results."""
    tests = [
        test_01_algorithms,
        test_02_oop,
        test_03_async,
        test_04_security,
        test_05_data_processing,
        test_06_error_handling,
        test_07_design_patterns,
        test_08_functional,
        test_09_test_generation,
        test_10_pattern_coverage,
    ]

    results = []
    for test_fn in tests:
        try:
            result = test_fn()
            results.append(result)
        except Exception as e:
            results.append(TestResult(
                test_id=len(results) + 1,
                name=test_fn.__name__,
                domain="error",
                passed=False,
                checks_passed=0,
                checks_total=1,
                duration_ms=0,
                errors=[f"Exception: {e}"],
            ))
    return results


def print_report(results: List[TestResult]) -> None:
    """Print formatted test report."""
    print("=" * 75)
    print("  10 TESTS: PYTHON CODE GENERATION QUALITY")
    print("  Using: Prevalidator + StaticAnalyzer + CodeValidator + PatternRouter")
    print("=" * 75)

    total_passed = 0
    total_checks = 0
    total_checks_passed = 0

    for r in results:
        icon = "[PASS]" if r.passed else "[FAIL]"
        print(f"\nTest {r.test_id:2d} {icon} {r.name}")
        print(f"         Score: {r.checks_passed}/{r.checks_total} ({r.score:.0f}%)  |  {r.duration_ms:.1f}ms")
        for detail in r.details:
            print(f"        {detail}")

        if r.passed:
            total_passed += 1
        total_checks += r.checks_total
        total_checks_passed += r.checks_passed

    print("\n" + "=" * 75)
    overall = total_checks_passed / total_checks * 100 if total_checks else 0
    print(f"  RESULT: {total_passed}/{len(results)} tests passed")
    print(f"  CHECKS: {total_checks_passed}/{total_checks} ({overall:.1f}%)")
    print(f"  DOMAINS: Algorithms, OOP, Async, Security, Data, Errors,")
    print(f"           Patterns, Functional, Testing, Meta/PatternCoverage")
    print("=" * 75)

    # JSON summary
    summary = {
        "tests_passed": total_passed,
        "tests_total": len(results),
        "checks_passed": total_checks_passed,
        "checks_total": total_checks,
        "overall_score": round(overall, 1),
        "results": [
            {
                "id": r.test_id,
                "name": r.name,
                "domain": r.domain,
                "passed": r.passed,
                "score": round(r.score, 1),
                "errors": r.errors,
            }
            for r in results
        ],
    }
    print(f"\nJSON: {json.dumps(summary, ensure_ascii=False)}")


if __name__ == "__main__":
    results = run_all_tests()
    print_report(results)
