# -*- coding: utf-8 -*-
"""
budget_estimator.py — Автоматическая оценка бюджета задачи
==========================================================

Фаза 2: Определяет бюджет задачи на основе:
- Режима выполнения (FAST, DEEP3, DEEP6, SEARCH)
- Пользовательских предпочтений (max_wait, priority)
- Характеристик запроса (длина промпта, сложность)

Принцип: "Агент определяет базовый бюджет по режиму,
          пользователь ограничивает потолком max_wait"

Использование:
    from core.budget_estimator import estimate_task_budget, BudgetEstimator

    # Простой вызов
    budget_seconds = estimate_task_budget(
        mode=ExecutionMode.DEEP3,
        user_prefs=user_prefs,
        prompt_length=500
    )

    # Или через класс
    estimator = BudgetEstimator(user_prefs)
    budget = estimator.create_budget(mode, prompt)
"""

from typing import Optional, Dict, Any
from dataclasses import dataclass

from .execution_mode import ExecutionMode
from .user_timeout_config import UserTimeoutPreferences
from .time_budget import TimeBudget, BudgetPresets


@dataclass
class BudgetEstimate:
    """Результат оценки бюджета."""
    total_seconds: float
    mode: str
    steps: list
    critical_step: str
    adjustments: Dict[str, float]  # Какие корректировки применены
    confidence: float  # Уверенность в оценке (0.0 - 1.0)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_seconds": self.total_seconds,
            "mode": self.mode,
            "steps": self.steps,
            "critical_step": self.critical_step,
            "adjustments": self.adjustments,
            "confidence": f"{self.confidence:.0%}"
        }


