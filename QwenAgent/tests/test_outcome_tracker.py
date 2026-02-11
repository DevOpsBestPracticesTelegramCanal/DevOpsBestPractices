"""
Week 13: Outcome Feedback Loop Tests

~35 tests covering:
- OutcomeRecord creation and defaults
- OutcomeTracker CRUD (record, query, cleanup)
- Profile stats analytics
- Rule effectiveness analytics
- Task type stats
- Risk accuracy analytics
- Profile suggestion (historical learning)
- Cleanup and TTL
- Stats and observability
"""

import time
import pytest

from core.outcome_tracker import (
    OutcomeTracker,
    OutcomeRecord,
    _query_hash,
)


@pytest.fixture
def tracker():
    """In-memory OutcomeTracker for tests."""
    t = OutcomeTracker(db_path=":memory:")
    yield t
    t.close()


def _make_record(**kwargs) -> OutcomeRecord:
    """Helper to create OutcomeRecord with sensible defaults."""
    defaults = {
        "query_hash": _query_hash("test query"),
        "task_type": "code_gen",
        "risk_level": "medium",
        "validation_profile": "balanced",
        "complexity": "MODERATE",
        "n_candidates": 2,
        "best_score": 0.85,
        "all_passed": True,
        "generation_time": 24.0,
        "validation_time": 0.5,
        "total_time": 25.0,
        "rules_run": "ast_syntax,no_eval_exec,complexity",
        "rules_passed": "ast_syntax,no_eval_exec",
        "rules_failed": "complexity",
        "n_rules_run": 3,
        "n_rules_passed": 2,
        "n_rules_failed": 1,
    }
    defaults.update(kwargs)
    return OutcomeRecord(**defaults)


# ============================================================
# TestOutcomeRecord — dataclass basics
# ============================================================

class TestOutcomeRecord:
    """OutcomeRecord dataclass behavior."""

    def test_defaults(self):
        r = OutcomeRecord()
        assert r.task_type == "general"
        assert r.risk_level == "medium"
        assert r.validation_profile == "balanced"
        assert r.best_score == 0.0
        assert r.all_passed is False

    def test_timestamp_auto(self):
        before = time.time()
        r = OutcomeRecord()
        after = time.time()
        assert before <= r.timestamp <= after

    def test_custom_fields(self):
        r = _make_record(task_type="bug_fix", risk_level="high")
        assert r.task_type == "bug_fix"
        assert r.risk_level == "high"
        assert r.n_rules_run == 3


class TestQueryHash:
    """_query_hash utility."""

    def test_consistent(self):
        assert _query_hash("hello") == _query_hash("hello")

    def test_different_inputs(self):
        assert _query_hash("hello") != _query_hash("world")

    def test_length(self):
        h = _query_hash("test query")
        assert len(h) == 12


# ============================================================
# TestRecord — CRUD operations
# ============================================================

class TestRecord:
    """Recording and retrieving outcomes."""

    def test_record_returns_id(self, tracker):
        r = _make_record()
        row_id = tracker.record(r)
        assert row_id >= 1

    def test_record_increments_total(self, tracker):
        assert tracker.get_total_outcomes() == 0
        tracker.record(_make_record())
        assert tracker.get_total_outcomes() == 1
        tracker.record(_make_record())
        assert tracker.get_total_outcomes() == 2

    def test_record_multiple_profiles(self, tracker):
        tracker.record(_make_record(validation_profile="fast_dev"))
        tracker.record(_make_record(validation_profile="balanced"))
        tracker.record(_make_record(validation_profile="critical"))
        assert tracker.get_total_outcomes() == 3


# ============================================================
# TestProfileStats — per-profile analytics
# ============================================================

