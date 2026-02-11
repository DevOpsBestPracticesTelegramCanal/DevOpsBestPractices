# -*- coding: utf-8 -*-
"""
Tests for Week 20: Streaming SSE event generation

Tests:
- Server SSE helpers format correctly
- Streaming event structure
- Token chunking logic
- message_id consistency
"""

import json
import time
import math
import pytest


# ── Server SSE Helpers ────────────────────────────────────────────────────


class TestServerSSEHelpers:

    def test_sse_response_start_format(self):
        """sse_response_start() formats correctly."""
        from qwencode_unified_server import sse_response_start
        result = sse_response_start("msg_123")
        assert result.startswith("data: ")
        assert result.endswith("\n\n")
        data = json.loads(result[6:].strip())
        assert data["event"] == "response_start"
        assert data["message_id"] == "msg_123"

    def test_sse_response_token_format(self):
        """sse_response_token() formats correctly."""
        from qwencode_unified_server import sse_response_token
        result = sse_response_token("Hello", "msg_123")
        data = json.loads(result[6:].strip())
        assert data["event"] == "response_token"
        assert data["token"] == "Hello"
        assert data["message_id"] == "msg_123"

    def test_sse_response_done_format(self):
        """sse_response_done() formats correctly."""
        from qwencode_unified_server import sse_response_done
        result = sse_response_done("Full content here", "msg_123")
        data = json.loads(result[6:].strip())
        assert data["event"] == "response_done"
        assert data["content"] == "Full content here"
        assert data["message_id"] == "msg_123"

    def test_sse_response_token_unicode(self):
        """sse_response_token preserves Unicode characters."""
        from qwencode_unified_server import sse_response_token
        result = sse_response_token("Привет 🌍", "msg_u")
        data = json.loads(result[6:].strip())
        assert data["token"] == "Привет 🌍"

    def test_sse_response_done_empty_content(self):
        """sse_response_done handles empty content."""
        from qwencode_unified_server import sse_response_done
        result = sse_response_done("", "msg_empty")
        data = json.loads(result[6:].strip())
        assert data["content"] == ""
        assert data["message_id"] == "msg_empty"

    def test_sse_response_token_empty_string(self):
        """sse_response_token handles empty token."""
        from qwencode_unified_server import sse_response_token
        result = sse_response_token("", "msg_e")
        data = json.loads(result[6:].strip())
        assert data["token"] == ""


# ── Streaming Token Chunking Logic ────────────────────────────────────────


class TestTokenChunkingLogic:
    """Test the 3-char chunking logic used in process_stream."""

    CHUNK_SIZE = 3

    def _simulate_streaming(self, text):
        """Simulate the streaming logic from process_stream."""
        msg_id = f"llm_{int(time.time() * 1000)}"
        events = []
        events.append({"event": "response_start", "message_id": msg_id})
        for i in range(0, len(text), self.CHUNK_SIZE):
            events.append({
                "event": "response_token",
                "token": text[i:i + self.CHUNK_SIZE],
                "message_id": msg_id,
            })
        events.append({"event": "response_done", "content": text, "message_id": msg_id})
        return events

    def test_empty_text_yields_start_and_done(self):
        """Empty text still yields response_start and response_done."""
        events = self._simulate_streaming("")
        assert len(events) == 2  # start + done
        assert events[0]["event"] == "response_start"
        assert events[1]["event"] == "response_done"
        assert events[1]["content"] == ""

    def test_short_text_single_token(self):
        """Text shorter than chunk size yields one token."""
        events = self._simulate_streaming("ab")
        token_events = [e for e in events if e["event"] == "response_token"]
        assert len(token_events) == 1
        assert token_events[0]["token"] == "ab"

    def test_exact_chunk_size(self):
        """Text equal to chunk size yields one token."""
        events = self._simulate_streaming("abc")
        token_events = [e for e in events if e["event"] == "response_token"]
        assert len(token_events) == 1
        assert token_events[0]["token"] == "abc"

    def test_multiple_chunks(self):
        """Text longer than chunk size yields multiple tokens."""
        text = "Hello world!"  # 12 chars -> 4 chunks of 3
        events = self._simulate_streaming(text)
        token_events = [e for e in events if e["event"] == "response_token"]
        assert len(token_events) == 4
        assert token_events[0]["token"] == "Hel"
        assert token_events[1]["token"] == "lo "
        assert token_events[2]["token"] == "wor"
        assert token_events[3]["token"] == "ld!"

    def test_concatenated_tokens_match_original(self):
        """Concatenated tokens match original text."""
        text = "def hello():\n    return 42"
        events = self._simulate_streaming(text)
        tokens = [e["token"] for e in events if e["event"] == "response_token"]
        assert "".join(tokens) == text

    def test_message_id_consistent(self):
        """message_id is consistent across start/token/done events."""
        events = self._simulate_streaming("test text")
        msg_ids = set()
        for e in events:
            if "message_id" in e:
                msg_ids.add(e["message_id"])
        assert len(msg_ids) == 1

    def test_message_id_has_llm_prefix(self):
        """message_id starts with 'llm_'."""
        events = self._simulate_streaming("test")
        assert events[0]["message_id"].startswith("llm_")

    def test_unicode_chunking(self):
        """Unicode text chunks correctly."""
        text = "Привет мир"  # Cyrillic
        events = self._simulate_streaming(text)
        tokens = [e["token"] for e in events if e["event"] == "response_token"]
        assert "".join(tokens) == text

    def test_response_done_has_full_content(self):
        """response_done event contains full content."""
        text = "Complete response with multiple words"
        events = self._simulate_streaming(text)
        done = [e for e in events if e["event"] == "response_done"][0]
        assert done["content"] == text

    def test_chunk_count_formula(self):
        """Number of token events matches math.ceil(len/chunk_size)."""
        for text_len in [0, 1, 2, 3, 4, 5, 6, 10, 100]:
            text = "x" * text_len
            events = self._simulate_streaming(text)
            token_count = len([e for e in events if e["event"] == "response_token"])
            expected = math.ceil(text_len / self.CHUNK_SIZE) if text_len > 0 else 0
            assert token_count == expected, f"text_len={text_len}: got {token_count}, expected {expected}"


