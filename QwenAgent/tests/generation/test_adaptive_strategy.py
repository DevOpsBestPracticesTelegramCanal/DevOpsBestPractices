"""
Tests for Week 4: Adaptive Temperature & Smart Candidate Count.
"""

import json
import os
import tempfile
import pytest
from unittest.mock import MagicMock, AsyncMock

from core.generation.adaptive_strategy import (
    AdaptiveStrategy,
    AdaptiveConfig,
    CodegenComplexity,
    StrategyOutcome,
    _DEFAULT_STRATEGIES,
    _TIME_PER_CANDIDATE,
)


# ---------------------------------------------------------------------------
# TestCodegenComplexity — classification tests
# ---------------------------------------------------------------------------


class TestCodegenComplexity:
    """Test classify_complexity() for various query types."""

    @pytest.fixture
    def strategy(self):
        return AdaptiveStrategy(persist=False)

    def test_trivial_hello_world(self, strategy):
        assert strategy.classify_complexity("write hello world") == CodegenComplexity.TRIVIAL

    def test_trivial_fizzbuzz(self, strategy):
        assert strategy.classify_complexity("Write a fizzbuzz program") == CodegenComplexity.TRIVIAL

    def test_trivial_add_two_numbers(self, strategy):
        assert strategy.classify_complexity("add two numbers") == CodegenComplexity.TRIVIAL

    def test_simple_sort(self, strategy):
        assert strategy.classify_complexity("write a sort function") == CodegenComplexity.SIMPLE

    def test_simple_parse_json(self, strategy):
        assert strategy.classify_complexity("parse json from a string") == CodegenComplexity.SIMPLE

    def test_moderate_fallback_by_length(self, strategy):
        """Medium-length query without special keywords → MODERATE."""
        query = "write a function that takes a list of items and does something interesting with them"
        result = strategy.classify_complexity(query)
        assert result == CodegenComplexity.MODERATE

    def test_complex_middleware(self, strategy):
        assert strategy.classify_complexity("implement API middleware for rate limiting") == CodegenComplexity.COMPLEX

    def test_complex_design_pattern(self, strategy):
        assert strategy.classify_complexity("write a design pattern for observer") == CodegenComplexity.COMPLEX

    def test_critical_auth(self, strategy):
        assert strategy.classify_complexity("implement JWT auth for users") == CodegenComplexity.CRITICAL

    def test_critical_encryption(self, strategy):
        assert strategy.classify_complexity("write encrypt/decrypt functions with AES") == CodegenComplexity.CRITICAL

    def test_critical_security(self, strategy):
        assert strategy.classify_complexity("implement password hashing with bcrypt") == CodegenComplexity.CRITICAL

    def test_swecas_override_to_critical(self, strategy):
        """SWECAS 500-599 → always CRITICAL regardless of keywords."""
        assert strategy.classify_complexity("write hello world", swecas_code=512) == CodegenComplexity.CRITICAL

    def test_swecas_non_security_no_override(self, strategy):
        """SWECAS outside 500-599 → normal classification."""
        assert strategy.classify_complexity("write hello world", swecas_code=100) == CodegenComplexity.TRIVIAL

    def test_case_insensitive(self, strategy):
        assert strategy.classify_complexity("WRITE JWT AUTH") == CodegenComplexity.CRITICAL


# ---------------------------------------------------------------------------
# TestStrategySelection — correct n/temps for each complexity
# ---------------------------------------------------------------------------


