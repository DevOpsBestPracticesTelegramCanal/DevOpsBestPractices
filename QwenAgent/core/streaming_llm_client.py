# -*- coding: utf-8 -*-
"""
streaming_llm_client.py — Стриминговый LLM клиент с трёхуровневым таймаутом
============================================================================

Фаза 1 системы управления таймаутами QwenCode.

Три типа таймаутов:
1. TTFT (Time To First Token) — модель не начала генерацию
2. Idle timeout — модель замолчала посреди генерации
3. Absolute max — жёсткий потолок безопасности

Использование:
    client = StreamingLLMClient()
    async for token in client.generate_stream(prompt, model):
        print(token, end="")
"""

import time
import asyncio
import aiohttp
import json
from dataclasses import dataclass, field
from typing import AsyncIterator, Optional, Callable, List, Dict, Any
from enum import Enum

# Phase 4: Intent-Aware Scheduler (optional import)
try:
    from .intent_scheduler import StreamAnalyzer, IntentScheduler, SchedulerDecision
    INTENT_SCHEDULER_AVAILABLE = True
except ImportError:
    INTENT_SCHEDULER_AVAILABLE = False
    StreamAnalyzer = None


class GenerationState(Enum):
    """Состояния генерации, видимые монитору."""
    WAITING_FIRST_TOKEN = "waiting_first_token"
    GENERATING = "generating"
    IDLE = "idle"
    COMPLETED = "completed"
    TIMED_OUT = "timed_out"


@dataclass
class GenerationMetrics:
    """
    Метрики одного вызова LLM — основа для observability.

    Собирает данные для:
    - Мониторинга производительности
    - Предиктивного уровня (Фаза 3)
    - Отладки таймаутов
    """
    ttft: Optional[float] = None          # Time to First Token (секунды)
    total_time: float = 0.0
    tokens_generated: int = 0
    avg_itl: float = 0.0                  # Average Inter-Token Latency
    max_itl: float = 0.0                  # Максимальная пауза между токенами
    state: GenerationState = GenerationState.WAITING_FIRST_TOKEN
    timeout_reason: Optional[str] = None
    partial_result: str = ""
    model: str = ""
    prompt_tokens: int = 0                # Приблизительно

    def to_dict(self) -> Dict[str, Any]:
        """Сериализация для логов и API."""
        return {
            "ttft": round(self.ttft, 3) if self.ttft else None,
            "total_time": round(self.total_time, 3),
            "tokens_generated": self.tokens_generated,
            "avg_itl": round(self.avg_itl, 4) if self.avg_itl else 0,
            "max_itl": round(self.max_itl, 4) if self.max_itl else 0,
            "state": self.state.value,
            "timeout_reason": self.timeout_reason,
            "model": self.model,
            "prompt_tokens": self.prompt_tokens,
            "tps": round(self.tokens_generated / self.total_time, 1) if self.total_time > 0 else 0
        }


@dataclass
class TimeoutConfig:
    """
    Конфигурация таймаутов — то, что задаёт пользователь или система.

    Defaults оптимизированы для qwen2.5-coder:7b на средней машине.
    """
    ttft_timeout: float = 30.0       # Макс. ожидание первого токена
    idle_timeout: float = 15.0       # Макс. пауза между токенами
    absolute_max: float = 600.0      # Жёсткий потолок (safety net)

    def with_overrides(self, **kwargs) -> 'TimeoutConfig':
        """Создать копию с переопределёнными значениями."""
        return TimeoutConfig(
            ttft_timeout=kwargs.get('ttft_timeout', self.ttft_timeout),
            idle_timeout=kwargs.get('idle_timeout', self.idle_timeout),
            absolute_max=kwargs.get('absolute_max', self.absolute_max)
        )

    def __repr__(self):
        return f"TimeoutConfig(ttft={self.ttft_timeout}s, idle={self.idle_timeout}s, max={self.absolute_max}s)"


# ═══════════════════════════════════════════════════════════════════════════════
# ИСКЛЮЧЕНИЯ С МЕТРИКАМИ
# ═══════════════════════════════════════════════════════════════════════════════

class LLMTimeoutError(Exception):
    """Базовый класс для таймаут-исключений с метриками."""
    def __init__(self, metrics: GenerationMetrics, message: str = None):
        self.metrics = metrics
        msg = message or (
            f"{metrics.timeout_reason}: "
            f"generated {metrics.tokens_generated} tokens "
            f"in {metrics.total_time:.1f}s"
        )
        super().__init__(msg)

    @property
    def partial_result(self) -> str:
        """Частичный результат до таймаута."""
        return self.metrics.partial_result


class TTFTTimeoutError(LLMTimeoutError):
    """Модель не начала генерацию в течение ttft_timeout."""
    pass


class IdleTimeoutError(LLMTimeoutError):
    """Модель замолчала посреди генерации (idle_timeout)."""
    pass


class AbsoluteTimeoutError(LLMTimeoutError):
    """Превышен абсолютный потолок времени (absolute_max)."""
    pass


# ═══════════════════════════════════════════════════════════════════════════════
# STREAMING LLM CLIENT
# ═══════════════════════════════════════════════════════════════════════════════

