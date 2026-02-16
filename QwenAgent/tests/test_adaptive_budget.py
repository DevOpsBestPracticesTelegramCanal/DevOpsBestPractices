"""
Week 27 Tests: Adaptive Budget Architecture

Tests for 3-level adaptive budget system:
- Level 1: _should_skip_multi_candidate() — skip MC on low budget/simple tasks/constrained platform
- Level 2: adapt_for_platform() — reduce candidates based on platform/model/budget
- Level 3: Graceful fallback — _compute_mc_timeout(), budget tracking
- Integration: stats tracking, pipeline_start event fields

~45 tests covering all scenarios.
"""

import os
import sys
import time
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Level 2: AdaptiveStrategy.adapt_for_platform() tests
# ---------------------------------------------------------------------------

class TestAdaptForPlatform:
    """Tests for platform-aware candidate count adaptation."""

    @pytest.fixture
    def strategy(self):
        from core.generation.adaptive_strategy import AdaptiveStrategy
        return AdaptiveStrategy(persist=False)

    @pytest.fixture
    def complex_config(self, strategy):
        """Get a COMPLEX config with 3 candidates."""
        return strategy.get_strategy("implement JWT auth middleware with database integration")

    @pytest.fixture
    def simple_config(self, strategy):
        """Get a SIMPLE config with 1 candidate."""
        return strategy.get_strategy("write hello world")

    def test_no_adaptation_needed(self, strategy, complex_config):
        """No adaptation when platform is fine and budget is large."""
        with patch("core.generation.adaptive_strategy.sys") as mock_sys, \
             patch("core.generation.adaptive_strategy.os") as mock_os:
            mock_sys.platform = "linux"
            mock_os.cpu_count.return_value = 16
            adapted = strategy.adapt_for_platform(
                complex_config, model_name="qwen2.5-coder:7b", budget_seconds=1200.0,
            )
            # Should return same config unchanged
            assert adapted.n_candidates == complex_config.n_candidates
            assert adapted.temperatures == complex_config.temperatures

    def test_windows_cpu_7b_caps_to_1(self, strategy, complex_config):
        """Windows + 7B model → 1 candidate."""
        with patch("core.generation.adaptive_strategy.sys") as mock_sys, \
             patch("core.generation.adaptive_strategy.os") as mock_os:
            mock_sys.platform = "win32"
            mock_os.cpu_count.return_value = 12
            adapted = strategy.adapt_for_platform(
                complex_config, model_name="qwen2.5-coder:7b", budget_seconds=1200.0,
            )
            assert adapted.n_candidates == 1
            assert len(adapted.temperatures) == 1
            assert "Windows CPU" in adapted.reasoning

    def test_windows_cpu_3b_no_cap(self, strategy, complex_config):
        """Windows + 3B model → no cap (small model is fast)."""
        with patch("core.generation.adaptive_strategy.sys") as mock_sys, \
             patch("core.generation.adaptive_strategy.os") as mock_os:
            mock_sys.platform = "win32"
            mock_os.cpu_count.return_value = 16
            adapted = strategy.adapt_for_platform(
                complex_config, model_name="qwen2.5-coder:3b", budget_seconds=1200.0,
            )
            assert adapted.n_candidates == complex_config.n_candidates

    def test_low_cpu_count_caps_to_1(self, strategy, complex_config):
        """< 8 CPU cores → 1 candidate."""
        with patch("core.generation.adaptive_strategy.sys") as mock_sys, \
             patch("core.generation.adaptive_strategy.os") as mock_os:
            mock_sys.platform = "linux"
            mock_os.cpu_count.return_value = 4
            adapted = strategy.adapt_for_platform(
                complex_config, model_name="qwen2.5-coder:7b", budget_seconds=1200.0,
            )
            assert adapted.n_candidates == 1
            assert "CPU cores=4" in adapted.reasoning

    def test_tight_budget_caps_candidates(self, strategy, complex_config):
        """Budget 200s → max 1 candidate (200/120 = 1)."""
        with patch("core.generation.adaptive_strategy.sys") as mock_sys, \
             patch("core.generation.adaptive_strategy.os") as mock_os:
            mock_sys.platform = "linux"
            mock_os.cpu_count.return_value = 16
            adapted = strategy.adapt_for_platform(
                complex_config, model_name="qwen2.5-coder:7b", budget_seconds=200.0,
            )
            assert adapted.n_candidates <= 1
            assert "budget=" in adapted.reasoning

    def test_medium_budget_caps_candidates(self, strategy, complex_config):
        """Budget 300s → max 2 candidates (300/120 = 2)."""
        with patch("core.generation.adaptive_strategy.sys") as mock_sys, \
             patch("core.generation.adaptive_strategy.os") as mock_os:
            mock_sys.platform = "linux"
            mock_os.cpu_count.return_value = 16
            adapted = strategy.adapt_for_platform(
                complex_config, model_name="qwen2.5-coder:7b", budget_seconds=300.0,
            )
            assert adapted.n_candidates <= 2

    def test_simple_config_unchanged(self, strategy, simple_config):
        """Simple config (1 candidate) is never reduced further."""
        with patch("core.generation.adaptive_strategy.sys") as mock_sys, \
             patch("core.generation.adaptive_strategy.os") as mock_os:
            mock_sys.platform = "win32"
            mock_os.cpu_count.return_value = 4
            adapted = strategy.adapt_for_platform(
                simple_config, model_name="qwen2.5-coder:7b", budget_seconds=100.0,
            )
            assert adapted.n_candidates == 1

    def test_large_model_tags(self, strategy, complex_config):
        """Various large model tags are detected."""
        for tag in ["13b", "14b", "32b", "70b", "72b"]:
            with patch("core.generation.adaptive_strategy.sys") as mock_sys, \
                 patch("core.generation.adaptive_strategy.os") as mock_os:
                mock_sys.platform = "win32"
                mock_os.cpu_count.return_value = 12
                adapted = strategy.adapt_for_platform(
                    complex_config, model_name=f"model:{tag}", budget_seconds=1200.0,
                )
                assert adapted.n_candidates == 1, f"Failed for model tag {tag}"

    def test_middle_temperature_selected(self, strategy):
        """When capping to 1 candidate, middle temperature is selected."""
        config = strategy.get_strategy("implement JWT auth middleware with database integration")
        if len(config.temperatures) >= 3:
            with patch("core.generation.adaptive_strategy.sys") as mock_sys, \
                 patch("core.generation.adaptive_strategy.os") as mock_os:
                mock_sys.platform = "win32"
                mock_os.cpu_count.return_value = 12
                adapted = strategy.adapt_for_platform(
                    config, model_name="qwen2.5-coder:7b", budget_seconds=1200.0,
                )
                assert len(adapted.temperatures) == 1
                middle_idx = len(config.temperatures) // 2
                assert adapted.temperatures[0] == config.temperatures[middle_idx]

    def test_estimated_time_adjusted(self, strategy, complex_config):
        """Estimated time should be recalculated for adapted candidate count."""
        with patch("core.generation.adaptive_strategy.sys") as mock_sys, \
             patch("core.generation.adaptive_strategy.os") as mock_os:
            mock_sys.platform = "win32"
            mock_os.cpu_count.return_value = 12
            adapted = strategy.adapt_for_platform(
                complex_config, model_name="qwen2.5-coder:7b", budget_seconds=1200.0,
            )
            assert adapted.estimated_time_seconds < complex_config.estimated_time_seconds

    def test_reasoning_includes_platform_info(self, strategy, complex_config):
        """Adapted config reasoning includes platform constraints."""
        with patch("core.generation.adaptive_strategy.sys") as mock_sys, \
             patch("core.generation.adaptive_strategy.os") as mock_os:
            mock_sys.platform = "win32"
            mock_os.cpu_count.return_value = 4
            adapted = strategy.adapt_for_platform(
                complex_config, model_name="qwen2.5-coder:7b", budget_seconds=200.0,
            )
            assert "Platform:" in adapted.reasoning

    def test_confidence_preserved(self, strategy, complex_config):
        """Confidence score is preserved after adaptation."""
        with patch("core.generation.adaptive_strategy.sys") as mock_sys, \
             patch("core.generation.adaptive_strategy.os") as mock_os:
            mock_sys.platform = "win32"
            mock_os.cpu_count.return_value = 12
            adapted = strategy.adapt_for_platform(
                complex_config, model_name="qwen2.5-coder:7b", budget_seconds=1200.0,
            )
            assert adapted.confidence == complex_config.confidence

    def test_complexity_preserved(self, strategy, complex_config):
        """Complexity level is preserved after adaptation."""
        with patch("core.generation.adaptive_strategy.sys") as mock_sys, \
             patch("core.generation.adaptive_strategy.os") as mock_os:
            mock_sys.platform = "win32"
            mock_os.cpu_count.return_value = 12
            adapted = strategy.adapt_for_platform(
                complex_config, model_name="qwen2.5-coder:7b", budget_seconds=1200.0,
            )
            assert adapted.complexity == complex_config.complexity


