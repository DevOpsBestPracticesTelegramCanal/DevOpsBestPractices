"""Tests for AsyncLLMAdapter."""

import asyncio
import pytest

from core.generation.llm_adapter import AsyncLLMAdapter


class FakeAsyncClient:
    """Mimics StreamingLLMClient with generate_stream + generate."""

    def __init__(self):
        self.calls = []

    async def generate_stream(self, *args, **kwargs):
        yield "hello"

    async def generate(self, prompt, model, timeout_override=None,
                       system_prompt=None, options=None):
        self.calls.append({
            "prompt": prompt,
            "model": model,
            "system_prompt": system_prompt,
            "options": options,
        })
        return f"response for temp={options.get('temperature')}"


class FakeSyncClient:
    """Mimics TimeoutLLMClient (no generate_stream)."""

    def __init__(self):
        self.calls = []

    def generate(self, prompt, model, timeout_override=None,
                 system_prompt=None, options=None):
        self.calls.append({
            "prompt": prompt,
            "model": model,
            "options": options,
        })
        return f"sync response"


class TestAsyncLLMAdapter:

    async def test_model_name(self):
        adapter = AsyncLLMAdapter(FakeAsyncClient(), model="test-7b")
        assert adapter.model_name == "test-7b"

    async def test_async_client_passthrough(self):
        client = FakeAsyncClient()
        adapter = AsyncLLMAdapter(client, model="qwen-7b")

        result = await adapter.generate(
            prompt="hello",
            system="you are helpful",
            temperature=0.5,
            seed=42,
        )

        assert "temp=0.5" in result
        assert len(client.calls) == 1
        assert client.calls[0]["model"] == "qwen-7b"
        assert client.calls[0]["options"] == {"temperature": 0.5, "seed": 42}
        assert client.calls[0]["system_prompt"] == "you are helpful"

    async def test_sync_client_in_threadpool(self):
        client = FakeSyncClient()
        adapter = AsyncLLMAdapter(client, model="qwen-3b")

        result = await adapter.generate(
            prompt="hello",
            system="sys",
            temperature=0.8,
            seed=100,
        )

        assert result == "sync response"
        assert len(client.calls) == 1
        assert client.calls[0]["options"] == {"temperature": 0.8, "seed": 100}

    async def test_detects_async_client(self):
        adapter = AsyncLLMAdapter(FakeAsyncClient())
        assert adapter._is_async is True

    async def test_detects_sync_client(self):
        adapter = AsyncLLMAdapter(FakeSyncClient())
        assert adapter._is_async is False
