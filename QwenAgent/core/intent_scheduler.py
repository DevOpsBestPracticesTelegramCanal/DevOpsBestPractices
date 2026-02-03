# -*- coding: utf-8 -*-
"""
intent_scheduler.py — Intent-Aware Scheduler
=============================================

Phase 4 системы управления таймаутами QwenCode.

Анализирует токены в реальном времени для:
- Детекции намерений LLM (генерация кода, объяснение, tool call)
- Динамической корректировки таймаутов
- Раннего завершения при обнаружении паттернов завершения
- Продления при обнаружении сложной генерации

Принципы:
1. Streaming Analysis — анализ токенов по мере поступления
2. Pattern Detection — распознавание паттернов завершения/продолжения
3. Adaptive Timeout — динамическая корректировка на основе контекста
4. Early Exit — досрочное завершение при явном completion

Использование:
    from core.intent_scheduler import IntentScheduler, StreamAnalyzer

    scheduler = IntentScheduler()
    analyzer = scheduler.create_analyzer(initial_timeout=60)

    # В streaming loop:
    for token in stream:
        decision = analyzer.process_token(token)
        if decision.should_terminate:
            break
        if decision.timeout_adjustment:
            adjust_timeout(decision.new_timeout)
"""

import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any, Callable, Tuple
from enum import Enum


class DetectedIntent(Enum):
    """Распознанные намерения LLM."""
    UNKNOWN = "unknown"
    THINKING = "thinking"           # Размышление/анализ
    CODE_GENERATION = "code_gen"    # Генерация кода
    EXPLANATION = "explanation"     # Объяснение
    TOOL_CALL = "tool_call"         # Вызов инструмента
    LIST_GENERATION = "list_gen"    # Генерация списка
    ERROR_HANDLING = "error"        # Обработка ошибки
    COMPLETION = "completion"       # Завершение ответа
    CONTINUATION = "continuation"   # Продолжение генерации


class CompletionSignal(Enum):
    """Сигналы завершения."""
    NONE = "none"
    WEAK = "weak"           # Возможно завершение
    STRONG = "strong"       # Вероятно завершение
    DEFINITE = "definite"   # Точно завершение


@dataclass
class TokenAnalysis:
    """Результат анализа одного токена."""
    token: str
    position: int
    intent: DetectedIntent
    completion_signal: CompletionSignal
    confidence: float
    context_tokens: List[str]  # Последние N токенов для контекста


@dataclass
class SchedulerDecision:
    """Решение планировщика."""
    should_terminate: bool = False      # Прервать генерацию?
    should_extend: bool = False         # Продлить таймаут?
    timeout_adjustment: float = 0.0     # Корректировка таймаута (секунды)
    new_timeout: float = 0.0            # Новый таймаут (если корректировка)
    reason: str = ""                    # Причина решения
    detected_intent: DetectedIntent = DetectedIntent.UNKNOWN
    completion_signal: CompletionSignal = CompletionSignal.NONE


@dataclass
class StreamState:
    """Состояние потока генерации."""
    tokens: List[str] = field(default_factory=list)
    token_count: int = 0
    start_time: float = field(default_factory=time.time)
    last_token_time: float = field(default_factory=time.time)
    current_intent: DetectedIntent = DetectedIntent.UNKNOWN
    intent_confidence: float = 0.0
    in_code_block: bool = False
    code_block_depth: int = 0
    in_tool_call: bool = False
    bracket_depth: int = 0
    completion_signals: List[CompletionSignal] = field(default_factory=list)


