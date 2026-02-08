# -*- coding: utf-8 -*-
"""
Tests for SolutionCache (core/solution_cache.py).

Tests cover:
- Store and lookup solutions
- TTL expiration
- Hit/miss statistics
- Confidence boosting
- Invalidation
- Backward-compatible get/save API
- Edge cases (empty DB, closed connection)
"""

import os
import sys
import tempfile
import time
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.solution_cache import SolutionCache


@pytest.fixture
def cache(tmp_path):
    """Fresh SolutionCache with temp database."""
    db_path = str(tmp_path / "test_cache.db")
    c = SolutionCache(db_path=db_path, ttl_seconds=3600)
    yield c
    c.close()


class TestStore:
    """Tests for storing solutions."""

    def test_store_returns_true(self, cache):
        result = cache.store(
            error_type="TypeError",
            error_msg="expected str got int",
            solution="def fix(): return str(x)",
        )
        assert result is True

    def test_store_empty_solution_returns_false(self, cache):
        result = cache.store(
            error_type="TypeError",
            error_msg="expected str got int",
            solution="",
        )
        assert result is False

    def test_store_with_all_fields(self, cache):
        result = cache.store(
            error_type="ImportError",
            error_msg="No module named requests",
            code_context="import requests",
            solution="pip install requests",
            swecas_category="IMPORT_ERROR",
            confidence=0.9,
        )
        assert result is True

    def test_upsert_keeps_higher_confidence(self, cache):
        cache.store(error_type="X", error_msg="Y", solution="sol1", confidence=0.5)
        cache.store(error_type="X", error_msg="Y", solution="sol2", confidence=0.9)

        result = cache.lookup("X", "Y")
        assert result is not None
        assert result["confidence"] == 0.9
        assert result["solution"] == "sol2"

    def test_upsert_does_not_lower_confidence(self, cache):
        cache.store(error_type="X", error_msg="Y", solution="sol1", confidence=0.9)
        cache.store(error_type="X", error_msg="Y", solution="sol2", confidence=0.5)

        result = cache.lookup("X", "Y")
        assert result is not None
        assert result["confidence"] == 0.9


class TestLookup:
    """Tests for looking up solutions."""

    def test_lookup_existing(self, cache):
        cache.store(error_type="TypeError", error_msg="bad type", solution="fix it")
        result = cache.lookup("TypeError", "bad type")
        assert result is not None
        assert result["solution"] == "fix it"

    def test_lookup_missing(self, cache):
        result = cache.lookup("TypeError", "nonexistent error")
        assert result is None

    def test_lookup_increments_hit_count(self, cache):
        cache.store(error_type="E", error_msg="M", solution="S")

        r1 = cache.lookup("E", "M")
        assert r1["hit_count"] == 1

        r2 = cache.lookup("E", "M")
        assert r2["hit_count"] == 2

    def test_lookup_min_confidence_filter(self, cache):
        cache.store(error_type="E", error_msg="M", solution="S", confidence=0.3)

        # Default min_confidence=0.5 → should not find
        result = cache.lookup("E", "M")
        assert result is None

        # Lower threshold → should find
        result = cache.lookup("E", "M", min_confidence=0.2)
        assert result is not None

    def test_lookup_returns_swecas_category(self, cache):
        cache.store(error_type="E", error_msg="M", solution="S", swecas_category="TYPE_ERROR")
        result = cache.lookup("E", "M")
        assert result["swecas_category"] == "TYPE_ERROR"


class TestTTL:
    """Tests for TTL expiration."""

    def test_expired_entry_not_returned(self):
        """Entry with 1-second TTL expires quickly."""
        with tempfile.TemporaryDirectory() as tmp:
            cache = SolutionCache(
                db_path=os.path.join(tmp, "ttl.db"),
                ttl_seconds=1,  # 1 second TTL
            )
            cache.store(error_type="E", error_msg="M", solution="S")

            # Immediately available
            assert cache.lookup("E", "M") is not None

            # Wait for expiration
            time.sleep(1.1)

            assert cache.lookup("E", "M") is None
            cache.close()

    def test_cleanup_expired(self):
        """cleanup_expired removes old entries."""
        with tempfile.TemporaryDirectory() as tmp:
            cache = SolutionCache(
                db_path=os.path.join(tmp, "cleanup.db"),
                ttl_seconds=1,
            )
            cache.store(error_type="E", error_msg="M", solution="S")
            time.sleep(1.1)

            removed = cache.cleanup_expired()
            assert removed >= 1
            cache.close()


