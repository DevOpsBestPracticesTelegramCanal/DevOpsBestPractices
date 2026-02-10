"""
Tests for Week 18: Parallel Candidate Validation.

Covers:
- ValidationStats dataclass
- Parallel candidate validation in _validate_pool()
- max_validation_workers config
- RuleRunner max_workers parameter
- PipelineConfig / PipelineResult extensions
- Backward compatibility with existing callers
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
    ValidationStats,
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


class SlowRule(Rule):
    """Rule that sleeps to simulate work."""

    name = "slow_rule"
    severity = RuleSeverity.INFO

    def __init__(self, delay: float = 0.1):
        self.delay = delay

    def check(self, code: str) -> RuleResult:
        time.sleep(self.delay)
        return self._ok(score=1.0)


class CrashingRule(Rule):
    """Rule that always raises RuntimeError."""

    name = "crashing_rule"
    severity = RuleSeverity.CRITICAL

    def check(self, code: str) -> RuleResult:
        raise RuntimeError("validator crash")


class ConcurrencyTracker:
    """Thread-safe counter that tracks max concurrent executions."""

    def __init__(self):
        self._lock = threading.Lock()
        self._current = 0
        self.max_concurrent = 0

    def enter(self):
        with self._lock:
            self._current += 1
            if self._current > self.max_concurrent:
                self.max_concurrent = self._current

    def exit(self):
        with self._lock:
            self._current -= 1


class TrackingRule(Rule):
    """Rule that tracks concurrent executions via a shared ConcurrencyTracker."""

    name = "tracking_rule"
    severity = RuleSeverity.INFO

    def __init__(self, tracker: ConcurrencyTracker, delay: float = 0.05):
        self.tracker = tracker
        self.delay = delay

    def check(self, code: str) -> RuleResult:
        self.tracker.enter()
        try:
            time.sleep(self.delay)
            return self._ok(score=1.0)
        finally:
            self.tracker.exit()


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
# TestValidationStats
# ===========================================================================

class TestValidationStats:
    """ValidationStats dataclass defaults, to_dict, and speedup calculation."""

    def test_defaults(self):
        stats = ValidationStats()
        assert stats.parallel is True
        assert stats.n_candidates == 0
        assert stats.per_candidate_times == []
        assert stats.sequential_estimate == 0.0
        assert stats.parallel_actual == 0.0
        assert stats.speedup == 1.0
        assert stats.max_workers_used == 0

    def test_to_dict(self):
        stats = ValidationStats(
            parallel=True,
            n_candidates=3,
            per_candidate_times=[0.12345, 0.23456, 0.34567],
            sequential_estimate=0.70368,
            parallel_actual=0.35,
            speedup=2.01,
            max_workers_used=3,
        )
        d = stats.to_dict()
        assert d["parallel"] is True
        assert d["n_candidates"] == 3
        assert len(d["per_candidate_times"]) == 3
        assert d["speedup"] == 2.01
        assert d["max_workers_used"] == 3
        # Rounding
        assert d["per_candidate_times"][0] == 0.1235

    def test_speedup_calculation(self):
        stats = ValidationStats(
            sequential_estimate=1.0,
            parallel_actual=0.5,
            speedup=2.0,
        )
        assert stats.speedup == 2.0


# ===========================================================================
# TestParallelCandidateValidation
# ===========================================================================

class TestParallelCandidateValidation:
    """Core parallel validation logic in _validate_pool()."""

    def test_two_candidates_parallel(self):
        """Two candidates validated in parallel returns ValidationStats."""
        config = PipelineConfig(
            n_candidates=2,
            parallel_candidate_validation=True,
            fail_fast_validation=False,
            max_validation_workers=4,
        )
        pipeline = MultiCandidatePipeline(MockLLM(), config=config,
                                          rules=[SlowRule(delay=0.05)])
        pool = _make_pool(2)

        stats = pipeline._validate_pool(pool, fail_fast=False)

        assert isinstance(stats, ValidationStats)
        assert stats.parallel is True
        assert stats.n_candidates == 2
        assert len(stats.per_candidate_times) == 2
        # All candidates should be VALIDATED
        for c in pool.candidates:
            assert c.status == CandidateStatus.VALIDATED

    def test_candidate_order_preserved(self):
        """Validation results are attached to the correct candidate."""
        config = PipelineConfig(
            n_candidates=3,
            parallel_candidate_validation=True,
            fail_fast_validation=False,
        )
        pipeline = MultiCandidatePipeline(MockLLM(), config=config,
                                          rules=[SlowRule(delay=0.02)])
        pool = _make_pool(3)
        # Give candidates distinct codes to verify order
        for i, c in enumerate(pool.candidates):
            c.code = GOOD_CODE + f"\n# candidate {i}\n"

        pipeline._validate_pool(pool, fail_fast=False)

        # Each candidate should have its own validation scores
        for c in pool.candidates:
            assert c.status == CandidateStatus.VALIDATED
            assert len(c.validation_scores) > 0

    def test_parallel_faster_than_sequential(self):
        """Parallel validation of 2 slow candidates is faster than 2x delay."""
        delay = 0.1
        config = PipelineConfig(
            n_candidates=2,
            parallel_candidate_validation=True,
            fail_fast_validation=False,
        )
        pipeline = MultiCandidatePipeline(MockLLM(), config=config,
                                          rules=[SlowRule(delay=delay)])
        pool = _make_pool(2)

        stats = pipeline._validate_pool(pool, fail_fast=False)

        # Wall-clock should be significantly less than 2 * delay
        assert stats.parallel_actual < 2 * delay * 0.95
        assert stats.speedup > 1.0

    def test_disabled_falls_back_sequential(self):
        """When parallel_candidate_validation=False, runs sequentially."""
        config = PipelineConfig(
            n_candidates=2,
            parallel_candidate_validation=False,
            fail_fast_validation=False,
        )
        pipeline = MultiCandidatePipeline(MockLLM(), config=config,
                                          rules=[SlowRule(delay=0.02)])
        pool = _make_pool(2)

        stats = pipeline._validate_pool(pool, fail_fast=False)

        assert stats.parallel is False
        assert stats.max_workers_used == 1
        for c in pool.candidates:
            assert c.status == CandidateStatus.VALIDATED

    def test_single_candidate_sequential(self):
        """A single candidate always runs sequentially."""
        config = PipelineConfig(
            n_candidates=1,
            parallel_candidate_validation=True,
            fail_fast_validation=False,
        )
        pipeline = MultiCandidatePipeline(MockLLM(), config=config,
                                          rules=[SlowRule(delay=0.02)])
        pool = _make_pool(1)

        stats = pipeline._validate_pool(pool, fail_fast=False)

        assert stats.parallel is False
        assert stats.n_candidates == 1

    def test_fail_fast_forces_sequential(self):
        """fail_fast=True disables parallel candidate validation."""
        config = PipelineConfig(
            n_candidates=2,
            parallel_candidate_validation=True,
            fail_fast_validation=True,
        )
        pipeline = MultiCandidatePipeline(MockLLM(), config=config,
                                          rules=[SlowRule(delay=0.02)])
        pool = _make_pool(2)

        stats = pipeline._validate_pool(pool, fail_fast=True)

        assert stats.parallel is False

    def test_exception_isolation(self):
        """If one candidate's validation crashes, others still complete."""
        config = PipelineConfig(
            n_candidates=2,
            parallel_candidate_validation=True,
            fail_fast_validation=False,
        )
        pipeline = MultiCandidatePipeline(MockLLM(), config=config,
                                          rules=[SlowRule(delay=0.02)])
        pool = _make_pool(2)

        # Monkeypatch: make first candidate's validation crash
        original = pipeline._validate_single_candidate

        def _patched(candidate, validator, fail_fast, parallel):
            if candidate.id == 0:
                raise RuntimeError("boom")
            return original(candidate, validator, fail_fast, parallel)

        pipeline._validate_single_candidate = _patched

        stats = pipeline._validate_pool(pool, fail_fast=False)

        # Second candidate should still be validated
        assert pool.candidates[1].status == CandidateStatus.VALIDATED
        assert stats.n_candidates == 2

    @pytest.mark.asyncio
    async def test_stats_in_pipeline_result(self):
        """Full pipeline run produces validation_stats in PipelineResult."""
        config = PipelineConfig(
            n_candidates=2,
            parallel_candidate_validation=True,
            fail_fast_validation=False,
        )
        pipeline = MultiCandidatePipeline(MockLLM(), config=config,
                                          rules=[SlowRule(delay=0.02)])

        result = await pipeline.run(query="Write fibonacci")

        assert result.validation_stats is not None
        assert isinstance(result.validation_stats, ValidationStats)
        assert result.validation_stats.n_candidates == 2