# ---------------------------------------------------------------------------
# Level 1: _should_skip_multi_candidate() tests
# ---------------------------------------------------------------------------

class TestShouldSkipMultiCandidate:
    """Tests for MC pipeline skip logic."""

    @pytest.fixture
    def agent(self):
        """Create minimal agent mock with _should_skip_multi_candidate."""
        from core.qwencode_agent import QwenCodeAgent
        # Import the method and bind it to a mock
        mock_agent = MagicMock()
        mock_agent.config = MagicMock()
        mock_agent.config.pipeline_model = "qwen2.5-coder:7b"
        mock_agent.config.model = "qwen2.5-coder:3b"
        # Week 29: Trinity disabled by default in skip tests
        mock_agent.trinity_manager = None
        # Bind the real method
        mock_agent._should_skip_multi_candidate = QwenCodeAgent._should_skip_multi_candidate.__get__(mock_agent)
        return mock_agent

    def test_trivial_complexity_skips(self, agent):
        skip, reason = agent._should_skip_multi_candidate("trivial", 600.0)
        assert skip is True
        assert "complexity" in reason.lower()

    def test_simple_complexity_skips(self, agent):
        skip, reason = agent._should_skip_multi_candidate("simple", 600.0)
        assert skip is True
        assert "complexity" in reason.lower()

    def test_simple_uppercase_skips(self, agent):
        skip, reason = agent._should_skip_multi_candidate("SIMPLE", 600.0)
        assert skip is True

    def test_moderate_does_not_skip(self, agent):
        """MODERATE complexity should not skip MC."""
        with patch("core.qwencode_agent.sys") as mock_sys:
            mock_sys.platform = "linux"
            skip, reason = agent._should_skip_multi_candidate("moderate", 600.0)
            assert skip is False

    def test_complex_does_not_skip(self, agent):
        """COMPLEX complexity should not skip MC with high budget."""
        with patch("core.qwencode_agent.sys") as mock_sys:
            mock_sys.platform = "linux"
            skip, reason = agent._should_skip_multi_candidate("complex", 600.0)
            assert skip is False

    def test_low_budget_skips(self, agent):
        """Budget < 180s should skip MC regardless of complexity."""
        skip, reason = agent._should_skip_multi_candidate("complex", 100.0)
        assert skip is True
        assert "budget" in reason.lower()

    def test_budget_exactly_180_does_not_skip(self, agent):
        """Budget == 180s should not skip (boundary)."""
        with patch("core.qwencode_agent.sys") as mock_sys:
            mock_sys.platform = "linux"
            skip, reason = agent._should_skip_multi_candidate("complex", 180.0)
            assert skip is False

    def test_windows_cpu_7b_low_budget_skips(self, agent):
        """Windows + 7B + budget < 600 → skip."""
        skip, reason = agent._should_skip_multi_candidate("complex", 400.0)
        assert skip is True
        assert "Windows" in reason

    def test_windows_cpu_7b_high_budget_no_skip(self, agent):
        """Windows + 7B + budget >= 600 → no skip."""
        skip, reason = agent._should_skip_multi_candidate("complex", 600.0)
        assert skip is False
        assert reason == ""

    def test_returns_tuple(self, agent):
        """Return value is always a (bool, str) tuple."""
        result = agent._should_skip_multi_candidate("complex", 600.0)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], bool)
        assert isinstance(result[1], str)

    def test_trinity_override_never_skips(self, agent):
        """Week 29: When Trinity is enabled, NEVER skip MC pipeline."""
        trinity = MagicMock()
        trinity.enabled = True
        agent.trinity_manager = trinity
        # Even TRIVIAL with low budget should NOT skip
        skip, reason = agent._should_skip_multi_candidate("trivial", 50.0)
        assert skip is False
        assert "trinity" in reason.lower()

    def test_trinity_disabled_still_skips(self, agent):
        """When Trinity is disabled, normal skip rules apply."""
        trinity = MagicMock()
        trinity.enabled = False
        agent.trinity_manager = trinity
        skip, reason = agent._should_skip_multi_candidate("trivial", 600.0)
        assert skip is True


