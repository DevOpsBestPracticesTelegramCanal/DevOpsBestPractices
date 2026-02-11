# 📋 ПОШАГОВАЯ ПРОГРАММА РЕАЛИЗАЦИИ

## 🎯 ЦЕЛИ

| Метрика | До | После | Метод |
|---------|-----|-------|-------|
| Infra success (K8s/TF) | 0% | **100%** | Template Cache |
| Качество кода | 65% | **92%** | Self-Correction Loop |
| Ошибки валидации | 30% | **<5%** | 5-Level Validation |
| Legacy deps (v2→v4) | 70% | **0%** | Modernizer |
| Edge cases | 40% | **85%** | Feedback Loop |
| Latency (cache) | 30s+ | **<10ms** | TIER 0 Cache |

---

## 📅 ROADMAP (8 недель)

```
┌─────────────────────────────────────────────────────────────────┐
│   ФАЗА 1 (Недели 1-2): VALIDATION PIPELINE                      │
│   ├── 5-Level Validation System                                 │
│   ├── Adaptive Validation Profiles                              │
│   └── Domain-specific validators (K8s, TF, Docker)              │
├─────────────────────────────────────────────────────────────────┤
│   ФАЗА 2 (Недели 3-4): SELF-CORRECTION                          │
│   ├── Multi-Stage Generator                                     │
│   ├── Feedback extraction                                       │
│   └── Multi-candidate selection                                 │
├─────────────────────────────────────────────────────────────────┤
│   ФАЗА 3 (Недели 5-6): MEMORY & FEEDBACK                        │
│   ├── Working Memory для многошаговых задач                     │
│   ├── Feedback Loop (обучение на ошибках)                       │
│   └── Anti-pattern detection                                    │
├─────────────────────────────────────────────────────────────────┤
│   ФАЗА 4 (Недели 7-8): INTEGRATION & TESTING                    │
│   ├── Full Pipeline Integration                                 │
│   ├── Benchmarks на 50+ задачах                                 │
│   └── Performance optimization                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 🔧 ФАЗА 1: VALIDATION PIPELINE (Недели 1-2)

### Неделя 1: 5-Level Validation System

**Файл:** `core/validator.py`

**Уровни:**
| Level | Инструмент | Время | Что проверяет |
|-------|-----------|-------|---------------|
| L0 | AST Parser | 50ms | Синтаксис |
| L1 | ruff + mypy + bandit | 200ms | Lint + types + security |
| L2 | Sandbox execution | 500ms | Runtime errors |
| L3 | Hypothesis | 1s | Edge cases |
| L4 | kubeval/tflint/hadolint | 500ms | Domain-specific |

**Задачи:**
- [ ] Реализовать L0-L1 валидаторы
- [ ] Интегрировать внешние инструменты (ruff, bandit)
- [ ] Добавить domain-specific проверки (K8s, Terraform)
- [ ] Написать тесты

### Неделя 2: Adaptive Profiles

**Файл:** `core/validator.py` (ValidationProfile)

**Профили:**
```python
FAST_DEV = {
    "levels": [L0, L1],
    "timeout": 1.0,
    "fail_fast": True
}  # Для простых задач

SAFE_FIX = {
    "levels": [L0, L1, L2, L3, L4],
    "timeout": 10.0,
    "sandbox": True
}  # Для production

BACKGROUND_AUDIT = {
    "levels": [L0, L1, L2, L3, L4],
    "timeout": 60.0,
    "async": True
}  # Фоновый аудит
```

**Задачи:**
- [ ] Реализовать выбор профиля по типу задачи
- [ ] Добавить автоопределение risk level
- [ ] Интегрировать с SWECAS классификатором

---

## 🔁 ФАЗА 2: SELF-CORRECTION (Недели 3-4)

### Неделя 3: Multi-Stage Generator

**Файл:** `core/self_correction.py`

**Алгоритм:**
```
1. Генерация (temp=0.5)
      ↓
2. Валидация (5-Level)
      ↓
3. Ошибки? → Извлечь feedback
      ↓
4. Улучшить prompt
      ↓
5. Повторить (до 3 раз)
      ↓