# ===========================================================================
# TestMaxValidationWorkers
# ===========================================================================

class TestMaxValidationWorkers:
    """max_validation_workers config and cap enforcement."""

    def test_default_is_4(self):
        config = PipelineConfig()
        assert config.max_validation_workers == 4

    def test_config_override(self):
        config = PipelineConfig(max_validation_workers=2)
        assert config.max_validation_workers == 2

    def test_workers_capped_by_pool_size(self):
        """Workers should not exceed number of candidates."""
        config = PipelineConfig(
            n_candidates=2,
            parallel_candidate_validation=True,
            fail_fast_validation=False,
            max_validation_workers=8,
        )
        pipeline = MultiCandidatePipeline(MockLLM(), config=config,
                                          rules=[SlowRule(delay=0.02)])
        pool = _make_pool(2)

        stats = pipeline._validate_pool(pool, fail_fast=False)

        assert stats.max_workers_used == 2  # capped to pool.size


# ===========================================================================
# TestRuleRunnerMaxWorkers
# ===========================================================================

class TestRuleRunnerMaxWorkers:
    """RuleRunner max_workers parameter (Step 1)."""

    def test_default_none(self):
        runner = RuleRunner([SlowRule(delay=0.01)])
        assert runner.max_workers is None

    def test_caps_thread_pool(self):
        """max_workers=1 should force single-threaded execution."""
        rule_a = SlowRule(delay=0.05)
        rule_a.name = "slow_a"
        rule_b = SlowRule(delay=0.05)
        rule_b.name = "slow_b"
        runner = RuleRunner([rule_a, rule_b], max_workers=1)

        t0 = time.perf_counter()
        results = runner.run("x = 1", parallel=True)
        elapsed = time.perf_counter() - t0

        # With max_workers=1, two 0.05s rules run sequentially ≈ 0.1s
        assert len(results) == 2
        assert elapsed >= 0.08  # should be ~0.1s

    def test_backward_compat_no_arg(self):
        """RuleRunner without max_workers works as before."""
        runner = RuleRunner([SlowRule(delay=0.01)])
        results = runner.run("x = 1")
        assert len(results) == 1
        assert results[0].passed


