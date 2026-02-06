# -*- coding: utf-8 -*-
"""
timeout_llm_client.py — Синхронный LLM клиент с таймаутами
==========================================================

Синхронная обёртка над StreamingLLMClient для использования
в текущем Flask-приложении без полной миграции на async.

Использование:
    from core.timeout_llm_client import TimeoutLLMClient, TimeoutConfig

    client = TimeoutLLMClient()

    # Простая генерация
    result = client.generate("Write hello world in Python", "qwen2.5-coder:3b")

    # С fallback на лёгкую модель
    result, metrics = client.generate_with_fallback(
        prompt="Complex task...",
        model="qwen2.5-coder:7b",
        fallback_model="qwen2.5-coder:3b"
    )
"""

import asyncio
import threading
from typing import Optional, Tuple, Iterator, Callable, Dict, Any
from dataclasses import dataclass

# Allow nested event loops (fixes "This event loop is already running")
try:
    import nest_asyncio
    nest_asyncio.apply()
except ImportError:
    pass  # nest_asyncio not installed, may cause issues in Flask

from .streaming_llm_client import (
    StreamingLLMClient,
    TimeoutConfig,
    GenerationMetrics,
    GenerationState,
    TTFTTimeoutError,
    IdleTimeoutError,
    AbsoluteTimeoutError,
    LLMTimeoutError
)

# Re-export для удобства
__all__ = [
    'TimeoutLLMClient',
    'TimeoutConfig',
    'GenerationMetrics',
    'GenerationState',
    'TTFTTimeoutError',
    'IdleTimeoutError',
    'AbsoluteTimeoutError',
    'LLMTimeoutError'
]


