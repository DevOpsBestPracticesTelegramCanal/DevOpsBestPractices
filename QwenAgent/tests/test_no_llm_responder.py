# -*- coding: utf-8 -*-
"""
Tests for core/no_llm_responder.py — NoLLMResponder stub, ResponseType, NoLLMResponse.
"""

import pytest
from core.no_llm_responder import ResponseType, NoLLMResponse, NoLLMResponder


# ── ResponseType Enum ────────────────────────────────────────────────────


class TestResponseType:
    def test_cached(self):
        assert ResponseType.CACHED.value == "cached"

    def test_pattern(self):
        assert ResponseType.PATTERN.value == "pattern"

    def test_math(self):
        assert ResponseType.MATH.value == "math"

    def test_greeting(self):
        assert ResponseType.GREETING.value == "greeting"

    def test_enum_count(self):
        assert len(ResponseType) == 4


# ── NoLLMResponse Dataclass ──────────────────────────────────────────────


class TestNoLLMResponse:
    def test_default_success_false(self):
        r = NoLLMResponse()
        assert r.success is False

    def test_default_response_empty(self):
        r = NoLLMResponse()
        assert r.response == ""

    def test_default_confidence_zero(self):
        r = NoLLMResponse()
        assert r.confidence == 0.0

    def test_default_type_pattern(self):
        r = NoLLMResponse()
        assert r.response_type == ResponseType.PATTERN

    def test_custom_values(self):
        r = NoLLMResponse(success=True, response="hello", confidence=0.95,
                          response_type=ResponseType.GREETING)
        assert r.success is True
        assert r.response == "hello"
        assert r.confidence == 0.95
        assert r.response_type == ResponseType.GREETING


# ── NoLLMResponder Stub ──────────────────────────────────────────────────


class TestNoLLMResponder:
    def test_init_no_cache(self):
        r = NoLLMResponder()
        assert r.solution_cache is None

    def test_init_with_cache(self):
        cache = object()
        r = NoLLMResponder(solution_cache=cache)
        assert r.solution_cache is cache

    def test_try_respond_returns_failure(self):
        r = NoLLMResponder()
        result = r.try_respond("hello")
        assert isinstance(result, NoLLMResponse)
        assert result.success is False

    def test_try_respond_with_context(self):
        r = NoLLMResponder()
        result = r.try_respond("test", context={"key": "val"})
        assert result.success is False

    def test_process_returns_none(self):
        r = NoLLMResponder()
        assert r.process("any query") is None

    def test_process_empty_query(self):
        r = NoLLMResponder()
        assert r.process("") is None
