"""
LLM Adapter — bridges existing LLM clients to the MultiCandidateGenerator.

The generator expects an async interface with temperature/seed support.
This adapter wraps either:
  - StreamingLLMClient (async, preferred)
  - TimeoutLLMClient (sync, runs in threadpool)

Usage:
    from core.streaming_llm_client import StreamingLLMClient
    from core.generation.llm_adapter import AsyncLLMAdapter

    async_client = StreamingLLMClient("http://localhost:11434")
    adapter = AsyncLLMAdapter(async_client, model="qwen2.5-coder:7b")
    # adapter now satisfies LLMProtocol for MultiCandidateGenerator
"""

import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class AsyncLLMAdapter:
    """
    Adapts StreamingLLMClient or TimeoutLLMClient to LLMProtocol.

    LLMProtocol requires:
        model_name: str
        async def generate(prompt, system, temperature, seed) -> str
    """

    def __init__(
        self,
        client,
        model: str = "qwen2.5-coder:7b",
        timeout_config=None,
    ):
        """
        Args:
            client: StreamingLLMClient (async) or TimeoutLLMClient (sync).
            model: Ollama model name to use for generation.
            timeout_config: Optional TimeoutConfig override per-call.
        """
        self._client = client
        self._model = model
        self._timeout_config = timeout_config
        self._is_async = hasattr(client, "generate_stream")  # StreamingLLMClient

    @property
    def model_name(self) -> str:
        return self._model

    async def generate(
        self,
        prompt: str,
        system: str,
        temperature: float,
        seed: int,
    ) -> str:
        """
        Generate code via Ollama with explicit temperature and seed.

        Maps to Ollama's `options` field in the request body.
        """
        options = {"temperature": temperature, "seed": seed}

        if self._is_async:
            return await self._client.generate(
                prompt=prompt,
                model=self._model,
                timeout_override=self._timeout_config,
                system_prompt=system,
                options=options,
            )
        else:
            # Sync client — run in threadpool to avoid blocking event loop
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(
                None,
                lambda: self._client.generate(
                    prompt=prompt,
                    model=self._model,
                    timeout_override=self._timeout_config,
                    system_prompt=system,
                    options=options,
                ),
            )
