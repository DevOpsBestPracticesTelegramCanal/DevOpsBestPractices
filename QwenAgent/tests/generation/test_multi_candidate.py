"""Tests for MultiCandidateGenerator."""

import asyncio
import pytest
from dataclasses import dataclass
from typing import Optional

from core.generation.multi_candidate import MultiCandidateGenerator, MultiCandidateConfig
from core.generation.candidate import CandidateStatus


# ---------------------------------------------------------------------------
# Mock LLM
# ---------------------------------------------------------------------------

class MockLLM:
    """Deterministic mock that returns code based on temperature."""

    model_name = "mock-3b"

    def __init__(self, delay: float = 0.01, fail_index: Optional[int] = None):
        self.delay = delay
        self.fail_index = fail_index
        self.call_count = 0

    async def generate(self, prompt: str, system: str, temperature: float, seed: int) -> str:
        self.call_count += 1
        if self.fail_index is not None and self.call_count == self.fail_index:
            raise RuntimeError("LLM mock failure")

        await asyncio.sleep(self.delay)

        # Deterministic output based on temperature
        if temperature < 0.3:
            return 'def f():\n    """Conservative."""\n    return 1'
        elif temperature < 0.6:
            return 'def f():\n    """Balanced."""\n    return 2'
        else:
            return 'def f():\n    """Creative."""\n    return 3'


# ---------------------------------------------------------------------------
# Mock Task
# ---------------------------------------------------------------------------

@dataclass
class FakeTask:
    task_id: str = "test_task"
    query: str = "Write a function"
    affected_files: list = None
    swecas_code: int = 600
    type: object = None
    risk_level: object = None

    def __post_init__(self):
        self.affected_files = self.affected_files or []


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestMultiCandidateGenerator:

    @pytest.mark.asyncio
    async def test_generates_n_candidates(self):
        llm = MockLLM()
        gen = MultiCandidateGenerator(llm)
        pool = await gen.generate(FakeTask(), n=3)

        assert pool.size == 3
        assert llm.call_count == 3

    @pytest.mark.asyncio
    async def test_different_temperatures(self):
        llm = MockLLM()
        gen = MultiCandidateGenerator(llm)
        pool = await gen.generate(FakeTask(), n=3)

        temps = {c.temperature for c in pool.candidates}
        assert len(temps) == 3
        assert 0.2 in temps
        assert 0.5 in temps
        assert 0.8 in temps

    @pytest.mark.asyncio
    async def test_different_seeds(self):
        llm = MockLLM()
        gen = MultiCandidateGenerator(llm)
        pool = await gen.generate(FakeTask(), n=3)

        seeds = {c.seed for c in pool.candidates}
        assert len(seeds) == 3

    @pytest.mark.asyncio
    async def test_different_code_variants(self):
        llm = MockLLM()
        gen = MultiCandidateGenerator(llm)
        pool = await gen.generate(FakeTask(), n=3)

        codes = {c.code for c in pool.candidates}
        # Each temperature produces different code
        assert len(codes) == 3

    @pytest.mark.asyncio
    async def test_sequential_mode(self):
        llm = MockLLM()
        gen = MultiCandidateGenerator(llm)
        pool = await gen.generate(FakeTask(), n=2, parallel=False)

        assert pool.size == 2

    @pytest.mark.asyncio
    async def test_generation_time_recorded(self):
        llm = MockLLM(delay=0.05)
        gen = MultiCandidateGenerator(llm)
        pool = await gen.generate(FakeTask(), n=2)

        for c in pool.candidates:
            assert c.generation_time >= 0.04  # at least the delay

    @pytest.mark.asyncio
    async def test_custom_config(self):
        config = MultiCandidateConfig(
            temperatures=(0.1, 0.9),
            base_seed=100,
        )
        llm = MockLLM()
        gen = MultiCandidateGenerator(llm, config=config)
        pool = await gen.generate(FakeTask(), n=2)

        assert pool.size == 2
        assert pool.candidates[0].temperature == 0.1
        assert pool.candidates[1].temperature == 0.9
        assert pool.candidates[0].seed == 100
        assert pool.candidates[1].seed == 101

    @pytest.mark.asyncio
    async def test_model_name_propagated(self):
        llm = MockLLM()
        gen = MultiCandidateGenerator(llm)
        pool = await gen.generate(FakeTask(), n=1)

        assert pool.candidates[0].model == "mock-3b"

    @pytest.mark.asyncio
    async def test_task_id_propagated(self):
        llm = MockLLM()
        gen = MultiCandidateGenerator(llm)
        pool = await gen.generate(FakeTask(task_id="abc123"), n=1)

        assert pool.task_id == "abc123"
        assert pool.candidates[0].task_id == "abc123"

    @pytest.mark.asyncio
    async def test_initial_status_is_generated(self):
        llm = MockLLM()
        gen = MultiCandidateGenerator(llm)
        pool = await gen.generate(FakeTask(), n=2)

        for c in pool.candidates:
            assert c.status == CandidateStatus.GENERATED