class TestStrategySelection:
    """Test get_strategy() returns correct n_candidates and temperatures."""

    @pytest.fixture
    def strategy(self):
        return AdaptiveStrategy(persist=False)

    def test_trivial_strategy(self, strategy):
        config = strategy.get_strategy("write hello world")
        assert config.n_candidates == 1
        assert config.temperatures == (0.2,)
        assert config.complexity == CodegenComplexity.TRIVIAL

    def test_simple_strategy(self, strategy):
        config = strategy.get_strategy("sort a list")
        assert config.n_candidates == 1
        assert config.temperatures == (0.3,)
        assert config.complexity == CodegenComplexity.SIMPLE

    def test_moderate_strategy(self, strategy):
        query = "write a function that takes a list of items and does something interesting with them"
        config = strategy.get_strategy(query)
        assert config.n_candidates == 2
        assert config.temperatures == (0.2, 0.6)

    def test_complex_strategy(self, strategy):
        config = strategy.get_strategy("implement API middleware for authentication and rate limiting")
        assert config.n_candidates == 3
        assert len(config.temperatures) == 3

    def test_critical_strategy(self, strategy):
        config = strategy.get_strategy("implement JWT auth with token refresh")
        assert config.n_candidates == 3
        assert config.temperatures == (0.1, 0.4, 0.7)

    def test_reasoning_includes_complexity(self, strategy):
        config = strategy.get_strategy("write hello world")
        assert "trivial" in config.reasoning

    def test_reasoning_includes_swecas(self, strategy):
        config = strategy.get_strategy("write code", swecas_code=512)
        assert "SWECAS" in config.reasoning
        assert "512" in config.reasoning

    def test_estimated_time(self, strategy):
        config = strategy.get_strategy("write hello world")
        assert config.estimated_time_seconds == 1 * _TIME_PER_CANDIDATE

    def test_confidence_high_for_keyword_match(self, strategy):
        config = strategy.get_strategy("implement JWT auth")
        assert config.confidence >= 0.9


# ---------------------------------------------------------------------------
# TestHistoryRecording — persistence and capping
# ---------------------------------------------------------------------------


class TestHistoryRecording:
    """Test record_outcome() persistence and history management."""

    def test_record_adds_to_history(self):
        strategy = AdaptiveStrategy(persist=False)
        config = strategy.get_strategy("write hello world")
        strategy.record_outcome(
            config=config, best_score=0.95, all_passed=True,
            total_time=20.0, query="write hello world",
        )
        assert len(strategy._history) == 1
        assert strategy._history[0].complexity == "trivial"

    def test_persist_and_reload(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "history.json")

            # Write
            s1 = AdaptiveStrategy(history_path=path, persist=True)
            config = s1.get_strategy("write hello world")
            s1.record_outcome(
                config=config, best_score=0.9, all_passed=True,
                total_time=22.0, query="write hello world",
            )
            assert os.path.exists(path)

            # Reload
            s2 = AdaptiveStrategy(history_path=path, persist=True)
            assert len(s2._history) == 1
            assert s2._history[0].best_score == 0.9

    def test_history_capped_at_max(self):
        strategy = AdaptiveStrategy(persist=False)
        config = strategy.get_strategy("sort a list")
        for i in range(250):
            strategy.record_outcome(
                config=config, best_score=0.8, all_passed=True,
                total_time=20.0, query=f"query_{i}",
            )
        assert len(strategy._history) == AdaptiveStrategy.MAX_HISTORY

    def test_no_persist_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "history.json")
            strategy = AdaptiveStrategy(history_path=path, persist=False)
            config = strategy.get_strategy("write hello world")
            strategy.record_outcome(
                config=config, best_score=0.9, all_passed=True,
                total_time=20.0, query="test",
            )
            assert not os.path.exists(path)


# ---------------------------------------------------------------------------
# TestLearningFromHistory — adaptive adjustments
# ---------------------------------------------------------------------------


