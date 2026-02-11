"""
Quality Prompts для QwenCode Generator
======================================
Инжектит требования качества в промпт LLM.

Решает проблему: LLM генерирует "школьный" код без best practices.

Использование:
    from core.codegen.quality_prompts import inject_quality_requirements, get_prompt_for_task
    
    enhanced_prompt = inject_quality_requirements(user_query, task_type="python")
"""

from typing import Dict, Optional
from enum import Enum


class TaskType(Enum):
    PYTHON = "python"
    KUBERNETES = "kubernetes"
    TERRAFORM = "terraform"
    GITHUB_ACTIONS = "github_actions"
    DOCKERFILE = "dockerfile"
    REST_API = "rest_api"
    ALGORITHM = "algorithm"
    DATABASE = "database"


# =============================================================================
# QUALITY REQUIREMENTS BY TASK TYPE
# =============================================================================

QUALITY_REQUIREMENTS: Dict[str, str] = {
    "python": """
## ОБЯЗАТЕЛЬНЫЕ ТРЕБОВАНИЯ К PYTHON КОДУ:

1. **Type Hints**: Укажи типы для ВСЕХ параметров и return value
   - Используй `list[int]`, `dict[str, Any]`, `Optional[str]`
   - Для callable: `Callable[[int, str], bool]`

2. **Docstring**: Google-style с Args, Returns, Raises
   ```python
   def func(param: str) -> bool:
       \"\"\"Краткое описание.
       
       Args:
           param: Описание параметра.
       
       Returns:
           Описание возвращаемого значения.
           
       Raises:
           ValueError: Когда param невалиден.
       \"\"\"
   ```

3. **Edge Cases**: Обработай граничные случаи
   - None/пустой input → ранний return или raise
   - Невалидные типы → проверка isinstance или TypeGuard
   - Пустые коллекции → проверка `if not items:`

4. **Константы**: Выноси magic values
   - `TIMEOUT_SECONDS = 30` вместо `timeout=30`
   - `EMAIL_REGEX = re.compile(...)` вместо inline regex

5. **Guard Clauses**: Используй ранний return
   ```python
   if not data:
       return []
   # основная логика
   ```

6. **Thread Safety**: Если многопоточность
   - `threading.RLock()` вместо `Lock()` для reentrant
   - `with self._lock:` для context manager
""",

    "kubernetes": """
## ОБЯЗАТЕЛЬНЫЕ ТРЕБОВАНИЯ К KUBERNETES YAML:

1. **API Version**: Используй стабильные версии
   - `apiVersion: apps/v1` (НЕ v1beta1, v1beta2)
   - `apiVersion: networking.k8s.io/v1` (НЕ extensions/v1beta1)

2. **Labels**: Следуй схеме app.kubernetes.io
   ```yaml
   labels:
     app.kubernetes.io/name: myapp
     app.kubernetes.io/version: "1.0"
     app.kubernetes.io/component: backend
   ```

3. **Resources**: ВСЕГДА указывай requests и limits
   ```yaml
   resources:
     requests:
       cpu: "100m"
       memory: "64Mi"
     limits:
       cpu: "200m"
       memory: "128Mi"
   ```

4. **Probes**: ВСЕГДА добавляй health checks
   ```yaml
   livenessProbe:
     httpGet:
       path: /health
       port: 8080
     initialDelaySeconds: 30
     periodSeconds: 10
   readinessProbe:
     httpGet:
       path: /ready
       port: 8080
     initialDelaySeconds: 5
     periodSeconds: 5
   ```

5. **Image Tags**: НИКОГДА не используй :latest
   - `nginx:1.27-alpine` ✓
   - `nginx:latest` ✗

6. **Security Context**: Добавь ограничения
   ```yaml
   securityContext:
     allowPrivilegeEscalation: false
     capabilities:
       drop: ["ALL"]
   ```
""",

    "terraform": """
## ОБЯЗАТЕЛЬНЫЕ ТРЕБОВАНИЯ К TERRAFORM (AWS Provider 5.x):

1. **Provider Version**: Используй актуальную версию
   ```hcl
   terraform {
     required_version = ">= 1.5"
     required_providers {
       aws = {
         source  = "hashicorp/aws"
         version = "~> 5.0"
       }
     }
   }
   ```

2. **S3 Buckets**: НЕ используй deprecated атрибуты
   - ❌ `acl = "private"` — deprecated
   - ✓ Используй `aws_s3_bucket_ownership_controls`
   - ❌ `lifecycle_rule {}` внутри bucket — deprecated
   - ✓ Используй `aws_s3_bucket_lifecycle_configuration`
   - ❌ `versioning {}` внутри bucket — deprecated
   - ✓ Используй `aws_s3_bucket_versioning`

3. **Security**: ВСЕГДА добавляй
   ```hcl
   resource "aws_s3_bucket_public_access_block" "main" {
     bucket                  = aws_s3_bucket.main.id
     block_public_acls       = true
     block_public_policy     = true
     ignore_public_acls      = true
     restrict_public_buckets = true
   }
   
   resource "aws_s3_bucket_server_side_encryption_configuration" "main" {
     bucket = aws_s3_bucket.main.id
     rule {
       apply_server_side_encryption_by_default {
         sse_algorithm = "AES256"
       }
     }
   }
   ```

4. **Variables**: Добавляй validation
   ```hcl
   variable "bucket_name" {
     type = string
     validation {
       condition     = can(regex("^[a-z0-9.-]+$", var.bucket_name))
       error_message = "Bucket name must be DNS-compliant."
     }
   }
   ```

5. **Outputs**: Описывай все важные атрибуты
   ```hcl
   output "bucket_arn" {
     description = "ARN of the S3 bucket"
     value       = aws_s3_bucket.main.arn
   }
   ```
""",

    "github_actions": """
## ОБЯЗАТЕЛЬНЫЕ ТРЕБОВАНИЯ К GITHUB ACTIONS:

1. **Action Versions**: Используй последние major версии
   - `actions/checkout@v4` (НЕ v2, v3)
   - `actions/setup-python@v5` (НЕ v2, v3, v4)
   - `actions/setup-node@v4`
   - `docker/build-push-action@v5`

2. **Python Version**: Используй поддерживаемые версии
   - ✓ `python-version: '3.11'` или `'3.12'`
   - ❌ `python-version: '3.7'` или `'3.8'` (EOL)

3. **Caching**: ВСЕГДА включай cache
   ```yaml
   - uses: actions/setup-python@v5
     with:
       python-version: '3.12'
       cache: 'pip'
   ```

4. **Concurrency**: Добавляй для экономии ресурсов
   ```yaml
   concurrency:
     group: ${{ github.workflow }}-${{ github.ref }}
     cancel-in-progress: true
   ```

5. **Matrix Testing**: Тестируй на нескольких версиях
   ```yaml
   strategy:
     fail-fast: false
     matrix:
       python-version: ['3.11', '3.12']
   ```

6. **Linting**: Используй современные инструменты
   - ✓ `ruff check .` — быстрый, современный
   - ❌ `flake8 .` — устаревший, медленный
""",

    "dockerfile": """
## ОБЯЗАТЕЛЬНЫЕ ТРЕБОВАНИЯ К DOCKERFILE:

1. **Multi-stage Build**: Уменьшай размер образа
   ```dockerfile
   FROM python:3.12-slim AS builder
   # ... установка зависимостей
   
   FROM python:3.12-slim
   COPY --from=builder /opt/venv /opt/venv
   ```

2. **Non-root User**: Запускай от непривилегированного пользователя
   ```dockerfile
   RUN groupadd -r appgroup && useradd -r -g appgroup appuser
   USER appuser
   ```

3. **Image Tags**: Используй конкретные версии
   - ✓ `python:3.12-slim`
   - ❌ `python:latest`

4. **Layer Optimization**: Объединяй RUN команды
   ```dockerfile
   RUN pip install --no-cache-dir --upgrade pip && \\
       pip install --no-cache-dir -r requirements.txt
   ```

5. **Health Check**: Добавляй проверку здоровья
   ```dockerfile
   HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \\
       CMD curl -f http://localhost:8000/health || exit 1
   ```

6. **EXPOSE и CMD**: Документируй порт и команду запуска
   ```dockerfile
   EXPOSE 8000
   CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
   ```
""",

    "rest_api": """
## ОБЯЗАТЕЛЬНЫЕ ТРЕБОВАНИЯ К REST API:

1. **Input Validation**: ВСЕГДА валидируй входные данные
   ```python
   from pydantic import BaseModel, EmailStr
   
   class UserCreate(BaseModel):
       email: EmailStr
       name: str = Field(..., min_length=1, max_length=100)
   ```

2. **Error Handling**: Используй try/except с rollback
   ```python
   try:
       db.session.add(user)
       db.session.commit()
   except IntegrityError:
       db.session.rollback()
       raise HTTPException(400, "User already exists")
   ```

3. **HTTP Status Codes**: Правильные коды ответов
   - `201 Created` — создание ресурса
   - `400 Bad Request` — невалидные данные
   - `404 Not Found` — ресурс не найден
   - `409 Conflict` — конфликт (duplicate)

4. **Authentication**: НЕ оставляй endpoints открытыми
   ```python
   @app.route('/users')
   @jwt_required()
   def list_users():
       ...
   ```

5. **Pagination**: Для list endpoints
   ```python
   @app.get('/users')
   def list_users(page: int = 1, per_page: int = 20):
       per_page = min(per_page, 100)  # Лимит
       ...
   ```

6. **Debug Mode**: НИКОГДА в production
   ```python
   if __name__ == '__main__':
       app.run(debug=False)  # НЕ debug=True!
   ```
""",

    "algorithm": """
## ОБЯЗАТЕЛЬНЫЕ ТРЕБОВАНИЯ К АЛГОРИТМАМ:

1. **Complexity Analysis**: Укажи в docstring
   ```python
   def binary_search(arr: list[int], target: int) -> int:
       \"\"\"Binary search in sorted array.
       
       Time: O(log n)
       Space: O(1)
       \"\"\"
   ```

2. **Optimizations**: Добавляй стандартные оптимизации
   - Bubble sort → early termination (swapped flag)
   - Binary search → overflow-safe mid: `left + (right - left) // 2`

3. **Edge Cases**: Обрабатывай граничные случаи
   ```python
   if not arr:
       return -1
   if len(arr) == 1:
       return 0 if arr[0] == target else -1
   ```

4. **In-place vs Copy**: Документируй поведение
   ```python
   def sort_inplace(arr: list[int]) -> list[int]:
       \"\"\"Sorts array IN-PLACE and returns reference.\"\"\"
   ```

5. **Type Hints**: Точные типы для алгоритмов
   ```python
   def merge_sort(arr: list[T]) -> list[T]:
       ...
   ```
""",

    "database": """
## ОБЯЗАТЕЛЬНЫЕ ТРЕБОВАНИЯ К РАБОТЕ С БД:

1. **Connection Pooling**: Используй пулы соединений
   ```python
   engine = create_engine(url, pool_size=5, max_overflow=10)
   ```

2. **Transactions**: Явно управляй транзакциями
   ```python
   with db.session.begin():
       db.session.add(obj)
   # auto-commit on exit
   ```

3. **Parameterized Queries**: НИКОГДА не конкатенируй SQL
   ```python
   # ✓ Правильно
   cursor.execute("SELECT * FROM users WHERE id = %s", (user_id,))
   
   # ✗ SQL Injection!
   cursor.execute(f"SELECT * FROM users WHERE id = {user_id}")
   ```

4. **Indexes**: Добавляй индексы для частых запросов
   ```python
   class User(Base):
       email = Column(String, unique=True, index=True)
   ```

5. **Migrations**: Используй Alembic/Django migrations
   ```bash
   alembic revision --autogenerate -m "add users table"
   alembic upgrade head
   ```
""",
}