class TestProfileStats:
    """get_profile_stats() analytics."""

    def test_empty_db(self, tracker):
        stats = tracker.get_profile_stats()
        assert stats == {}

    def test_single_profile(self, tracker):
        tracker.record(_make_record(validation_profile="balanced", best_score=0.9))
        tracker.record(_make_record(validation_profile="balanced", best_score=0.8))
        stats = tracker.get_profile_stats()
        assert "balanced" in stats
        assert stats["balanced"]["count"] == 2
        assert stats["balanced"]["avg_score"] == 0.85

    def test_multiple_profiles(self, tracker):
        tracker.record(_make_record(validation_profile="fast_dev", best_score=0.95))
        tracker.record(_make_record(validation_profile="critical", best_score=0.7))
        stats = tracker.get_profile_stats()
        assert len(stats) == 2
        assert stats["fast_dev"]["avg_score"] == 0.95
        assert stats["critical"]["avg_score"] == 0.7

    def test_success_rate(self, tracker):
        tracker.record(_make_record(validation_profile="balanced", all_passed=True))
        tracker.record(_make_record(validation_profile="balanced", all_passed=True))
        tracker.record(_make_record(validation_profile="balanced", all_passed=False))
        stats = tracker.get_profile_stats()
        # 2 out of 3 passed
        assert abs(stats["balanced"]["success_rate"] - 0.6667) < 0.01

    def test_avg_time(self, tracker):
        tracker.record(_make_record(validation_profile="fast_dev", total_time=1.0))
        tracker.record(_make_record(validation_profile="fast_dev", total_time=3.0))
        stats = tracker.get_profile_stats()
        assert stats["fast_dev"]["avg_time"] == 2.0


# ============================================================
# TestRuleEffectiveness — per-rule analytics
# ============================================================

class TestRuleEffectiveness:
    """get_rule_effectiveness() analytics."""

    def test_empty_db(self, tracker):
        stats = tracker.get_rule_effectiveness()
        assert stats == {}

    def test_single_outcome(self, tracker):
        tracker.record(_make_record(
            rules_run="ast_syntax,no_eval_exec",
            rules_passed="ast_syntax",
            rules_failed="no_eval_exec",
        ))
        stats = tracker.get_rule_effectiveness()
        assert "ast_syntax" in stats
        assert stats["ast_syntax"]["times_run"] == 1
        assert stats["ast_syntax"]["times_passed"] == 1
        assert stats["ast_syntax"]["times_failed"] == 0
        assert stats["no_eval_exec"]["times_failed"] == 1
        assert stats["no_eval_exec"]["fail_rate"] == 1.0

    def test_multiple_outcomes(self, tracker):
        tracker.record(_make_record(
            rules_run="ast_syntax",
            rules_passed="ast_syntax",
            rules_failed="",
        ))
        tracker.record(_make_record(
            rules_run="ast_syntax",
            rules_passed="",
            rules_failed="ast_syntax",
        ))
        stats = tracker.get_rule_effectiveness()
        assert stats["ast_syntax"]["times_run"] == 2
        assert stats["ast_syntax"]["times_passed"] == 1
        assert stats["ast_syntax"]["times_failed"] == 1
        assert stats["ast_syntax"]["fail_rate"] == 0.5


# ============================================================
# TestTaskTypeStats — per-task-type analytics
# ============================================================

class TestTaskTypeStats:
    """get_task_type_stats() analytics."""

    def test_empty_db(self, tracker):
        stats = tracker.get_task_type_stats()
        assert stats == {}

    def test_multiple_types(self, tracker):
        tracker.record(_make_record(task_type="code_gen", best_score=0.9))
        tracker.record(_make_record(task_type="code_gen", best_score=0.8))
        tracker.record(_make_record(task_type="bug_fix", best_score=0.7))
        stats = tracker.get_task_type_stats()
        assert stats["code_gen"]["count"] == 2
        assert stats["code_gen"]["avg_score"] == 0.85
        assert stats["bug_fix"]["count"] == 1


# ============================================================
# TestRiskAccuracy — risk level analytics
# ============================================================