class TestLearningFromHistory:
    """Test that learning adjusts strategies based on outcomes."""

    def _record_n(self, strategy, complexity_query, n, score, passed):
        """Record n outcomes for a query type."""
        config = strategy.get_strategy(complexity_query)
        for _ in range(n):
            strategy.record_outcome(
                config=config, best_score=score, all_passed=passed,
                total_time=20.0, query=complexity_query,
            )

    def test_downgrade_on_high_scores(self):
        """MODERATE with high scores → should downgrade to n=1."""
        strategy = AdaptiveStrategy(persist=False)
        # Force MODERATE classification
        query = "write a function that takes a list of items and does something interesting with them"
        assert strategy.classify_complexity(query) == CodegenComplexity.MODERATE
        initial_n = strategy._strategies[CodegenComplexity.MODERATE][0]
        assert initial_n == 2

        # Record many high-score outcomes
        config = strategy.get_strategy(query)
        for _ in range(10):
            strategy.record_outcome(
                config=config, best_score=0.95, all_passed=True,
                total_time=20.0, query=query,
            )

        new_n = strategy._strategies[CodegenComplexity.MODERATE][0]
        assert new_n < initial_n

    def test_upgrade_on_low_scores(self):
        """SIMPLE with low scores → should upgrade to n=2."""
        strategy = AdaptiveStrategy(persist=False)
        query = "sort a list"
        assert strategy.classify_complexity(query) == CodegenComplexity.SIMPLE
        initial_n = strategy._strategies[CodegenComplexity.SIMPLE][0]
        assert initial_n == 1

        config = strategy.get_strategy(query)
        for _ in range(10):
            strategy.record_outcome(
                config=config, best_score=0.5, all_passed=False,
                total_time=20.0, query=query,
            )

        new_n = strategy._strategies[CodegenComplexity.SIMPLE][0]
        assert new_n > initial_n

    def test_min_samples_required(self):
        """No learning until 5+ outcomes."""
        strategy = AdaptiveStrategy(persist=False)
        query = "sort a list"
        config = strategy.get_strategy(query)
        for _ in range(4):
            strategy.record_outcome(
                config=config, best_score=0.5, all_passed=False,
                total_time=20.0, query=query,
            )
        # Should not have changed
        assert strategy._strategies[CodegenComplexity.SIMPLE] == _DEFAULT_STRATEGIES[CodegenComplexity.SIMPLE]

    def test_critical_never_downgraded(self):
        """CRITICAL complexity should never be changed by learning."""
        strategy = AdaptiveStrategy(persist=False)
        query = "implement JWT auth"
        config = strategy.get_strategy(query)
        for _ in range(10):
            strategy.record_outcome(
                config=config, best_score=0.99, all_passed=True,
                total_time=20.0, query=query,
            )
        # CRITICAL should remain at 3 candidates
        assert strategy._strategies[CodegenComplexity.CRITICAL][0] == 3


# ---------------------------------------------------------------------------
# TestGetStats — stats reporting
# ---------------------------------------------------------------------------


class TestGetStats:
    """Test get_stats() output."""

    def test_empty_stats(self):
        strategy = AdaptiveStrategy(persist=False)
        stats = strategy.get_stats()
        assert stats["total_outcomes"] == 0
        assert stats["complexity_distribution"] == {}
        assert "trivial" in stats["current_strategies"]

    def test_stats_with_history(self):
        strategy = AdaptiveStrategy(persist=False)
        config = strategy.get_strategy("write hello world")
        strategy.record_outcome(
            config=config, best_score=0.9, all_passed=True,
            total_time=20.0, query="write hello world",
        )
        stats = strategy.get_stats()
        assert stats["total_outcomes"] == 1
        assert stats["complexity_distribution"]["trivial"] == 1
        assert stats["avg_scores"]["trivial"] == 0.9


# ---------------------------------------------------------------------------
# TestPipelineTemperatureOverride — generator temperature override
# ---------------------------------------------------------------------------


