# -*- coding: utf-8 -*-
"""
budget_estimator.py — Автоматическая оценка бюджета задачи с историей
=====================================================================

Фаза 2+3: Определяет бюджет задачи на основе:
- Режима выполнения (FAST, DEEP3, DEEP6, SEARCH)
- Пользовательских предпочтений (max_wait, priority)
- Характеристик запроса (длина промпта, сложность)
- ИСТОРИИ ВЫЗОВОВ (калибровка на железо пользователя)

Принцип работы истории:
1. Каждый вызов LLM записывается: (mode, prompt_tokens, actual_time)
2. После 20+ записей confidence достигает 1.0
3. Предсказание учитывает медианное время для похожих запросов
4. Суперлинейное масштабирование при >8k токенов

Использование:
    from core.budget_estimator import estimate_task_budget, BudgetEstimator

    # Простой вызов
    budget_seconds = estimate_task_budget(
        mode=ExecutionMode.DEEP3,
        user_prefs=user_prefs,
        prompt_length=500
    )

    # Или через класс с историей
    estimator = BudgetEstimator(user_prefs, history_file="llm_history.json")
    budget = estimator.create_budget(mode, prompt)

    # После выполнения - записать фактическое время
    estimator.record_actual(estimate, actual_seconds=45.2, success=True)
"""

import json
import os
import time
import statistics
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from dataclasses import dataclass, field, asdict
from datetime import datetime

from .execution_mode import ExecutionMode
from .user_timeout_config import UserTimeoutPreferences
from .time_budget import TimeBudget, BudgetPresets


@dataclass
class HistoryRecord:
    """Запись истории вызова LLM."""
    timestamp: float
    mode: str
    prompt_tokens: int
    output_tokens: int
    estimated_seconds: float
    actual_seconds: float
    success: bool
    model: str = "unknown"

    @property
    def ratio(self) -> float:
        """Отношение actual/estimated."""
        if self.estimated_seconds > 0:
            return self.actual_seconds / self.estimated_seconds
        return 1.0

    @property
    def tokens_per_second(self) -> float:
        """Скорость генерации токенов."""
        if self.actual_seconds > 0:
            return self.output_tokens / self.actual_seconds
        return 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "HistoryRecord":
        return cls(**data)


@dataclass
class BudgetEstimate:
    """Результат оценки бюджета."""
    total_seconds: float
    mode: str
    steps: list
    critical_step: str
    adjustments: Dict[str, float]  # Какие корректировки применены
    confidence: float  # Уверенность в оценке (0.0 - 1.0)
    history_based: bool = False  # Использована ли история
    similar_calls: int = 0  # Количество похожих вызовов в истории

    def to_dict(self) -> Dict[str, Any]:
        return {
            "total_seconds": self.total_seconds,
            "mode": self.mode,
            "steps": self.steps,
            "critical_step": self.critical_step,
            "adjustments": self.adjustments,
            "confidence": f"{self.confidence:.0%}",
            "history_based": self.history_based,
            "similar_calls": self.similar_calls
        }