class PatternMatcher:
    """
    Распознаватель паттернов в токенах.

    Использует regex и эвристики для детекции:
    - Начала/конца кода
    - Tool calls
    - Завершающих фраз
    - Паттернов продолжения
    """

    # Паттерны начала кода
    CODE_START_PATTERNS = [
        r"```\w*",           # Markdown code block
        r"def\s+\w+",        # Python function
        r"class\s+\w+",      # Python class
        r"function\s+\w+",   # JS function
        r"const\s+\w+\s*=",  # JS const
        r"import\s+",        # Import statement
        r"from\s+\w+",       # Python import
    ]

    # Паттерны конца кода
    CODE_END_PATTERNS = [
        r"```\s*$",          # End of code block
        r"return\s+\w+",     # Return statement
        r"raise\s+\w+",      # Raise exception
    ]

    # Паттерны tool call
    TOOL_CALL_PATTERNS = [
        r"\[TOOL:\s*\w+",    # QwenCode tool format
        r"\[tool:\s*\w+",    # Lowercase variant
        r"<tool>",           # XML-like tool
        r"\{\s*\"tool\"",    # JSON tool
    ]

    # Паттерны завершения
    COMPLETION_PATTERNS = {
        "strong": [
            r"Done\.?$",
            r"Completed\.?$",
            r"Finished\.?$",
            r"That's all\.?$",
            r"Hope this helps\.?$",
            r"Let me know if.*$",
            r"Is there anything else.*$",
        ],
        "weak": [
            r"\.\s*$",           # Ends with period
            r"!\s*$",            # Ends with exclamation
            r"\?\s*$",           # Ends with question (asking for confirmation)
            r":\s*$",            # Ends with colon (might continue)
        ]
    }

    # Паттерны продолжения
    CONTINUATION_PATTERNS = [
        r"First,?\s*",
        r"Next,?\s*",
        r"Then,?\s*",
        r"Also,?\s*",
        r"Additionally,?\s*",
        r"Furthermore,?\s*",
        r"Step\s+\d+",
        r"\d+\.\s+",          # Numbered list
        r"•\s+",              # Bullet point
        r"-\s+",              # Dash list
    ]

    @classmethod
    def detect_code_start(cls, text: str) -> bool:
        """Проверить начало кода."""
        for pattern in cls.CODE_START_PATTERNS:
            if re.search(pattern, text):
                return True
        return False

    @classmethod
    def detect_code_end(cls, text: str) -> bool:
        """Проверить конец кода."""
        for pattern in cls.CODE_END_PATTERNS:
            if re.search(pattern, text):
                return True
        return False

    @classmethod
    def detect_tool_call(cls, text: str) -> bool:
        """Проверить tool call."""
        for pattern in cls.TOOL_CALL_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False

    @classmethod
    def detect_completion(cls, text: str) -> CompletionSignal:
        """Проверить сигнал завершения."""
        for pattern in cls.COMPLETION_PATTERNS["strong"]:
            if re.search(pattern, text, re.IGNORECASE):
                return CompletionSignal.STRONG

        for pattern in cls.COMPLETION_PATTERNS["weak"]:
            if re.search(pattern, text):
                return CompletionSignal.WEAK

        return CompletionSignal.NONE

    @classmethod
    def detect_continuation(cls, text: str) -> bool:
        """Проверить сигнал продолжения."""
        for pattern in cls.CONTINUATION_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                return True
        return False


