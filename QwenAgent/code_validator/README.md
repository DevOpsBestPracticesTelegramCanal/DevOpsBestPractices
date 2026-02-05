# Code Validator 🛡️

**Многоуровневая система валидации AI-сгенерированного Python-кода**

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

---

## 🎯 Зачем это нужно?

AI-модели (GPT, Claude, Gemini) генерируют код, который может содержать:
- **Уязвимости безопасности** (eval, exec, system calls)
- **Синтаксические ошибки**
- **Бесконечные циклы** и утечки памяти
- **Нарушения стиля** и типизации

Code Validator проверяет код на **6 уровнях** до его выполнения.

---

## 📦 Установка

```bash
# Минимальная (только core, без внешних зависимостей)
pip install code-validator

# С статическим анализом
pip install code-validator[static]

# Полная установка
pip install code-validator[full]

# Из исходников
git clone https://github.com/example/code-validator
cd code-validator
pip install -e ".[full]"
```

---

## 🚀 Быстрый старт

### Проверка безопасности (1 строка)

```python
from code_validator import is_safe

code = """
import os
os.system("rm -rf /")
"""

if is_safe(code):
    exec(code)  # Никогда не выполнится!
else:
    print("Код отклонён!")
```

### Полная валидация

```python
from code_validator import validate_code

code = """
def fibonacci(n: int) -> int:
    if n <= 1:
        return n
    return fibonacci(n - 1) + fibonacci(n - 2)
"""

report = validate_code(code)
print(report.summary())
```

Вывод:
```
══════════════════════════════════════════════════
  ОТЧЁТ О ВАЛИДАЦИИ
══════════════════════════════════════════════════
  Статус: PASSED
  Время: 0.234s
  Пройдено уровней: 4/5
──────────────────────────────────────────────────
  ✓ PREVALIDATION: 0.001s
  ✓ STATIC_ANALYSIS: 0.198s
  ✓ SANDBOX_EXECUTION: 0.032s
  ⊘ PROPERTY_TESTING: пропущен (Имя функции не указано)
  ✓ RESOURCE_MONITORING: 0.001s
══════════════════════════════════════════════════
```

---

## 🔍 Уровни проверки

| Уровень | Название | Что проверяет | Время |
|---------|----------|---------------|-------|
| 0 | **Превалидация** | Синтаксис, запрещённые импорты, опасные паттерны | ~1ms |
| 1 | **Статический анализ** | Ruff, Mypy, Bandit | ~100ms |
| 2 | **Sandbox** | Безопасное выполнение в изоляции | ~1-10s |
| 3 | **Property-тесты** | Hypothesis: граничные случаи | ~5-30s |
| 4 | **Ресурсы** | Память, CPU, время | ~0ms |

---

## ⚙️ Конфигурация

```python
from code_validator import CodeValidator, ValidatorConfig, SandboxType

config = ValidatorConfig(
    # Поведение
    stop_on_failure=True,       # Остановиться при первой ошибке
    
    # Превалидация
    max_code_length=50_000,     # Максимум символов
    max_lines=1000,             # Максимум строк
    
    # Статический анализ
    use_ruff=True,
    use_mypy=True,
    use_bandit=True,
    static_analysis_timeout=30,
    
    # Sandbox
    sandbox_type=SandboxType.SUBPROCESS,  # или DOCKER, RESTRICTED_PYTHON
    sandbox_timeout=10.0,
    sandbox_max_memory_mb=128,
    
    # Property-тесты
    enable_property_tests=True,
    property_test_examples=100,
)

validator = CodeValidator(config)
report = validator.validate(code, test_function_name="my_function")
```

---

## 🐳 Docker Sandbox (максимальная изоляция)

```python
from code_validator import execute_safe, SandboxType

# Выполнение в Docker-контейнере
result = execute_safe(
    code,
    sandbox_type=SandboxType.DOCKER,
)

print(result.stdout)
```

Контейнер запускается с ограничениями:
- ❌ Без сети (`--network=none`)
- ❌ Без записи (`--read-only`)
- 🔒 128MB RAM
- 🔒 50% CPU
- 🔒 10 секунд таймаут

---

## 🧪 Property-тесты

Проверка свойств функции без знания конкретных результатов:

```python
from code_validator import test_function_properties

def sort_list(items: list[int]) -> list[int]:
    return sorted(items)

result = test_function_properties(sort_list, max_examples=200)

# Автоматически проверяет:
# ✓ Не выбрасывает исключения на любых входных данных
# ✓ Детерминированность: f(x) == f(x)
# ✓ Идемпотентность: f(f(x)) == f(x) (для сортировки — да!)
```