class TimeoutLLMClient:
    """
    Синхронный фасад над стриминговым клиентом.

    Предоставляет:
    1. Синхронную генерацию с полным мониторингом
    2. Fallback на лёгкую модель при таймауте
    3. Синхронный стриминг (через итератор)
    4. Доступ к истории вызовов для предиктивного уровня
    """

    def __init__(
        self,
        base_url: str = "http://localhost:11434",
        timeout_config: TimeoutConfig = None,
        enable_intent_scheduler: bool = True
    ):
        self._async_client = StreamingLLMClient(base_url, timeout_config)
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._lock = threading.Lock()
        self._enable_intent_scheduler = enable_intent_scheduler

    def _prepare_intent_scheduler(self, timeout: float = None):
        """
        Prepare IntentScheduler for next generation (Phase 4).
        Creates a fresh StreamAnalyzer with the given timeout.
        """
        if self._enable_intent_scheduler:
            self._async_client.create_stream_analyzer(timeout)

    def _get_loop(self) -> asyncio.AbstractEventLoop:
        """Получить или создать event loop для sync операций."""
        with self._lock:
            if self._loop is None or self._loop.is_closed():
                self._loop = asyncio.new_event_loop()
            return self._loop

    def generate(
        self,
        prompt: str,
        model: str,
        timeout_override: TimeoutConfig = None,
        system_prompt: str = None,
        options: dict = None
    ) -> str:
        """
        Синхронная генерация с полным мониторингом.

        Args:
            prompt: Текст запроса
            model: Имя модели Ollama
            timeout_override: Переопределение таймаутов
            system_prompt: Системный промпт (опционально)
            options: Ollama generation options (temperature, seed, etc.)

        Returns:
            Полный ответ модели

        Raises:
            TTFTTimeoutError: Модель не начала генерацию
            IdleTimeoutError: Модель замолчала
            AbsoluteTimeoutError: Превышен абсолютный лимит
        """
        # Phase 4: Prepare IntentScheduler for this generation
        effective_timeout = timeout_override.absolute_max if timeout_override else None
        self._prepare_intent_scheduler(effective_timeout)

        loop = self._get_loop()
        return loop.run_until_complete(
            self._async_client.generate(
                prompt, model, timeout_override, system_prompt,
                options=options
            )
        )

    def generate_stream_sync(
        self,
        prompt: str,
        model: str,
        timeout_override: TimeoutConfig = None,
        on_token: Callable[[str], None] = None,
        system_prompt: str = None
    ) -> str:
        """
        Синхронная генерация с callback для каждого токена.

        Args:
            prompt: Текст запроса
            model: Имя модели Ollama
            timeout_override: Переопределение таймаутов
            on_token: Callback для каждого токена (для UI)
            system_prompt: Системный промпт

        Returns:
            Полный ответ модели
        """
        loop = self._get_loop()

        async def _generate():
            result = []
            async for token in self._async_client.generate_stream(
                prompt, model, timeout_override, system_prompt=system_prompt
            ):
                result.append(token)
                if on_token:
                    on_token(token)
            return "".join(result)

        return loop.run_until_complete(_generate())

    def generate_with_fallback(
        self,
        prompt: str,
        model: str,
        fallback_model: str = None,
        timeout_override: TimeoutConfig = None,
        system_prompt: str = None
    ) -> Tuple[str, GenerationMetrics]:
        """
        Генерация с автоматическим fallback на лёгкую модель при таймауте.

        Реализует Уровень 1 стратегии отказоустойчивости:
        - Тяжёлая модель не справилась → пробуем лёгкую
        - Сохраняем partial_result даже при fallback

        Args:
            prompt: Текст запроса
            model: Основная (тяжёлая) модель
            fallback_model: Резервная (лёгкая) модель
            timeout_override: Переопределение таймаутов
            system_prompt: Системный промпт

        Returns:
            Tuple[result, metrics]: Результат и метрики вызова
        """
        try:
            result = self.generate(prompt, model, timeout_override, system_prompt)
            metrics = self._async_client.call_history[-1] if self._async_client.call_history else GenerationMetrics()
            return result, metrics

        except (IdleTimeoutError, TTFTTimeoutError, AbsoluteTimeoutError) as e:
            # Сохраняем partial result от первой попытки
            partial_from_heavy = e.partial_result

            if fallback_model and fallback_model != model:
                print(f"[FALLBACK] {model} timeout → trying {fallback_model}")

                try:
                    # Fallback модель - увеличенные таймауты для CPU
                    # На CPU даже 3B модель может требовать 20-30 сек на prefill
                    fallback_config = TimeoutConfig(
                        ttft_timeout=45,   # Достаточно для CPU prefill
                        idle_timeout=20,   # Между токенами
                        absolute_max=timeout_override.absolute_max if timeout_override else 180
                    )

                    result = self.generate(prompt, fallback_model, fallback_config, system_prompt)
                    metrics = self._async_client.call_history[-1] if self._async_client.call_history else GenerationMetrics()
                    metrics.timeout_reason = f"fallback_from_{model}"

                    # Если есть partial от тяжёлой модели, можно использовать
                    # (опционально — для анализа)
                    return result, metrics

                except LLMTimeoutError as fallback_error:
                    # Даже fallback не помог — возвращаем что есть
                    print(f"[FALLBACK FAILED] {fallback_model} also timed out")

                    # Объединяем partial results
                    combined_partial = partial_from_heavy or fallback_error.partial_result
                    fallback_error.metrics.partial_result = combined_partial
                    raise fallback_error

            # Нет fallback модели — пробрасываем исходное исключение
            raise

    def generate_safe(
        self,
        prompt: str,
        model: str,
        fallback_model: str = None,
        timeout_override: TimeoutConfig = None,
        system_prompt: str = None,
        default_on_error: str = ""
    ) -> Tuple[str, GenerationMetrics, Optional[Exception]]:
        """
        Безопасная генерация — никогда не выбрасывает исключения.

        Возвращает результат, метрики и ошибку (если была).
        Всегда возвращает хотя бы partial_result или default_on_error.

        Args:
            prompt: Текст запроса
            model: Основная модель
            fallback_model: Резервная модель
            timeout_override: Переопределение таймаутов
            system_prompt: Системный промпт
            default_on_error: Значение по умолчанию при полной ошибке

        Returns:
            Tuple[result, metrics, error]: Результат, метрики, ошибка (или None)
        """
        try:
            result, metrics = self.generate_with_fallback(
                prompt, model, fallback_model, timeout_override, system_prompt
            )
            return result, metrics, None

        except LLMTimeoutError as e:
            # Возвращаем partial result
            result = e.partial_result or default_on_error
            return result, e.metrics, e

        except Exception as e:
            # Неожиданная ошибка
            metrics = GenerationMetrics(
                model=model,
                state=GenerationState.TIMED_OUT,
                timeout_reason=f"unexpected_error: {type(e).__name__}"
            )
            return default_on_error, metrics, e

    @property
    def history(self) -> list:
        """История вызовов для предиктивного уровня."""
        return self._async_client.call_history

    @property
    def config(self) -> TimeoutConfig:
        """Текущая конфигурация таймаутов."""
        return self._async_client.config

    @config.setter
    def config(self, value: TimeoutConfig):
        """Обновить конфигурацию таймаутов."""
        self._async_client.config = value

    def get_stats(self) -> Dict[str, Any]:
        """Статистика по вызовам."""
        return self._async_client.get_stats()

    def clear_history(self):
        """Очистить историю вызовов."""
        self._async_client.call_history.clear()