class StreamAnalyzer:
    """
    Анализатор потока токенов.

    Отслеживает состояние генерации и принимает решения
    о корректировке таймаутов в реальном времени.
    """

    # Размер контекстного окна (последние N токенов)
    CONTEXT_WINDOW = 20

    # Пороги для решений
    EARLY_EXIT_TOKEN_THRESHOLD = 50      # Минимум токенов для early exit
    EXTEND_THRESHOLD_TOKENS = 200        # Токенов для возможного продления
    MAX_EXTENSION_FACTOR = 2.0           # Максимальное продление (x2)
    MIN_TIMEOUT = 10.0                   # Минимальный таймаут
    MAX_TIMEOUT = 600.0                  # Максимальный таймаут

    # Корректировки по intent
    INTENT_TIMEOUT_MULTIPLIERS = {
        DetectedIntent.CODE_GENERATION: 1.5,   # Код требует больше времени
        DetectedIntent.TOOL_CALL: 0.8,         # Tool calls быстрее
        DetectedIntent.EXPLANATION: 1.2,       # Объяснения средние
        DetectedIntent.LIST_GENERATION: 1.3,   # Списки средние
        DetectedIntent.THINKING: 1.4,          # Размышления долгие
        DetectedIntent.ERROR_HANDLING: 0.7,    # Ошибки быстро
        DetectedIntent.COMPLETION: 0.5,        # Завершение = сократить
        DetectedIntent.CONTINUATION: 1.3,      # Продолжение = добавить
    }

    def __init__(
        self,
        initial_timeout: float = 60.0,
        on_decision: Callable[[SchedulerDecision], None] = None
    ):
        """
        Инициализация анализатора.

        Args:
            initial_timeout: Начальный таймаут (секунды)
            on_decision: Callback для решений
        """
        self.initial_timeout = initial_timeout
        self.current_timeout = initial_timeout
        self.on_decision = on_decision
        self.state = StreamState()
        self.decisions: List[SchedulerDecision] = []
        self._intent_history: List[DetectedIntent] = []

    def process_token(self, token: str) -> SchedulerDecision:
        """
        Обработать новый токен.

        Args:
            token: Новый токен

        Returns:
            SchedulerDecision с рекомендацией
        """
        # Обновляем состояние
        self.state.tokens.append(token)
        self.state.token_count += 1
        self.state.last_token_time = time.time()

        # Получаем контекст
        context = self.state.tokens[-self.CONTEXT_WINDOW:]
        context_text = "".join(context)

        # Анализируем токен
        analysis = self._analyze_token(token, context_text)

        # Обновляем intent
        self._update_intent(analysis)

        # Принимаем решение
        decision = self._make_decision(analysis)

        # Сохраняем решение
        self.decisions.append(decision)

        # Callback
        if self.on_decision and (decision.should_terminate or decision.should_extend):
            self.on_decision(decision)

        return decision

    def process_chunk(self, chunk: str) -> SchedulerDecision:
        """
        Обработать чанк текста (несколько токенов).

        Args:
            chunk: Текстовый чанк

        Returns:
            Финальное решение для чанка
        """
        # Простая токенизация по пробелам и переносам
        tokens = re.findall(r'\S+|\s+', chunk)
        last_decision = SchedulerDecision()

        for token in tokens:
            last_decision = self.process_token(token)
            if last_decision.should_terminate:
                break

        return last_decision

    def get_current_state(self) -> Dict[str, Any]:
        """Получить текущее состояние."""
        return {
            "token_count": self.state.token_count,
            "elapsed": time.time() - self.state.start_time,
            "current_intent": self.state.current_intent.value,
            "intent_confidence": self.state.intent_confidence,
            "in_code_block": self.state.in_code_block,
            "in_tool_call": self.state.in_tool_call,
            "current_timeout": self.current_timeout,
            "decisions_made": len(self.decisions)
        }

    def get_recommendation(self) -> Dict[str, Any]:
        """Получить итоговую рекомендацию."""
        # Анализируем историю решений
        extensions = sum(1 for d in self.decisions if d.should_extend)
        terminations = sum(1 for d in self.decisions if d.should_terminate)

        # Определяем доминирующий intent
        if self._intent_history:
            intent_counts = {}
            for intent in self._intent_history:
                intent_counts[intent] = intent_counts.get(intent, 0) + 1
            dominant_intent = max(intent_counts, key=intent_counts.get)
        else:
            dominant_intent = DetectedIntent.UNKNOWN

        return {
            "dominant_intent": dominant_intent.value,
            "total_tokens": self.state.token_count,
            "total_extensions": extensions,
            "total_termination_signals": terminations,
            "final_timeout": self.current_timeout,
            "timeout_change": self.current_timeout - self.initial_timeout,
            "recommendation": self._get_final_recommendation()
        }

    def _analyze_token(self, token: str, context: str) -> TokenAnalysis:
        """Анализировать токен в контексте."""
        # Определяем intent
        intent = self._detect_intent(token, context)

        # Определяем сигнал завершения
        completion = PatternMatcher.detect_completion(context)

        # Уверенность
        confidence = self._calculate_confidence(intent, context)

        return TokenAnalysis(
            token=token,
            position=self.state.token_count,
            intent=intent,
            completion_signal=completion,
            confidence=confidence,
            context_tokens=self.state.tokens[-self.CONTEXT_WINDOW:]
        )

    def _detect_intent(self, token: str, context: str) -> DetectedIntent:
        """Определить intent по токену и контексту."""
        # Проверяем code block
        if "```" in token:
            if self.state.in_code_block:
                self.state.in_code_block = False
                self.state.code_block_depth -= 1
            else:
                self.state.in_code_block = True
                self.state.code_block_depth += 1
            return DetectedIntent.CODE_GENERATION

        if self.state.in_code_block:
            return DetectedIntent.CODE_GENERATION

        # Проверяем tool call
        if PatternMatcher.detect_tool_call(context):
            self.state.in_tool_call = True
            return DetectedIntent.TOOL_CALL

        if self.state.in_tool_call:
            if "]" in token:
                self.state.in_tool_call = False
            return DetectedIntent.TOOL_CALL

        # Проверяем code start без block
        if PatternMatcher.detect_code_start(context):
            return DetectedIntent.CODE_GENERATION

        # Проверяем completion
        completion = PatternMatcher.detect_completion(context)
        if completion == CompletionSignal.STRONG:
            return DetectedIntent.COMPLETION

        # Проверяем continuation
        if PatternMatcher.detect_continuation(context):
            return DetectedIntent.CONTINUATION

        # Проверяем list generation
        if re.search(r'^\s*[-•*]\s+|\d+\.\s+', context):
            return DetectedIntent.LIST_GENERATION

        # Проверяем thinking patterns
        thinking_patterns = ["let me", "i think", "first", "consider", "analyzing"]
        if any(p in context.lower() for p in thinking_patterns):
            return DetectedIntent.THINKING

        # Default
        return DetectedIntent.EXPLANATION

    def _update_intent(self, analysis: TokenAnalysis):
        """Обновить текущий intent."""
        self._intent_history.append(analysis.intent)

        # Ограничиваем историю
        if len(self._intent_history) > 50:
            self._intent_history = self._intent_history[-50:]

        # Обновляем состояние
        if analysis.confidence > self.state.intent_confidence:
            self.state.current_intent = analysis.intent
            self.state.intent_confidence = analysis.confidence

        # Записываем completion signals
        if analysis.completion_signal != CompletionSignal.NONE:
            self.state.completion_signals.append(analysis.completion_signal)

    def _calculate_confidence(self, intent: DetectedIntent, context: str) -> float:
        """Рассчитать уверенность в intent."""
        confidence = 0.5

        # Бонус за явные маркеры
        if intent == DetectedIntent.CODE_GENERATION and "```" in context:
            confidence += 0.3
        if intent == DetectedIntent.TOOL_CALL and "[TOOL:" in context:
            confidence += 0.4

        # Бонус за длину контекста
        if len(context) > 100:
            confidence += 0.1

        return min(confidence, 1.0)

    def _make_decision(self, analysis: TokenAnalysis) -> SchedulerDecision:
        """Принять решение на основе анализа."""
        decision = SchedulerDecision(
            detected_intent=analysis.intent,
            completion_signal=analysis.completion_signal
        )

        # Проверяем early termination
        if self._should_terminate(analysis):
            decision.should_terminate = True
            decision.reason = f"Completion detected: {analysis.completion_signal.value}"
            return decision

        # Проверяем необходимость продления
        extension = self._calculate_extension(analysis)
        if extension != 0:
            decision.should_extend = extension > 0
            decision.timeout_adjustment = extension
            decision.new_timeout = max(
                self.MIN_TIMEOUT,
                min(self.MAX_TIMEOUT, self.current_timeout + extension)
            )
            self.current_timeout = decision.new_timeout
            decision.reason = f"Intent {analysis.intent.value} requires adjustment"

        return decision

    def _should_terminate(self, analysis: TokenAnalysis) -> bool:
        """Проверить условия для раннего завершения."""
        # Не завершаем слишком рано
        if self.state.token_count < self.EARLY_EXIT_TOKEN_THRESHOLD:
            return False

        # Не завершаем в середине кода
        if self.state.in_code_block or self.state.in_tool_call:
            return False

        # Проверяем сильные сигналы завершения
        if analysis.completion_signal == CompletionSignal.DEFINITE:
            return True

        # Проверяем несколько сильных сигналов подряд
        recent_signals = self.state.completion_signals[-3:]
        strong_count = sum(1 for s in recent_signals if s == CompletionSignal.STRONG)
        if strong_count >= 2:
            return True

        return False

    def _calculate_extension(self, analysis: TokenAnalysis) -> float:
        """Рассчитать корректировку таймаута."""
        # Базовый множитель для intent
        multiplier = self.INTENT_TIMEOUT_MULTIPLIERS.get(analysis.intent, 1.0)

        # Корректировка не нужна для нейтрального multiplier
        if multiplier == 1.0:
            return 0.0

        # Рассчитываем корректировку
        if multiplier > 1.0:
            # Продление: добавляем % от начального
            extension = self.initial_timeout * (multiplier - 1.0) * 0.2
        else:
            # Сокращение: отнимаем % от оставшегося
            extension = -self.current_timeout * (1.0 - multiplier) * 0.1

        # Ограничиваем корректировку
        max_extension = self.initial_timeout * (self.MAX_EXTENSION_FACTOR - 1.0)
        extension = max(-self.current_timeout * 0.5, min(max_extension, extension))

        return extension

    def _get_final_recommendation(self) -> str:
        """Получить текстовую рекомендацию."""
        if self.state.token_count == 0:
            return "No tokens processed"

        if self.current_timeout > self.initial_timeout * 1.3:
            return "Consider increasing timeout for similar tasks"
        elif self.current_timeout < self.initial_timeout * 0.7:
            return "Task completed faster than expected"
        else:
            return "Timeout was appropriate"