6. Выбрать лучший
```

**Задачи:**
- [ ] Реализовать SelfCorrectionGenerator
- [ ] Добавить extraction ошибок в feedback
- [ ] Реализовать улучшение prompt на основе feedback
- [ ] Добавить scoring кандидатов

### Неделя 4: Multi-Candidate Selection

**Файл:** `core/self_correction.py` (MultiCandidateGenerator)

**Стратегия:**
- Генерация 3 кандидатов (temp: 0.2, 0.5, 0.8)
- Параллельная валидация
- Выбор по composite score

**Задачи:**
- [ ] Реализовать параллельную генерацию
- [ ] Добавить weighted scoring
- [ ] Интегрировать с Self-Correction

---

## 🧠 ФАЗА 3: MEMORY & FEEDBACK (Недели 5-6)

### Неделя 5: Working Memory

**Файл:** `core/memory.py`

**Структура:**
```python
WorkingMemory:
    goal: str           # Цель задачи
    plan: List[str]     # Шаги выполнения  
    facts: List[str]    # Извлечённые факты
    decisions: List[str] # Принятые решения
    tool_log: List[Dict] # История инструментов
```

**Задачи:**
- [ ] Реализовать WorkingMemory dataclass
- [ ] Добавить compact() для сжатия в prompt
- [ ] Интегрировать в pipeline генерации

### Неделя 6: Feedback Loop

**Файл:** `core/memory.py` (FeedbackLoop)

**Функции:**
- Логирование outcomes (applied/rejected/rollback)
- Анализ частых ошибок → anti-patterns
- Injection warnings в prompt

**Задачи:**
- [ ] Реализовать SQLite схему для outcomes
- [ ] Добавить анализ anti-patterns
- [ ] Генерация warnings для prompt
- [ ] Интеграция с pipeline

---

## 🔗 ФАЗА 4: INTEGRATION (Недели 7-8)

### Неделя 7: Full Pipeline

**Файл:** `core/pipeline.py`

**Flow:**
```
Request
    ↓
[1] Task Classifier → type, risk_level, language
    ↓
[2] TIER 0: Template Cache → 100% DevOps
    ↓ (miss)
[3] Build Enhanced Prompt:
    - Quality requirements
    - Few-shot examples  
    - Feedback warnings
    - Working memory context
    ↓
[4] Generate (tier-based):
    - TIER 1: Simple
    - TIER 2: Self-correction
    - TIER 3: Multi-candidate
    ↓
[5] Post-process: Modernizer
    ↓
[6] Validate: 5-Level
    ↓
[7] Log Feedback
    ↓
Result
```

**Задачи:**
- [ ] Интегрировать все компоненты
- [ ] Добавить tier selection логику
- [ ] Реализовать graceful degradation

### Неделя 8: Testing & Optimization

**Задачи:**
- [ ] Benchmark на 50+ задачах из PDF
- [ ] Профилирование latency
- [ ] Оптимизация bottlenecks
- [ ] Документация

---

## 📊 МЕТРИКИ УСПЕХА

### KPIs по фазам:

| Фаза | Метрика | Цель |
|------|---------|------|
| 1 | Validation coverage | 95% ошибок обнаружено |
| 2 | Self-correction success | +40% качества |
| 3 | Repeat errors | -50% повторяющихся ошибок |
| 4 | E2E success rate | >90% на benchmark |

### Тестовые задачи:

1. **Algorithms:** bubble sort, binary search, LRU cache
2. **Infrastructure:** K8s deployment, Terraform S3, GitHub Actions
3. **API:** REST CRUD, validation, auth
4. **Security:** SQL injection prevention, secrets management

---

## 🚀 БЫСТРЫЙ СТАРТ

```bash
# 1. Копировать файлы
cp -r qwencode_improvements/ /path/to/project/

# 2. Установить зависимости
pip install ruff pytest pyyaml

# 3. Запустить тесты
cd qwencode_improvements
python -m pytest tests/ -v

# 4. Протестировать pipeline
python -c "
import asyncio
from core.pipeline import QwenCodePipeline, MockLLMClient

async def test():
    pipeline = QwenCodePipeline(MockLLMClient())
    result = await pipeline.generate('create nginx deployment')
    print(result.summary())

asyncio.run(test())
"
```

---

## 📁 СТРУКТУРА ФАЙЛОВ

```
qwencode_improvements/
├── cache/
│   └── devops_templates.py    # TIER 0: 10+ DevOps шаблонов
├── core/
│   ├── validator.py           # 5-Level Validation
│   ├── modernizer.py          # Post-processing
│   ├── self_correction.py     # Self-Correction Loop
│   ├── memory.py              # Working Memory + Feedback
│   ├── pipeline.py            # Full Pipeline Integration
│   └── enhanced_generator.py  # Basic enhanced generator
├── prompts/
│   └── quality_prompts.py     # Quality requirements
├── knowledge/
│   └── few_shot.py            # Few-shot examples
├── tests/
│   └── test_all.py            # Pytest tests
├── README.md
└── ROADMAP.md                 # ← Этот файл
```

---

**Ключевой вывод:** Слабости модели 7B компенсируются системным дизайном. Не нужно переходить на 32B для получения качественного кода — инвестиции в pipeline дают лучший ROI.
