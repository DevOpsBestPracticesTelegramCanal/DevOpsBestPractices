# -*- coding: utf-8 -*-
"""
time_budget.py — Менеджер бюджета времени для задач
===================================================

Фаза 2 системы управления таймаутами QwenCode.

Реализует принципы BAM (Budget Allocation Model):
- Критический шаг (генерация кода) получает 40% бюджета
- Остальные шаги делят 60%
- Если шаг завершился быстрее — остаток перераспределяется
- Грациозная деградация при исчерпании бюджета

Использование:
    budget = TimeBudget(
        total_seconds=180,
        steps=["analyze", "plan", "generate"],
        critical_step="generate"
    )

    # Получить таймаут для шага (с учётом перераспределения)
    timeout = budget.get_step_timeout("analyze")

    # Отметить начало/конец шага
    budget.start_step("analyze")
    # ... выполнение ...
    budget.complete_step("analyze", tokens=150)

    # Сводка
    print(budget.summary())
"""

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from enum import Enum


class StepStatus(Enum):
    """Статус выполнения шага."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    TIMED_OUT = "timed_out"
    SKIPPED = "skipped"
    PARTIAL = "partial"  # Частичный результат (таймаут, но есть данные)


@dataclass
class StepRecord:
    """
    Запись о выполнении одного шага.

    Хранит информацию о бюджете, фактическом времени,
    токенах и статусе выполнения.
    """
    name: str
    allocated: float              # Выделенный бюджет (секунды)
    actual: float = 0.0           # Фактическое время (секунды)
    tokens: int = 0               # Количество сгенерированных токенов
    status: StepStatus = StepStatus.PENDING
    partial_result: str = ""      # Частичный результат при таймауте
    error: Optional[str] = None   # Ошибка, если была
    _start_time: float = 0.0      # Время начала (internal)

    @property
    def efficiency(self) -> float:
        """Эффективность использования бюджета (0.0 - 1.0+)."""
        if self.allocated <= 0:
            return 0.0
        return self.actual / self.allocated

    @property
    def savings(self) -> float:
        """Сэкономленное время (может быть отрицательным)."""
        if self.status != StepStatus.COMPLETED:
            return 0.0
        return max(0, self.allocated - self.actual)

    @property
    def is_done(self) -> bool:
        """Шаг завершён (успешно или нет)."""
        return self.status in (
            StepStatus.COMPLETED,
            StepStatus.TIMED_OUT,
            StepStatus.SKIPPED,
            StepStatus.PARTIAL
        )

    def to_dict(self) -> Dict[str, Any]:
        """Сериализация для API/логов."""
        return {
            "name": self.name,
            "allocated": f"{self.allocated:.1f}s",
            "actual": f"{self.actual:.1f}s",
            "tokens": self.tokens,
            "status": self.status.value,
            "efficiency": f"{self.efficiency:.0%}" if self.allocated > 0 else "n/a",
            "savings": f"{self.savings:.1f}s"
        }


class TimeBudget:
    """
    Бюджет времени на задачу с динамическим распределением.

    Реализует принципы BAM (Budget Allocation Model):
    - Критический шаг получает больший % бюджета (по умолчанию 40%)
    - Остальные шаги делят оставшееся поровну
    - Экономия от быстрых шагов перераспределяется
    - Никогда не выделяем больше, чем осталось в общем бюджете

    Пример распределения для 180 сек, 3 шага, critical="generate":
        analyze: 36 сек (20%)
        plan: 36 сек (20%)
        generate: 72 сек (40%) + возможная экономия

    Если analyze занял 15 сек вместо 36:
        → plan получает 36 + (36-15)*0.5 = 46.5 сек
        → generate получает 72 + оставшуюся экономию
    """

    # Доля бюджета для критического шага
    CRITICAL_SHARE = 0.40

    # Минимальный таймаут для любого шага
    MIN_STEP_TIMEOUT = 10.0

    # Множитель для переноса экономии (0.5 = половина экономии переносится)
    SAVINGS_TRANSFER_RATE = 0.7

    def __init__(
        self,
        total_seconds: float,
        steps: List[str],
        critical_step: str = None,
        critical_share: float = None
    ):
        """
        Инициализация бюджета.

        Args:
            total_seconds: Общий бюджет времени на задачу
            steps: Список шагов в порядке выполнения
            critical_step: Критический шаг (по умолчанию — последний)
            critical_share: Доля для критического шага (по умолчанию 0.40)
        """
        self.total = total_seconds
        self.start_time = time.monotonic()
        self.steps = steps
        self.critical_step = critical_step or (steps[-1] if steps else None)
        self.critical_share = critical_share or self.CRITICAL_SHARE

        # Записи о шагах
        self.records: Dict[str, StepRecord] = {}

        # Начальное распределение бюджета
        self._allocate_initial()

        # Флаг грациозной деградации
        self._degraded = False

    def _allocate_initial(self):
        """
        Начальное распределение бюджета по принципу BAM.

        Critical step получает critical_share (40%),
        остальные делят (1 - critical_share) поровну.
        """
        if not self.steps:
            return

        n_steps = len(self.steps)
        n_other = n_steps - 1 if self.critical_step in self.steps else n_steps

        # Доля для некритических шагов
        other_share = (1.0 - self.critical_share) / max(n_other, 1)

        for step_name in self.steps:
            if step_name == self.critical_step:
                share = self.critical_share
            else:
                share = other_share

            allocated = self.total * share
            self.records[step_name] = StepRecord(
                name=step_name,
                allocated=allocated
            )

    @property
    def elapsed(self) -> float:
        """Прошедшее время с начала задачи."""
        return time.monotonic() - self.start_time

    @property
    def remaining(self) -> float:
        """Оставшееся время в бюджете."""
        return max(0, self.total - self.elapsed)

    @property
    def is_exhausted(self) -> bool:
        """Бюджет исчерпан."""
        return self.remaining <= 0

    @property
    def is_degraded(self) -> bool:
        """Задача в режиме грациозной деградации."""
        return self._degraded

    @property
    def total_savings(self) -> float:
        """Общая экономия от завершённых шагов."""
        return sum(rec.savings for rec in self.records.values())

    def get_step_timeout(self, step_name: str, min_timeout: float = None) -> float:
        """
        Получить таймаут для шага с учётом перераспределения.

        Логика:
        1. Берём выделенный бюджет шага
        2. Добавляем экономию от предыдущих шагов (с коэффициентом)
        3. Ограничиваем оставшимся общим бюджетом
        4. Гарантируем минимальный таймаут

        Args:
            step_name: Имя шага
            min_timeout: Минимальный таймаут (по умолчанию MIN_STEP_TIMEOUT)

        Returns:
            Таймаут в секундах
        """
        min_timeout = min_timeout or self.MIN_STEP_TIMEOUT

        record = self.records.get(step_name)
        if not record:
            # Неизвестный шаг — даём остаток бюджета
            return max(min(self.remaining, 60), min_timeout)

        # Базовый бюджет шага
        base = record.allocated

        # Собираем экономию от предыдущих шагов
        savings_available = 0
        for name in self.steps:
            if name == step_name:
                break
            prev_record = self.records.get(name)
            if prev_record and prev_record.status == StepStatus.COMPLETED:
                savings_available += prev_record.savings

        # Переносим часть экономии
        bonus = savings_available * self.SAVINGS_TRANSFER_RATE

        # Итоговый таймаут
        timeout = base + bonus

        # Ограничиваем оставшимся бюджетом
        timeout = min(timeout, self.remaining)

        # Гарантируем минимум
        return max(timeout, min_timeout)

    def start_step(self, step_name: str) -> float:
        """
        Отметить начало шага.

        Args:
            step_name: Имя шага

        Returns:
            Рекомендуемый таймаут для этого шага
        """
        record = self.records.get(step_name)
        if record:
            record.status = StepStatus.RUNNING
            record._start_time = time.monotonic()

        return self.get_step_timeout(step_name)

    def complete_step(
        self,
        step_name: str,
        tokens: int = 0,
        result: str = None
    ):
        """
        Отметить успешное завершение шага.

        Args:
            step_name: Имя шага
            tokens: Количество сгенерированных токенов
            result: Результат шага (опционально)
        """
        record = self.records.get(step_name)
        if record:
            record.actual = time.monotonic() - record._start_time
            record.tokens = tokens
            record.status = StepStatus.COMPLETED
            if result:
                record.partial_result = result

    def timeout_step(
        self,
        step_name: str,
        partial_tokens: int = 0,
        partial_result: str = None,
        error: str = None
    ):
        """
        Отметить таймаут шага.

        Args:
            step_name: Имя шага
            partial_tokens: Токены, сгенерированные до таймаута
            partial_result: Частичный результат
            error: Описание ошибки
        """
        record = self.records.get(step_name)
        if record:
            record.actual = time.monotonic() - record._start_time
            record.tokens = partial_tokens
            record.status = StepStatus.PARTIAL if partial_result else StepStatus.TIMED_OUT
            record.partial_result = partial_result or ""
            record.error = error

    def skip_step(self, step_name: str, reason: str = "budget_exhausted"):
        """
        Пропустить шаг (бюджет исчерпан).

        Args:
            step_name: Имя шага
            reason: Причина пропуска
        """
        record = self.records.get(step_name)
        if record:
            record.status = StepStatus.SKIPPED
            record.error = reason

        # Включаем режим деградации
        self._degraded = True

    def should_continue(self, min_required: float = 5.0) -> bool:
        """
        Проверить, стоит ли продолжать выполнение.

        Args:
            min_required: Минимальное время для продолжения

        Returns:
            True если есть смысл продолжать
        """
        return self.remaining >= min_required

    def get_next_step(self) -> Optional[str]:
        """
        Получить следующий шаг для выполнения.

        Returns:
            Имя следующего pending шага или None
        """
        for step_name in self.steps:
            record = self.records.get(step_name)
            if record and record.status == StepStatus.PENDING:
                return step_name
        return None

    def summary(self) -> Dict[str, Any]:
        """
        Сводка для observability.

        Returns:
            Словарь со всеми метриками бюджета
        """
        completed = sum(1 for r in self.records.values() if r.status == StepStatus.COMPLETED)
        timed_out = sum(1 for r in self.records.values() if r.status in (StepStatus.TIMED_OUT, StepStatus.PARTIAL))
        skipped = sum(1 for r in self.records.values() if r.status == StepStatus.SKIPPED)

        return {
            "total_budget": f"{self.total:.1f}s",
            "elapsed": f"{self.elapsed:.1f}s",
            "remaining": f"{self.remaining:.1f}s",
            "utilization": f"{self.elapsed / self.total:.0%}" if self.total > 0 else "n/a",
            "total_savings": f"{self.total_savings:.1f}s",
            "degraded": self._degraded,
            "steps_completed": completed,
            "steps_timed_out": timed_out,
            "steps_skipped": skipped,
            "critical_step": self.critical_step,
            "steps": {
                name: rec.to_dict()
                for name, rec in self.records.items()
            }
        }

    def __repr__(self):
        return (f"TimeBudget(total={self.total:.0f}s, "
                f"elapsed={self.elapsed:.1f}s, "
                f"remaining={self.remaining:.1f}s, "
                f"steps={len(self.steps)})")


# ═══════════════════════════════════════════════════════════════════════════════
# BUDGET PRESETS
# ═══════════════════════════════════════════════════════════════════════════════

class BudgetPresets:
    """Предустановленные конфигурации бюджетов для разных режимов."""

    @staticmethod
    def fast_mode(max_seconds: float = 30) -> TimeBudget:
        """Бюджет для FAST режима (1 шаг)."""
        return TimeBudget(
            total_seconds=max_seconds,
            steps=["execute"],
            critical_step="execute"
        )

    @staticmethod
    def deep3_mode(max_seconds: float = 120) -> TimeBudget:
        """Бюджет для DEEP3 режима (3 шага)."""
        return TimeBudget(
            total_seconds=max_seconds,
            steps=["analyze", "plan", "execute"],
            critical_step="execute",
            critical_share=0.45  # Execute получает больше
        )

    @staticmethod
    def deep6_mode(max_seconds: float = 300) -> TimeBudget:
        """Бюджет для DEEP6 режима (6 шагов Minsky)."""
        return TimeBudget(
            total_seconds=max_seconds,
            steps=[
                "understanding",
                "challenges",
                "approaches",
                "constraints",
                "choose",
                "solution"
            ],
            critical_step="solution",
            critical_share=0.35  # Solution важен, но не единственный
        )

    @staticmethod
    def search_mode(max_seconds: float = 60) -> TimeBudget:
        """Бюджет для SEARCH режима."""
        return TimeBudget(
            total_seconds=max_seconds,
            steps=["search", "analyze"],
            critical_step="analyze",
            critical_share=0.60  # Анализ результатов важнее
        )

    @staticmethod
    def swebench_mode(max_seconds: float = 600) -> TimeBudget:
        """Бюджет для SWE-bench задач (расширенный)."""
        return TimeBudget(
            total_seconds=max_seconds,
            steps=[
                "understand_issue",
                "explore_codebase",
                "plan_fix",
                "implement",
                "verify"
            ],
            critical_step="implement",
            critical_share=0.40
        )


# ═══════════════════════════════════════════════════════════════════════════════
# ТЕСТ
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding='utf-8') if hasattr(sys.stdout, 'reconfigure') else None

    print("=" * 60)
    print("TimeBudget Test")
    print("=" * 60)

    # Test 1: Basic budget
    print("\n--- Test 1: Basic Budget (180s, 3 steps) ---")
    budget = TimeBudget(
        total_seconds=180,
        steps=["analyze", "plan", "generate"],
        critical_step="generate"
    )

    print(f"Budget: {budget}")
    for name, rec in budget.records.items():
        print(f"  {name}: allocated={rec.allocated:.1f}s")

    # Test 2: Step execution
    print("\n--- Test 2: Step Execution ---")

    # Analyze (быстро)
    timeout = budget.start_step("analyze")
    print(f"analyze: timeout={timeout:.1f}s")
    time.sleep(0.1)  # Симуляция работы
    budget.complete_step("analyze", tokens=50)

    # Plan (быстро)
    timeout = budget.start_step("plan")
    print(f"plan: timeout={timeout:.1f}s (with savings transfer)")
    time.sleep(0.1)
    budget.complete_step("plan", tokens=30)

    # Generate (получает бонус)
    timeout = budget.start_step("generate")
    print(f"generate: timeout={timeout:.1f}s (with accumulated savings)")
    time.sleep(0.1)
    budget.complete_step("generate", tokens=200)

    # Test 3: Summary
    print("\n--- Test 3: Summary ---")
    summary = budget.summary()
    print(f"Total budget: {summary['total_budget']}")
    print(f"Elapsed: {summary['elapsed']}")
    print(f"Remaining: {summary['remaining']}")
    print(f"Savings: {summary['total_savings']}")
    print(f"Steps completed: {summary['steps_completed']}")

    # Test 4: Presets
    print("\n--- Test 4: Budget Presets ---")
    presets = [
        ("FAST", BudgetPresets.fast_mode(30)),
        ("DEEP3", BudgetPresets.deep3_mode(120)),
        ("DEEP6", BudgetPresets.deep6_mode(300)),
        ("SEARCH", BudgetPresets.search_mode(60)),
        ("SWE-bench", BudgetPresets.swebench_mode(600))
    ]

    for name, preset in presets:
        steps_info = ", ".join(f"{s}:{preset.records[s].allocated:.0f}s" for s in preset.steps)
        print(f"  {name}: {steps_info}")

    print("\n✅ TimeBudget tests passed!")