class IntentScheduler:
    """
    Intent-Aware Scheduler - главный класс Phase 4.

    Управляет созданием анализаторов и агрегацией статистики.
    """

    def __init__(self):
        self.analyzers: List[StreamAnalyzer] = []
        self.stats = {
            "total_sessions": 0,
            "early_terminations": 0,
            "timeout_extensions": 0,
            "average_token_count": 0.0,
            "intent_distribution": {}
        }

    def create_analyzer(
        self,
        initial_timeout: float = 60.0,
        on_decision: Callable[[SchedulerDecision], None] = None
    ) -> StreamAnalyzer:
        """
        Создать новый анализатор потока.

        Args:
            initial_timeout: Начальный таймаут
            on_decision: Callback для решений

        Returns:
            StreamAnalyzer для обработки токенов
        """
        analyzer = StreamAnalyzer(initial_timeout, on_decision)
        self.analyzers.append(analyzer)
        self.stats["total_sessions"] += 1
        return analyzer

    def finalize_analyzer(self, analyzer: StreamAnalyzer):
        """
        Завершить анализатор и обновить статистику.

        Args:
            analyzer: Завершаемый анализатор
        """
        recommendation = analyzer.get_recommendation()

        # Обновляем статистику
        if any(d.should_terminate for d in analyzer.decisions):
            self.stats["early_terminations"] += 1

        extensions = sum(1 for d in analyzer.decisions if d.should_extend)
        self.stats["timeout_extensions"] += extensions

        # Обновляем среднее
        n = self.stats["total_sessions"]
        old_avg = self.stats["average_token_count"]
        new_count = analyzer.state.token_count
        self.stats["average_token_count"] = (old_avg * (n - 1) + new_count) / n

        # Intent distribution
        intent = recommendation["dominant_intent"]
        self.stats["intent_distribution"][intent] = \
            self.stats["intent_distribution"].get(intent, 0) + 1

    def get_stats(self) -> Dict[str, Any]:
        """Получить агрегированную статистику."""
        return self.stats.copy()


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

