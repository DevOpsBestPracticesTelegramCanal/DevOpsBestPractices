# -*- coding: utf-8 -*-
"""
Tests for core/token_streamer.py — Week 20: SyncTokenStreamer
"""

import asyncio
import queue
import time
import threading
import pytest

from core.token_streamer import SyncTokenStreamer, create_token_streamer, _SENTINEL


# ── Helpers ──────────────────────────────────────────────────────────────


async def _async_gen_tokens(tokens, delay=0):
    """Async generator yielding a list of tokens with optional delay."""
    for t in tokens:
        if delay:
            await asyncio.sleep(delay)
        yield t


def _make_factory(tokens, delay=0):
    """Create a factory callable returning async generator."""
    def factory():
        return _async_gen_tokens(tokens, delay)
    return factory


# ── Basic Functionality ──────────────────────────────────────────────────


class TestSyncTokenStreamerBasic:

    def test_yields_all_tokens(self):
        """SyncTokenStreamer yields all tokens from async generator."""
        tokens = ["Hello", " ", "world", "!"]
        streamer = SyncTokenStreamer(_make_factory(tokens))
        result = list(streamer)
        assert result == tokens

    def test_empty_generator(self):
        """Handles empty generator (0 tokens)."""
        streamer = SyncTokenStreamer(_make_factory([]))
        result = list(streamer)
        assert result == []

    def test_single_token(self):
        """Single token streams correctly."""
        streamer = SyncTokenStreamer(_make_factory(["only"]))
        result = list(streamer)
        assert result == ["only"]

    def test_unicode_tokens_preserved(self):
        """Unicode tokens preserved correctly."""
        tokens = ["Привет", " мир", "! 🌍", "日本語"]
        streamer = SyncTokenStreamer(_make_factory(tokens))
        result = list(streamer)
        assert result == tokens

    def test_large_token_count(self):
        """Large token count (1000+) streams correctly."""
        tokens = [f"token_{i}" for i in range(1200)]
        streamer = SyncTokenStreamer(_make_factory(tokens))
        result = list(streamer)
        assert len(result) == 1200
        assert result[0] == "token_0"
        assert result[-1] == "token_1199"

    def test_concatenated_output_matches(self):
        """Concatenated tokens match expected full text."""
        tokens = ["def ", "hello", "()", ":\n", "    pass"]
        streamer = SyncTokenStreamer(_make_factory(tokens))
        full = "".join(streamer)
        assert full == "def hello():\n    pass"

    def test_sentinel_not_leaked(self):
        """Sentinel object is never yielded to caller."""
        tokens = ["a", "b", "c"]
        streamer = SyncTokenStreamer(_make_factory(tokens))
        result = list(streamer)
        assert _SENTINEL not in result
        assert len(result) == 3


# ── Error Handling ───────────────────────────────────────────────────────


class TestSyncTokenStreamerErrors:

    def test_propagates_exception(self):
        """Propagates exceptions from async generator."""
        async def _failing_gen():
            yield "ok"
            raise ValueError("async boom")

        streamer = SyncTokenStreamer(lambda: _failing_gen())
        with pytest.raises(ValueError, match="async boom"):
            list(streamer)

    def test_propagates_runtime_error(self):
        """Propagates RuntimeError from async generator."""
        async def _runtime_gen():
            raise RuntimeError("runtime fail")
            yield "never"  # pragma: no cover

        streamer = SyncTokenStreamer(lambda: _runtime_gen())
        with pytest.raises(RuntimeError, match="runtime fail"):
            list(streamer)

    def test_partial_tokens_before_error(self):
        """Yields partial tokens before exception."""
        async def _partial_gen():
            yield "a"
            yield "b"
            raise ValueError("mid-stream error")

        streamer = SyncTokenStreamer(lambda: _partial_gen())
        collected = []
        with pytest.raises(ValueError, match="mid-stream error"):
            for t in streamer:
                collected.append(t)
        assert collected == ["a", "b"]

    def test_timeout_on_slow_generator(self):
        """Respects timeout — raises on slow generator."""
        async def _slow_gen():
            yield "start"
            await asyncio.sleep(10)  # Way longer than timeout
            yield "never"

        streamer = SyncTokenStreamer(lambda: _slow_gen(), timeout=0.5)
        collected = []
        with pytest.raises(TimeoutError):
            for t in streamer:
                collected.append(t)
        assert collected == ["start"]


# ── Threading / Lifecycle ────────────────────────────────────────────────


class TestSyncTokenStreamerThreading:

    def test_thread_terminates_after_iteration(self):
        """Thread terminates after iteration completes."""
        tokens = ["x", "y", "z"]
        streamer = SyncTokenStreamer(_make_factory(tokens))
        result = list(streamer)
        assert result == ["x", "y", "z"]
        # Thread should have joined/finished
        if streamer._thread:
            streamer._thread.join(timeout=3)
            assert not streamer._thread.is_alive()

    def test_multiple_sequential_uses(self):
        """Multiple sequential uses of same factory work."""
        factory = _make_factory(["a", "b"])
        # First iteration
        s1 = SyncTokenStreamer(factory)
        r1 = list(s1)
        assert r1 == ["a", "b"]
        # Second iteration with new instance
        s2 = SyncTokenStreamer(factory)
        r2 = list(s2)
        assert r2 == ["a", "b"]

    def test_queue_backpressure(self):
        """Queue backpressure with slow consumer."""
        # Small queue, many tokens
        tokens = [f"t{i}" for i in range(50)]
        streamer = SyncTokenStreamer(_make_factory(tokens), queue_size=4)
        result = list(streamer)
        assert len(result) == 50
        assert result[0] == "t0"
        assert result[-1] == "t49"

    def test_done_flag_set_on_early_exit(self):
        """The _done flag is set when consumer stops early."""
        async def _infinite_gen():
            i = 0
            while True:
                yield f"t{i}"
                i += 1
                await asyncio.sleep(0.001)

        streamer = SyncTokenStreamer(lambda: _infinite_gen(), timeout=2)
        collected = []
        for t in streamer:
            collected.append(t)
            if len(collected) >= 5:
                break
        assert len(collected) == 5


# ── Factory Function ─────────────────────────────────────────────────────


class TestCreateTokenStreamer:

    def test_create_with_mock_client(self):
        """create_token_streamer works with a mock streaming client."""

        class MockStreamingClient:
            async def generate_stream(self, prompt, model, **kwargs):
                for word in prompt.split():
                    yield word

        client = MockStreamingClient()
        streamer = create_token_streamer(
            streaming_client=client,
            prompt="hello world test",
            model="test-model",
        )
        result = list(streamer)
        assert result == ["hello", "world", "test"]

    def test_create_with_system_prompt(self):
        """create_token_streamer passes system_prompt correctly."""
        received_kwargs = {}

        class MockClient:
            async def generate_stream(self, **kwargs):
                received_kwargs.update(kwargs)
                yield "ok"

        client = MockClient()
        streamer = create_token_streamer(
            streaming_client=client,
            prompt="test",
            model="m",
            system_prompt="be helpful",
        )
        list(streamer)
        assert received_kwargs.get("system_prompt") == "be helpful"

    def test_create_with_timeout_override(self):
        """create_token_streamer passes timeout_override correctly."""
        received_kwargs = {}

        class MockClient:
            async def generate_stream(self, **kwargs):
                received_kwargs.update(kwargs)
                yield "ok"

        client = MockClient()
        streamer = create_token_streamer(
            streaming_client=client,
            prompt="test",
            model="m",
            timeout_override="custom_timeout",
        )
        list(streamer)
        assert received_kwargs.get("timeout_override") == "custom_timeout"