class BudgetEstimator:
    """
    Оценщик бюджета для задач.

    Учитывает:
    1. Режим выполнения (базовый бюджет)
    2. Длину промпта (корректировка на prefill)
    3. Приоритет пользователя (speed/quality)
    4. Потолок max_wait (жёсткое ограничение)
    5. Историю выполнения (если доступна)
    """

    # Базовые бюджеты по режимам (секунды)
    MODE_BASE_BUDGETS = {
        ExecutionMode.FAST: 30,
        ExecutionMode.DEEP3: 120,
        ExecutionMode.DEEP6: 300,
        ExecutionMode.SEARCH: 45,
        ExecutionMode.SEARCH_DEEP: 180,
    }

    # Шаги по режимам
    MODE_STEPS = {
        ExecutionMode.FAST: ["execute"],
        ExecutionMode.DEEP3: ["analyze", "plan", "execute"],
        ExecutionMode.DEEP6: [
            "understanding", "challenges", "approaches",
            "constraints", "choose", "solution"
        ],
        ExecutionMode.SEARCH: ["search", "summarize"],
        ExecutionMode.SEARCH_DEEP: ["search", "analyze", "synthesize"],
    }

    # Критические шаги по режимам
    MODE_CRITICAL_STEPS = {
        ExecutionMode.FAST: "execute",
        ExecutionMode.DEEP3: "execute",
        ExecutionMode.DEEP6: "solution",
        ExecutionMode.SEARCH: "summarize",
        ExecutionMode.SEARCH_DEEP: "synthesize",
    }

    # Множители для приоритета пользователя
    PRIORITY_MULTIPLIERS = {
        "speed": 0.6,
        "balanced": 1.0,
        "quality": 1.5,
    }

    # Пороги длины промпта для корректировки
    PROMPT_LENGTH_THRESHOLDS = [
        (500, 1.0),    # < 500 слов: без корректировки
        (1000, 1.1),   # 500-1000: +10%
        (2000, 1.25),  # 1000-2000: +25%
        (5000, 1.5),   # 2000-5000: +50%
        (10000, 2.0),  # 5000-10000: +100%
        (float('inf'), 2.5),  # > 10000: +150%
    ]

    def __init__(self, user_prefs: UserTimeoutPreferences = None):
        """
        Инициализация оценщика.

        Args:
            user_prefs: Пользовательские предпочтения
        """
        self.user_prefs = user_prefs or UserTimeoutPreferences()
        self.history: list = []  # История оценок для калибровки

    def estimate(
        self,
        mode: ExecutionMode,
        prompt: str = "",
        complexity_hint: str = None
    ) -> BudgetEstimate:
        """
        Оценить бюджет для задачи.

        Args:
            mode: Режим выполнения
            prompt: Текст запроса (для оценки длины)
            complexity_hint: Подсказка о сложности ("simple", "medium", "complex")

        Returns:
            BudgetEstimate с деталями оценки
        """
        adjustments = {}

        # 1. Базовый бюджет по режиму
        base = self.MODE_BASE_BUDGETS.get(mode, 120)
        adjustments["base"] = base

        # 2. Корректировка по длине промпта
        prompt_length = len(prompt.split()) if prompt else 0
        prompt_multiplier = self._get_prompt_multiplier(prompt_length)
        adjustments["prompt_length"] = prompt_multiplier

        # 3. Корректировка по приоритету пользователя
        priority_multiplier = self.PRIORITY_MULTIPLIERS.get(
            self.user_prefs.priority, 1.0
        )
        adjustments["priority"] = priority_multiplier

        # 4. Корректировка по сложности (если указана)
        complexity_multiplier = 1.0
        if complexity_hint:
            complexity_multiplier = {
                "simple": 0.7,
                "medium": 1.0,
                "complex": 1.5,
                "very_complex": 2.0
            }.get(complexity_hint, 1.0)
            adjustments["complexity"] = complexity_multiplier

        # Вычисляем итоговый бюджет
        estimated = base * prompt_multiplier * priority_multiplier * complexity_multiplier

        # 5. Ограничиваем пользовательским max_wait
        final = min(estimated, self.user_prefs.max_wait)
        if final < estimated:
            adjustments["max_wait_cap"] = self.user_prefs.max_wait

        # Определяем уверенность
        confidence = self._calculate_confidence(prompt_length, complexity_hint)

        return BudgetEstimate(
            total_seconds=final,
            mode=mode.value,
            steps=self.MODE_STEPS.get(mode, ["execute"]),
            critical_step=self.MODE_CRITICAL_STEPS.get(mode, "execute"),
            adjustments=adjustments,
            confidence=confidence
        )

    def create_budget(
        self,
        mode: ExecutionMode,
        prompt: str = "",
        complexity_hint: str = None
    ) -> TimeBudget:
        """
        Создать TimeBudget на основе оценки.

        Args:
            mode: Режим выполнения
            prompt: Текст запроса
            complexity_hint: Подсказка о сложности

        Returns:
            Готовый TimeBudget объект
        """
        estimate = self.estimate(mode, prompt, complexity_hint)

        return TimeBudget(
            total_seconds=estimate.total_seconds,
            steps=estimate.steps,
            critical_step=estimate.critical_step
        )

    def _get_prompt_multiplier(self, word_count: int) -> float:
        """Получить множитель на основе длины промпта."""
        for threshold, multiplier in self.PROMPT_LENGTH_THRESHOLDS:
            if word_count < threshold:
                return multiplier
        return 2.5

    def _calculate_confidence(
        self,
        prompt_length: int,
        complexity_hint: str
    ) -> float:
        """
        Рассчитать уверенность в оценке.

        Высокая уверенность: есть complexity_hint, средняя длина промпта
        Низкая уверенность: нет подсказок, очень длинный/короткий промпт
        """
        confidence = 0.7  # Базовая уверенность

        # Подсказка о сложности повышает уверенность
        if complexity_hint:
            confidence += 0.15

        # Экстремальная длина снижает уверенность
        if prompt_length < 50 or prompt_length > 5000:
            confidence -= 0.1

        # История использования повышает уверенность
        if len(self.history) > 10:
            confidence += 0.1

        return min(max(confidence, 0.3), 1.0)

    def record_actual(
        self,
        estimate: BudgetEstimate,
        actual_seconds: float,
        success: bool
    ):
        """
        Записать фактическое время для калибровки.

        Args:
            estimate: Исходная оценка
            actual_seconds: Фактическое время выполнения
            success: Успешно ли завершилась задача
        """
        self.history.append({
            "estimate": estimate.total_seconds,
            "actual": actual_seconds,
            "ratio": actual_seconds / estimate.total_seconds if estimate.total_seconds > 0 else 1.0,
            "success": success,
            "mode": estimate.mode
        })

        # Ограничиваем историю
        if len(self.history) > 100:
            self.history = self.history[-100:]


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

