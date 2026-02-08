"""
Tests for Week 3: Multi-Candidate Pipeline integration into QwenCodeAgent.
"""

import pytest
from unittest.mock import patch, MagicMock
from core.qwencode_agent import QwenCodeAgent, QwenCodeConfig, HAS_MULTI_CANDIDATE


class TestMultiCandidateHeuristic:
    """Test _is_code_generation_task() heuristic."""

    @pytest.fixture
    def agent(self):
        with patch.object(QwenCodeAgent, '__init__', lambda self, *a, **kw: None):
            a = QwenCodeAgent.__new__(QwenCodeAgent)
            # Minimal init for heuristic test
            a.config = QwenCodeConfig()
            a.multi_candidate_pipeline = None
            a.stats = {}
            return a

    @pytest.mark.parametrize("query", [
        "Write a function to sort a list",
        "Create a Dockerfile for Flask app",
        "Implement binary search in Python",
        "Generate code for a REST API",
        "write python script for data processing",
        "write dockerfile for nginx",
        "write terraform module for AWS",
        "write test for login function",
    ])
    def test_code_gen_detected(self, agent, query):
        assert agent._is_code_generation_task(query) is True

    @pytest.mark.parametrize("query", [
        "Read file main.py",
        "Edit line 5 in foo.py",
        "Explain what this code does",
        "ls core/",
        "fix in app.py the import error",
        "modify config.yaml to add logging",
        "show me the file structure",
        "what is a decorator?",
        "run the tests",
    ])
    def test_non_code_gen_rejected(self, agent, query):
        assert agent._is_code_generation_task(query) is False


class TestMultiCandidateInit:
    """Test that Multi-Candidate pipeline initializes in agent."""

    def test_has_multi_candidate_flag(self):
        assert HAS_MULTI_CANDIDATE is True, "generation package must be importable"

    def test_pipeline_initialized(self):
        agent = QwenCodeAgent(QwenCodeConfig(model="qwen2.5-coder:7b"))
        assert agent.multi_candidate_pipeline is not None
        assert agent.stats["multi_candidate_runs"] == 0
        assert agent.stats["multi_candidate_fallbacks"] == 0


class TestMultiCandidateStreamIntegration:
    """Test process_stream() Multi-Candidate path with mocked pipeline."""

    def test_mc_path_yields_events(self):
        """When pipeline succeeds, process_stream yields multi_candidate events."""
        agent = QwenCodeAgent(QwenCodeConfig(model="qwen2.5-coder:7b"))

        # Mock the pipeline
        mock_result = MagicMock()
        mock_result.code = "def factorial(n):\n    return 1 if n <= 1 else n * factorial(n-1)"
        mock_result.score = 0.92
        mock_result.all_passed = True
        mock_result.best = MagicMock()
        mock_result.best.validation_scores = []
        mock_result.summary.return_value = {
            "candidates_generated": 3,
            "best_score": 0.92,
            "all_passed": True,
        }

        agent.multi_candidate_pipeline.run_sync = MagicMock(return_value=mock_result)

        events = list(agent.process_stream("Write a function to compute factorial"))
        event_types = [e.get("event") for e in events]

        assert "status" in event_types
        assert "tool_start" in event_types
        assert "tool_result" in event_types
        assert "response" in event_types
        assert "done" in event_types

        # Check the response event has multi_candidate route
        response_evt = next(e for e in events if e.get("event") == "response")
        assert response_evt["route_method"] == "multi_candidate"
        assert "factorial" in response_evt["text"]

        # Check stats
        assert agent.stats["multi_candidate_runs"] == 1

    def test_mc_fallback_on_error(self):
        """When pipeline fails, process_stream falls back to LLM path."""
        agent = QwenCodeAgent(QwenCodeConfig(model="qwen2.5-coder:7b"))

        # Mock pipeline to raise
        agent.multi_candidate_pipeline.run_sync = MagicMock(
            side_effect=RuntimeError("Pipeline crashed")
        )

        # Mock _call_llm to avoid actual LLM call
        agent._call_llm = MagicMock(return_value="def factorial(n): pass")

        events = list(agent.process_stream("Write a function to compute factorial"))
        event_types = [e.get("event") for e in events]

        # Should have fallback status and eventually a response
        assert any("falling back" in str(e.get("text", "")).lower() for e in events if e.get("event") == "status")
        assert agent.stats["multi_candidate_fallbacks"] == 1

    def test_non_codegen_skips_mc(self):
        """Non-code-gen queries should NOT go through multi-candidate."""
        agent = QwenCodeAgent(QwenCodeConfig(model="qwen2.5-coder:7b"))

        # Mock to track if pipeline was called
        agent.multi_candidate_pipeline.run_sync = MagicMock()
        agent._call_llm = MagicMock(return_value="The file contains X...")

        events = list(agent.process_stream("Explain what recursion is"))

        # Pipeline should NOT have been called
        agent.multi_candidate_pipeline.run_sync.assert_not_called()


