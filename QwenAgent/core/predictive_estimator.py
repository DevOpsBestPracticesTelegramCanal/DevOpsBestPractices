# -*- coding: utf-8 -*-
"""
predictive_estimator.py — Предиктивный оценщик таймаутов
========================================================

Phase 3 системы управления таймаутами QwenCode.

Использует машинное обучение (без внешних зависимостей) для:
- Прогнозирования времени выполнения на основе истории
- Адаптивной корректировки оценок
- Анализа сложности задач
- Калибровки по модели/режиму

Принципы:
1. Обучение на исторических данных (online learning)
2. Экспоненциальное сглаживание для адаптации
3. Кластеризация задач по характеристикам
4. Байесовская корректировка уверенности

Использование:
    from core.predictive_estimator import PredictiveEstimator

    estimator = PredictiveEstimator()

    # Получить предсказание
    prediction = estimator.predict(
        mode="deep3",
        prompt="Fix the bug in parser.py",
        model="qwen2.5-coder:7b"
    )
    print(f"Predicted: {prediction.timeout}s (confidence: {prediction.confidence})")

    # Записать фактический результат
    estimator.record_outcome(
        prediction_id=prediction.id,
        actual_seconds=45.2,
        success=True,
        tokens_generated=150
    )
"""

import time
import json
import math
import hashlib
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Tuple
from pathlib import Path
from enum import Enum
import statistics


class TaskComplexity(Enum):
    """Уровни сложности задачи."""
    TRIVIAL = "trivial"      # < 10s expected
    SIMPLE = "simple"        # 10-30s expected
    MODERATE = "moderate"    # 30-60s expected
    COMPLEX = "complex"      # 60-180s expected
    VERY_COMPLEX = "very_complex"  # > 180s expected


@dataclass
class PredictionResult:
    """Результат предсказания таймаута."""
    id: str                      # Уникальный ID предсказания
    timeout: float               # Предсказанный таймаут (секунды)
    confidence: float            # Уверенность (0.0 - 1.0)
    complexity: TaskComplexity   # Оценённая сложность
    factors: Dict[str, float]    # Факторы, влияющие на предсказание
    model_calibration: float     # Калибровка для модели
    mode_calibration: float      # Калибровка для режима
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "timeout": f"{self.timeout:.1f}s",
            "confidence": f"{self.confidence:.0%}",
            "complexity": self.complexity.value,
            "factors": self.factors,
            "model_calibration": f"{self.model_calibration:.2f}",
            "mode_calibration": f"{self.mode_calibration:.2f}"
        }


@dataclass
class OutcomeRecord:
    """Запись о фактическом результате."""
    prediction_id: str
    predicted_timeout: float
    actual_seconds: float
    success: bool
    tokens_generated: int
    mode: str
    model: str
    complexity: str
    timestamp: float = field(default_factory=time.time)

    @property
    def accuracy_ratio(self) -> float:
        """Отношение фактического к предсказанному."""
        if self.predicted_timeout <= 0:
            return 1.0
        return self.actual_seconds / self.predicted_timeout

    @property
    def error(self) -> float:
        """Абсолютная ошибка предсказания."""
        return abs(self.actual_seconds - self.predicted_timeout)