# ═══════════════════════════════════════════════════════════════════════════════
# CONVENIENCE FUNCTIONS
# ═══════════════════════════════════════════════════════════════════════════════

_default_client: Optional[TimeoutLLMClient] = None


def get_client(
    base_url: str = "http://localhost:11434",
    timeout_config: TimeoutConfig = None
) -> TimeoutLLMClient:
    """
    Получить или создать глобальный клиент.

    Использование:
        client = get_client()
        result = client.generate("Hello", "qwen2.5-coder:3b")
    """
    global _default_client
    if _default_client is None:
        _default_client = TimeoutLLMClient(base_url, timeout_config)
    return _default_client


def generate_with_timeout(
    prompt: str,
    model: str,
    ttft_timeout: float = 30,
    idle_timeout: float = 15,
    absolute_max: float = 300,
    fallback_model: str = None
) -> Tuple[str, GenerationMetrics]:
    """
    Удобная функция для генерации с настраиваемыми таймаутами.

    Использование:
        result, metrics = generate_with_timeout(
            "Write a function",
            "qwen2.5-coder:7b",
            ttft_timeout=45,
            fallback_model="qwen2.5-coder:3b"
        )
    """
    client = get_client()
    config = TimeoutConfig(
        ttft_timeout=ttft_timeout,
        idle_timeout=idle_timeout,
        absolute_max=absolute_max
    )
    return client.generate_with_fallback(
        prompt, model, fallback_model, timeout_override=config
    )


# ═══════════════════════════════════════════════════════════════════════════════
# ТЕСТ
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 60)
    print("TimeoutLLMClient Test (Sync)")
    print("=" * 60)

    client = TimeoutLLMClient(
        timeout_config=TimeoutConfig(
            ttft_timeout=30,
            idle_timeout=15,
            absolute_max=120
        )
    )

    prompt = "Write a Python function to check if a number is prime. Be brief."
    model = "qwen2.5-coder:3b"

    print(f"\nPrompt: {prompt}")
    print(f"Model: {model}")
    print(f"Config: {client.config}")

    # Test 1: Simple generate
    print("\n--- Test 1: Simple Generate ---")
    try:
        result = client.generate(prompt, model)
        print(f"Result:\n{result}")
    except LLMTimeoutError as e:
        print(f"Timeout: {e}")
        print(f"Partial: {e.partial_result[:100]}...")

    # Test 2: Generate with fallback
    print("\n--- Test 2: Generate with Fallback ---")
    result, metrics = client.generate_with_fallback(
        prompt=prompt,
        model="qwen2.5-coder:7b",
        fallback_model="qwen2.5-coder:3b"
    )
    print(f"Result:\n{result}")
    print(f"Metrics: {metrics.to_dict()}")

    # Test 3: Safe generate
    print("\n--- Test 3: Safe Generate ---")
    result, metrics, error = client.generate_safe(
        prompt=prompt,
        model=model,
        default_on_error="[Generation failed]"
    )
    print(f"Result: {result[:100]}...")
    print(f"Error: {error}")

    # Stats
    print(f"\n--- Stats ---")
    print(f"Stats: {client.get_stats()}")