class TestRiskAccuracy:
    """get_risk_accuracy() analytics."""

    def test_empty_db(self, tracker):
        stats = tracker.get_risk_accuracy()
        assert stats == {}

    def test_risk_levels(self, tracker):
        tracker.record(_make_record(risk_level="low", best_score=0.95, all_passed=True))
        tracker.record(_make_record(risk_level="critical", best_score=0.6, all_passed=False))
        stats = tracker.get_risk_accuracy()
        assert stats["low"]["avg_score"] == 0.95
        assert stats["low"]["success_rate"] == 1.0
        assert stats["critical"]["avg_score"] == 0.6
        assert stats["critical"]["success_rate"] == 0.0


# ============================================================
# TestSuggestProfile — historical learning
# ============================================================

class TestSuggestProfile:
    """suggest_profile() based on historical outcomes."""

    def test_no_data(self, tracker):
        result = tracker.suggest_profile("code_gen", "MODERATE")
        assert result is None

    def test_insufficient_data(self, tracker):
        """Needs >= 3 outcomes to suggest."""
        tracker.record(_make_record(task_type="code_gen", complexity="MODERATE",
                                     validation_profile="balanced", best_score=0.9))
        tracker.record(_make_record(task_type="code_gen", complexity="MODERATE",
                                     validation_profile="balanced", best_score=0.8))
        result = tracker.suggest_profile("code_gen", "MODERATE")
        assert result is None  # only 2 outcomes

    def test_suggests_best_profile(self, tracker):
        """With enough data, suggests the highest-scoring profile."""
        for _ in range(3):
            tracker.record(_make_record(
                task_type="code_gen", complexity="MODERATE",
                validation_profile="balanced", best_score=0.8,
            ))
        for _ in range(3):
            tracker.record(_make_record(
                task_type="code_gen", complexity="MODERATE",
                validation_profile="fast_dev", best_score=0.95,
            ))
        result = tracker.suggest_profile("code_gen", "MODERATE")
        assert result == "fast_dev"

    def test_different_task_types_isolated(self, tracker):
        """Suggestions are scoped to task_type + complexity."""
        for _ in range(3):
            tracker.record(_make_record(
                task_type="code_gen", complexity="MODERATE",
                validation_profile="balanced", best_score=0.9,
            ))
        for _ in range(3):
            tracker.record(_make_record(
                task_type="bug_fix", complexity="COMPLEX",
                validation_profile="critical", best_score=0.7,
            ))
        assert tracker.suggest_profile("code_gen", "MODERATE") == "balanced"
        assert tracker.suggest_profile("bug_fix", "COMPLEX") == "critical"


# ============================================================
# TestCleanup — TTL and maintenance
# ============================================================

class TestCleanup:
    """cleanup_old() TTL-based cleanup."""

    def test_cleanup_removes_old(self, tracker):
        old = _make_record()
        old.timestamp = time.time() - 100
        tracker.record(old)
        tracker.record(_make_record())  # fresh
        assert tracker.get_total_outcomes() == 2
        deleted = tracker.cleanup_old(max_age_seconds=50)
        assert deleted == 1
        assert tracker.get_total_outcomes() == 1

    def test_cleanup_nothing_to_delete(self, tracker):
        tracker.record(_make_record())
        deleted = tracker.cleanup_old(max_age_seconds=86400)
        assert deleted == 0


# ============================================================
# TestStats — overall observability
# ============================================================

class TestStats:
    """get_stats() overall tracker statistics."""

    def test_empty_stats(self, tracker):
        stats = tracker.get_stats()
        assert stats["total_outcomes"] == 0
        assert stats["avg_score"] == 0
        assert stats["success_rate"] == 0.0

    def test_populated_stats(self, tracker):
        tracker.record(_make_record(best_score=0.9, all_passed=True, total_time=10.0))
        tracker.record(_make_record(best_score=0.7, all_passed=False, total_time=20.0))
        stats = tracker.get_stats()
        assert stats["total_outcomes"] == 2
        assert stats["avg_score"] == 0.8
        assert stats["avg_time"] == 15.0
        assert stats["success_rate"] == 0.5
        assert stats["ttl_days"] == 30

    def test_db_path_in_stats(self, tracker):
        stats = tracker.get_stats()
        assert stats["db_path"] == ":memory:"