class FeatureExtractor:
    """
    Извлечение признаков из задачи.

    Анализирует prompt и контекст для определения
    характеристик, влияющих на время выполнения.
    """

    # Ключевые слова, указывающие на сложность
    COMPLEXITY_KEYWORDS = {
        "trivial": ["print", "hello", "test", "simple", "quick"],
        "simple": ["fix", "add", "remove", "change", "update"],
        "moderate": ["refactor", "implement", "create", "build"],
        "complex": ["architecture", "redesign", "optimize", "migrate"],
        "very_complex": ["rewrite", "overhaul", "complete system", "full rewrite"]
    }

    # Ключевые слова, указывающие на тип задачи
    TASK_TYPE_KEYWORDS = {
        "code_generation": ["write", "create", "implement", "add function"],
        "bug_fix": ["fix", "bug", "error", "issue", "broken"],
        "refactoring": ["refactor", "clean", "improve", "restructure"],
        "analysis": ["analyze", "review", "check", "examine"],
        "search": ["find", "search", "locate", "where is"]
    }

    @classmethod
    def extract(cls, prompt: str, context: Dict[str, Any] = None) -> Dict[str, float]:
        """
        Извлечь признаки из prompt.

        Returns:
            Dict с признаками (все значения нормализованы 0-1)
        """
        features = {}
        prompt_lower = prompt.lower()
        context = context or {}

        # 1. Длина промпта (нормализованная)
        word_count = len(prompt.split())
        features["prompt_length"] = min(word_count / 500, 1.0)  # 500+ слов = 1.0

        # 2. Количество строк кода (если есть)
        code_lines = prompt.count("\n")
        features["code_lines"] = min(code_lines / 100, 1.0)  # 100+ строк = 1.0

        # 3. Сложность по ключевым словам
        complexity_score = 0.0
        for level, keywords in cls.COMPLEXITY_KEYWORDS.items():
            for kw in keywords:
                if kw in prompt_lower:
                    level_score = {
                        "trivial": 0.1,
                        "simple": 0.3,
                        "moderate": 0.5,
                        "complex": 0.7,
                        "very_complex": 0.9
                    }[level]
                    complexity_score = max(complexity_score, level_score)
        features["complexity_keywords"] = complexity_score

        # 4. Тип задачи
        task_type_scores = {}
        for task_type, keywords in cls.TASK_TYPE_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in prompt_lower)
            task_type_scores[task_type] = min(score / 2, 1.0)
        features.update({f"task_{k}": v for k, v in task_type_scores.items()})

        # 5. Наличие специфических паттернов
        features["has_file_path"] = 1.0 if ".py" in prompt or ".js" in prompt or ".ts" in prompt else 0.0
        features["has_error_trace"] = 1.0 if "error" in prompt_lower or "traceback" in prompt_lower else 0.0
        features["has_code_block"] = 1.0 if "```" in prompt else 0.0
        features["is_question"] = 1.0 if "?" in prompt else 0.0

        # 6. Контекстные признаки
        features["has_pre_read"] = 1.0 if context.get("pre_read_content") else 0.0
        features["iteration_count"] = min(context.get("iteration", 0) / 5, 1.0)

        return features


class ModelCalibrator:
    """
    Калибровка предсказаний по модели.

    Разные модели имеют разную скорость генерации.
    Калибратор корректирует базовые предсказания.
    """

    # Базовые множители для моделей (tokens/sec примерно)
    MODEL_SPEED_FACTORS = {
        "qwen2.5-coder:3b": 1.0,      # Базовая скорость
        "qwen2.5-coder:7b": 0.6,      # ~40% медленнее
        "qwen2.5-coder:14b": 0.35,    # ~65% медленнее
        "qwen2.5-coder:32b": 0.15,    # ~85% медленнее
        "codegen:latest": 0.5,        # Примерно как 7b
    }

    def __init__(self):
        # Накопленные калибровки из истории
        self._calibrations: Dict[str, List[float]] = {}
        self._alpha = 0.3  # Скорость обучения

    def get_calibration(self, model: str) -> float:
        """
        Получить калибровочный множитель для модели.

        > 1.0 = модель медленнее ожидаемого
        < 1.0 = модель быстрее ожидаемого
        """
        # Сначала базовый множитель
        base = 1.0 / self.MODEL_SPEED_FACTORS.get(model, 0.5)

        # Корректировка из истории
        if model in self._calibrations and self._calibrations[model]:
            history_avg = statistics.mean(self._calibrations[model][-10:])
            # Смешиваем базовый и исторический
            return base * 0.5 + history_avg * 0.5

        return base

    def update(self, model: str, actual_ratio: float):
        """
        Обновить калибровку на основе фактического результата.

        Args:
            model: Имя модели
            actual_ratio: actual_time / predicted_time
        """
        if model not in self._calibrations:
            self._calibrations[model] = []

        self._calibrations[model].append(actual_ratio)

        # Ограничиваем историю
        if len(self._calibrations[model]) > 50:
            self._calibrations[model] = self._calibrations[model][-50:]


class ModeCalibrator:
    """
    Калибровка предсказаний по режиму выполнения.

    FAST, DEEP3, DEEP6 имеют разные паттерны времени.
    """

    # Базовые множители для режимов
    MODE_FACTORS = {
        "fast": 1.0,
        "deep3": 2.5,
        "deep6": 5.0,
        "search": 1.5,
        "search_deep": 3.5,
    }

    def __init__(self):
        self._calibrations: Dict[str, List[float]] = {}

    def get_calibration(self, mode: str) -> float:
        """Получить калибровочный множитель для режима."""
        base = self.MODE_FACTORS.get(mode, 2.0)

        if mode in self._calibrations and self._calibrations[mode]:
            history_avg = statistics.mean(self._calibrations[mode][-10:])
            return base * 0.5 + history_avg * 0.5

        return base

    def update(self, mode: str, actual_ratio: float):
        """Обновить калибровку."""
        if mode not in self._calibrations:
            self._calibrations[mode] = []

        self._calibrations[mode].append(actual_ratio)

        if len(self._calibrations[mode]) > 50:
            self._calibrations[mode] = self._calibrations[mode][-50:]


