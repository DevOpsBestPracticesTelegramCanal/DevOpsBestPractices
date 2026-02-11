# -*- coding: utf-8 -*-
"""
Tests for core/solution_cache.py — SolutionCache SQLite-backed cache.
"""

import os
import time
import tempfile
import pytest
from core.solution_cache import SolutionCache, DEFAULT_TTL_SECONDS


@pytest.fixture
def cache(tmp_path):
    """Create a SolutionCache with a temporary database."""
    db_path = str(tmp_path / "test_cache.db")
    c = SolutionCache(db_path=db_path, ttl_seconds=3600)
    yield c
    c.close()


@pytest.fixture
def short_ttl_cache(tmp_path):
    """Cache with 1-second TTL for expiration tests."""
    db_path = str(tmp_path / "short_ttl.db")
    c = SolutionCache(db_path=db_path, ttl_seconds=1)
    yield c
    c.close()


# ── Init ─────────────────────────────────────────────────────────────────


class TestSolutionCacheInit:
    def test_db_created(self, cache, tmp_path):
        assert os.path.exists(str(tmp_path / "test_cache.db"))

    def test_initial_hits_zero(self, cache):
        assert cache._hits == 0

    def test_initial_misses_zero(self, cache):
        assert cache._misses == 0

    def test_connection_open(self, cache):
        assert cache._conn is not None

    def test_default_ttl(self):
        assert DEFAULT_TTL_SECONDS == 7 * 24 * 3600


# ── Hash ─────────────────────────────────────────────────────────────────


class TestHashError:
    def test_hash_deterministic(self):
        h1 = SolutionCache._hash_error("TypeError", "bad args")
        h2 = SolutionCache._hash_error("TypeError", "bad args")
        assert h1 == h2

    def test_hash_length_16(self):
        h = SolutionCache._hash_error("X", "Y")
        assert len(h) == 16

    def test_hash_case_insensitive(self):
        h1 = SolutionCache._hash_error("TypeError", "Msg")
        h2 = SolutionCache._hash_error("typeerror", "msg")
        assert h1 == h2

    def test_hash_strips_whitespace(self):
        h1 = SolutionCache._hash_error("TypeError", "msg")
        h2 = SolutionCache._hash_error("  TypeError  ", "  msg  ")
        assert h1 == h2

    def test_different_errors_different_hashes(self):
        h1 = SolutionCache._hash_error("TypeError", "msg1")
        h2 = SolutionCache._hash_error("ValueError", "msg2")
        assert h1 != h2


# ── Store & Lookup ───────────────────────────────────────────────────────


class TestStoreAndLookup:
    def test_store_returns_true(self, cache):
        assert cache.store("TypeError", "bad arg", solution="fix it") is True

    def test_lookup_finds_stored(self, cache):
        cache.store("TypeError", "bad arg", solution="fix it")
        result = cache.lookup("TypeError", "bad arg")
        assert result is not None
        assert result["solution"] == "fix it"

    def test_lookup_miss(self, cache):
        result = cache.lookup("TypeError", "nonexistent")
        assert result is None

    def test_lookup_increments_hit_count(self, cache):
        cache.store("TypeError", "msg", solution="sol")
        r1 = cache.lookup("TypeError", "msg")
        assert r1["hit_count"] == 1
        r2 = cache.lookup("TypeError", "msg")
        assert r2["hit_count"] == 2

    def test_store_empty_solution_returns_false(self, cache):
        assert cache.store("TypeError", "msg", solution="") is False

    def test_upsert_higher_confidence_wins(self, cache):
        cache.store("TypeError", "msg", solution="v1", confidence=0.5)
        cache.store("TypeError", "msg", solution="v2", confidence=0.9)
        result = cache.lookup("TypeError", "msg")
        assert result["confidence"] == 0.9
        assert result["solution"] == "v2"

    def test_upsert_lower_confidence_keeps_max(self, cache):
        cache.store("TypeError", "msg", solution="v1", confidence=0.9)
        cache.store("TypeError", "msg", solution="v2", confidence=0.3)
        result = cache.lookup("TypeError", "msg")
        assert result["confidence"] == 0.9

    def test_min_confidence_filter(self, cache):
        cache.store("TypeError", "msg", solution="sol", confidence=0.3)
        assert cache.lookup("TypeError", "msg", min_confidence=0.5) is None
        assert cache.lookup("TypeError", "msg", min_confidence=0.2) is not None


