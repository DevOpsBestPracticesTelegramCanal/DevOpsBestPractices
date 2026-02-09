"""
Week 15: Self-Correction Loop Tests

Tests that the self-correction loop:
- Passes through cleanly when first attempt succeeds
- Re-generates with error feedback when validation fails
- Stops after MAX_ITERATIONS
- Stops early when all validators pass
- Correctly extracts and formats validation errors
- Tracks improvement across iterations
- Picks the overall best across all iterations
- Handles pipeline errors gracefully
"""

import time
import pytest
from unittest.mock import MagicMock, patch, call
from dataclasses import dataclass, field
from typing import List, Optional

from core.generation.self_correction import (
    SelfCorrectionLoop,
    CorrectionResult,
    CorrectionAttempt,
    extract_validation_errors,
    build_correction_prompt,
    extract_key_issues,
    MAX_ITERATIONS,
    MIN_SCORE_FOR_CORRECTION,
)
from core.generation.candidate import (
    Candidate,
    CandidatePool,
    CandidateStatus,
    ValidationScore,
)
from core.generation.pipeline import PipelineResult


# ────────────────────────────────────────────────────────────
# Helpers
# ────────────────────────────────────────────────────────────

def _make_candidate(
    score: float = 0.8,
    passed: bool = True,
    errors: Optional[List[str]] = None,
    code: str = "def hello():\n    return 'world'",
) -> Candidate:
    c = Candidate(
        id=0, task_id="test", code=code,
        temperature=0.5, seed=42, model="test",
    )
    vs = ValidationScore(
        validator_name="ast_syntax",
        passed=passed,
        score=score,
        errors=errors or [],
        warnings=[],
    )
    c.add_validation(vs)
    return c


def _make_pipeline_result(
    score: float = 0.8,
    all_passed: bool = True,
    code: str = "def hello():\n    return 'world'",
    errors: Optional[List[str]] = None,
    validation_scores: Optional[List[ValidationScore]] = None,
) -> PipelineResult:
    c = Candidate(
        id=0, task_id="test", code=code,
        temperature=0.5, seed=42, model="test",
    )
    if validation_scores:
        for vs in validation_scores:
            c.add_validation(vs)
    else:
        c.add_validation(ValidationScore(
            validator_name="ast_syntax",
            passed=all_passed,
            score=score,
            errors=errors or [],
        ))
    pool = CandidatePool(task_id="test")
    pool.add(c)
    pool.best = c
    return PipelineResult(
        pool=pool,
        best=c,
        all_passed=all_passed,
        total_time=1.0,
        generation_time=0.5,
        validation_time=0.3,
    )


def _make_mock_pipeline(results):
    """Create a mock pipeline that returns results in sequence."""
    pipeline = MagicMock()
    pipeline.run_sync = MagicMock(side_effect=results)
    pipeline.config = MagicMock()
    pipeline.config.n_candidates = 2
    return pipeline


# ────────────────────────────────────────────────────────────
# TestExtractValidationErrors
# ────────────────────────────────────────────────────────────

class TestExtractValidationErrors:
    """Tests for extract_validation_errors()."""

    def test_no_result(self):
        assert extract_validation_errors(None) == []

    def test_no_best(self):
        result = MagicMock()
        result.best = None
        assert extract_validation_errors(result) == []

    def test_all_passed(self):
        result = _make_pipeline_result(all_passed=True)
        assert extract_validation_errors(result) == []

    def test_with_errors(self):
        result = _make_pipeline_result(
            all_passed=False,
            score=0.5,
            errors=["SyntaxError: unexpected indent"],
        )
        errors = extract_validation_errors(result)
        assert len(errors) == 1
        assert "ast_syntax" in errors[0]
        assert "SyntaxError" in errors[0]

    def test_multiple_validators_with_errors(self):
        vs1 = ValidationScore(
            validator_name="ast_syntax",
            passed=False, score=0.0,
            errors=["SyntaxError: line 5"],
        )
        vs2 = ValidationScore(
            validator_name="no_eval_exec",
            passed=False, score=0.0,
            errors=["eval() detected on line 3"],
        )
        vs3 = ValidationScore(
            validator_name="complexity",
            passed=True, score=0.9,
        )
        result = _make_pipeline_result(
            all_passed=False, score=0.3,
            validation_scores=[vs1, vs2, vs3],
        )
        errors = extract_validation_errors(result)
        assert len(errors) == 2
        assert any("ast_syntax" in e for e in errors)
        assert any("no_eval_exec" in e for e in errors)