# ---------------------------------------------------------------------------
# Level 1: _compute_mc_timeout() tests
# ---------------------------------------------------------------------------

class TestComputeMcTimeout:
    """Tests for adaptive MC timeout calculation."""

    @pytest.fixture
    def agent(self):
        from core.qwencode_agent import QwenCodeAgent
        mock_agent = MagicMock()
        mock_config = MagicMock()
        mock_config.total_timeout = 1200.0
        mock_agent.multi_candidate_pipeline = MagicMock()
        mock_agent.multi_candidate_pipeline.config.generation_config = mock_config
        mock_agent._compute_mc_timeout = QwenCodeAgent._compute_mc_timeout.__get__(mock_agent)
        return mock_agent

    def test_respects_budget(self, agent):
        """MC timeout should be at most 80% of remaining budget."""
        timeout = agent._compute_mc_timeout(500.0)
        assert timeout <= 500.0 * 0.8
        assert timeout == 400.0  # min(1200, 500*0.8) = 400

    def test_respects_configured_ceiling(self, agent):
        """MC timeout should not exceed configured total_timeout."""
        timeout = agent._compute_mc_timeout(2000.0)
        assert timeout == 1200.0  # min(1200, 2000*0.8=1600) = 1200

    def test_low_budget_scales_down(self, agent):
        """Low budget → proportionally lower timeout."""
        timeout = agent._compute_mc_timeout(200.0)
        assert timeout == 160.0  # 200 * 0.8

    def test_no_generation_config_uses_default(self):
        """When no generation_config, uses 1200s default."""
        from core.qwencode_agent import QwenCodeAgent
        mock_agent = MagicMock()
        mock_agent.multi_candidate_pipeline = MagicMock()
        mock_agent.multi_candidate_pipeline.config.generation_config = None
        mock_agent._compute_mc_timeout = QwenCodeAgent._compute_mc_timeout.__get__(mock_agent)
        timeout = mock_agent._compute_mc_timeout(500.0)
        assert timeout == 400.0  # min(1200, 500*0.8)


