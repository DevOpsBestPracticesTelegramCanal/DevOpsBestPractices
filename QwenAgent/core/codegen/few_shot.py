"""
Few-Shot Examples Bank для QwenCode Generator
==============================================
Банк качественных примеров кода для few-shot learning.

LLM лучше учится на примерах, чем на инструкциях.
Этот модуль предоставляет качественные примеры для типовых задач.

Использование:
    from core.codegen.few_shot import get_example, get_relevant_examples
    
    example = get_example("email_validation")
    examples_for_prompt = get_relevant_examples("validate email address")
"""

from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class CodeExample:
    """Пример кода с метаданными"""
    name: str
    description: str
    keywords: List[str]
    bad_code: str
    good_code: str
    why_better: List[str]


# =============================================================================
# PYTHON EXAMPLES
# =============================================================================

EXAMPLES: Dict[str, CodeExample] = {
    
    "email_validation": CodeExample(
        name="Email Validation",
        description="Валидация email адреса с regex",
        keywords=["email", "validate", "validation", "regex", "mail"],
        bad_code='''
def validate_email(email):
    regex = r'^[a-z0-9]+[\._]?[a-z0-9]+[@]\w+[.]\w{2,3}$'
    if re.search(regex, email):
        return True
    else:
        return False
''',
        good_code='''
import re
from typing import Optional

# Compiled regex for performance
EMAIL_REGEX = re.compile(
    r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$"
)

def validate_email(email: str) -> bool:
    """Validate email address format.
    
    Args:
        email: Email address to validate.
    
    Returns:
        True if email format is valid, False otherwise.
    
    Note:
        For production use, consider email-validator library
        with DNS/MX verification.
    """
    if not email or not isinstance(email, str):
        return False
    return EMAIL_REGEX.fullmatch(email.strip()) is not None
''',
        why_better=[
            "Type hints для параметров и return",
            "Compiled regex (константа) для производительности",
            "fullmatch() вместо search() для точного матча",
            "Обработка edge cases (None, пустая строка, не-строка)",
            "Поддержка длинных TLD (.museum, .technology)",
            "Docstring с рекомендацией для production",
        ]
    ),
    
    "bubble_sort": CodeExample(
        name="Bubble Sort",
        description="Сортировка пузырьком с оптимизацией",
        keywords=["bubble", "sort", "sorting", "algorithm"],
        bad_code='''
def bubble_sort(arr):
    n = len(arr)
    for i in range(n):
        for j in range(0, n-i-1):
            if arr[j] > arr[j+1]:
                arr[j], arr[j+1] = arr[j+1], arr[j]
    return arr
''',
        good_code='''
def bubble_sort(arr: list[int]) -> list[int]:
    """Sort array in-place using optimized bubble sort.
    
    Uses early termination when array becomes sorted,
    improving best-case from O(n²) to O(n).
    
    Args:
        arr: List of integers to sort.
    
    Returns:
        The same list, sorted in ascending order.
    
    Time: O(n²) worst/avg, O(n) best (already sorted).
    Space: O(1) - in-place sorting.
    """
    n = len(arr)
    
    for i in range(n):
        swapped = False
        
        for j in range(0, n - i - 1):
            if arr[j] > arr[j + 1]:
                arr[j], arr[j + 1] = arr[j + 1], arr[j]
                swapped = True
        
        # Early termination: array is sorted
        if not swapped:
            break
    
    return arr
''',
        why_better=[
            "swapped flag для O(n) на уже отсортированных данных",
            "Type hints (list[int] -> list[int])",
            "Docstring с complexity analysis",
            "Комментарий объясняет оптимизацию",
            "Явное указание in-place поведения",
        ]
    ),
    
    "binary_search": CodeExample(
        name="Binary Search",
        description="Бинарный поиск с обработкой edge cases",
        keywords=["binary", "search", "find", "sorted", "array"],
        bad_code='''
def binary_search(arr, target):
    left = 0
    right = len(arr) - 1
    while left <= right:
        mid = (left + right) // 2
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            left = mid + 1
        else:
            right = mid - 1
    return -1
''',
        good_code='''
def binary_search(arr: list[int], target: int) -> int:
    """Find target in sorted array using binary search.
    
    Args:
        arr: Sorted list of integers (ascending order).
        target: Value to find.
    
    Returns:
        Index of target if found, -1 otherwise.
    
    Time: O(log n)
    Space: O(1)
    
    Note:
        Array must be sorted. For unsorted arrays, use
        linear search or sort first.
    """
    if not arr:
        return -1
    
    left, right = 0, len(arr) - 1
    
    while left <= right:
        # Overflow-safe midpoint calculation
        mid = left + (right - left) // 2
        
        if arr[mid] == target:
            return mid
        elif arr[mid] < target:
            left = mid + 1
        else:
            right = mid - 1
    
    return -1
''',
        why_better=[
            "Overflow-safe mid: left + (right - left) // 2",
            "Type hints",
            "Docstring с complexity и requirements",
            "Edge case: пустой массив",
            "Комментарий про отсортированность",
        ]
    ),
    
    "lru_cache": CodeExample(
        name="LRU Cache (Thread-Safe)",
        description="Thread-safe LRU кэш с OrderedDict",
        keywords=["cache", "lru", "thread", "safe", "concurrent"],
        bad_code='''
from collections import OrderedDict
import threading

class LRUCache:
    def __init__(self, capacity):
        self.capacity = capacity
        self.cache = OrderedDict()
        self.lock = threading.Lock()
    
    def get(self, key):
        with self.lock:
            if key not in self.cache:
                return None
            self.cache.move_to_end(key)
            return self.cache[key]
    
    def put(self, key, value):
        with self.lock:
            if key in self.cache:
                del self.cache[key]
            self.cache[key] = value
            if len(self.cache) > self.capacity:
                self.cache.popitem(last=False)
''',
        good_code='''
import threading
from collections import OrderedDict
from typing import TypeVar, Generic, Optional

K = TypeVar('K')
V = TypeVar('V')


class LRUCache(Generic[K, V]):
    """Thread-safe LRU cache with O(1) operations.
    
    Uses OrderedDict for O(1) access and ordering,
    and RLock for thread safety with reentrant support.
    
    Args:
        capacity: Maximum number of items in cache.
    
    Example:
        cache = LRUCache[str, int](capacity=100)
        cache.put("key", 42)
        value = cache.get("key")  # 42
    """
    
    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError("Capacity must be positive")
        
        self.capacity = capacity
        self.cache: OrderedDict[K, V] = OrderedDict()
        self._lock = threading.RLock()  # Reentrant for nested calls
    
    def get(self, key: K) -> Optional[V]:
        """Get value by key, updating access order.
        
        Returns:
            Value if found, None otherwise.
        """
        with self._lock:
            if key not in self.cache:
                return None
            
            # Move to end (most recently used)
            self.cache.move_to_end(key)
            return self.cache[key]
    
    def put(self, key: K, value: V) -> None:
        """Add or update key-value pair.
        
        If cache is full, evicts least recently used item.
        """
        with self._lock:
            if key in self.cache:
                # Update existing: move to end
                self.cache.move_to_end(key)
            
            self.cache[key] = value
            
            # Evict LRU if over capacity
            if len(self.cache) > self.capacity:
                self.cache.popitem(last=False)
    
    def __len__(self) -> int:
        with self._lock:
            return len(self.cache)
    
    def __contains__(self, key: K) -> bool:
        with self._lock:
            return key in self.cache
''',
        why_better=[
            "Generic types (LRUCache[K, V])",
            "RLock вместо Lock для reentrant safety",
            "_lock с underscore (private convention)",
            "Validation в __init__ (capacity > 0)",
            "Docstring с примером использования",
            "__len__ и __contains__ для удобства",
        ]
    ),
    
    "rest_api_user": CodeExample(
        name="REST API User CRUD",
        description="CRUD API для пользователей с валидацией",
        keywords=["api", "rest", "crud", "user", "endpoint", "flask", "fastapi"],
        bad_code='''
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///users.db'
db = SQLAlchemy(app)

class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80))
    email = db.Column(db.String(120))

@app.route('/users', methods=['POST'])
def create_user():
    data = request.get_json()
    new_user = User(username=data['username'], email=data['email'])
    db.session.add(new_user)
    db.session.commit()
    return jsonify({'message': 'Created'}), 201

if __name__ == '__main__':
    db.create_all()
    app.run(debug=True)
''',
        good_code='''
import os
from flask import Flask, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from marshmallow import Schema, fields, validate, ValidationError
from sqlalchemy.exc import IntegrityError

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL', 'sqlite:///users.db'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)


class User(db.Model):
    """User model with unique constraints."""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(120), unique=True, nullable=False, index=True)


class UserSchema(Schema):
    """Validation schema for user input."""
    username = fields.Str(
        required=True, 
        validate=validate.Length(min=3, max=80)
    )
    email = fields.Email(required=True)


user_schema = UserSchema()


@app.route('/users', methods=['GET'])
def list_users():
    """List users with pagination."""
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 20, type=int), 100)
    
    users = User.query.paginate(page=page, per_page=per_page, error_out=False)
    
    return jsonify({
        'users': [{'id': u.id, 'username': u.username, 'email': u.email} 
                  for u in users.items],
        'total': users.total,
        'page': page,
        'pages': users.pages
    })


@app.route('/users', methods=['POST'])
def create_user():
    """Create new user with validation."""
    try:
        data = user_schema.load(request.get_json())
    except ValidationError as err:
        return jsonify({'errors': err.messages}), 400
    
    try:
        user = User(**data)
        db.session.add(user)
        db.session.commit()
        return jsonify({
            'message': 'User created',
            'id': user.id
        }), 201
    except IntegrityError:
        db.session.rollback()
        return jsonify({'error': 'Username or email already exists'}), 409


@app.route('/users/<int:user_id>', methods=['GET'])
def get_user(user_id: int):
    """Get user by ID."""
    user = User.query.get_or_404(user_id)
    return jsonify({
        'id': user.id,
        'username': user.username,
        'email': user.email
    })


if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    # NEVER debug=True in production!
    app.run(debug=False)
''',
        why_better=[
            "Input validation (Marshmallow schema)",
            "Error handling с rollback",
            "Pagination для list endpoint",
            "Environment variable для DB URL",
            "Unique constraints + indexes",
            "debug=False (НИКОГДА True в production)",
            "HTTP 409 Conflict для duplicates",
        ]
    ),
}