# ────────────────────────────────────────────────────────────
# TestBuildCorrectionPrompt
# ────────────────────────────────────────────────────────────

class TestBuildCorrectionPrompt:
    """Tests for build_correction_prompt()."""

    def test_contains_original_query(self):
        prompt = build_correction_prompt(
            "write a sort function",
            "def sort(): pass",
            ["[ast_syntax] SyntaxError"],
            2,
        )
        assert "write a sort function" in prompt

    def test_contains_previous_code(self):
        prompt = build_correction_prompt(
            "write a sort function",
            "def sort(): pass",
            ["[ast_syntax] SyntaxError"],
            2,
        )
        assert "def sort(): pass" in prompt

    def test_contains_errors(self):
        prompt = build_correction_prompt(
            "write a sort function",
            "def sort(): pass",
            ["[ast_syntax] SyntaxError: unexpected indent"],
            2,
        )
        assert "SyntaxError: unexpected indent" in prompt

    def test_contains_iteration_number(self):
        prompt = build_correction_prompt("q", "c", ["e"], 3)
        assert "3" in prompt
        assert "CORRECTION ATTEMPT" in prompt

    def test_caps_errors_at_10(self):
        errors = [f"[rule] Error {i}" for i in range(20)]
        prompt = build_correction_prompt("q", "c", errors, 2)
        # Should contain at most 10 error lines
        error_lines = [l for l in prompt.split("\n") if l.strip().startswith("- [rule]")]
        assert len(error_lines) <= 10


# ────────────────────────────────────────────────────────────
# TestExtractKeyIssues
# ────────────────────────────────────────────────────────────

class TestExtractKeyIssues:
    """Tests for extract_key_issues() — recurring error detection."""

    def test_empty_attempts(self):
        assert extract_key_issues([]) == []

    def test_no_recurring(self):
        a1 = CorrectionAttempt(
            iteration=1, best_score=0.5, all_passed=False,
            code="", errors=["[ast_syntax] error1"],
        )
        a2 = CorrectionAttempt(
            iteration=2, best_score=0.6, all_passed=False,
            code="", errors=["[complexity] error2"],
        )
        result = extract_key_issues([a1, a2])
        assert result == []

    def test_recurring_detected(self):
        a1 = CorrectionAttempt(
            iteration=1, best_score=0.5, all_passed=False,
            code="", errors=["[ast_syntax] SyntaxError"],
        )
        a2 = CorrectionAttempt(
            iteration=2, best_score=0.6, all_passed=False,
            code="", errors=["[ast_syntax] SyntaxError again"],
        )
        result = extract_key_issues([a1, a2])
        assert len(result) == 1
        assert "ast_syntax" in result[0]
        assert "2/2" in result[0]

    def test_multiple_recurring(self):
        a1 = CorrectionAttempt(
            iteration=1, best_score=0.5, all_passed=False,
            code="", errors=["[ast_syntax] e1", "[no_eval_exec] e2"],
        )
        a2 = CorrectionAttempt(
            iteration=2, best_score=0.6, all_passed=False,
            code="", errors=["[ast_syntax] e3", "[no_eval_exec] e4"],
        )
        a3 = CorrectionAttempt(
            iteration=3, best_score=0.7, all_passed=False,
            code="", errors=["[ast_syntax] e5"],
        )
        result = extract_key_issues([a1, a2, a3])
        assert len(result) == 2
        assert any("ast_syntax" in r and "3/3" in r for r in result)
        assert any("no_eval_exec" in r and "2/3" in r for r in result)


# ────────────────────────────────────────────────────────────
# TestSelfCorrectionLoop
# ────────────────────────────────────────────────────────────