# ---------------------------------------------------------------------------
# Stats tracking tests
# ---------------------------------------------------------------------------

class TestStatsTracking:
    """Tests for new Week 27 stats keys."""

    def test_stats_keys_in_source(self):
        """New stats keys should be present in agent source code."""
        import inspect
        from core.qwencode_agent import QwenCodeAgent
        source = inspect.getsource(QwenCodeAgent)
        assert '"multi_candidate_skips"' in source
        assert '"multi_candidate_budget_fallbacks"' in source


# ---------------------------------------------------------------------------
# Integration: combined scenarios
# ---------------------------------------------------------------------------

class TestAdaptiveBudgetIntegration:
    """Integration tests for the full adaptive budget flow."""

    def test_trivial_task_full_flow(self):
        """Trivial task → skip MC → strategy returns 1 candidate anyway."""
        from core.generation.adaptive_strategy import AdaptiveStrategy
        strategy = AdaptiveStrategy(persist=False)
        config = strategy.get_strategy("write hello world")
        assert config.n_candidates == 1
        assert config.complexity.value == "trivial"

        # Platform adaptation should be no-op for 1 candidate
        with patch("core.generation.adaptive_strategy.sys") as mock_sys, \
             patch("core.generation.adaptive_strategy.os") as mock_os:
            mock_sys.platform = "win32"
            mock_os.cpu_count.return_value = 4
            adapted = strategy.adapt_for_platform(config, "qwen2.5-coder:7b", 200.0)
            assert adapted.n_candidates == 1

    def test_complex_task_on_weak_hardware(self):
        """Complex task + weak hardware → candidates reduced."""
        from core.generation.adaptive_strategy import AdaptiveStrategy
        strategy = AdaptiveStrategy(persist=False)
        config = strategy.get_strategy("implement JWT auth middleware with database ORM integration")
        assert config.complexity.value == "complex" or config.complexity.value == "critical"
        assert config.n_candidates >= 2  # complex/critical = 3

        with patch("core.generation.adaptive_strategy.sys") as mock_sys, \
             patch("core.generation.adaptive_strategy.os") as mock_os:
            mock_sys.platform = "win32"
            mock_os.cpu_count.return_value = 8
            adapted = strategy.adapt_for_platform(config, "qwen2.5-coder:7b", 600.0)
            assert adapted.n_candidates == 1  # Windows + 7B → 1

    def test_complex_task_on_strong_hardware(self):
        """Complex task + strong hardware + large budget → no reduction."""
        from core.generation.adaptive_strategy import AdaptiveStrategy
        strategy = AdaptiveStrategy(persist=False)
        config = strategy.get_strategy("implement JWT auth middleware with database ORM integration")

        with patch("core.generation.adaptive_strategy.sys") as mock_sys, \
             patch("core.generation.adaptive_strategy.os") as mock_os:
            mock_sys.platform = "linux"
            mock_os.cpu_count.return_value = 32
            adapted = strategy.adapt_for_platform(config, "qwen2.5-coder:7b", 1200.0)
            assert adapted.n_candidates == config.n_candidates

    def test_budget_boundary_120s(self):
        """Budget exactly 120s → 1 candidate (120/120=1)."""
        from core.generation.adaptive_strategy import AdaptiveStrategy
        strategy = AdaptiveStrategy(persist=False)
        config = strategy.get_strategy("implement JWT auth middleware with database ORM integration")

        with patch("core.generation.adaptive_strategy.sys") as mock_sys, \
             patch("core.generation.adaptive_strategy.os") as mock_os:
            mock_sys.platform = "linux"
            mock_os.cpu_count.return_value = 32
            adapted = strategy.adapt_for_platform(config, "qwen2.5-coder:7b", 120.0)
            assert adapted.n_candidates == 1

    def test_budget_360s_allows_3_candidates(self):
        """Budget 360s → max 3 candidates (360/120=3)."""
        from core.generation.adaptive_strategy import AdaptiveStrategy
        strategy = AdaptiveStrategy(persist=False)
        config = strategy.get_strategy("implement JWT auth middleware with database ORM integration")

        with patch("core.generation.adaptive_strategy.sys") as mock_sys, \
             patch("core.generation.adaptive_strategy.os") as mock_os:
            mock_sys.platform = "linux"
            mock_os.cpu_count.return_value = 32
            adapted = strategy.adapt_for_platform(config, "qwen2.5-coder:7b", 360.0)
            assert adapted.n_candidates <= 3

    def test_multiple_constraints_combined(self):
        """Windows + low CPU + tight budget → first matching constraint wins."""
        from core.generation.adaptive_strategy import AdaptiveStrategy
        strategy = AdaptiveStrategy(persist=False)
        config = strategy.get_strategy("implement JWT auth middleware with database ORM integration")

        with patch("core.generation.adaptive_strategy.sys") as mock_sys, \
             patch("core.generation.adaptive_strategy.os") as mock_os:
            mock_sys.platform = "win32"
            mock_os.cpu_count.return_value = 4
            adapted = strategy.adapt_for_platform(config, "qwen2.5-coder:7b", 200.0)
            assert adapted.n_candidates == 1
            # Windows CPU is the first constraint that fires
            assert "Windows CPU" in adapted.reasoning
            assert "Platform:" in adapted.reasoning