class StreamingLLMClient:
    """
    Асинхронный стриминговый LLM-клиент с трёхуровневым таймаутом.

    Решает проблемы:
    1. Зависание Ollama без ответа → TTFTTimeoutError
    2. Модель замолчала посреди генерации → IdleTimeoutError
    3. Слишком долгая генерация → AbsoluteTimeoutError

    Всегда сохраняет partial_result — то, что успели сгенерировать.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        timeout_config: TimeoutConfig = None
    ):
        self.base_url = base_url.rstrip('/')
        self.config = timeout_config or TimeoutConfig()

        # История вызовов для предиктивной оценки (Фаза 3)
        self.call_history: List[GenerationMetrics] = []
        self._max_history = 100

        # Phase 4: Intent-Aware Scheduler
        self._stream_analyzer: Optional['StreamAnalyzer'] = None
        self._intent_scheduler: Optional['IntentScheduler'] = None
        if INTENT_SCHEDULER_AVAILABLE:
            self._intent_scheduler = IntentScheduler()

    def set_stream_analyzer(self, analyzer: 'StreamAnalyzer'):
        """Set stream analyzer for intent-aware processing (Phase 4)."""
        self._stream_analyzer = analyzer

    def create_stream_analyzer(self, initial_timeout: float = None) -> Optional['StreamAnalyzer']:
        """Create and set a new stream analyzer."""
        if not INTENT_SCHEDULER_AVAILABLE or not self._intent_scheduler:
            return None
        timeout = initial_timeout or self.config.absolute_max
        self._stream_analyzer = self._intent_scheduler.create_analyzer(timeout)
        return self._stream_analyzer

    def get_intent_stats(self) -> Dict[str, Any]:
        """Get intent scheduler statistics."""
        if self._intent_scheduler:
            return self._intent_scheduler.get_stats()
        return {}

    async def generate_stream(
        self,
        prompt: str,
        model: str,
        timeout_override: Optional[TimeoutConfig] = None,
        on_state_change: Optional[Callable[[GenerationState, GenerationMetrics], None]] = None,
        system_prompt: str = None
    ) -> AsyncIterator[str]:
        """
        Генерация со стримингом и мониторингом активности.

        Args:
            prompt: Текст запроса
            model: Имя модели Ollama (e.g., "qwen2.5-coder:7b")
            timeout_override: Переопределение таймаутов для этого вызова
            on_state_change: Callback при смене состояния (для UI)
            system_prompt: Системный промпт (опционально)

        Yields:
            Токены по мере генерации

        Raises:
            TTFTTimeoutError: Модель не начала генерацию
            IdleTimeoutError: Модель замолчала
            AbsoluteTimeoutError: Превышен абсолютный лимит
        """
        config = timeout_override or self.config
        metrics = GenerationMetrics(
            model=model,
            prompt_tokens=len(prompt.split())  # Приблизительно
        )

        start_time = time.monotonic()
        last_token_time = start_time
        buffer: List[str] = []

        # Подготовка запроса
        request_body = {
            "model": model,
            "prompt": prompt,
            "stream": True
        }
        if system_prompt:
            request_body["system"] = system_prompt

        try:
            timeout = aiohttp.ClientTimeout(
                total=config.absolute_max,
                sock_read=config.idle_timeout + 5  # Немного больше idle для сетевых задержек
            )

            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    f"{self.base_url}/api/generate",
                    json=request_body
                ) as response:

                    if response.status != 200:
                        error_text = await response.text()
                        raise RuntimeError(f"Ollama error {response.status}: {error_text}")

                    async for line in response.content:
                        now = time.monotonic()
                        elapsed = now - start_time

                        # --- Safety net: абсолютный потолок ---
                        if elapsed > config.absolute_max:
                            metrics.state = GenerationState.TIMED_OUT
                            metrics.timeout_reason = "absolute_max"
                            metrics.total_time = elapsed
                            metrics.partial_result = "".join(buffer)
                            self._record(metrics)
                            raise AbsoluteTimeoutError(metrics)

                        # --- TTFT timeout: модель не начала ---
                        if metrics.ttft is None and (now - start_time) > config.ttft_timeout:
                            metrics.state = GenerationState.TIMED_OUT
                            metrics.timeout_reason = "ttft_timeout"
                            metrics.total_time = elapsed
                            self._record(metrics)
                            raise TTFTTimeoutError(metrics)

                        # Парсим chunk от Ollama
                        chunk = self._parse_chunk(line)
                        if not chunk:
                            continue

                        # Проверяем done
                        if chunk.get("done"):
                            metrics.state = GenerationState.COMPLETED
                            break

                        token = chunk.get("response", "")
                        if not token:
                            continue

                        # --- Первый токен: фиксируем TTFT ---
                        if metrics.ttft is None:
                            metrics.ttft = now - start_time
                            metrics.state = GenerationState.GENERATING
                            if on_state_change:
                                on_state_change(metrics.state, metrics)

                        # --- Обновляем метрики ---
                        itl = now - last_token_time
                        metrics.max_itl = max(metrics.max_itl, itl)
                        metrics.tokens_generated += 1
                        last_token_time = now
                        buffer.append(token)

                        yield token

                        # --- Phase 4: Intent-aware analysis ---
                        if INTENT_SCHEDULER_AVAILABLE and hasattr(self, '_stream_analyzer') and self._stream_analyzer:
                            decision = self._stream_analyzer.process_token(token)
                            # Dynamic timeout adjustment
                            if decision.should_extend and decision.new_timeout > 0:
                                config = TimeoutConfig(
                                    ttft_timeout=config.ttft_timeout,
                                    idle_timeout=config.idle_timeout,
                                    absolute_max=min(decision.new_timeout, config.absolute_max * 2)
                                )
                            # Early termination on strong completion signal
                            if decision.should_terminate:
                                metrics.state = GenerationState.COMPLETED
                                metrics.timeout_reason = "intent_early_exit"
                                break

                        # --- Idle timeout проверка ---
                        # (будет проверена на следующей итерации)

        except asyncio.TimeoutError:
            # aiohttp timeout
            now = time.monotonic()
            elapsed = now - start_time
            metrics.total_time = elapsed
            metrics.partial_result = "".join(buffer)

            if metrics.ttft is None:
                metrics.state = GenerationState.TIMED_OUT
                metrics.timeout_reason = "ttft_timeout"
                self._record(metrics)
                raise TTFTTimeoutError(metrics)
            else:
                metrics.state = GenerationState.TIMED_OUT
                metrics.timeout_reason = "idle_timeout"
                self._record(metrics)
                raise IdleTimeoutError(metrics)

        except aiohttp.ClientError as e:
            # Сетевая ошибка
            metrics.total_time = time.monotonic() - start_time
            metrics.partial_result = "".join(buffer)
            metrics.state = GenerationState.TIMED_OUT
            metrics.timeout_reason = f"network_error: {type(e).__name__}"
            self._record(metrics)
            raise

        # Успешное завершение
        metrics.total_time = time.monotonic() - start_time
        if metrics.tokens_generated > 0:
            metrics.avg_itl = metrics.total_time / metrics.tokens_generated
        metrics.partial_result = "".join(buffer)
        self._record(metrics)

    async def generate(
        self,
        prompt: str,
        model: str,
        timeout_override: Optional[TimeoutConfig] = None,
        system_prompt: str = None
    ) -> str:
        """
        Асинхронная генерация без стриминга (собирает весь ответ).

        Returns:
            Полный ответ модели
        """
        result = []
        async for token in self.generate_stream(
            prompt, model, timeout_override, system_prompt=system_prompt
        ):
            result.append(token)
        return "".join(result)

    def _record(self, metrics: GenerationMetrics):
        """Сохраняем метрики для предиктивного уровня (Фаза 3)."""
        self.call_history.append(metrics)
        # Скользящее окно
        if len(self.call_history) > self._max_history:
            self.call_history = self.call_history[-self._max_history:]

    def _parse_chunk(self, line: bytes) -> Optional[dict]:
        """Парсит JSON-chunk из стриминга Ollama."""
        try:
            text = line.decode("utf-8").strip()
            if not text:
                return None
            return json.loads(text)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return None

    def get_stats(self) -> Dict[str, Any]:
        """Статистика по последним вызовам."""
        if not self.call_history:
            return {"calls": 0}

        completed = [m for m in self.call_history if m.state == GenerationState.COMPLETED]
        timeouts = [m for m in self.call_history if m.state == GenerationState.TIMED_OUT]

        return {
            "total_calls": len(self.call_history),
            "completed": len(completed),
            "timeouts": len(timeouts),
            "timeout_rate": f"{len(timeouts) / len(self.call_history):.1%}",
            "avg_ttft": round(sum(m.ttft for m in completed if m.ttft) / max(len(completed), 1), 2),
            "avg_total_time": round(sum(m.total_time for m in completed) / max(len(completed), 1), 2),
            "avg_tokens": round(sum(m.tokens_generated for m in completed) / max(len(completed), 1), 0),
        }


# ═══════════════════════════════════════════════════════════════════════════════
# ТЕСТ
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    async def test():
        print("=" * 60)
        print("StreamingLLMClient Test")
        print("=" * 60)

        client = StreamingLLMClient(
            timeout_config=TimeoutConfig(
                ttft_timeout=30,
                idle_timeout=15,
                absolute_max=120
            )
        )

        prompt = "Write a Python function to calculate factorial. Be brief."
        model = "qwen2.5-coder:3b"

        print(f"\nPrompt: {prompt}")
        print(f"Model: {model}")
        print(f"Config: {client.config}")
        print("\n--- Response ---")

        try:
            async for token in client.generate_stream(prompt, model):
                print(token, end="", flush=True)
            print("\n--- Done ---")
        except LLMTimeoutError as e:
            print(f"\n\n[TIMEOUT] {e}")
            print(f"Partial result: {e.partial_result[:100]}...")

        print(f"\nStats: {client.get_stats()}")

        if client.call_history:
            last = client.call_history[-1]
            print(f"Last call metrics: {last.to_dict()}")

    asyncio.run(test())