# Глобальный планировщик
_global_scheduler: Optional[IntentScheduler] = None


def get_scheduler() -> IntentScheduler:
    """Получить глобальный планировщик."""
    global _global_scheduler
    if _global_scheduler is None:
        _global_scheduler = IntentScheduler()
    return _global_scheduler


def create_stream_analyzer(
    initial_timeout: float = 60.0,
    on_decision: Callable[[SchedulerDecision], None] = None
) -> StreamAnalyzer:
    """Создать анализатор через глобальный планировщик."""
    return get_scheduler().create_analyzer(initial_timeout, on_decision)


# ═══════════════════════════════════════════════════════════════════════════════
# ТЕСТ
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys
    if sys.platform == 'win32':
        sys.stdout.reconfigure(encoding='utf-8')

    print("=" * 60)
    print("IntentScheduler Test (Phase 4)")
    print("=" * 60)

    scheduler = IntentScheduler()

    # Test 1: Basic analysis
    print("\n--- Test 1: Basic Token Analysis ---")
    analyzer = scheduler.create_analyzer(initial_timeout=60)

    test_stream = [
        "Let", " me", " analyze", " this", " problem", ".",
        "\n", "```", "python", "\n",
        "def", " fix", "(", ")", ":", "\n",
        "    ", "return", " True", "\n",
        "```", "\n",
        "Done", ".", " Let", " me", " know", " if", " you", " need", " help", "."
    ]

    print(f"  Processing {len(test_stream)} tokens...")
    for token in test_stream:
        decision = analyzer.process_token(token)
        if decision.should_terminate or decision.should_extend:
            print(f"    Token '{token.strip()}': {decision.reason}")

    state = analyzer.get_current_state()
    print(f"\n  Final state:")
    print(f"    Tokens: {state['token_count']}")
    print(f"    Intent: {state['current_intent']}")
    print(f"    Timeout: {state['current_timeout']:.1f}s")

    # Test 2: Code generation detection
    print("\n--- Test 2: Code Generation Detection ---")
    analyzer2 = scheduler.create_analyzer(initial_timeout=60)

    code_stream = "Here's the solution:\n```python\nclass Parser:\n    def parse(self):\n        pass\n```"
    decision = analyzer2.process_chunk(code_stream)

    state2 = analyzer2.get_current_state()
    print(f"  Detected intent: {state2['current_intent']}")
    print(f"  In code block: {state2['in_code_block']}")
    print(f"  Timeout adjusted to: {state2['current_timeout']:.1f}s")

    # Test 3: Tool call detection
    print("\n--- Test 3: Tool Call Detection ---")
    analyzer3 = scheduler.create_analyzer(initial_timeout=60)

    tool_stream = "I'll read the file first.\n[TOOL: read(file_path=\"test.py\")]"
    decision = analyzer3.process_chunk(tool_stream)

    state3 = analyzer3.get_current_state()
    print(f"  Detected intent: {state3['current_intent']}")
    print(f"  In tool call: {state3['in_tool_call']}")

    # Test 4: Early termination
    print("\n--- Test 4: Early Termination ---")
    analyzer4 = scheduler.create_analyzer(initial_timeout=60)

    # Generate enough tokens first
    for i in range(60):
        analyzer4.process_token(f"word{i} ")

    # Then add completion signal
    completion_stream = "That's all. Let me know if you need anything else."
    decision = analyzer4.process_chunk(completion_stream)

    print(f"  Should terminate: {decision.should_terminate}")
    print(f"  Reason: {decision.reason}")

    # Test 5: Scheduler stats
    print("\n--- Test 5: Scheduler Statistics ---")
    for analyzer in [analyzer, analyzer2, analyzer3, analyzer4]:
        scheduler.finalize_analyzer(analyzer)

    stats = scheduler.get_stats()
    print(f"  Total sessions: {stats['total_sessions']}")
    print(f"  Early terminations: {stats['early_terminations']}")
    print(f"  Timeout extensions: {stats['timeout_extensions']}")
    print(f"  Avg token count: {stats['average_token_count']:.1f}")
    print(f"  Intent distribution: {stats['intent_distribution']}")

    # Test 6: Recommendations
    print("\n--- Test 6: Recommendations ---")
    analyzer5 = scheduler.create_analyzer(initial_timeout=30)
    for i in range(100):
        analyzer5.process_token(f"complex_code_{i} ")

    rec = analyzer5.get_recommendation()
    print(f"  Dominant intent: {rec['dominant_intent']}")
    print(f"  Total tokens: {rec['total_tokens']}")
    print(f"  Timeout change: {rec['timeout_change']:.1f}s")
    print(f"  Recommendation: {rec['recommendation']}")

    print("\n" + "=" * 60)
    print("IntentScheduler tests passed!")
    print("=" * 60)