# =============================================================================
# FUNCTIONS
# =============================================================================

def get_example(name: str) -> Optional[CodeExample]:
    """
    Получить пример по имени.
    
    Args:
        name: Имя примера (например, 'email_validation')
        
    Returns:
        CodeExample или None
    """
    return EXAMPLES.get(name)


def get_relevant_examples(query: str, max_examples: int = 2) -> List[CodeExample]:
    """
    Найти релевантные примеры по запросу.
    
    Args:
        query: Запрос пользователя
        max_examples: Максимум примеров
        
    Returns:
        Список релевантных примеров
    """
    query_lower = query.lower()
    relevant = []
    
    for name, example in EXAMPLES.items():
        # Проверяем keywords
        if any(kw in query_lower for kw in example.keywords):
            relevant.append(example)
    
    return relevant[:max_examples]


def format_example_for_prompt(example: CodeExample) -> str:
    """
    Форматирует пример для вставки в промпт.
    
    Args:
        example: CodeExample для форматирования
        
    Returns:
        Отформатированная строка
    """
    return f"""
### Пример: {example.name}
{example.description}

❌ **ПЛОХО** (типичная ошибка):
```python
{example.bad_code.strip()}
```

✅ **ХОРОШО** (качественный код):
```python
{example.good_code.strip()}
```

**Почему лучше:**
{chr(10).join(f'- {reason}' for reason in example.why_better)}
"""