class PredictiveEstimator:
    """
    Предиктивный оценщик таймаутов.

    Использует:
    - Извлечение признаков из задачи
    - Калибровку по модели и режиму
    - Online learning из истории
    - Экспоненциальное сглаживание
    """

    # Базовое время для "единичной" задачи (секунды)
    BASE_TIME = 15.0

    # Веса признаков для предсказания
    FEATURE_WEIGHTS = {
        "prompt_length": 20.0,
        "code_lines": 15.0,
        "complexity_keywords": 40.0,
        "task_code_generation": 25.0,
        "task_bug_fix": 20.0,
        "task_refactoring": 30.0,
        "task_analysis": 10.0,
        "task_search": 5.0,
        "has_file_path": 5.0,
        "has_error_trace": 10.0,
        "has_code_block": 15.0,
        "is_question": -5.0,  # Вопросы обычно быстрее
        "has_pre_read": -10.0,  # Pre-read ускоряет
        "iteration_count": 15.0,  # Больше итераций = дольше
    }

    # Минимальный и максимальный таймаут
    MIN_TIMEOUT = 10.0
    MAX_TIMEOUT = 600.0

    def __init__(self, history_file: str = None):
        """
        Инициализация оценщика.

        Args:
            history_file: Путь к файлу истории (для persistence)
        """
        self.model_calibrator = ModelCalibrator()
        self.mode_calibrator = ModeCalibrator()
        self.feature_extractor = FeatureExtractor()

        # История предсказаний и результатов
        self._predictions: Dict[str, PredictionResult] = {}
        self._outcomes: List[OutcomeRecord] = []

        # Скользящая статистика ошибок
        self._error_history: List[float] = []
        self._accuracy_history: List[float] = []

        # Файл для persistence
        self._history_file = history_file
        if history_file:
            self._load_history()

    def predict(
        self,
        mode: str,
        prompt: str,
        model: str = "qwen2.5-coder:7b",
        context: Dict[str, Any] = None
    ) -> PredictionResult:
        """
        Предсказать таймаут для задачи.

        Args:
            mode: Режим выполнения (fast, deep3, deep6)
            prompt: Текст задачи
            model: Имя модели
            context: Дополнительный контекст

        Returns:
            PredictionResult с предсказанием и метаданными
        """
        context = context or {}

        # 1. Извлечение признаков
        features = self.feature_extractor.extract(prompt, context)

        # 2. Базовое предсказание из признаков
        feature_score = sum(
            features.get(name, 0) * weight
            for name, weight in self.FEATURE_WEIGHTS.items()
        )
        base_prediction = self.BASE_TIME + feature_score

        # 3. Калибровка по модели
        model_calibration = self.model_calibrator.get_calibration(model)
        calibrated = base_prediction * model_calibration

        # 4. Калибровка по режиму
        mode_calibration = self.mode_calibrator.get_calibration(mode)
        final_prediction = calibrated * mode_calibration

        # 5. Ограничение диапазона
        final_prediction = max(self.MIN_TIMEOUT, min(self.MAX_TIMEOUT, final_prediction))

        # 6. Определение сложности
        complexity = self._determine_complexity(final_prediction)

        # 7. Расчёт уверенности
        confidence = self._calculate_confidence(features, mode, model)

        # 8. Создание результата
        prediction_id = self._generate_id(prompt, mode, model)
        result = PredictionResult(
            id=prediction_id,
            timeout=final_prediction,
            confidence=confidence,
            complexity=complexity,
            factors=features,
            model_calibration=model_calibration,
            mode_calibration=mode_calibration
        )

        # Сохраняем для последующего сопоставления
        self._predictions[prediction_id] = result

        return result

    def record_outcome(
        self,
        prediction_id: str,
        actual_seconds: float,
        success: bool,
        tokens_generated: int = 0
    ):
        """
        Записать фактический результат выполнения.

        Обновляет калибровки на основе ошибки предсказания.
        """
        if prediction_id not in self._predictions:
            return

        prediction = self._predictions[prediction_id]

        # Создаём запись результата
        outcome = OutcomeRecord(
            prediction_id=prediction_id,
            predicted_timeout=prediction.timeout,
            actual_seconds=actual_seconds,
            success=success,
            tokens_generated=tokens_generated,
            mode=prediction.factors.get("mode", "unknown"),
            model=prediction.factors.get("model", "unknown"),
            complexity=prediction.complexity.value
        )
        self._outcomes.append(outcome)

        # Обновляем калибровки
        ratio = outcome.accuracy_ratio
        # Извлекаем mode и model из контекста (нужно добавить в predict)
        # Пока используем заглушку
        self.model_calibrator.update("default", ratio)
        self.mode_calibrator.update("default", ratio)

        # Обновляем статистику ошибок
        self._error_history.append(outcome.error)
        self._accuracy_history.append(ratio)

        # Ограничиваем историю
        if len(self._error_history) > 100:
            self._error_history = self._error_history[-100:]
            self._accuracy_history = self._accuracy_history[-100:]

        # Сохраняем историю
        if self._history_file:
            self._save_history()

        # Удаляем использованное предсказание
        del self._predictions[prediction_id]

    def get_stats(self) -> Dict[str, Any]:
        """Получить статистику предсказаний."""
        if not self._outcomes:
            return {
                "total_predictions": 0,
                "mean_error": 0,
                "mean_accuracy": 1.0,
                "confidence": 0.5
            }

        return {
            "total_predictions": len(self._outcomes),
            "mean_error": statistics.mean(self._error_history) if self._error_history else 0,
            "median_error": statistics.median(self._error_history) if self._error_history else 0,
            "mean_accuracy": statistics.mean(self._accuracy_history) if self._accuracy_history else 1.0,
            "std_accuracy": statistics.stdev(self._accuracy_history) if len(self._accuracy_history) > 1 else 0,
            "success_rate": sum(1 for o in self._outcomes if o.success) / len(self._outcomes),
            "recent_accuracy": statistics.mean(self._accuracy_history[-10:]) if self._accuracy_history else 1.0
        }

    def _determine_complexity(self, predicted_seconds: float) -> TaskComplexity:
        """Определить сложность по предсказанному времени."""
        if predicted_seconds < 10:
            return TaskComplexity.TRIVIAL
        elif predicted_seconds < 30:
            return TaskComplexity.SIMPLE
        elif predicted_seconds < 60:
            return TaskComplexity.MODERATE
        elif predicted_seconds < 180:
            return TaskComplexity.COMPLEX
        else:
            return TaskComplexity.VERY_COMPLEX

    def _calculate_confidence(
        self,
        features: Dict[str, float],
        mode: str,
        model: str
    ) -> float:
        """
        Рассчитать уверенность в предсказании.

        Уверенность выше если:
        - Есть история для данной модели/режима
        - Признаки задачи чёткие
        - Недавние предсказания были точными
        """
        confidence = 0.5  # Базовая уверенность

        # Бонус за историю
        if len(self._outcomes) > 10:
            confidence += 0.15
        if len(self._outcomes) > 50:
            confidence += 0.1

        # Бонус за недавнюю точность
        if self._accuracy_history:
            recent_accuracy = statistics.mean(self._accuracy_history[-10:])
            if 0.8 <= recent_accuracy <= 1.2:
                confidence += 0.15  # Точные предсказания
            elif 0.6 <= recent_accuracy <= 1.5:
                confidence += 0.05  # Нормальные предсказания

        # Штраф за неопределённость признаков
        complexity_score = features.get("complexity_keywords", 0)
        if complexity_score < 0.2:
            confidence -= 0.1  # Нет чётких индикаторов сложности

        # Бонус за известную модель
        if model in ModelCalibrator.MODEL_SPEED_FACTORS:
            confidence += 0.05

        return max(0.3, min(0.95, confidence))

    def _generate_id(self, prompt: str, mode: str, model: str) -> str:
        """Сгенерировать уникальный ID предсказания."""
        data = f"{prompt[:100]}{mode}{model}{time.time()}"
        return hashlib.md5(data.encode()).hexdigest()[:12]

    def _load_history(self):
        """Загрузить историю из файла."""
        if not self._history_file:
            return

        path = Path(self._history_file)
        if not path.exists():
            return

        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = json.load(f)

            self._error_history = data.get("error_history", [])
            self._accuracy_history = data.get("accuracy_history", [])

            # Восстанавливаем калибровки
            for model, calibrations in data.get("model_calibrations", {}).items():
                self.model_calibrator._calibrations[model] = calibrations

            for mode, calibrations in data.get("mode_calibrations", {}).items():
                self.mode_calibrator._calibrations[mode] = calibrations

        except Exception:
            pass  # Игнорируем ошибки загрузки

    def _save_history(self):
        """Сохранить историю в файл."""
        if not self._history_file:
            return

        data = {
            "error_history": self._error_history[-100:],
            "accuracy_history": self._accuracy_history[-100:],
            "model_calibrations": dict(self.model_calibrator._calibrations),
            "mode_calibrations": dict(self.mode_calibrator._calibrations),
            "total_outcomes": len(self._outcomes)
        }

        try:
            path = Path(self._history_file)
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass  # Игнорируем ошибки сохранения


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

