"""Tests for Candidate and CandidatePool data structures."""

import pytest
from core.generation.candidate import (
    Candidate,
    CandidatePool,
    CandidateStatus,
    ValidationScore,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_candidate(cid: int = 0, code: str = "def f(): pass") -> Candidate:
    return Candidate(
        id=cid,
        task_id="test",
        code=code,
        temperature=0.5,
        seed=42 + cid,
        model="test-model",
    )


def _make_score(name: str = "test", passed: bool = True, score: float = 0.8) -> ValidationScore:
    return ValidationScore(
        validator_name=name,
        passed=passed,
        score=score,
        errors=[] if passed else ["error"],
    )


# ---------------------------------------------------------------------------
# Candidate tests
# ---------------------------------------------------------------------------

class TestCandidate:
    def test_initial_state(self):
        c = _make_candidate()
        assert c.status == CandidateStatus.GENERATED
        assert c.total_score == 0.0
        assert not c.has_critical_errors
        assert not c.all_passed  # no validations yet

    def test_add_validation_updates_score(self):
        c = _make_candidate()
        c.add_validation(_make_score("a", True, 0.9))
        assert c.total_score == pytest.approx(0.9)
        assert c.all_passed

    def test_multiple_validations_weighted(self):
        c = _make_candidate()
        c.add_validation(ValidationScore("a", True, 1.0, weight=2.0))
        c.add_validation(ValidationScore("b", True, 0.5, weight=1.0))
        # weighted avg = (1.0*2 + 0.5*1) / (2+1) = 2.5/3 ≈ 0.833
        assert c.total_score == pytest.approx(2.5 / 3, abs=0.01)

    def test_critical_error_penalty(self):
        c = _make_candidate()
        c.add_validation(_make_score("ok", True, 0.9))
        c.add_validation(ValidationScore("bad", False, 0.0, errors=["crash"]))
        # One critical error → ×0.5
        assert c.total_score < 0.5
        assert c.has_critical_errors

    def test_code_lines(self):
        c = _make_candidate(code="line1\nline2\nline3")
        assert c.code_lines == 3

    def test_to_dict_has_keys(self):
        c = _make_candidate()
        d = c.to_dict()
        assert "id" in d
        assert "total_score" in d
        assert "status" in d
        assert d["status"] == "generated"


# ---------------------------------------------------------------------------
# CandidatePool tests
# ---------------------------------------------------------------------------

class TestCandidatePool:
    def test_empty_pool_raises(self):
        pool = CandidatePool(task_id="t")
        with pytest.raises(ValueError, match="No candidates"):
            pool.select_best()

    def test_select_best_picks_highest_score(self):
        pool = CandidatePool(task_id="t")
        for i in range(3):
            c = _make_candidate(cid=i)
            c.add_validation(_make_score("v", True, 0.3 * (i + 1)))
            pool.add(c)

        best = pool.select_best()
        assert best.id == 2  # highest score
        assert best.status == CandidateStatus.SELECTED

    def test_rejected_candidates_marked(self):
        pool = CandidatePool(task_id="t")
        for i in range(3):
            c = _make_candidate(cid=i)
            c.add_validation(_make_score("v", True, 0.5))
            pool.add(c)

        pool.select_best()
        rejected = [c for c in pool.candidates if c.status == CandidateStatus.REJECTED]
        assert len(rejected) == 2

    def test_stats(self):
        pool = CandidatePool(task_id="t")
        for i in range(3):
            c = _make_candidate(cid=i)
            c.add_validation(_make_score("v", True, 0.5 + i * 0.1))
            c.generation_time = 1.0 + i
            pool.add(c)

        s = pool.stats()
        assert s["total"] == 3
        assert s["passed_count"] == 3
        assert s["avg_generation_time"] == pytest.approx(2.0)
