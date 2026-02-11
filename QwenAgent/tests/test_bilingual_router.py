# -*- coding: utf-8 -*-
"""
Tests for core/bilingual_context_router.py — BilingualContextRouter stub.
"""

import pytest
from core.bilingual_context_router import BilingualContextRouter


class TestBilingualContextRouterInit:
    def test_default_tier1_5_disabled(self):
        r = BilingualContextRouter()
        assert r.enable_tier1_5 is False

    def test_enable_tier1_5(self):
        r = BilingualContextRouter(enable_tier1_5=True)
        assert r.enable_tier1_5 is True


class TestBilingualContextRouterRoute:
    def test_route_returns_dict(self):
        r = BilingualContextRouter()
        result = r.route("hello")
        assert isinstance(result, dict)

    def test_route_tool_none(self):
        r = BilingualContextRouter()
        assert r.route("any query")["tool"] is None

    def test_route_tier_4(self):
        r = BilingualContextRouter()
        assert r.route("query")["tier"] == 4

    def test_route_confidence_zero(self):
        r = BilingualContextRouter()
        assert r.route("query")["confidence"] == 0.0

    def test_route_args_empty(self):
        r = BilingualContextRouter()
        assert r.route("query")["args"] == ""

    def test_route_has_all_keys(self):
        r = BilingualContextRouter()
        result = r.route("test")
        assert set(result.keys()) == {"tool", "args", "tier", "confidence"}


class TestBilingualContextRouterStats:
    def test_stats_returns_dict(self):
        r = BilingualContextRouter()
        stats = r.get_stats()
        assert isinstance(stats, dict)

    def test_stats_all_zeros(self):
        r = BilingualContextRouter()
        stats = r.get_stats()
        for key in ("total_requests", "tier0_hits", "tier1_hits", "tier2_hits",
                     "tier1_5_hits", "tier4_escalations"):
            assert stats[key] == 0

    def test_stats_rates_zero(self):
        r = BilingualContextRouter()
        stats = r.get_stats()
        assert stats["no_llm_rate"] == 0.0
        assert stats["escalation_rate"] == 0.0

    def test_stats_has_all_keys(self):
        r = BilingualContextRouter()
        expected_keys = {
            "total_requests", "tier0_hits", "tier1_hits", "tier2_hits",
            "tier1_5_hits", "tier4_escalations", "no_llm_rate", "escalation_rate",
        }
        assert set(r.get_stats().keys()) == expected_keys