class BudgetEstimator:
    """
    Оценщик бюджета для задач с историей вызовов.

    Учитывает:
    1. Режим выполнения (базовый бюджет)
    2. Длину промпта (корректировка на prefill)
    3. Приоритет пользователя (speed/quality)
    4. Потолок max_wait (жёсткое ограничение)
    5. ИСТОРИЮ ВЫПОЛНЕНИЯ (калибровка на железо пользователя)

    История:
    - Сохраняется в JSON файл между сессиями
    - После 20+ записей confidence достигает 1.0
    - Предсказание основано на медиане похожих вызовов
    - Учитывает суперлинейное масштабирование >8k токенов
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

    # Пороги длины промпта для корректировки (токены)
    PROMPT_LENGTH_THRESHOLDS = [
        (500, 1.0),    # < 500 токенов: без корректировки
        (1000, 1.1),   # 500-1000: +10%
        (2000, 1.25),  # 1000-2000: +25%
        (5000, 1.5),   # 2000-5000: +50%
        (8000, 2.0),   # 5000-8000: +100% (граница суперлинейности)
        (16000, 3.0),  # 8000-16000: +200% (суперлинейное масштабирование)
        (float('inf'), 4.0),  # > 16000: +300%
    ]

    # Эмпирические коэффициенты суперлинейного масштабирования
    # При >8k токенов время растёт быстрее чем линейно
    SUPERLINEAR_THRESHOLD = 8000
    SUPERLINEAR_EXPONENT = 1.3  # t ~ tokens^1.3 при >8k

    # Минимальное количество записей для надёжного предсказания
    MIN_HISTORY_FOR_PREDICTION = 5
    FULL_CONFIDENCE_HISTORY = 20

    def __init__(
        self,
        user_prefs: UserTimeoutPreferences = None,
        history_file: str = None,
        auto_save: bool = True
    ):
        """
        Инициализация оценщика с историей.

        Args:
            user_prefs: Пользовательские предпочтения
            history_file: Путь к файлу истории (по умолчанию .qwencode/budget_history.json)
            auto_save: Автоматически сохранять историю после каждой записи
        """
        self.user_prefs = user_prefs or UserTimeoutPreferences()
        self.auto_save = auto_save

        # Определяем путь к файлу истории
        if history_file:
            self.history_file = Path(history_file)
        else:
            qwencode_dir = Path.home() / ".qwencode"
            qwencode_dir.mkdir(exist_ok=True)
            self.history_file = qwencode_dir / "budget_history.json"

        # Загружаем историю
        self.history: List[HistoryRecord] = self._load_history()

    # ═══════════════════════════════════════════════════════════════════════════
    # HISTORY PERSISTENCE
    # ═══════════════════════════════════════════════════════════════════════════

    def _load_history(self) -> List[HistoryRecord]:
        """Загрузить историю из файла."""
        if not self.history_file.exists():
            return []

        try:
            with open(self.history_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return [HistoryRecord.from_dict(r) for r in data]
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            print(f"[BudgetEstimator] Warning: Could not load history: {e}")
            return []

    def _save_history(self):
        """Сохранить историю в файл."""
        try:
            with open(self.history_file, 'w', encoding='utf-8') as f:
                data = [r.to_dict() for r in self.history]
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[BudgetEstimator] Warning: Could not save history: {e}")

    # ═══════════════════════════════════════════════════════════════════════════
    # HISTORY-BASED PREDICTION
    # ═══════════════════════════════════════════════════════════════════════════

    def _find_similar_calls(
        self,
        mode: str,
        prompt_tokens: int,
        tolerance: float = 0.3
    ) -> List[HistoryRecord]:
        """
        Найти похожие вызовы в истории.

        Args:
            mode: Режим выполнения
            prompt_tokens: Количество токенов промпта
            tolerance: Допустимое отклонение по токенам (30%)

        Returns:
            Список похожих записей
        """
        similar = []
        min_tokens = int(prompt_tokens * (1 - tolerance))
        max_tokens = int(prompt_tokens * (1 + tolerance))

        for record in self.history:
            if record.mode == mode and record.success:
                if min_tokens <= record.prompt_tokens <= max_tokens:
                    similar.append(record)

        return similar

    def _predict_from_history(
        self,
        mode: str,
        prompt_tokens: int
    ) -> Tuple[Optional[float], int]:
        """
        Предсказать время на основе истории.

        Args:
            mode: Режим выполнения
            prompt_tokens: Количество токенов

        Returns:
            (predicted_seconds, similar_count) или (None, 0) если недостаточно данных
        """
        similar = self._find_similar_calls(mode, prompt_tokens)

        if len(similar) < self.MIN_HISTORY_FOR_PREDICTION:
            return None, 0

        # Используем медиану для устойчивости к выбросам
        actual_times = [r.actual_seconds for r in similar]
        median_time = statistics.median(actual_times)

        # Корректировка на суперлинейное масштабирование
        if prompt_tokens > self.SUPERLINEAR_THRESHOLD:
            # Если большинство похожих вызовов были с меньшим количеством токенов,
            # применяем суперлинейную корректировку
            avg_similar_tokens = statistics.mean([r.prompt_tokens for r in similar])
            if avg_similar_tokens < prompt_tokens:
                ratio = prompt_tokens / avg_similar_tokens
                # t ~ tokens^1.3 для >8k токенов
                scale_factor = ratio ** self.SUPERLINEAR_EXPONENT
                median_time *= scale_factor

        return median_time, len(similar)

    def _get_calibration_factor(self) -> float:
        """
        Получить калибровочный коэффициент на основе истории.

        Если оценки систематически занижены/завышены, корректируем.
        """
        if len(self.history) < self.MIN_HISTORY_FOR_PREDICTION:
            return 1.0

        # Считаем среднее отношение actual/estimated
        ratios = [r.ratio for r in self.history if r.success]
        if not ratios:
            return 1.0

        # Используем медиану для устойчивости
        median_ratio = statistics.median(ratios)

        # Ограничиваем корректировку разумными пределами (0.5x - 2.0x)
        return max(0.5, min(2.0, median_ratio))

    # ═══════════════════════════════════════════════════════════════════════════
    # MAIN ESTIMATION
    # ═══════════════════════════════════════════════════════════════════════════

    def estimate(
        self,
        mode: ExecutionMode,
        prompt: str = "",
        complexity_hint: str = None,
        prompt_tokens: int = None
    ) -> BudgetEstimate:
        """
        Оценить бюджет для задачи.

        Args:
            mode: Режим выполнения
            prompt: Текст запроса (для оценки длины)
            complexity_hint: Подсказка о сложности ("simple", "medium", "complex")
            prompt_tokens: Точное количество токенов (если известно)

        Returns:
            BudgetEstimate с деталями оценки
        """
        adjustments = {}
        history_based = False
        similar_count = 0

        # Оценка токенов (примерно 1.3 токена на слово для английского)
        if prompt_tokens is None:
            word_count = len(prompt.split()) if prompt else 0
            prompt_tokens = int(word_count * 1.3)

        mode_str = mode.value if hasattr(mode, 'value') else str(mode)

        # ═══════════════════════════════════════════════════════════════════════
        # ПОПЫТКА ПРЕДСКАЗАНИЯ ИЗ ИСТОРИИ
        # ═══════════════════════════════════════════════════════════════════════

        history_prediction, similar_count = self._predict_from_history(mode_str, prompt_tokens)

        if history_prediction is not None:
            # Используем предсказание из истории
            history_based = True
            estimated = history_prediction
            adjustments["history_prediction"] = history_prediction
            adjustments["similar_calls"] = similar_count
        else:
            # ═══════════════════════════════════════════════════════════════════
            # FALLBACK: ФОРМУЛЬНАЯ ОЦЕНКА
            # ═══════════════════════════════════════════════════════════════════

            # 1. Базовый бюджет по режиму
            base = self.MODE_BASE_BUDGETS.get(mode, 120)
            adjustments["base"] = base

            # 2. Корректировка по длине промпта
            prompt_multiplier = self._get_prompt_multiplier(prompt_tokens)
            adjustments["prompt_tokens"] = prompt_tokens
            adjustments["prompt_multiplier"] = prompt_multiplier

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

            # 5. Калибровочный коэффициент из истории
            calibration = self._get_calibration_factor()
            if calibration != 1.0:
                adjustments["calibration"] = calibration

            # Вычисляем итоговый бюджет
            estimated = base * prompt_multiplier * priority_multiplier * complexity_multiplier * calibration

        # ═══════════════════════════════════════════════════════════════════════
        # ФИНАЛЬНЫЕ ОГРАНИЧЕНИЯ
        # ═══════════════════════════════════════════════════════════════════════

        # Ограничиваем пользовательским max_wait
        final = min(estimated, self.user_prefs.max_wait)
        if final < estimated:
            adjustments["max_wait_cap"] = self.user_prefs.max_wait

        # Определяем уверенность
        confidence = self._calculate_confidence(prompt_tokens, complexity_hint, similar_count)

        return BudgetEstimate(
            total_seconds=final,
            mode=mode_str,
            steps=self.MODE_STEPS.get(mode, ["execute"]),
            critical_step=self.MODE_CRITICAL_STEPS.get(mode, "execute"),
            adjustments=adjustments,
            confidence=confidence,
            history_based=history_based,
            similar_calls=similar_count
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

    def _get_prompt_multiplier(self, token_count: int) -> float:
        """
        Получить множитель на основе количества токенов.

        Включает суперлинейное масштабирование для >8k токенов.
        """
        for threshold, multiplier in self.PROMPT_LENGTH_THRESHOLDS:
            if token_count < threshold:
                return multiplier

        # Суперлинейное масштабирование для очень длинных промптов
        return 4.0

    def _calculate_confidence(
        self,
        prompt_tokens: int,
        complexity_hint: str,
        similar_calls: int = 0
    ) -> float:
        """
        Рассчитать уверенность в оценке.

        Уверенность растёт с количеством похожих вызовов в истории.
        После 20+ записей достигает 1.0.

        Args:
            prompt_tokens: Количество токенов в промпте
            complexity_hint: Подсказка о сложности
            similar_calls: Количество похожих вызовов в истории
        """
        # Базовая уверенность зависит от истории
        if similar_calls >= self.FULL_CONFIDENCE_HISTORY:
            # После 20+ похожих вызовов - максимальная уверенность
            confidence = 1.0
        elif similar_calls >= self.MIN_HISTORY_FOR_PREDICTION:
            # 5-20 похожих вызовов - высокая уверенность
            confidence = 0.7 + (similar_calls - self.MIN_HISTORY_FOR_PREDICTION) * 0.02
        else:
            # Мало данных - формульная оценка
            confidence = 0.5

        # Подсказка о сложности повышает уверенность
        if complexity_hint and similar_calls < self.MIN_HISTORY_FOR_PREDICTION:
            confidence += 0.1

        # Экстремальная длина снижает уверенность (только без истории)
        if similar_calls < self.MIN_HISTORY_FOR_PREDICTION:
            if prompt_tokens < 50 or prompt_tokens > 10000:
                confidence -= 0.1

        # Общая история тоже повышает уверенность (калибровка)
        total_history = len(self.history)
        if total_history >= self.FULL_CONFIDENCE_HISTORY:
            confidence = min(confidence + 0.1, 1.0)
        elif total_history >= self.MIN_HISTORY_FOR_PREDICTION:
            confidence = min(confidence + 0.05, 1.0)

        return max(0.3, min(1.0, confidence))

    def record_actual(
        self,
        estimate: BudgetEstimate,
        actual_seconds: float,
        success: bool,
        prompt_tokens: int = 0,
        output_tokens: int = 0,
        model: str = "unknown"
    ):
        """
        Записать фактическое время для калибровки.

        Args:
            estimate: Исходная оценка
            actual_seconds: Фактическое время выполнения
            success: Успешно ли завершилась задача
            prompt_tokens: Количество токенов в промпте
            output_tokens: Количество сгенерированных токенов
            model: Название модели
        """
        # Извлекаем prompt_tokens из adjustments если не передан
        if prompt_tokens == 0:
            prompt_tokens = estimate.adjustments.get("prompt_tokens", 0)

        record = HistoryRecord(
            timestamp=time.time(),
            mode=estimate.mode,
            prompt_tokens=prompt_tokens,
            output_tokens=output_tokens,
            estimated_seconds=estimate.total_seconds,
            actual_seconds=actual_seconds,
            success=success,
            model=model
        )

        self.history.append(record)

        # Ограничиваем историю (храним последние 500 записей)
        if len(self.history) > 500:
            self.history = self.history[-500:]

        # Автосохранение
        if self.auto_save:
            self._save_history()

    def get_statistics(self) -> Dict[str, Any]:
        """
        Получить статистику по истории вызовов.

        Returns:
            Словарь со статистикой
        """
        if not self.history:
            return {"total_calls": 0, "message": "No history yet"}

        successful = [r for r in self.history if r.success]
        failed = [r for r in self.history if not r.success]

        stats = {
            "total_calls": len(self.history),
            "successful": len(successful),
            "failed": len(failed),
            "success_rate": f"{len(successful) / len(self.history) * 100:.1f}%",
        }

        if successful:
            ratios = [r.ratio for r in successful]
            stats["median_ratio"] = f"{statistics.median(ratios):.2f}"
            stats["mean_ratio"] = f"{statistics.mean(ratios):.2f}"

            times = [r.actual_seconds for r in successful]
            stats["median_time"] = f"{statistics.median(times):.1f}s"
            stats["total_time"] = f"{sum(times):.0f}s"

            # Статистика по режимам
            modes = {}
            for r in successful:
                if r.mode not in modes:
                    modes[r.mode] = []
                modes[r.mode].append(r.actual_seconds)

            stats["by_mode"] = {
                mode: f"{statistics.median(times):.1f}s (n={len(times)})"
                for mode, times in modes.items()
            }

        # Калибровочный коэффициент
        stats["calibration_factor"] = f"{self._get_calibration_factor():.2f}"
        stats["confidence_level"] = "high" if len(self.history) >= self.FULL_CONFIDENCE_HISTORY else "medium" if len(self.history) >= self.MIN_HISTORY_FOR_PREDICTION else "low"

        return stats

    def clear_history(self):
        """Очистить историю."""
        self.history = []
        if self.auto_save:
            self._save_history()


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
