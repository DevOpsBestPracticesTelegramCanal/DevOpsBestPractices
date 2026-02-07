"""Tests for Cross-Architecture Review module."""

import json
import time
import pytest
from unittest.mock import patch, MagicMock

from core.cross_arch_review import (
    CrossArchReviewer,
    CircuitBreaker,
    CircuitState,
    CostTracker,
    ReviewIssue,
    ReviewResult,
    ReviewSeverity,
    HAS_ANTHROPIC,
)


# ---------------------------------------------------------------------------
# TestShouldReview
# ---------------------------------------------------------------------------

class TestShouldReview:
    """Test should_review() gating logic."""

    def _make_reviewer(self, enabled=True):
        """Create reviewer with mocked anthropic client."""
        with patch("core.cross_arch_review.HAS_ANTHROPIC", True):
            r = CrossArchReviewer.__new__(CrossArchReviewer)
            r._enabled = enabled
            r._client = MagicMock() if enabled else None
            r.circuit_breaker = CircuitBreaker()
            r.cost_tracker = CostTracker(monthly_budget=5.0)
            r._review_count = 0
            r._issues_found = 0
            import threading
            r._lock = threading.Lock()
            return r

    def test_disabled_reviewer_returns_false(self):
        r = self._make_reviewer(enabled=False)
        assert r.should_review(swecas_code=500) is False

    def test_security_swecas_triggers_review(self):
        r = self._make_reviewer()
        assert r.should_review(swecas_code=500) is True

    def test_infra_swecas_triggers_review(self):
        r = self._make_reviewer()
        assert r.should_review(swecas_code=900) is True

    def test_performance_swecas_triggers_review(self):
        r = self._make_reviewer()
        assert r.should_review(swecas_code=700) is True

    def test_non_critical_swecas_no_review(self):
        r = self._make_reviewer()
        assert r.should_review(swecas_code=100, code="x = 1") is False

    def test_force_overrides_swecas(self):
        r = self._make_reviewer()
        assert r.should_review(swecas_code=100, force=True) is True

    def test_long_code_triggers_review(self):
        r = self._make_reviewer()
        code = "\n".join(f"line_{i} = {i}" for i in range(60))
        assert r.should_review(code=code) is True

    def test_circuit_breaker_blocks(self):
        r = self._make_reviewer()
        # Trip circuit breaker
        for _ in range(3):
            r.circuit_breaker.record_failure()
        assert r.should_review(swecas_code=500) is False


# ---------------------------------------------------------------------------
# TestCircuitBreaker
# ---------------------------------------------------------------------------