def get_examples_for_prompt(query: str, max_examples: int = 2) -> str:
    """
    Получить отформатированные примеры для промпта.
    
    Args:
        query: Запрос пользователя
        max_examples: Максимум примеров
        
    Returns:
        Строка с примерами для промпта
    """
    examples = get_relevant_examples(query, max_examples)
    
    if not examples:
        return ""
    
    formatted = [format_example_for_prompt(ex) for ex in examples]
    
    return "\n\n---\n\n".join([
        "## ПРИМЕРЫ КАЧЕСТВЕННОГО КОДА\n\nСледуй этим паттернам:",
        *formatted
    ])


def list_examples() -> List[str]:
    """Список всех доступных примеров"""
    return list(EXAMPLES.keys())


# =============================================================================
# EXAMPLE USAGE
# =============================================================================

if __name__ == "__main__":
    # Тест 1: Получение примера
    print("=== Пример email_validation ===")
    ex = get_example("email_validation")
    if ex:
        print(f"Name: {ex.name}")
        print(f"Keywords: {ex.keywords}")
        print(f"Why better: {ex.why_better[:3]}...")
    
    # Тест 2: Поиск релевантных
    print("\n=== Релевантные примеры ===")
    queries = [
        "validate email address",
        "implement binary search",
        "create REST API for users",
    ]
    
    for q in queries:
        examples = get_relevant_examples(q)
        names = [ex.name for ex in examples]
        print(f"'{q}' → {names}")
    
    # Тест 3: Форматирование для промпта
    print("\n=== Форматированный пример ===")
    prompt_examples = get_examples_for_prompt("write bubble sort algorithm")
    print(prompt_examples[:500] + "...")
