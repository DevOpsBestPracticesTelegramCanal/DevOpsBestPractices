# -*- coding: utf-8 -*-
"""
token_streamer.py — Async-to-sync bridge for token streaming
=============================================================

Week 20: Bridges the async StreamingLLMClient.generate_stream()
to a synchronous iterator using Thread + Queue.

Usage:
    streamer = SyncTokenStreamer(
        lambda: client.generate_stream(prompt, model)
    )
    for token in streamer:
        print(token, end="")
"""

import queue
import asyncio
import threading
from typing import Callable, Any, Iterator


_SENTINEL = object()  # Marks end of stream


class SyncTokenStreamer:
    """Bridge async token generator to sync iteration via Thread+Queue.

    The async generator runs in a dedicated thread with its own event loop.
    Tokens are pushed into a queue.Queue consumed by the sync caller.

    Args:
        async_gen_factory: Callable returning an async generator of str tokens.
        timeout: Max seconds to wait for each token (default 60).
        queue_size: Max buffered tokens before backpressure (default 256).
    """

    def __init__(self, async_gen_factory: Callable, timeout: float = 60,
                 queue_size: int = 256):
        self._factory = async_gen_factory
        self._timeout = timeout
        self._queue: queue.Queue = queue.Queue(maxsize=queue_size)
        self._thread: threading.Thread | None = None
        self._error: Exception | None = None
        self._done = False

    def __iter__(self) -> Iterator[str]:
        self._done = False
        self._error = None
        self._thread = threading.Thread(target=self._run_async, daemon=True)
        self._thread.start()
        try:
            while True:
                try:
                    item = self._queue.get(timeout=self._timeout)
                except queue.Empty:
                    raise TimeoutError(
                        f"SyncTokenStreamer: no token received in {self._timeout}s"
                    )
                if item is _SENTINEL:
                    break
                if isinstance(item, BaseException):
                    raise item
                yield item
        finally:
            self._done = True
            # Ensure thread finishes
            if self._thread and self._thread.is_alive():
                self._thread.join(timeout=2)

    def _run_async(self):
        """Run async generator in a new event loop on this thread."""
        async def _consume():
            try:
                async for token in self._factory():
                    if self._done:
                        break
                    self._queue.put(token)
            except Exception as e:
                self._queue.put(e)
            finally:
                self._queue.put(_SENTINEL)

        try:
            asyncio.run(_consume())
        except Exception as e:
            # If asyncio.run itself fails, push the error
            try:
                self._queue.put(e)
                self._queue.put(_SENTINEL)
            except Exception:
                pass


def create_token_streamer(
    streaming_client,
    prompt: str,
    model: str,
    system_prompt: str = None,
    timeout_override=None,
    timeout: float = 60,
) -> SyncTokenStreamer:
    """Convenience factory: create a SyncTokenStreamer for a StreamingLLMClient.

    Args:
        streaming_client: StreamingLLMClient instance with generate_stream().
        prompt: Full prompt text.
        model: Ollama model name.
        system_prompt: Optional system prompt.
        timeout_override: Optional TimeoutConfig override.
        timeout: Per-token timeout in seconds.

    Returns:
        SyncTokenStreamer ready for iteration.
    """
    def _factory():
        kwargs = {"prompt": prompt, "model": model}
        if system_prompt:
            kwargs["system_prompt"] = system_prompt
        if timeout_override:
            kwargs["timeout_override"] = timeout_override
        return streaming_client.generate_stream(**kwargs)

    return SyncTokenStreamer(_factory, timeout=timeout)