class TestSelfCorrectionLoop:
    """Tests for the SelfCorrectionLoop class."""

    def test_first_attempt_passes_no_correction(self):
        """When first attempt passes all validators, no correction needed."""
        pipeline = _make_mock_pipeline([
            _make_pipeline_result(score=0.95, all_passed=True),
        ])
        loop = SelfCorrectionLoop(pipeline, max_iterations=3)
        result = loop.run_sync(query="write a function")

        assert result.total_iterations == 1
        assert result.all_passed is True
        assert result.corrected is False
        assert result.best_score == 0.95
        assert pipeline.run_sync.call_count == 1

    def test_correction_after_failure(self):
        """When first attempt fails, correction should be attempted."""
        pipeline = _make_mock_pipeline([
            _make_pipeline_result(
                score=0.5, all_passed=False, code="bad code",
                errors=["SyntaxError: invalid syntax"],
            ),
            _make_pipeline_result(
                score=0.9, all_passed=True, code="good code",
            ),
        ])
        loop = SelfCorrectionLoop(pipeline, max_iterations=3)
        result = loop.run_sync(query="write a function")

        assert result.total_iterations == 2
        assert result.all_passed is True
        assert result.corrected is True
        assert result.improvement > 0
        assert result.best_score == 0.9
        assert pipeline.run_sync.call_count == 2

    def test_max_iterations_respected(self):
        """Should stop after max_iterations even if not all passed."""
        failing_result = _make_pipeline_result(
            score=0.5, all_passed=False,
            errors=["persistent error"],
        )
        pipeline = _make_mock_pipeline([failing_result] * 5)
        loop = SelfCorrectionLoop(pipeline, max_iterations=3)
        result = loop.run_sync(query="write a function")

        assert result.total_iterations == 3
        assert result.all_passed is False
        assert pipeline.run_sync.call_count == 3

    def test_early_stop_on_success(self):
        """Should stop as soon as all validators pass."""
        pipeline = _make_mock_pipeline([
            _make_pipeline_result(score=0.4, all_passed=False, errors=["e1"]),
            _make_pipeline_result(score=0.95, all_passed=True),
            _make_pipeline_result(score=0.99, all_passed=True),  # Should not reach this
        ])
        loop = SelfCorrectionLoop(pipeline, max_iterations=5)
        result = loop.run_sync(query="write a function")

        assert result.total_iterations == 2
        assert result.all_passed is True
        assert pipeline.run_sync.call_count == 2

    def test_low_score_stops_early(self):
        """Don't try to correct garbage code (below min_score)."""
        pipeline = _make_mock_pipeline([
            _make_pipeline_result(score=0.05, all_passed=False, errors=["total garbage"]),
            _make_pipeline_result(score=0.95, all_passed=True),  # Should not reach
        ])
        loop = SelfCorrectionLoop(pipeline, max_iterations=3, min_score=0.1)
        result = loop.run_sync(query="write a function")

        assert result.total_iterations == 1
        assert pipeline.run_sync.call_count == 1

    def test_picks_overall_best(self):
        """If iteration 2 is worse than iteration 1, pick iteration 1."""
        # Note: passed=False with errors → total_score = score * 0.5 (penalty)
        pipeline = _make_mock_pipeline([
            _make_pipeline_result(score=0.7, all_passed=False, code="decent code", errors=["e1"]),
            _make_pipeline_result(score=0.5, all_passed=False, code="worse code", errors=["e2"]),
            _make_pipeline_result(score=0.6, all_passed=False, code="ok code", errors=["e3"]),
        ])
        loop = SelfCorrectionLoop(pipeline, max_iterations=3)
        result = loop.run_sync(query="write a function")

        assert result.total_iterations == 3
        # score=0.7 with penalty → 0.35, which is still the highest
        assert result.best_score == pytest.approx(0.35, abs=0.01)
        assert result.best_code == "decent code"

    def test_pipeline_error_stops_loop(self):
        """Pipeline error should stop the loop gracefully."""
        # passed=False, score=0.5, errors → total_score = 0.5 * 0.5 = 0.25
        pipeline = _make_mock_pipeline([
            _make_pipeline_result(score=0.5, all_passed=False, errors=["e1"]),
            RuntimeError("LLM timeout"),
        ])
        loop = SelfCorrectionLoop(pipeline, max_iterations=3)
        result = loop.run_sync(query="write a function")

        assert result.total_iterations == 1  # Only first attempt completed
        assert result.best_score == pytest.approx(0.25, abs=0.01)

    def test_on_iteration_callback(self):
        """Callback should be called for each iteration."""
        pipeline = _make_mock_pipeline([
            _make_pipeline_result(score=0.5, all_passed=False, errors=["e1"]),
            _make_pipeline_result(score=0.9, all_passed=True),
        ])
        loop = SelfCorrectionLoop(pipeline, max_iterations=3)
        calls = []

        def on_iter(iteration, attempt):
            calls.append((iteration, attempt.best_score))

        result = loop.run_sync(query="write a function", on_iteration=on_iter)

        assert len(calls) == 2
        # passed=False, score=0.5, errors → total_score = 0.25
        assert calls[0] == (1, pytest.approx(0.25, abs=0.01))
        # passed=True, score=0.9 → total_score = 0.9
        assert calls[1] == (2, pytest.approx(0.9, abs=0.01))

    def test_max_iterations_one_means_no_correction(self):
        """max_iterations=1 means only one attempt, no correction."""
        pipeline = _make_mock_pipeline([
            _make_pipeline_result(score=0.5, all_passed=False, errors=["e1"]),
        ])
        loop = SelfCorrectionLoop(pipeline, max_iterations=1)
        result = loop.run_sync(query="write a function")

        assert result.total_iterations == 1
        assert result.corrected is False
        assert pipeline.run_sync.call_count == 1