class TestCircuitBreaker:

    def test_starts_closed(self):
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request() is True

    def test_opens_after_threshold(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.CLOSED
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.allow_request() is False

    def test_half_open_after_cooldown(self):
        cb = CircuitBreaker(failure_threshold=1, cooldown_sec=0.1)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN
        assert cb.allow_request() is True

    def test_success_closes_from_half_open(self):
        cb = CircuitBreaker(failure_threshold=1, cooldown_sec=0.01)
        cb.record_failure()
        time.sleep(0.02)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_failure_in_half_open_reopens(self):
        cb = CircuitBreaker(failure_threshold=1, cooldown_sec=0.01)
        cb.record_failure()
        time.sleep(0.02)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_reset(self):
        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request() is True


# ---------------------------------------------------------------------------
# TestCostTracker
# ---------------------------------------------------------------------------

class TestCostTracker:

    def test_starts_with_full_budget(self):
        ct = CostTracker(monthly_budget=5.0)
        assert ct.has_budget() is True
        assert ct.remaining_budget == 5.0

    def test_recording_reduces_budget(self):
        ct = CostTracker(monthly_budget=0.001)
        ct.record(input_tokens=100_000, output_tokens=100_000)
        # Should have used some budget
        assert ct.total_cost > 0

    def test_budget_exhaustion(self):
        ct = CostTracker(monthly_budget=0.0001)
        ct.record(input_tokens=10_000_000, output_tokens=10_000_000)
        assert ct.has_budget() is False


# ---------------------------------------------------------------------------
# TestParseResponse
# ---------------------------------------------------------------------------

class TestParseResponse:

    def test_valid_json_array(self):
        text = json.dumps([
            {"severity": "critical", "category": "security", "description": "SQL injection", "line": 5, "suggestion": "Use parameterized queries"},
            {"severity": "warning", "category": "performance", "description": "O(n^2) loop"},
        ])
        issues = CrossArchReviewer._parse_review_response(text)
        assert len(issues) == 2
        assert issues[0].severity == ReviewSeverity.CRITICAL
        assert issues[0].category == "security"
        assert issues[1].severity == ReviewSeverity.WARNING

    def test_markdown_fenced_json(self):
        text = '```json\n[{"severity": "info", "category": "style", "description": "missing docstring"}]\n```'
        issues = CrossArchReviewer._parse_review_response(text)
        assert len(issues) == 1
        assert issues[0].severity == ReviewSeverity.INFO

    def test_empty_array(self):
        issues = CrossArchReviewer._parse_review_response("[]")
        assert issues == []

    def test_invalid_json_returns_empty(self):
        issues = CrossArchReviewer._parse_review_response("not json at all")
        assert issues == []


# ---------------------------------------------------------------------------
# TestReviewResult
# ---------------------------------------------------------------------------

class TestReviewResult:

    def test_has_critical_true(self):
        result = ReviewResult(issues=[
            ReviewIssue(severity=ReviewSeverity.CRITICAL, category="security", description="RCE"),
        ])
        assert result.has_critical is True

    def test_has_critical_false(self):
        result = ReviewResult(issues=[
            ReviewIssue(severity=ReviewSeverity.WARNING, category="style", description="naming"),
        ])
        assert result.has_critical is False

    def test_summary_includes_counts(self):
        result = ReviewResult(
            issues=[
                ReviewIssue(severity=ReviewSeverity.CRITICAL, category="security", description="a"),
                ReviewIssue(severity=ReviewSeverity.WARNING, category="perf", description="b"),
                ReviewIssue(severity=ReviewSeverity.INFO, category="style", description="c"),
            ],
            model="haiku",
            cost_usd=0.001,
        )
        s = result.summary()
        assert "3 issues" in s
        assert "1 critical" in s
        assert "1 warning" in s
        assert "1 info" in s

    def test_skipped_result(self):
        result = ReviewResult(skipped=True, skip_reason="no api key")
        assert "skipped" in result.summary().lower()
        assert result.has_critical is False


# ---------------------------------------------------------------------------
# TestReview (with mocked Anthropic API)
# ---------------------------------------------------------------------------

class TestReview:

    def _make_reviewer_with_mock(self):
        """Create a reviewer with a mocked anthropic client."""
        r = CrossArchReviewer.__new__(CrossArchReviewer)
        r._enabled = True
        r._client = MagicMock()
        r.circuit_breaker = CircuitBreaker()
        r.cost_tracker = CostTracker(monthly_budget=5.0)
        r._review_count = 0
        r._issues_found = 0
        import threading
        r._lock = threading.Lock()
        return r

    def _mock_response(self, text="[]", input_tokens=100, output_tokens=50):
        resp = MagicMock()
        resp.usage.input_tokens = input_tokens
        resp.usage.output_tokens = output_tokens
        content_block = MagicMock()
        content_block.text = text
        resp.content = [content_block]
        return resp

    def test_successful_review(self):
        r = self._make_reviewer_with_mock()
        issues_json = json.dumps([
            {"severity": "warning", "category": "correctness", "description": "off by one"},
        ])
        r._client.messages.create.return_value = self._mock_response(text=issues_json)

        result = r.review(code="def foo(): pass", query="test")
        assert not result.skipped
        assert len(result.issues) == 1
        assert result.issues[0].severity == ReviewSeverity.WARNING
        assert result.cost_usd > 0

    def test_api_error_records_failure(self):
        r = self._make_reviewer_with_mock()
        r._client.messages.create.side_effect = RuntimeError("API down")

        result = r.review(code="def foo(): pass")
        assert result.skipped is True
        assert "API error" in result.skip_reason
        # Circuit breaker should have recorded a failure
        assert r.circuit_breaker._failure_count == 1

    def test_cost_tracked(self):
        r = self._make_reviewer_with_mock()
        r._client.messages.create.return_value = self._mock_response(
            input_tokens=500, output_tokens=200
        )
        result = r.review(code="x = 1")
        assert result.input_tokens == 500
        assert result.output_tokens == 200
        assert r.cost_tracker.total_cost > 0

    def test_disabled_review_returns_skipped(self):
        r = self._make_reviewer_with_mock()
        r._enabled = False
        result = r.review(code="x = 1")
        assert result.skipped is True

    def test_stats_updated(self):
        r = self._make_reviewer_with_mock()
        r._client.messages.create.return_value = self._mock_response(
            text='[{"severity": "info", "category": "style", "description": "ok"}]'
        )
        r.review(code="x = 1")
        stats = r.get_stats()
        assert stats["review_count"] == 1
        assert stats["issues_found"] == 1
