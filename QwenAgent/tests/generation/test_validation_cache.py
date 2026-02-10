"""
Tests for Week 19: Validation Result Cache.

Covers:
- ValidationCache class (LRU, thread-safety, key generation)
- Serialization/deserialization round-trip
- Integration with _validate_single_candidate and _validate_pool
- PipelineConfig / ValidationStats cache fields
- Backward compatibility
"""

import asyncio
import threading
import time
import pytest
from unittest.mock import MagicMock

from code_validator.rules.base import Rule, RuleResult, RuleRunner, RuleSeverity
from core.generation.candidate import (
    Candidate,
    CandidatePool,
    CandidateStatus,
    ValidationScore,
)
from core.generation.pipeline import (
    MultiCandidatePipeline,
    PipelineConfig,
    PipelineResult,
    ValidationCache,
    ValidationStats,
    _serialize_rule_results,
    _deserialize_rule_results,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

GOOD_CODE = (
    'def fibonacci(n: int) -> int:\n'
    '    """Return nth Fibonacci number."""\n'
    '    if n <= 1:\n'
    '        return n\n'
    '    a, b = 0, 1\n'
    '    for _ in range(2, n + 1):\n'
    '        a, b = b, a + b\n'
    '    return b\n'
)

BAD_CODE = 'def foo(:\n  pass\n'

ANOTHER_CODE = (
    'def factorial(n: int) -> int:\n'
    '    """Return n factorial."""\n'
    '    if n <= 1:\n'
    '        return 1\n'
    '    return n * factorial(n - 1)\n'
)


class CountingRule(Rule):
    """Rule that counts how many times check() is called."""

    name = "counting_rule"
    severity = RuleSeverity.INFO

    def __init__(self):
        self._count = 0
        self._lock = threading.Lock()

    @property
    def call_count(self):
        with self._lock:
            return self._count

    def check(self, code: str) -> RuleResult:
        with self._lock:
            self._count += 1
        return self._ok(score=0.9, messages=["counted"])


class FailingRule(Rule):
    """Rule that always fails with a specific message."""

    name = "failing_rule"
    severity = RuleSeverity.ERROR

    def check(self, code: str) -> RuleResult:
        return self._fail(score=0.2, messages=["syntax error found"])


class SlowRule(Rule):
    """Rule that sleeps to simulate work."""

    name = "slow_rule"
    severity = RuleSeverity.INFO

    def __init__(self, delay: float = 0.1):
        self.delay = delay

    def check(self, code: str) -> RuleResult:
        time.sleep(self.delay)
        return self._ok(score=1.0)


class MockLLM:
    """Minimal mock LLM for pipeline integration tests."""

    model_name = "mock-7b"

    def __init__(self):
        self.call_count = 0

    async def generate(self, prompt, system, temperature, seed):
        self.call_count += 1
        await asyncio.sleep(0.01)
        return GOOD_CODE


def _make_candidate(cid: int, code: str = GOOD_CODE) -> Candidate:
    return Candidate(
        id=cid,
        task_id="test",
        code=code,
        temperature=0.2,
        seed=42,
        model="mock",
    )


def _make_pool(n: int = 2, code: str = GOOD_CODE) -> CandidatePool:
    pool = CandidatePool(task_id="test")
    for i in range(n):
        pool.add(_make_candidate(i, code))
    return pool


# ===========================================================================
# TestValidationCacheUnit
# ===========================================================================

class TestValidationCacheUnit:
    """Unit tests for ValidationCache: key gen, put/get, LRU, stats, clear."""

    def test_make_key_deterministic(self):
        """Same code + rules always produce the same key."""
        cache = ValidationCache()
        key1 = cache._make_key("print(1)", ["rule_a", "rule_b"])
        key2 = cache._make_key("print(1)", ["rule_a", "rule_b"])
        assert key1 == key2

    def test_different_code_different_key(self):
        """Different code produces a different cache key."""
        cache = ValidationCache()
        key1 = cache._make_key("print(1)", ["rule_a"])
        key2 = cache._make_key("print(2)", ["rule_a"])
        assert key1 != key2

    def test_different_rules_different_key(self):
        """Different rule sets produce a different cache key."""
        cache = ValidationCache()
        key1 = cache._make_key("print(1)", ["rule_a"])
        key2 = cache._make_key("print(1)", ["rule_b"])
        assert key1 != key2

    def test_rule_order_independent(self):
        """Rule names are sorted, so order doesn't matter."""
        cache = ValidationCache()
        key1 = cache._make_key("x = 1", ["rule_b", "rule_a"])
        key2 = cache._make_key("x = 1", ["rule_a", "rule_b"])
        assert key1 == key2

    def test_put_and_get(self):
        """Put a value, get it back."""
        cache = ValidationCache()
        data = [{"rule_name": "r", "passed": True, "score": 1.0}]
        cache.put("code", ["r"], data)

        result = cache.get("code", ["r"])
        assert result == data

    def test_get_miss(self):
        """get() returns None for unknown key."""
        cache = ValidationCache()
        assert cache.get("unknown", ["r"]) is None

    def test_lru_eviction(self):
        """When max_size is exceeded, oldest entry is evicted."""
        cache = ValidationCache(max_size=2)
        cache.put("code_a", ["r"], [{"a": 1}])
        cache.put("code_b", ["r"], [{"b": 2}])
        cache.put("code_c", ["r"], [{"c": 3}])  # should evict code_a

        assert cache.get("code_a", ["r"]) is None  # evicted
        assert cache.get("code_b", ["r"]) is not None
        assert cache.get("code_c", ["r"]) is not None

    def test_get_stats(self):
        """get_stats returns correct counters."""
        cache = ValidationCache(max_size=10)
        cache.put("code", ["r"], [{"x": 1}])
        cache.get("code", ["r"])   # hit
        cache.get("code", ["r"])   # hit
        cache.get("other", ["r"])  # miss

        stats = cache.get_stats()
        assert stats["cache_size"] == 1
        assert stats["max_size"] == 10
        assert stats["cache_hits"] == 2
        assert stats["cache_misses"] == 1
        assert stats["hit_rate_percent"] == pytest.approx(66.7, abs=0.1)

    def test_clear(self):
        """clear() empties cache and resets counters."""
        cache = ValidationCache()
        cache.put("code", ["r"], [{"x": 1}])
        cache.get("code", ["r"])  # hit
        cache.clear()

        assert cache.get("code", ["r"]) is None
        stats = cache.get_stats()
        assert stats["cache_size"] == 0
        assert stats["cache_hits"] == 0
        # The miss from the get after clear counts
        assert stats["cache_misses"] == 1


# ===========================================================================
# TestValidationCacheThreadSafety
# ===========================================================================

class TestValidationCacheThreadSafety:
    """Thread-safety under concurrent access."""

    def test_concurrent_puts(self):
        """Many threads writing to cache simultaneously doesn't crash."""
        cache = ValidationCache(max_size=50)
        errors = []

        def writer(tid):
            try:
                for i in range(20):
                    cache.put(f"code_{tid}_{i}", ["r"], [{"tid": tid, "i": i}])
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        stats = cache.get_stats()
        assert stats["cache_size"] <= 50  # respects max_size

    def test_concurrent_get_and_put(self):
        """Mixed reads and writes from multiple threads."""
        cache = ValidationCache(max_size=100)
        cache.put("shared", ["r"], [{"shared": True}])
        errors = []

        def reader():
            try:
                for _ in range(50):
                    cache.get("shared", ["r"])
            except Exception as e:
                errors.append(e)

        def writer(tid):
            try:
                for i in range(50):
                    cache.put(f"w_{tid}_{i}", ["r"], [{"w": i}])
            except Exception as e:
                errors.append(e)

        threads = (
            [threading.Thread(target=reader) for _ in range(5)]
            + [threading.Thread(target=writer, args=(t,)) for t in range(5)]
        )
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0


# ===========================================================================
# TestSerializationRoundtrip
# ===========================================================================

class TestSerializationRoundtrip:
    """_serialize_rule_results / _deserialize_rule_results fidelity."""

    def test_roundtrip_preserves_fields(self):
        """Serialize then deserialize produces equivalent RuleResults."""
        originals = [
            RuleResult(
                rule_name="syntax",
                passed=True,
                score=0.95,
                severity=RuleSeverity.INFO,
                messages=["all good"],
                duration=0.123,
            ),
            RuleResult(
                rule_name="lint",
                passed=False,
                score=0.3,
                severity=RuleSeverity.ERROR,
                messages=["line too long", "missing import"],
                duration=0.456,
            ),
        ]

        serialized = _serialize_rule_results(originals)
        deserialized = _deserialize_rule_results(serialized)

        assert len(deserialized) == 2
        for orig, deser in zip(originals, deserialized):
            assert deser.rule_name == orig.rule_name
            assert deser.passed == orig.passed
            assert deser.score == orig.score
            assert deser.severity == orig.severity
            assert deser.messages == orig.messages

    def test_duration_zero_on_deserialize(self):
        """Deserialized results have duration=0.0 (instant cache retrieval)."""
        originals = [
            RuleResult(
                rule_name="check",
                passed=True,
                score=1.0,
                severity=RuleSeverity.INFO,
                messages=[],
                duration=5.678,
            ),
        ]

        deserialized = _deserialize_rule_results(_serialize_rule_results(originals))
        assert deserialized[0].duration == 0.0

    def test_severity_preserved(self):
        """All severity levels survive serialization."""
        for sev in RuleSeverity:
            original = RuleResult(
                rule_name="test",
                passed=True,
                score=1.0,
                severity=sev,
                messages=[],
            )
            roundtripped = _deserialize_rule_results(
                _serialize_rule_results([original])
            )[0]
            assert roundtripped.severity == sev


# ===========================================================================
# TestCacheIntegration
# ===========================================================================

class TestCacheIntegration:
    """Cache integrated into _validate_single_candidate and _validate_pool."""

    def test_first_validation_is_miss(self):
        """First validation of a candidate is a cache miss."""
        rule = CountingRule()
        config = PipelineConfig(
            n_candidates=1,
            validation_cache_enabled=True,
            fail_fast_validation=False,
        )
        pipeline = MultiCandidatePipeline(MockLLM(), config=config, rules=[rule])
        pool = _make_pool(1)

        stats = pipeline._validate_pool(pool, fail_fast=False)

        assert rule.call_count == 1
        assert stats.cache_misses == 1
        assert stats.cache_hits == 0

    def test_second_same_code_is_hit(self):
        """Re-validating the same code skips actual validation (cache hit)."""
        rule = CountingRule()
        config = PipelineConfig(
            n_candidates=1,
            validation_cache_enabled=True,
            fail_fast_validation=False,
        )
        pipeline = MultiCandidatePipeline(MockLLM(), config=config, rules=[rule])

        # First validation
        pool1 = _make_pool(1)
        pipeline._validate_pool(pool1, fail_fast=False)
        assert rule.call_count == 1

        # Second validation with same code
        pool2 = _make_pool(1)
        stats = pipeline._validate_pool(pool2, fail_fast=False)

        assert rule.call_count == 1  # NOT called again
        assert stats.cache_hits == 1
        assert stats.cache_misses == 0

    def test_different_code_is_miss(self):
        """Different code causes a cache miss."""
        rule = CountingRule()
        config = PipelineConfig(
            n_candidates=1,
            validation_cache_enabled=True,
            fail_fast_validation=False,
        )
        pipeline = MultiCandidatePipeline(MockLLM(), config=config, rules=[rule])

        pool1 = _make_pool(1, code=GOOD_CODE)
        pipeline._validate_pool(pool1, fail_fast=False)

        pool2 = _make_pool(1, code=ANOTHER_CODE)
        stats = pipeline._validate_pool(pool2, fail_fast=False)

        assert rule.call_count == 2  # called for both
        assert stats.cache_hits == 0
        assert stats.cache_misses == 1

    def test_cached_scores_match_original(self):
        """Cached validation produces the same scores as fresh validation."""
        rule = CountingRule()
        config = PipelineConfig(
            n_candidates=1,
            validation_cache_enabled=True,
            fail_fast_validation=False,
        )
        pipeline = MultiCandidatePipeline(MockLLM(), config=config, rules=[rule])

        # First run
        pool1 = _make_pool(1)
        pipeline._validate_pool(pool1, fail_fast=False)
        original_scores = [
            (vs.validator_name, vs.passed, vs.score)
            for vs in pool1.candidates[0].validation_scores
        ]

        # Second run (cached)
        pool2 = _make_pool(1)
        pipeline._validate_pool(pool2, fail_fast=False)
        cached_scores = [
            (vs.validator_name, vs.passed, vs.score)
            for vs in pool2.candidates[0].validation_scores
        ]

        assert original_scores == cached_scores

    def test_parallel_pool_identical_candidates_uses_cache(self):
        """Parallel pool with identical code: first candidate is miss, rest are hits."""
        rule = CountingRule()
        config = PipelineConfig(
            n_candidates=3,
            parallel_candidate_validation=False,  # sequential for deterministic order
            fail_fast_validation=False,
            validation_cache_enabled=True,
        )
        pipeline = MultiCandidatePipeline(MockLLM(), config=config, rules=[rule])
        pool = _make_pool(3, code=GOOD_CODE)  # all same code

        stats = pipeline._validate_pool(pool, fail_fast=False)

        # Only the first candidate should trigger actual validation
        assert rule.call_count == 1
        assert stats.cache_hits == 2
        assert stats.cache_misses == 1


# ===========================================================================
# TestPipelineConfigCache
# ===========================================================================

class TestPipelineConfigCache:
    """PipelineConfig cache-related fields (Week 19)."""

    def test_defaults(self):
        config = PipelineConfig()
        assert config.validation_cache_enabled is True
        assert config.max_validation_cache_size == 256

    def test_disabled_means_no_cache(self):
        """When validation_cache_enabled=False, pipeline has no cache."""
        config = PipelineConfig(validation_cache_enabled=False)
        pipeline = MultiCandidatePipeline(MockLLM(), config=config)
        assert pipeline._validation_cache is None


# ===========================================================================
# TestValidationStatsCache
# ===========================================================================

class TestValidationStatsCache:
    """ValidationStats cache_hits / cache_misses fields (Week 19)."""

    def test_new_fields_exist(self):
        stats = ValidationStats()
        assert stats.cache_hits == 0
        assert stats.cache_misses == 0

    def test_in_to_dict(self):
        stats = ValidationStats(cache_hits=5, cache_misses=3)
        d = stats.to_dict()
        assert d["cache_hits"] == 5
        assert d["cache_misses"] == 3


# ===========================================================================
# TestBackwardCompatibility
# ===========================================================================

class TestBackwardCompatibility:
    """Ensure cache doesn't break existing callers."""

    @pytest.mark.asyncio
    async def test_default_pipeline_works(self):
        """Default config (cache enabled) still works end-to-end."""
        pipeline = MultiCandidatePipeline(MockLLM())
        result = await pipeline.run(query="Write fibonacci")
        assert result.best is not None
        assert len(result.code) > 0

    def test_cache_disabled_works(self):
        """Pipeline with cache disabled validates correctly."""
        rule = CountingRule()
        config = PipelineConfig(
            n_candidates=1,
            validation_cache_enabled=False,
            fail_fast_validation=False,
        )
        pipeline = MultiCandidatePipeline(MockLLM(), config=config, rules=[rule])
        pool = _make_pool(1)

        stats = pipeline._validate_pool(pool, fail_fast=False)

        assert rule.call_count == 1
        assert stats.cache_hits == 0
        assert stats.cache_misses == 0
        for c in pool.candidates:
            assert c.status == CandidateStatus.VALIDATED

    def test_stats_default_zeros(self):
        """ValidationStats cache fields default to zero."""
        stats = ValidationStats()
        d = stats.to_dict()
        assert d["cache_hits"] == 0
        assert d["cache_misses"] == 0