# =============================================================================
# FUNCTIONS
# =============================================================================

def inject_quality_requirements(prompt: str, task_type: str) -> str:
    """
    Добавляет требования качества в промпт.
    
    Args:
        prompt: Оригинальный промпт пользователя
        task_type: Тип задачи (python, kubernetes, terraform, etc.)
        
    Returns:
        Промпт с добавленными требованиями качества
    """
    requirements = QUALITY_REQUIREMENTS.get(task_type.lower(), "")
    
    if requirements:
        return f"{requirements}\n\n---\n\nЗАДАЧА: {prompt}\n\nСгенерируй код, строго следуя требованиям выше."
    
    return prompt


def detect_task_type(query: str) -> str:
    """
    Автоматически определяет тип задачи по запросу.
    
    Args:
        query: Запрос пользователя
        
    Returns:
        Тип задачи (python, kubernetes, terraform, etc.)
    """
    query_lower = query.lower()
    
    # Kubernetes
    if any(kw in query_lower for kw in ['kubernetes', 'k8s', 'deployment', 'pod', 'service', 'ingress']):
        return 'kubernetes'
    
    # Terraform
    if any(kw in query_lower for kw in ['terraform', 'aws', 'infrastructure', 'iac', 's3', 'ec2', 'lambda']):
        return 'terraform'
    
    # GitHub Actions
    if any(kw in query_lower for kw in ['github action', 'ci/cd', 'workflow', 'pipeline']):
        return 'github_actions'
    
    # Dockerfile
    if any(kw in query_lower for kw in ['dockerfile', 'docker image', 'container']):
        return 'dockerfile'
    
    # REST API
    if any(kw in query_lower for kw in ['rest api', 'endpoint', 'crud', 'fastapi', 'flask api']):
        return 'rest_api'
    
    # Algorithms
    if any(kw in query_lower for kw in ['sort', 'search', 'algorithm', 'leetcode', 'binary search']):
        return 'algorithm'
    
    # Database
    if any(kw in query_lower for kw in ['database', 'sql', 'query', 'migration', 'orm']):
        return 'database'
    
    # Default: Python
    return 'python'