# ── TTL Expiration ───────────────────────────────────────────────────────


class TestTTLExpiration:
    def test_expired_entry_not_found(self, short_ttl_cache):
        short_ttl_cache.store("Err", "msg", solution="old")
        time.sleep(1.1)
        assert short_ttl_cache.lookup("Err", "msg") is None

    def test_cleanup_expired(self, short_ttl_cache):
        short_ttl_cache.store("Err", "msg", solution="old")
        time.sleep(1.1)
        removed = short_ttl_cache.cleanup_expired()
        assert removed >= 1

    def test_fresh_entry_survives_cleanup(self, cache):
        cache.store("Err", "msg", solution="fresh")
        removed = cache.cleanup_expired()
        assert removed == 0
        assert cache.lookup("Err", "msg") is not None


# ── Invalidate ───────────────────────────────────────────────────────────


class TestInvalidate:
    def test_invalidate_removes_entry(self, cache):
        cache.store("TypeError", "msg", solution="sol")
        assert cache.invalidate("TypeError", "msg") is True
        assert cache.lookup("TypeError", "msg") is None

    def test_invalidate_nonexistent(self, cache):
        assert cache.invalidate("Nope", "nothing") is True  # no error


# ── Backward Compat (get/save) ───────────────────────────────────────────


class TestBackwardCompat:
    def test_save_and_get(self, cache):
        cache.save("mykey", "myvalue")
        assert cache.get("mykey") == "myvalue"

    def test_get_miss(self, cache):
        assert cache.get("nonexistent") is None


# ── Boost Confidence ─────────────────────────────────────────────────────


class TestBoostConfidence:
    def test_boost_increases_confidence(self, cache):
        cache.store("Err", "msg", solution="sol", confidence=0.7)
        cache.boost_confidence("Err", "msg", boost=0.1)
        result = cache.lookup("Err", "msg")
        assert result["confidence"] == pytest.approx(0.8, abs=0.01)

    def test_boost_capped_at_1(self, cache):
        cache.store("Err", "msg", solution="sol", confidence=0.98)
        cache.boost_confidence("Err", "msg", boost=0.1)
        result = cache.lookup("Err", "msg")
        assert result["confidence"] <= 1.0


# ── Stats ────────────────────────────────────────────────────────────────


class TestCacheStats:
    def test_initial_stats(self, cache):
        stats = cache.get_stats()
        assert stats["total_solutions"] == 0
        assert stats["cache_hits"] == 0
        assert stats["cache_misses"] == 0
        assert stats["hit_rate_percent"] == 0.0

    def test_stats_after_operations(self, cache):
        cache.store("Err", "msg", solution="sol")
        cache.lookup("Err", "msg")  # hit
        cache.lookup("Err", "other")  # miss
        stats = cache.get_stats()
        assert stats["total_solutions"] == 1
        assert stats["cache_hits"] == 1
        assert stats["cache_misses"] == 1
        assert stats["hit_rate_percent"] == 50.0

    def test_stats_ttl(self, cache):
        assert cache.get_stats()["ttl_seconds"] == 3600

    def test_stats_db_path(self, cache, tmp_path):
        stats = cache.get_stats()
        assert "test_cache.db" in stats["db_path"]


# ── Close ────────────────────────────────────────────────────────────────


class TestClose:
    def test_close_sets_conn_none(self, tmp_path):
        db = str(tmp_path / "close_test.db")
        c = SolutionCache(db_path=db)
        c.close()
        assert c._conn is None

    def test_close_idempotent(self, tmp_path):
        db = str(tmp_path / "close_test.db")
        c = SolutionCache(db_path=db)
        c.close()
        c.close()  # should not raise