# ===========================================================================
# TestPipelineConfigExtension
# ===========================================================================

class TestPipelineConfigExtension:
    """New fields in PipelineConfig (Week 18)."""

    def test_parallel_candidate_validation_default(self):
        config = PipelineConfig()
        assert config.parallel_candidate_validation is True

    def test_max_validation_workers_default(self):
        config = PipelineConfig()
        assert config.max_validation_workers == 4


# ===========================================================================
# TestPipelineResultExtension
# ===========================================================================

class TestPipelineResultExtension:
    """validation_stats field on PipelineResult."""

    def test_validation_stats_field_exists(self):
        pool = _make_pool(1)
        result = PipelineResult(
            pool=pool,
            best=pool.candidates[0],
            all_passed=True,
            validation_stats=ValidationStats(n_candidates=1),
        )
        assert result.validation_stats is not None
        assert result.validation_stats.n_candidates == 1

    def test_validation_stats_in_summary(self):
        pool = _make_pool(1)
        stats = ValidationStats(
            parallel=True,
            n_candidates=1,
            speedup=1.5,
        )
        result = PipelineResult(
            pool=pool,
            best=pool.candidates[0],
            all_passed=True,
            validation_stats=stats,
        )
        summary = result.summary()
        assert "validation_stats" in summary
        assert summary["validation_stats"]["speedup"] == 1.5

    def test_summary_without_stats(self):
        """summary() works when validation_stats is None."""
        pool = _make_pool(1)
        result = PipelineResult(
            pool=pool,
            best=pool.candidates[0],
            all_passed=True,
        )
        summary = result.summary()
        assert "validation_stats" not in summary


# ===========================================================================
# TestBackwardCompatibility
# ===========================================================================

class TestBackwardCompatibility:
    """Ensure existing callers and tests are not broken."""

    @pytest.mark.asyncio
    async def test_old_callers_work(self):
        """Pipeline with default config still works end-to-end."""
        pipeline = MultiCandidatePipeline(MockLLM())
        result = await pipeline.run(query="Write fibonacci")

        assert result.best is not None
        assert len(result.code) > 0

    def test_validate_pool_returns_stats(self):
        """_validate_pool now returns ValidationStats instead of None."""
        pipeline = MultiCandidatePipeline(MockLLM())
        pool = _make_pool(2)

        stats = pipeline._validate_pool(pool)

        assert isinstance(stats, ValidationStats)
        for c in pool.candidates:
            assert c.status == CandidateStatus.VALIDATED

    @pytest.mark.asyncio
    async def test_existing_pipeline_patterns(self):
        """Standard pipeline usage patterns still work."""
        config = PipelineConfig(n_candidates=2, parallel_generation=False)
        pipeline = MultiCandidatePipeline(MockLLM(), config=config)

        result = await pipeline.run(query="test")

        assert result.pool.size == 2
        assert result.best is not None
        assert result.total_time > 0
        assert result.validation_time > 0
