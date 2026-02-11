# -*- coding: utf-8 -*-
"""
Tests for core/generation/selector.py — CandidateSelector & ScoringWeights.
"""

import pytest
from core.generation.candidate import (
    Candidate, CandidatePool, CandidateStatus, ValidationScore,
)
from core.generation.selector import CandidateSelector, ScoringWeights


def _make_candidate(cid, scores=None, code="x=1"):
    """Helper to create a Candidate with validation scores."""
    c = Candidate(id=cid, task_id="t1", code=code,
                  temperature=0.7, seed=42, model="test")
    if scores:
        for name, passed, score, errors in scores:
            c.add_validation(ValidationScore(
                validator_name=name, passed=passed, score=score,
                errors=errors,
            ))
    return c


def _make_pool(*candidates):
    pool = CandidatePool(task_id="t1")
    for c in candidates:
        pool.add(c)
    return pool


# ── ScoringWeights ───────────────────────────────────────────────────────


class TestScoringWeights:
    def test_default_weights_exist(self):
        sw = ScoringWeights()
        assert "ast_syntax" in sw.weights
        assert "static_ruff" in sw.weights

    def test_get_exact_match(self):
        sw = ScoringWeights()
        assert sw.get("ast_syntax") == 10.0

    def test_get_prefix_match(self):
        sw = ScoringWeights()
        assert sw.get("static_ruff_check") == 3.0

    def test_get_unknown_returns_default(self):
        sw = ScoringWeights()
        assert sw.get("nonexistent_validator") == 1.0

    def test_custom_weights(self):
        sw = ScoringWeights(weights={"custom": 5.0})
        assert sw.get("custom") == 5.0

    def test_all_passed_bonus_default(self):
        assert ScoringWeights().all_passed_bonus == 0.15

    def test_critical_error_penalty_default(self):
        assert ScoringWeights().critical_error_penalty == 0.5


# ── CandidateSelector.select ─────────────────────────────────────────────


class TestCandidateSelect:
    def test_empty_pool_raises(self):
        sel = CandidateSelector()
        pool = CandidatePool(task_id="t1")
        with pytest.raises(ValueError, match="Empty"):
            sel.select(pool)

    def test_single_candidate_selected(self):
        c = _make_candidate(1, [("ast_syntax", True, 1.0, [])])
        pool = _make_pool(c)
        winner = CandidateSelector().select(pool)
        assert winner.id == 1
        assert winner.status == CandidateStatus.SELECTED

    def test_best_score_wins(self):
        c1 = _make_candidate(1, [("ast_syntax", True, 0.5, [])])
        c2 = _make_candidate(2, [("ast_syntax", True, 1.0, [])])
        pool = _make_pool(c1, c2)
        winner = CandidateSelector().select(pool)
        assert winner.id == 2

    def test_loser_rejected(self):
        c1 = _make_candidate(1, [("ast_syntax", True, 0.5, [])])
        c2 = _make_candidate(2, [("ast_syntax", True, 1.0, [])])
        pool = _make_pool(c1, c2)
        CandidateSelector().select(pool)
        assert c1.status == CandidateStatus.REJECTED

    def test_pool_best_set(self):
        c1 = _make_candidate(1, [("ast_syntax", True, 1.0, [])])
        pool = _make_pool(c1)
        CandidateSelector().select(pool)
        assert pool.best is c1

    def test_critical_error_penalty(self):
        # c1: all passed, c2: has critical error
        c1 = _make_candidate(1, [("ast_syntax", True, 0.8, [])])
        c2 = _make_candidate(2, [("ast_syntax", False, 0.9, ["SyntaxError"])])
        pool = _make_pool(c1, c2)
        winner = CandidateSelector().select(pool)
        assert winner.id == 1  # c1 wins despite lower raw score

    def test_no_validation_scores_zero(self):
        c = _make_candidate(1)
        pool = _make_pool(c)
        sel = CandidateSelector()
        sel.select(pool)
        assert c.total_score == 0.0


# ── CandidateSelector.rank ───────────────────────────────────────────────


class TestCandidateRank:
    def test_rank_returns_sorted(self):
        c1 = _make_candidate(1, [("v", True, 0.3, [])])
        c2 = _make_candidate(2, [("v", True, 0.9, [])])
        c3 = _make_candidate(3, [("v", True, 0.6, [])])
        pool = _make_pool(c1, c2, c3)
        ranked = CandidateSelector().rank(pool)
        assert [c.id for c in ranked] == [2, 3, 1]

    def test_rank_does_not_modify_status(self):
        c1 = _make_candidate(1, [("v", True, 0.5, [])])
        c2 = _make_candidate(2, [("v", True, 0.9, [])])
        pool = _make_pool(c1, c2)
        CandidateSelector().rank(pool)
        assert c1.status == CandidateStatus.GENERATED
        assert c2.status == CandidateStatus.GENERATED

    def test_rank_three_candidates(self):
        c1 = _make_candidate(1, [("v", True, 1.0, [])])
        c2 = _make_candidate(2, [("v", True, 0.5, [])])
        c3 = _make_candidate(3, [("v", True, 0.7, [])])
        pool = _make_pool(c1, c2, c3)
        ranked = CandidateSelector().rank(pool)
        scores = [c.total_score for c in ranked]
        assert scores == sorted(scores, reverse=True)