def get_prompt_for_task(query: str, task_type: Optional[str] = None) -> str:
    """
    Получает полный промпт с требованиями качества.
    
    Args:
        query: Запрос пользователя
        task_type: Тип задачи (опционально, автоопределяется)
        
    Returns:
        Промпт с требованиями качества
    """
    if task_type is None:
        task_type = detect_task_type(query)
    
    return inject_quality_requirements(query, task_type)


def list_task_types() -> list:
    """Возвращает список поддерживаемых типов задач"""
    return list(QUALITY_REQUIREMENTS.keys())


# =============================================================================
# EXAMPLE USAGE
# =============================================================================

if __name__ == "__main__":
    # Пример 1: Python function
    print("=== Python Task ===")
    prompt = get_prompt_for_task("write a function to validate email addresses")
    print(prompt[:500] + "...\n")
    
    # Пример 2: Kubernetes
    print("=== Kubernetes Task ===")
    prompt = get_prompt_for_task("create kubernetes deployment for nginx")
    print(prompt[:500] + "...\n")
    
    # Пример 3: Автоопределение
    print("=== Auto-detect ===")
    test_queries = [
        "terraform module for s3 bucket",
        "github actions ci for python",
        "binary search algorithm",
    ]
    
    for q in test_queries:
        task_type = detect_task_type(q)
        print(f"'{q}' → {task_type}")