class TestStats:
    """Tests for get_stats()."""

    def test_empty_stats(self, cache):
        stats = cache.get_stats()
        assert stats["total_solutions"] == 0
        assert stats["cache_hits"] == 0
        assert stats["cache_misses"] == 0
        assert stats["hit_rate_percent"] == 0.0

    def test_stats_after_store(self, cache):
        cache.store(error_type="E", error_msg="M", solution="S")
        stats = cache.get_stats()
        assert stats["total_solutions"] == 1

    def test_stats_hit_rate(self, cache):
        cache.store(error_type="E", error_msg="M", solution="S")

        cache.lookup("E", "M")       # hit
        cache.lookup("E", "missing")  # miss

        stats = cache.get_stats()
        assert stats["cache_hits"] == 1
        assert stats["cache_misses"] == 1
        assert stats["hit_rate_percent"] == 50.0

    def test_stats_has_required_keys(self, cache):
        """Stats has all keys expected by qwencode_agent.py."""
        stats = cache.get_stats()
        required = ["total_solutions", "cache_hits", "cache_misses", "hit_rate_percent"]
        for key in required:
            assert key in stats, f"Missing key: {key}"


class TestConfidence:
    """Tests for confidence boosting."""

    def test_boost_confidence(self, cache):
        cache.store(error_type="E", error_msg="M", solution="S", confidence=0.7)
        cache.boost_confidence("E", "M", boost=0.1)

        result = cache.lookup("E", "M")
        assert result["confidence"] == pytest.approx(0.8, abs=0.01)

    def test_confidence_capped_at_one(self, cache):
        cache.store(error_type="E", error_msg="M", solution="S", confidence=0.95)
        cache.boost_confidence("E", "M", boost=0.2)

        result = cache.lookup("E", "M")
        assert result["confidence"] <= 1.0


class TestInvalidate:
    """Tests for invalidation."""

    def test_invalidate_existing(self, cache):
        cache.store(error_type="E", error_msg="M", solution="S")
        assert cache.invalidate("E", "M") is True
        assert cache.lookup("E", "M") is None

    def test_invalidate_nonexistent(self, cache):
        result = cache.invalidate("E", "nonexistent")
        assert result is True  # DELETE succeeds even if no rows


class TestBackwardCompat:
    """Tests for backward-compatible get/save API."""

    def test_save_and_get(self, cache):
        cache.save("my_key", "my_value")
        result = cache.get("my_key")
        assert result == "my_value"

    def test_get_nonexistent(self, cache):
        assert cache.get("nonexistent") is None


class TestEdgeCases:
    """Edge case tests."""

    def test_hash_deterministic(self):
        h1 = SolutionCache._hash_error("TypeError", "bad type")
        h2 = SolutionCache._hash_error("TypeError", "bad type")
        assert h1 == h2

    def test_hash_case_insensitive(self):
        h1 = SolutionCache._hash_error("TypeError", "Bad Type")
        h2 = SolutionCache._hash_error("typeerror", "bad type")
        assert h1 == h2

    def test_multiple_error_types(self, cache):
        cache.store(error_type="TypeError", error_msg="msg", solution="fix1")
        cache.store(error_type="ImportError", error_msg="msg", solution="fix2")

        r1 = cache.lookup("TypeError", "msg")
        r2 = cache.lookup("ImportError", "msg")
        assert r1["solution"] == "fix1"
        assert r2["solution"] == "fix2"

    def test_unicode_error_messages(self, cache):
        cache.store(
            error_type="ValueError",
            error_msg="ошибка валидации данных",
            solution="проверить входные параметры",
        )
        result = cache.lookup("ValueError", "ошибка валидации данных")
        assert result is not None
        assert "проверить" in result["solution"]