# ────────────────────────────────────────────────────────────
# TestCorrectionResult
# ────────────────────────────────────────────────────────────

class TestCorrectionResult:
    """Tests for CorrectionResult data structures."""

    def test_summary_format(self):
        result = CorrectionResult(
            best_code="code",
            best_score=0.9,
            all_passed=True,
            attempts=[
                CorrectionAttempt(
                    iteration=1, best_score=0.5, all_passed=False,
                    code="bad", errors=["e1"],
                ),
                CorrectionAttempt(
                    iteration=2, best_score=0.9, all_passed=True,
                    code="good", errors=[],
                ),
            ],
            total_iterations=2,
            total_time=5.0,
            initial_score=0.5,
            final_score=0.9,
            improvement=0.4,
            corrected=True,
        )
        s = result.summary()
        assert s["total_iterations"] == 2
        assert s["initial_score"] == 0.5
        assert s["final_score"] == 0.9
        assert s["improvement"] == 0.4
        assert s["corrected"] is True
        assert len(s["attempts"]) == 2

    def test_empty_result(self):
        result = CorrectionResult(
            best_code="", best_score=0.0, all_passed=False,
        )
        s = result.summary()
        assert s["total_iterations"] == 0
        assert s["corrected"] is False

    def test_improvement_calculation(self):
        """Improvement should be final - initial."""
        result = CorrectionResult(
            best_code="c", best_score=0.8, all_passed=False,
            initial_score=0.3, final_score=0.8, improvement=0.5,
            corrected=True,
        )
        assert result.improvement == pytest.approx(0.5, abs=0.01)


# ────────────────────────────────────────────────────────────
# TestCorrectionPromptContent
# ────────────────────────────────────────────────────────────

class TestCorrectionPromptContent:
    """Verify correction prompts contain all required elements."""

    def test_prompt_has_fix_instruction(self):
        prompt = build_correction_prompt("q", "c", ["e"], 2)
        assert "fix" in prompt.lower() or "correct" in prompt.lower()

    def test_prompt_includes_code_block(self):
        prompt = build_correction_prompt("q", "def foo(): pass", ["e"], 2)
        assert "```" in prompt
        assert "def foo(): pass" in prompt

    def test_prompt_has_error_list(self):
        errors = ["[ast_syntax] Error A", "[complexity] Error B"]
        prompt = build_correction_prompt("q", "c", errors, 2)
        assert "Error A" in prompt
        assert "Error B" in prompt


# ────────────────────────────────────────────────────────────
# TestSelfCorrectionIntegration
# ────────────────────────────────────────────────────────────