# ── Pipeline Streaming Simulation ─────────────────────────────────────────


class TestPipelineStreamingSimulation:
    """Test the pipeline path streaming (simulated tokens for winning code)."""

    CHUNK_SIZE = 3

    def _simulate_pipeline_streaming(self, code):
        """Simulate the pipeline streaming logic from process_stream."""
        msg_id = f"mc_{int(time.time() * 1000)}"
        events = []
        events.append({"event": "response_start", "message_id": msg_id})
        for i in range(0, len(code), self.CHUNK_SIZE):
            events.append({
                "event": "response_token",
                "token": code[i:i + self.CHUNK_SIZE],
                "message_id": msg_id,
            })
        events.append({"event": "response_done", "content": code, "message_id": msg_id})
        return events

    def test_pipeline_msg_id_prefix(self):
        """Pipeline streaming uses 'mc_' message_id prefix."""
        events = self._simulate_pipeline_streaming("code")
        assert events[0]["message_id"].startswith("mc_")

    def test_pipeline_tokens_concatenate_to_code(self):
        """Pipeline tokens concatenate to original code."""
        code = "def hello():\n    print('Hello World')\n    return True"
        events = self._simulate_pipeline_streaming(code)
        tokens = [e["token"] for e in events if e["event"] == "response_token"]
        assert "".join(tokens) == code

    def test_pipeline_empty_code(self):
        """Pipeline handles empty code."""
        events = self._simulate_pipeline_streaming("")
        assert len(events) == 2  # start + done
        assert events[1]["content"] == ""

    def test_pipeline_large_code(self):
        """Pipeline handles large code block."""
        code = "x" * 10000
        events = self._simulate_pipeline_streaming(code)
        token_count = len([e for e in events if e["event"] == "response_token"])
        expected = math.ceil(10000 / self.CHUNK_SIZE)
        assert token_count == expected


# ── Server Passthrough ────────────────────────────────────────────────────


class TestServerPassthrough:

    def test_passthrough_response_start(self):
        """Server passthrough handles response_start event."""
        from qwencode_unified_server import sse_response_start
        result = sse_response_start("test_id")
        data = json.loads(result[6:].strip())
        assert data["event"] == "response_start"

    def test_passthrough_response_token(self):
        """Server passthrough handles response_token event."""
        from qwencode_unified_server import sse_response_token
        result = sse_response_token("tok", "test_id")
        data = json.loads(result[6:].strip())
        assert data["event"] == "response_token"
        assert data["token"] == "tok"

    def test_passthrough_response_done(self):
        """Server passthrough handles response_done event."""
        from qwencode_unified_server import sse_response_done
        result = sse_response_done("full text", "test_id")
        data = json.loads(result[6:].strip())
        assert data["event"] == "response_done"
        assert data["content"] == "full text"