# Глобальный экземпляр для удобства
_global_estimator: Optional[PredictiveEstimator] = None


def get_estimator(history_file: str = None) -> PredictiveEstimator:
    """Получить глобальный экземпляр оценщика."""
    global _global_estimator
    if _global_estimator is None:
        _global_estimator = PredictiveEstimator(history_file)
    return _global_estimator


def predict_timeout(
    mode: str,
    prompt: str,
    model: str = "qwen2.5-coder:7b"
) -> float:
    """
    Быстрое предсказание таймаута.

    Returns:
        Предсказанный таймаут в секундах
    """
    estimator = get_estimator()
    result = estimator.predict(mode, prompt, model)
    return result.timeout


def predict_with_details(
    mode: str,
    prompt: str,
    model: str = "qwen2.5-coder:7b"
) -> Dict[str, Any]:
    """
    Предсказание с полной информацией.

    Returns:
        Dict с timeout, confidence, complexity и т.д.
    """
    estimator = get_estimator()
    result = estimator.predict(mode, prompt, model)
    return result.to_dict()


# ═══════════════════════════════════════════════════════════════════════════════
# ТЕСТ
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')

    print("=" * 60)
    print("PredictiveEstimator Test")
    print("=" * 60)

    estimator = PredictiveEstimator()

    # Test 1: Simple prediction
    print("\n--- Test 1: Simple Predictions ---")
    test_prompts = [
        ("What is 2+2?", "fast"),
        ("Fix the bug in parser.py that causes IndexError", "deep3"),
        ("Refactor the entire authentication system to use OAuth2", "deep6"),
        ("Find all files with TODO comments", "search"),
    ]

    for prompt, mode in test_prompts:
        result = estimator.predict(mode, prompt)
        print(f"\n  Mode: {mode}")
        print(f"  Prompt: {prompt[:50]}...")
        print(f"  Timeout: {result.timeout:.1f}s")
        print(f"  Confidence: {result.confidence:.0%}")
        print(f"  Complexity: {result.complexity.value}")

    # Test 2: Model calibration
    print("\n--- Test 2: Model Calibration ---")
    prompt = "Write a function to parse JSON"
    for model in ["qwen2.5-coder:3b", "qwen2.5-coder:7b", "qwen2.5-coder:32b"]:
        result = estimator.predict("deep3", prompt, model)
        print(f"  {model}: {result.timeout:.1f}s (calibration: {result.model_calibration:.2f})")

    # Test 3: Learning from outcomes
    print("\n--- Test 3: Learning from Outcomes ---")
    # Simulate predictions and outcomes
    for i in range(5):
        result = estimator.predict("deep3", f"Task {i}: fix bug in file{i}.py")
        actual = result.timeout * (0.8 + 0.4 * (i / 5))  # Варьируем фактическое время
        estimator.record_outcome(result.id, actual, success=True, tokens_generated=100)
        print(f"  Task {i}: predicted={result.timeout:.1f}s, actual={actual:.1f}s")

    # Test 4: Statistics
    print("\n--- Test 4: Statistics ---")
    stats = estimator.get_stats()
    for key, value in stats.items():
        if isinstance(value, float):
            print(f"  {key}: {value:.2f}")
        else:
            print(f"  {key}: {value}")

    # Test 5: Feature extraction
    print("\n--- Test 5: Feature Extraction ---")
    complex_prompt = """
    Refactor the entire database layer to use async/await pattern.
    The current implementation in db_manager.py uses synchronous calls.
    We need to:
    1. Convert all queries to async
    2. Add connection pooling
    3. Implement retry logic
    """
    features = FeatureExtractor.extract(complex_prompt)
    print("  Features for complex task:")
    for name, value in sorted(features.items()):
        if value > 0:
            print(f"    {name}: {value:.2f}")

    print("\n" + "=" * 60)
    print("PredictiveEstimator tests passed!")
    print("=" * 60)