class TestSelfCorrectionIntegration:
    """Integration tests verifying self-correction works with pipeline."""

    def test_correction_prompt_reaches_pipeline(self):
        """Verify the correction prompt is passed to pipeline.run_sync."""
        pipeline = _make_mock_pipeline([
            _make_pipeline_result(score=0.5, all_passed=False, errors=["syntax error"]),
            _make_pipeline_result(score=0.9, all_passed=True),
        ])
        loop = SelfCorrectionLoop(pipeline, max_iterations=3)
        result = loop.run_sync(query="write a sort function")

        # Second call should have a modified query with error feedback
        second_call = pipeline.run_sync.call_args_list[1]
        query_arg = second_call.kwargs.get("query", "")
        assert "CORRECTION ATTEMPT" in query_arg
        assert "write a sort function" in query_arg

    def test_kwargs_forwarded(self):
        """Pipeline kwargs should be forwarded through all iterations."""
        pipeline = _make_mock_pipeline([
            _make_pipeline_result(score=0.5, all_passed=False, errors=["e"]),
            _make_pipeline_result(score=0.9, all_passed=True),
        ])
        loop = SelfCorrectionLoop(pipeline, max_iterations=3)
        result = loop.run_sync(
            query="write a function",
            swecas_code=500,
            oss_context="use type hints",
        )

        # Both calls should have the extra kwargs
        for call_obj in pipeline.run_sync.call_args_list:
            assert call_obj.kwargs.get("swecas_code") == 500
            assert call_obj.kwargs.get("oss_context") == "use type hints"

    def test_task_id_includes_iteration(self):
        """Each iteration should have a unique task_id."""
        pipeline = _make_mock_pipeline([
            _make_pipeline_result(score=0.5, all_passed=False, errors=["e"]),
            _make_pipeline_result(score=0.9, all_passed=True),
        ])
        loop = SelfCorrectionLoop(pipeline, max_iterations=3)
        result = loop.run_sync(query="q", task_id="my_task")

        ids = [c.kwargs.get("task_id", "") for c in pipeline.run_sync.call_args_list]
        assert ids[0] == "my_task_iter1"
        assert ids[1] == "my_task_iter2"

    def test_agent_stats_fields_exist(self):
        """Agent stats should have self-correction fields."""
        try:
            from core.qwencode_agent import QwenCodeAgent
        except ImportError:
            pytest.skip("QwenCodeAgent not importable in test env")

        import inspect
        source = inspect.getsource(QwenCodeAgent)
        assert "correction_runs" in source
        assert "correction_iterations_total" in source
        assert "correction_improvements" in source
        assert "correction_all_passed_after" in source

    def test_self_correction_import(self):
        """Verify SelfCorrectionLoop is importable."""
        from core.generation.self_correction import (
            SelfCorrectionLoop,
            CorrectionResult,
            CorrectionAttempt,
            extract_validation_errors,
            build_correction_prompt,
            extract_key_issues,
        )
        assert SelfCorrectionLoop is not None
        assert MAX_ITERATIONS == 3


# ────────────────────────────────────────────────────────────
# TestEdgeCases
# ────────────────────────────────────────────────────────────

class TestEdgeCases:
    """Edge case tests for robustness."""

    def test_empty_code_from_pipeline(self):
        """Handle pipeline returning empty code."""
        pipeline = _make_mock_pipeline([
            _make_pipeline_result(score=0.0, all_passed=False, code="", errors=["empty"]),
        ])
        loop = SelfCorrectionLoop(pipeline, max_iterations=3)
        result = loop.run_sync(query="q")
        # score < min_score, should stop
        assert result.total_iterations == 1

    def test_no_errors_but_not_all_passed(self):
        """Handle case where not all passed but no errors extracted."""
        result = _make_pipeline_result(score=0.6, all_passed=False, errors=[])
        pipeline = _make_mock_pipeline([result])
        loop = SelfCorrectionLoop(pipeline, max_iterations=3)
        cr = loop.run_sync(query="q")
        # No errors to feed back → should stop after 1 iteration
        assert cr.total_iterations == 1

    def test_callback_error_ignored(self):
        """Callback errors should not crash the loop."""
        pipeline = _make_mock_pipeline([
            _make_pipeline_result(score=0.5, all_passed=False, errors=["e"]),
            _make_pipeline_result(score=0.9, all_passed=True),
        ])
        loop = SelfCorrectionLoop(pipeline, max_iterations=3)

        def bad_callback(iteration, attempt):
            raise ValueError("callback crashed")

        result = loop.run_sync(query="q", on_iteration=bad_callback)
        assert result.total_iterations == 2  # Should still complete

    def test_negative_max_iterations(self):
        """max_iterations < 1 should be clamped to 1."""
        pipeline = _make_mock_pipeline([
            _make_pipeline_result(score=0.9, all_passed=True),
        ])
        loop = SelfCorrectionLoop(pipeline, max_iterations=-1)
        assert loop.max_iterations == 1