class TestPipelineTemperatureOverride:
    """Test that temperature override works in the generator."""

    @pytest.fixture
    def mock_llm(self):
        llm = MagicMock()
        llm.model_name = "test-model"
        llm.generate = AsyncMock(return_value="def hello(): pass")
        return llm

    @pytest.mark.asyncio
    async def test_override_temps_used(self, mock_llm):
        from core.generation.multi_candidate import MultiCandidateGenerator, MultiCandidateConfig
        gen = MultiCandidateGenerator(mock_llm, MultiCandidateConfig(
            temperatures=(0.2, 0.5, 0.8), per_candidate_timeout=10.0,
        ))
        task = MagicMock()
        task.task_id = "test"
        task.query = "hello"
        task.affected_files = []
        task.swecas_code = None
        task.type = None
        task.risk_level = None

        pool = await gen.generate(task, n=1, parallel=False, temperatures=(0.99,))
        # The candidate should have used temperature 0.99
        assert pool.candidates[0].temperature == 0.99

    @pytest.mark.asyncio
    async def test_none_uses_default(self, mock_llm):
        from core.generation.multi_candidate import MultiCandidateGenerator, MultiCandidateConfig
        gen = MultiCandidateGenerator(mock_llm, MultiCandidateConfig(
            temperatures=(0.2, 0.5, 0.8), per_candidate_timeout=10.0,
        ))
        task = MagicMock()
        task.task_id = "test"
        task.query = "hello"
        task.affected_files = []
        task.swecas_code = None
        task.type = None
        task.risk_level = None

        pool = await gen.generate(task, n=1, parallel=False, temperatures=None)
        assert pool.candidates[0].temperature == 0.2

    @pytest.mark.asyncio
    async def test_single_temp_single_candidate(self, mock_llm):
        from core.generation.multi_candidate import MultiCandidateGenerator, MultiCandidateConfig
        gen = MultiCandidateGenerator(mock_llm, MultiCandidateConfig(
            temperatures=(0.2, 0.5, 0.8), per_candidate_timeout=10.0,
        ))
        task = MagicMock()
        task.task_id = "test"
        task.query = "hello"
        task.affected_files = []
        task.swecas_code = None
        task.type = None
        task.risk_level = None

        pool = await gen.generate(task, n=1, parallel=False, temperatures=(0.3,))
        assert pool.size == 1
        assert pool.candidates[0].temperature == 0.3


# ---------------------------------------------------------------------------
# TestAgentAdaptiveIntegration — agent creates strategy, uses it
# ---------------------------------------------------------------------------


class TestAgentAdaptiveIntegration:
    """Test AdaptiveStrategy integration in QwenCodeAgent."""

    def test_agent_has_adaptive_strategy(self):
        from core.qwencode_agent import QwenCodeAgent, QwenCodeConfig
        agent = QwenCodeAgent(QwenCodeConfig(model="qwen2.5-coder:7b"))
        assert agent.adaptive_strategy is not None

    def test_agent_has_adaptive_stats(self):
        from core.qwencode_agent import QwenCodeAgent, QwenCodeConfig
        agent = QwenCodeAgent(QwenCodeConfig(model="qwen2.5-coder:7b"))
        assert "adaptive_trivial" in agent.stats
        assert "adaptive_simple" in agent.stats
        assert "adaptive_moderate" in agent.stats
        assert "adaptive_complex" in agent.stats
        assert "adaptive_critical" in agent.stats
        assert "adaptive_time_saved_seconds" in agent.stats

    def test_trivial_uses_one_candidate(self):
        """Trivial query through agent should request 1 candidate."""
        from core.qwencode_agent import QwenCodeAgent, QwenCodeConfig

        agent = QwenCodeAgent(QwenCodeConfig(model="qwen2.5-coder:7b"))

        mock_result = MagicMock()
        mock_result.code = "print('hello world')"
        mock_result.score = 0.95
        mock_result.all_passed = True
        mock_result.best = MagicMock()
        mock_result.best.validation_scores = []
        mock_result.cross_review_result = None
        mock_result.total_time = 20.0
        mock_result.summary.return_value = {"candidates_generated": 1, "best_score": 0.95}

        agent.multi_candidate_pipeline.run_sync = MagicMock(return_value=mock_result)

        # "Write a function" triggers _is_code_generation_task, "hello world" triggers TRIVIAL
        events = list(agent.process_stream("Write a function for hello world"))

        # Verify run_sync was called with n=1
        call_kwargs = agent.multi_candidate_pipeline.run_sync.call_args
        assert call_kwargs is not None, "pipeline.run_sync was not called"
        kw = call_kwargs.kwargs if call_kwargs.kwargs else call_kwargs[1]
        assert kw.get("n") == 1

        # Should have status event with "1 code variant" and "trivial"
        status_events = [e for e in events if e.get("event") == "status"]
        status_texts = " ".join(e.get("text", "") for e in status_events)
        assert "1 code variant" in status_texts
        assert "trivial" in status_texts

        assert agent.stats["adaptive_trivial"] == 1
