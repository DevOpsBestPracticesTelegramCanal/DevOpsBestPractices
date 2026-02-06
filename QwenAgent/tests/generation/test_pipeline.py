"""Tests for MultiCandidatePipeline — full generate → validate → select flow."""

import asyncio
import pytest
from dataclasses import dataclass
from typing import Optional

from core.generation.pipeline import (
    MultiCandidatePipeline,
    PipelineConfig,
    PipelineResult,
)
from core.generation.candidate import CandidateStatus


# ---------------------------------------------------------------------------
# Mock LLM
# ---------------------------------------------------------------------------

class MockLLM:
    """Returns different code depending on temperature."""

    model_name = "mock-7b"

    def __init__(self):
        self.call_count = 0

    async def generate(
        self, prompt: str, system: str, temperature: float, seed: int
    ) -> str:
        self.call_count += 1
        await asyncio.sleep(0.01)

        # Low temp → clean code; high temp → messy code
        if temperature < 0.3:
            return (
                'def fibonacci(n: int) -> int:\n'
                '    """Return nth Fibonacci number."""\n'
                '    if n <= 1:\n'
                '        return n\n'
                '    a, b = 0, 1\n'
                '    for _ in range(2, n + 1):\n'
                '        a, b = b, a + b\n'
                '    return b\n'
            )
        elif temperature < 0.6:
            return (
                'def fibonacci(n):\n'
                '    """Fibonacci."""\n'
                '    if n <= 1:\n'
                '        return n\n'
                '    return fibonacci(n-1) + fibonacci(n-2)\n'
            )
        else:
            # Creative: shorter, no type hints, no docstring
            return (
                'def fib(n):\n'
                '    a,b = 0,1\n'
                '    for _ in range(n): a,b = b,a+b\n'
                '    return a\n'
            )


class BrokenLLM:
    """Returns syntax-error code."""

    model_name = "broken-3b"

    async def generate(self, prompt, system, temperature, seed):
        return "def broken(\n    # unclosed paren"


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPipeline:

    async def test_basic_pipeline(self):
        """Full pipeline: 3 candidates generated, validated, best selected."""
        llm = MockLLM()
        pipeline = MultiCandidatePipeline(llm)

        result = await pipeline.run(
            task_id="test_1",
            query="Write a fibonacci function",
        )

        assert isinstance(result, PipelineResult)
        assert result.pool.size == 3
        assert result.best is not None
        assert result.best.status == CandidateStatus.SELECTED
        assert len(result.code) > 0
        assert result.score > 0
        assert result.total_time > 0
        assert llm.call_count == 3

    async def test_best_candidate_has_highest_score(self):
        """The conservative (low temp) candidate should score highest."""
        pipeline = MultiCandidatePipeline(MockLLM())
        result = await pipeline.run(query="Write fibonacci")

        # Conservative code has type hints + docstring → should score better
        assert result.best.temperature == 0.2

    async def test_all_candidates_validated(self):
        """Every candidate should have validation scores."""
        pipeline = MultiCandidatePipeline(MockLLM())
        result = await pipeline.run(query="Write fibonacci")

        for c in result.pool.candidates:
            assert c.status in (CandidateStatus.SELECTED, CandidateStatus.REJECTED)
            assert len(c.validation_scores) > 0
            assert c.total_score >= 0

    async def test_rejected_candidates_marked(self):
        """Non-best candidates should be REJECTED."""
        pipeline = MultiCandidatePipeline(MockLLM())
        result = await pipeline.run(query="Write fibonacci", n=3)

        rejected = [
            c for c in result.pool.candidates
            if c.status == CandidateStatus.REJECTED
        ]
        assert len(rejected) == 2

    async def test_summary_has_required_fields(self):
        pipeline = MultiCandidatePipeline(MockLLM())
        result = await pipeline.run(query="test")

        s = result.summary()
        assert "candidates_generated" in s
        assert "best_id" in s
        assert "best_score" in s
        assert "all_passed" in s
        assert "total_time" in s
        assert "pool_stats" in s

    async def test_custom_n_candidates(self):
        llm = MockLLM()
        pipeline = MultiCandidatePipeline(llm)
        result = await pipeline.run(query="test", n=2)

        assert result.pool.size == 2
        assert llm.call_count == 2

    async def test_pipeline_config(self):
        config = PipelineConfig(n_candidates=2, parallel_generation=False)
        pipeline = MultiCandidatePipeline(MockLLM(), config=config)
        result = await pipeline.run(query="test")

        assert result.pool.size == 2

    async def test_broken_llm_still_validates(self):
        """Even bad code should go through validation (and fail gracefully)."""
        pipeline = MultiCandidatePipeline(BrokenLLM())
        result = await pipeline.run(query="test", n=1)

        assert result.pool.size == 1
        best = result.best
        assert best is not None
        # AST syntax should fail
        assert best.has_critical_errors

    async def test_sync_wrapper(self):
        """run_sync should produce the same result as run."""
        pipeline = MultiCandidatePipeline(MockLLM())
        result = pipeline.run_sync(query="test", n=2)

        assert result.pool.size == 2
        assert result.best is not None

    async def test_timing_fields(self):
        pipeline = MultiCandidatePipeline(MockLLM())
        result = await pipeline.run(query="test")

        assert result.generation_time > 0
        assert result.validation_time >= 0
        assert result.selection_time >= 0
        assert result.total_time >= result.generation_time