def estimate_task_budget(
    mode: ExecutionMode,
    user_prefs: UserTimeoutPreferences = None,
    prompt_length: int = 0,
    complexity: str = None
) -> float:
    """
    Быстрая оценка бюджета задачи.

    Args:
        mode: Режим выполнения
        user_prefs: Пользовательские предпочтения
        prompt_length: Длина промпта в словах
        complexity: Сложность ("simple", "medium", "complex")

    Returns:
        Бюджет в секундах
    """
    estimator = BudgetEstimator(user_prefs)
    prompt = " ".join(["word"] * prompt_length) if prompt_length else ""
    estimate = estimator.estimate(mode, prompt, complexity)
    return estimate.total_seconds


def create_mode_budget(
    mode: ExecutionMode,
    max_seconds: float = None,
    user_prefs: UserTimeoutPreferences = None
) -> TimeBudget:
    """
    Создать бюджет для режима.

    Args:
        mode: Режим выполнения
        max_seconds: Максимальное время (или из user_prefs)
        user_prefs: Пользовательские предпочтения

    Returns:
        TimeBudget для режима
    """
    prefs = user_prefs or UserTimeoutPreferences()
    max_time = max_seconds or prefs.max_wait

    if mode == ExecutionMode.FAST:
        return BudgetPresets.fast_mode(min(max_time, 30))
    elif mode == ExecutionMode.DEEP3:
        return BudgetPresets.deep3_mode(min(max_time, 180))
    elif mode == ExecutionMode.DEEP6:
        return BudgetPresets.deep6_mode(min(max_time, 300))
    elif mode == ExecutionMode.SEARCH:
        return BudgetPresets.search_mode(min(max_time, 60))
    else:
        return BudgetPresets.deep3_mode(min(max_time, 180))


# ═══════════════════════════════════════════════════════════════════════════════
# ТЕСТ
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8') if hasattr(sys.stdout, 'reconfigure') else None

    print("=" * 60)
    print("BudgetEstimator Test")
    print("=" * 60)

    # Test 1: Basic estimation
    print("\n--- Test 1: Basic Estimation ---")
    estimator = BudgetEstimator()

    for mode in [ExecutionMode.FAST, ExecutionMode.DEEP3, ExecutionMode.DEEP6]:
        estimate = estimator.estimate(mode)
        print(f"{mode.value}: {estimate.total_seconds:.0f}s "
              f"(steps: {estimate.steps}, critical: {estimate.critical_step})")

    # Test 2: With prompt length
    print("\n--- Test 2: Prompt Length Impact ---")
    prompts = [100, 500, 1000, 2000, 5000]
    for length in prompts:
        prompt = " ".join(["word"] * length)
        estimate = estimator.estimate(ExecutionMode.DEEP3, prompt)
        print(f"  {length} words: {estimate.total_seconds:.0f}s "
              f"(multiplier: {estimate.adjustments.get('prompt_length', 1.0):.2f})")

    # Test 3: With priority
    print("\n--- Test 3: Priority Impact ---")
    for priority in ["speed", "balanced", "quality"]:
        prefs = UserTimeoutPreferences(priority=priority, max_wait=300)
        est = BudgetEstimator(prefs)
        estimate = est.estimate(ExecutionMode.DEEP3)
        print(f"  {priority}: {estimate.total_seconds:.0f}s")

    # Test 4: Create budget
    print("\n--- Test 4: Create TimeBudget ---")
    budget = estimator.create_budget(ExecutionMode.DEEP3, "Test prompt here")
    print(f"  Budget: {budget}")
    print(f"  Steps: {list(budget.records.keys())}")

    # Test 5: Convenience functions
    print("\n--- Test 5: Convenience Functions ---")
    budget_secs = estimate_task_budget(
        ExecutionMode.DEEP6,
        prompt_length=1500,
        complexity="complex"
    )
    print(f"  DEEP6 + 1500 words + complex: {budget_secs:.0f}s")

    mode_budget = create_mode_budget(ExecutionMode.DEEP3, max_seconds=150)
    print(f"  DEEP3 mode budget: {mode_budget}")

    print("\n✅ BudgetEstimator tests passed!")