class TestCrossReviewInAgent:
    """Test cross-review SSE events and stats tracking in agent."""

    def test_cross_review_stats_tracked(self):
        agent = QwenCodeAgent(QwenCodeConfig(model="qwen2.5-coder:7b"))

        # Mock pipeline result WITH cross-review
        mock_cr = MagicMock()
        mock_cr.skipped = False
        mock_cr.has_critical = True
        mock_cr.model = "haiku"
        mock_cr.issues = [
            MagicMock(severity=MagicMock(value="critical"), category="security", description="SQL injection"),
        ]
        mock_cr.to_dict.return_value = {"issues": [{"severity": "critical"}], "has_critical": True}

        mock_result = MagicMock()
        mock_result.code = "def foo(): pass"
        mock_result.score = 0.9
        mock_result.all_passed = True
        mock_result.best = MagicMock()
        mock_result.best.validation_scores = []
        mock_result.cross_review_result = mock_cr
        mock_result.summary.return_value = {"candidates_generated": 2, "best_score": 0.9}

        agent.multi_candidate_pipeline.run_sync = MagicMock(return_value=mock_result)

        events = list(agent.process_stream("Write a function to validate user input"))

        assert agent.stats["cross_reviews"] == 1
        assert agent.stats["cross_review_criticals"] == 1

        # Check cross_review tool_result event emitted
        cr_events = [e for e in events if e.get("tool") == "cross_review"]
        assert len(cr_events) >= 1

    def test_no_cross_review_events_when_disabled(self):
        agent = QwenCodeAgent(QwenCodeConfig(model="qwen2.5-coder:7b"))

        mock_result = MagicMock()
        mock_result.code = "def foo(): pass"
        mock_result.score = 0.85
        mock_result.all_passed = True
        mock_result.best = MagicMock()
        mock_result.best.validation_scores = []
        mock_result.cross_review_result = None
        mock_result.summary.return_value = {"candidates_generated": 2}

        agent.multi_candidate_pipeline.run_sync = MagicMock(return_value=mock_result)

        events = list(agent.process_stream("Write a function to compute square root"))

        assert agent.stats["cross_reviews"] == 0
        cr_events = [e for e in events if e.get("tool") == "cross_review"]
        assert len(cr_events) == 0


class TestAdaptivePathInAgent:
    """Test Week 4 adaptive strategy integration in process_stream()."""

    def test_adaptive_passes_temperatures(self):
        """Adaptive config temperatures are forwarded to pipeline.run_sync()."""
        agent = QwenCodeAgent(QwenCodeConfig(model="qwen2.5-coder:7b"))

        mock_result = MagicMock()
        mock_result.code = "def foo(): pass"
        mock_result.score = 0.9
        mock_result.all_passed = True
        mock_result.best = MagicMock()
        mock_result.best.validation_scores = []
        mock_result.cross_review_result = None
        mock_result.total_time = 20.0
        mock_result.summary.return_value = {"candidates_generated": 1}

        agent.multi_candidate_pipeline.run_sync = MagicMock(return_value=mock_result)

        # "Write a function" triggers _is_code_generation_task
        list(agent.process_stream("Write a function for hello world"))

        call_kwargs = agent.multi_candidate_pipeline.run_sync.call_args
        assert call_kwargs is not None, "pipeline.run_sync was not called"
        # Should have temperatures kwarg
        kw = call_kwargs.kwargs if call_kwargs.kwargs else call_kwargs[1]
        assert "temperatures" in kw

    def test_adaptive_records_outcome(self):
        """Adaptive strategy records outcome after successful pipeline run."""
        agent = QwenCodeAgent(QwenCodeConfig(model="qwen2.5-coder:7b"))

        mock_result = MagicMock()
        mock_result.code = "def foo(): pass"
        mock_result.score = 0.85
        mock_result.all_passed = True
        mock_result.best = MagicMock()
        mock_result.best.validation_scores = []
        mock_result.cross_review_result = None
        mock_result.total_time = 25.0
        mock_result.summary.return_value = {"candidates_generated": 1}

        agent.multi_candidate_pipeline.run_sync = MagicMock(return_value=mock_result)

        # Capture history length before call
        history_before = len(agent.adaptive_strategy._history)

        # "Write a function" triggers _is_code_generation_task
        list(agent.process_stream("Write a function for hello world"))

        # Adaptive strategy should have recorded exactly 1 new outcome
        assert len(agent.adaptive_strategy._history) == history_before + 1