### Кастомные проверки свойств

```python
from code_validator import PropertyTester, CommonPropertyChecks

tester = PropertyTester()

# Проверка: длина списка сохраняется
result = tester.test_custom_property(
    my_function,
    property_check=CommonPropertyChecks.list_length_preserved,
    property_name="length_preserved"
)
```

---

## 🚫 Запрещённые паттерны

По умолчанию блокируются:

**Модули:**
```
os, sys, subprocess, shutil, pathlib,
socket, requests, urllib, http,
ctypes, multiprocessing, threading,
pickle, shelve, marshal,
importlib, runpy, __builtin__, builtins
```

**Функции:**
```
eval, exec, compile, open, input,
__import__, globals, locals, vars,
getattr, setattr, delattr, breakpoint
```

**Атрибуты (sandbox escape):**
```
__code__, __globals__, __builtins__,
__subclasses__, __bases__, __mro__
```

### Кастомизация

```python
from code_validator import Prevalidator

# Добавить свои запреты
validator = Prevalidator(
    forbidden_imports=frozenset({"os", "sys", "json", "datetime"}),
    forbidden_builtins=frozenset({"eval", "exec", "print"}),
)
```

---

## 📊 API Reference

### Быстрые функции

```python
# Проверка безопасности
is_safe(code: str) -> bool

# Полная валидация
validate_code(code: str, **config) -> ValidationReport

# Только превалидация
prevalidate(code: str, **config) -> PrevalidationResult

# Только статический анализ
analyze_static(code: str, **config) -> StaticAnalysisResult

# Безопасное выполнение
execute_safe(code: str, sandbox_type=...) -> ExecutionResult
```

### Классы

```python
# Главный валидатор
CodeValidator(config: ValidatorConfig)
    .validate(code, test_function_name=None) -> ValidationReport
    .quick_check(code) -> bool

# Превалидатор
Prevalidator(max_code_length=..., forbidden_imports=...)
    .validate(code) -> PrevalidationResult

# Статический анализатор
StaticAnalyzer(use_ruff=True, use_mypy=True, use_bandit=True)
    .analyze(code) -> StaticAnalysisResult

# Песочницы
SubprocessSandbox(config: SandboxConfig)
DockerSandbox(config: SandboxConfig, image="python:3.12-slim")
RestrictedPythonSandbox(config: SandboxConfig)
    .execute(code, globals_dict=None) -> ExecutionResult

# Property-тестер
PropertyTester(max_examples=100)
    .run_all_tests(func) -> PropertyTestSuiteResult
    .test_no_exception(func) -> PropertyTestResult
    .test_deterministic(func) -> PropertyTestResult
    .test_idempotent(func) -> PropertyTestResult
```

---

## 🔧 Интеграция в CI/CD

```yaml
# .github/workflows/validate.yml
name: Validate Generated Code

on: [push]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      
      - name: Setup Python
        uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      
      - name: Install dependencies
        run: pip install code-validator[full]
      
      - name: Validate code
        run: |
          python -c "
          from code_validator import validate_code
          import sys
          
          with open('generated_code.py') as f:
              code = f.read()
          
          report = validate_code(code)
          print(report.summary())
          
          if report.status.value == 'failed':
              sys.exit(1)
          "
```

---

## 📁 Структура проекта

```
code_validator/
├── __init__.py          # Точка входа, экспорты
├── prevalidator.py      # Уровень 0: AST-анализ
├── static_analysis.py   # Уровень 1: Ruff, Mypy, Bandit
├── sandbox.py           # Уровень 2: Изолированное выполнение
├── property_tests.py    # Уровень 3: Hypothesis
├── resource_guard.py    # Уровень 4: Мониторинг ресурсов
├── validator.py         # Оркестратор
├── example_usage.py     # Примеры
├── requirements.txt
├── pyproject.toml
└── README.md
```

---

## 🤝 Contributing

1. Fork репозитория
2. Создайте ветку (`git checkout -b feature/amazing`)
3. Commit изменений (`git commit -m 'Add amazing feature'`)
4. Push в ветку (`git push origin feature/amazing`)
5. Откройте Pull Request

---

## 📄 Лицензия

MIT License — используйте свободно!

---

## 🙏 Благодарности

- [Ruff](https://github.com/astral-sh/ruff) — молниеносный линтер
- [Mypy](https://github.com/python/mypy) — статическая типизация
- [Bandit](https://github.com/PyCQA/bandit) — анализ безопасности
- [Hypothesis](https://github.com/HypothesisWorks/hypothesis) — property-based testing
- [RestrictedPython](https://github.com/zopefoundation/RestrictedPython) — безопасное выполнение
