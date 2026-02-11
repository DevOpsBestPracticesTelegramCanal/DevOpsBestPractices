"""
Week 21: Tests for Role-Specialized Generators (A), Blackboard (B),
and Quality Escalation (C).

Test count target: ~70 tests covering:
  A) generator_roles.py — role definitions, mapping, prompt building
  B) blackboard.py — entry extraction, hints, recurring errors
     + self_correction.py integration with blackboard
  C) pipeline.py — QualityLevel, run_with_escalation, PipelineConfig
"""

import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from dataclasses import dataclass, field
from typing import List, Optional

from core.generation.generator_roles import (
    GeneratorRole,
    GENERATOR_ROLES,
    DEFAULT_ROLE_ORDER,
    get_roles_for_task,
    get_role_for_candidate,
    build_role_system_prompt,
    _COMPLEXITY_ROLES,
    _TASK_TYPE_ROLES,
)
from core.generation.blackboard import (
    BlackboardEntry,
    CandidateBlackboard,
)
from core.generation.candidate import (
    Candidate,
    CandidatePool,
    CandidateStatus,
    ValidationScore,
)
from core.generation.self_correction import (
    SelfCorrectionLoop,
    CorrectionResult,
    build_correction_prompt,
    extract_validation_errors,
)
from core.generation.pipeline import (
    QualityLevel,
    PipelineConfig,
    PipelineResult,
    MultiCandidatePipeline,
)


# ============================================================
# Helpers
# ============================================================

def _make_candidate(
    cid: int = 0,
    score: float = 0.8,
    passed: bool = True,
    errors: Optional[List[str]] = None,
    code: str = "def hello():\n    return 'world'",
    role: str = "",
) -> Candidate:
    c = Candidate(
        id=cid, task_id="test", code=code,
        temperature=0.5, seed=42, model="test",
        role=role,
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


def _make_candidate_multi_validators(
    cid: int = 0,
    validators: Optional[list] = None,
    code: str = "def f(): pass",
) -> Candidate:
    """Create candidate with multiple validation scores."""
    c = Candidate(
        id=cid, task_id="test", code=code,
        temperature=0.5, seed=42, model="test",
    )
    for v in (validators or []):
        c.add_validation(ValidationScore(
            validator_name=v["name"],
            passed=v.get("passed", True),
            score=v.get("score", 1.0),
            errors=v.get("errors", []),
            warnings=v.get("warnings", []),
        ))
    return c


def _make_pool(candidates: List[Candidate]) -> CandidatePool:
    pool = CandidatePool(task_id="test")
    for c in candidates:
        pool.add(c)
    if candidates:
        pool.best = candidates[0]
    return pool


def _make_pipeline_result(
    score: float = 0.8,
    all_passed: bool = True,
    errors: Optional[List[str]] = None,
    code: str = "def f(): pass",
) -> PipelineResult:
    c = _make_candidate(score=score, passed=all_passed, errors=errors, code=code)
    pool = _make_pool([c])
    return PipelineResult(
        pool=pool,
        best=c,
        all_passed=all_passed,
        total_time=1.0,
        generation_time=0.5,
        validation_time=0.3,
        selection_time=0.1,
    )


# ============================================================
# A: GENERATOR ROLES
# ============================================================

class TestGeneratorRoleDefinitions:
    """Test the role dataclass and built-in roles."""

    def test_four_roles_defined(self):
        assert len(GENERATOR_ROLES) == 4

    def test_role_names(self):
        expected = {"correctness", "security", "readability", "performance"}
        assert set(GENERATOR_ROLES.keys()) == expected

    def test_each_role_has_system_prefix(self):
        for name, role in GENERATOR_ROLES.items():
            assert role.system_prefix, f"{name} has empty system_prefix"
            assert len(role.system_prefix) > 20

    def test_each_role_has_temperature(self):
        for name, role in GENERATOR_ROLES.items():
            assert 0.0 <= role.temperature <= 1.0, f"{name} temp out of range"

    def test_correctness_is_lowest_temp(self):
        assert GENERATOR_ROLES["correctness"].temperature == 0.2

    def test_performance_is_highest_temp(self):
        assert GENERATOR_ROLES["performance"].temperature == 0.5

    def test_each_role_has_priority_validators(self):
        for name, role in GENERATOR_ROLES.items():
            assert role.priority_validators, f"{name} has no priority validators"

    def test_default_role_order(self):
        assert DEFAULT_ROLE_ORDER == ["correctness", "readability", "security", "performance"]


class TestGetRolesForTask:
    """Test role selection based on complexity and task type."""

    def test_single_candidate_gets_one_role(self):
        roles = get_roles_for_task(1)
        assert len(roles) == 1

    def test_three_candidates_get_three_roles(self):
        roles = get_roles_for_task(3)
        assert len(roles) == 3

    def test_roles_cycle_when_n_exceeds_available(self):
        roles = get_roles_for_task(8)
        assert len(roles) == 8
        assert roles[0].name == roles[4].name  # cycles

    def test_trivial_complexity_single_role(self):
        roles = get_roles_for_task(3, complexity="TRIVIAL")
        # TRIVIAL only has correctness, so all 3 should be correctness
        assert all(r.name == "correctness" for r in roles)

    def test_moderate_complexity_two_roles(self):
        roles = get_roles_for_task(2, complexity="MODERATE")
        names = [r.name for r in roles]
        assert names == ["correctness", "readability"]

    def test_critical_complexity(self):
        roles = get_roles_for_task(3, complexity="CRITICAL")
        names = [r.name for r in roles]
        assert names == ["correctness", "security", "performance"]

    def test_task_type_overrides_complexity(self):
        roles = get_roles_for_task(2, complexity="TRIVIAL", task_type="infrastructure")
        # task_type takes priority
        assert roles[0].name == "security"
        assert roles[1].name == "correctness"

    def test_infrastructure_task_type(self):
        roles = get_roles_for_task(3, task_type="infrastructure")
        assert roles[0].name == "security"

    def test_refactoring_task_type(self):
        roles = get_roles_for_task(2, task_type="refactoring")
        names = [r.name for r in roles]
        assert names == ["readability", "performance"]

    def test_unknown_complexity_uses_defaults(self):
        roles = get_roles_for_task(4, complexity="UNKNOWN")
        names = [r.name for r in roles]
        assert names == DEFAULT_ROLE_ORDER

    def test_unknown_task_type_uses_complexity(self):
        roles = get_roles_for_task(2, complexity="COMPLEX", task_type="unknown")
        names = [r.name for r in roles]
        assert names == ["correctness", "security"]


class TestGetRoleForCandidate:
    """Test single-candidate role lookup."""

    def test_first_candidate(self):
        role = get_role_for_candidate(0, 3)
        assert isinstance(role, GeneratorRole)

    def test_second_candidate_different_role(self):
        r0 = get_role_for_candidate(0, 3)
        r1 = get_role_for_candidate(1, 3)
        assert r0.name != r1.name

    def test_cycles_correctly(self):
        r0 = get_role_for_candidate(0, 8)
        r4 = get_role_for_candidate(4, 8)
        assert r0.name == r4.name


class TestBuildRoleSystemPrompt:
    """Test prompt construction with role prefix."""

    def test_prepends_role_prefix(self):
        role = GENERATOR_ROLES["security"]
        base = "You are an expert coder."
        result = build_role_system_prompt(role, base)
        assert result.startswith(role.system_prefix)
        assert base in result

    def test_separator_between_role_and_base(self):
        role = GENERATOR_ROLES["correctness"]
        result = build_role_system_prompt(role, "base prompt")
        # Should have blank line between role prefix and base
        assert "\n\n" in result

    def test_preserves_base_prompt(self):
        role = GENERATOR_ROLES["readability"]
        base = "Very specific instructions here."
        result = build_role_system_prompt(role, base)
        assert result.endswith(base)


class TestCandidateRoleField:
    """Test the role field on Candidate dataclass."""

    def test_default_role_empty(self):
        c = Candidate(id=0, task_id="t", code="x", temperature=0.5, seed=1, model="m")
        assert c.role == ""

    def test_role_set_explicitly(self):
        c = _make_candidate(role="security")
        assert c.role == "security"

    def test_role_in_dict_not_present_but_accessible(self):
        c = _make_candidate(role="correctness")
        # role is accessible on the object
        assert c.role == "correctness"


# ============================================================
# B: BLACKBOARD
# ============================================================

class TestBlackboardEntry:
    """Test the BlackboardEntry dataclass."""

    def test_default_confidence(self):
        e = BlackboardEntry(
            source_candidate_id=0,
            source_iteration=1,
            entry_type="good_pattern",
            validator_name="ast_syntax",
            content="test",
        )
        assert e.confidence == 0.8

    def test_custom_confidence(self):
        e = BlackboardEntry(
            source_candidate_id=0,
            source_iteration=1,
            entry_type="bad_pattern",
            validator_name="ast_syntax",
            content="test",
            confidence=0.5,
        )
        assert e.confidence == 0.5


class TestCandidateBlackboard:
    """Test the CandidateBlackboard accumulator."""

    def test_empty_blackboard(self):
        bb = CandidateBlackboard()
        assert bb.size == 0
        assert bb.build_hints_prompt() == ""

    def test_extract_good_pattern(self):
        bb = CandidateBlackboard()
        c = _make_candidate(score=1.0, passed=True)
        added = bb.extract_from_candidate(c, iteration=1)
        assert added == 1
        assert bb.size == 1
        assert bb.entries[0].entry_type == "good_pattern"

    def test_extract_bad_pattern(self):
        bb = CandidateBlackboard()
        c = _make_candidate(score=0.3, passed=False, errors=["syntax error at line 5"])
        added = bb.extract_from_candidate(c, iteration=1)
        assert added == 1
        assert bb.entries[0].entry_type == "bad_pattern"
        assert "syntax error" in bb.entries[0].content

    def test_extract_multiple_validators(self):
        bb = CandidateBlackboard()
        c = _make_candidate_multi_validators(validators=[
            {"name": "ast_syntax", "passed": True, "score": 1.0},
            {"name": "no_eval_exec", "passed": False, "score": 0.0,
             "errors": ["eval() found at line 3"]},
            {"name": "complexity", "passed": True, "score": 0.9},
        ])
        added = bb.extract_from_candidate(c, iteration=1)
        assert added == 3  # 2 good + 1 bad

    def test_caps_errors_per_validator(self):
        """Max 3 errors per validator to avoid prompt bloat."""
        bb = CandidateBlackboard()
        c = _make_candidate_multi_validators(validators=[
            {"name": "ruff", "passed": False, "score": 0.1,
             "errors": [f"E{i}: issue" for i in range(10)]},
        ])
        added = bb.extract_from_candidate(c, iteration=1)
        assert added == 3  # capped at 3

    def test_recurring_errors_detection(self):
        bb = CandidateBlackboard()
        # Same validator fails in iteration 1 and 2
        c1 = _make_candidate(cid=0, passed=False, errors=["error A"])
        c2 = _make_candidate(cid=1, passed=False, errors=["error B"])
        bb.extract_from_candidate(c1, iteration=1)
        bb.extract_from_candidate(c2, iteration=2)
        recurring = bb.get_recurring_errors(min_occurrences=2)
        assert len(recurring) == 1
        assert "ast_syntax" in recurring[0]
        assert "2x" in recurring[0]

    def test_no_recurring_with_single_failure(self):
        bb = CandidateBlackboard()
        c1 = _make_candidate(passed=False, errors=["error"])
        bb.extract_from_candidate(c1, iteration=1)
        assert bb.get_recurring_errors(min_occurrences=2) == []

    def test_build_hints_prompt_has_sections(self):
        bb = CandidateBlackboard()
        c1 = _make_candidate(cid=0, passed=False, errors=["err1"])
        c2 = _make_candidate(cid=1, passed=False, errors=["err2"])
        c3 = _make_candidate(cid=2, passed=True, score=1.0)
        bb.extract_from_candidate(c1, iteration=1)
        bb.extract_from_candidate(c2, iteration=2)
        bb.extract_from_candidate(c3, iteration=3)

        hints = bb.build_hints_prompt()
        assert "RECURRING ISSUES" in hints
        assert "AVOID" in hints
        assert "KEEP" in hints

    def test_build_hints_deduplicates(self):
        bb = CandidateBlackboard()
        # Same good pattern twice
        c1 = _make_candidate(cid=0, passed=True, score=1.0)
        c2 = _make_candidate(cid=1, passed=True, score=1.0)
        bb.extract_from_candidate(c1, iteration=1)
        bb.extract_from_candidate(c2, iteration=2)
        hints = bb.build_hints_prompt()
        # Should only appear once
        assert hints.count("ast_syntax") == 1

    def test_max_entries_eviction(self):
        bb = CandidateBlackboard(max_entries=5)
        for i in range(10):
            c = _make_candidate(cid=i, passed=True, score=1.0)
            bb.extract_from_candidate(c, iteration=i)
        assert bb.size == 5

    def test_clear(self):
        bb = CandidateBlackboard()
        c = _make_candidate(passed=True)
        bb.extract_from_candidate(c)
        bb.clear()
        assert bb.size == 0
        assert bb.get_recurring_errors() == []

    def test_to_dict(self):
        bb = CandidateBlackboard()
        c = _make_candidate(passed=True)
        bb.extract_from_candidate(c)
        d = bb.to_dict()
        assert "total_entries" in d
        assert "good_patterns" in d
        assert "bad_patterns" in d
        assert "recurring_errors" in d

    def test_no_validation_scores_returns_zero(self):
        bb = CandidateBlackboard()
        c = Candidate(id=0, task_id="t", code="x", temperature=0.5, seed=1, model="m")
        # No validation_scores populated
        added = bb.extract_from_candidate(c)
        assert added == 0


class TestBlackboardInSelfCorrection:
    """Test that SelfCorrectionLoop uses the blackboard."""

    def test_blackboard_created_by_default(self):
        mock_pipeline = MagicMock()
        loop = SelfCorrectionLoop(mock_pipeline)
        assert loop.blackboard is not None
        assert loop.use_blackboard is True

    def test_blackboard_disabled(self):
        mock_pipeline = MagicMock()
        loop = SelfCorrectionLoop(mock_pipeline, use_blackboard=False)
        assert loop.blackboard is None
        assert loop.use_blackboard is False

    def test_blackboard_accumulates_during_correction(self):
        """When correction runs multiple iterations, blackboard grows."""
        # Iteration 1: fails
        result1 = _make_pipeline_result(score=0.5, all_passed=False, errors=["err1"])
        # Iteration 2: passes
        result2 = _make_pipeline_result(score=0.9, all_passed=True)

        mock_pipeline = MagicMock()
        mock_pipeline.run_sync = MagicMock(side_effect=[result1, result2])

        loop = SelfCorrectionLoop(mock_pipeline, max_iterations=3)
        result = loop.run_sync(query="write code")

        assert loop.blackboard.size > 0
        assert result.blackboard_summary is not None
        assert result.blackboard_summary["total_entries"] > 0

    def test_blackboard_hints_in_correction_prompt(self):
        """build_correction_prompt includes blackboard_hints when provided."""
        prompt = build_correction_prompt(
            original_query="write sort",
            previous_code="def sort(): pass",
            errors=["[ast] error"],
            iteration=2,
            blackboard_hints="AVOID: eval()\nKEEP: type hints",
        )
        assert "KNOWLEDGE FROM PREVIOUS ATTEMPTS" in prompt
        assert "AVOID: eval()" in prompt
        assert "KEEP: type hints" in prompt

    def test_correction_prompt_without_hints(self):
        """build_correction_prompt works without blackboard_hints."""
        prompt = build_correction_prompt(
            original_query="write sort",
            previous_code="def sort(): pass",
            errors=["[ast] error"],
            iteration=2,
        )
        assert "KNOWLEDGE FROM PREVIOUS ATTEMPTS" not in prompt

    def test_correction_result_summary_includes_blackboard(self):
        """CorrectionResult.summary() includes blackboard section."""
        result = CorrectionResult(
            best_code="def f(): pass",
            best_score=0.8,
            all_passed=True,
            total_iterations=2,
            total_time=1.0,
            initial_score=0.5,
            final_score=0.8,
            improvement=0.3,
            corrected=True,
            blackboard_summary={"total_entries": 5, "good_patterns": 3, "bad_patterns": 2, "recurring_errors": []},
        )
        s = result.summary()
        assert "blackboard" in s
        assert s["blackboard"]["total_entries"] == 5

    def test_correction_result_summary_no_blackboard(self):
        """CorrectionResult.summary() omits blackboard when None."""
        result = CorrectionResult(
            best_code="x", best_score=0.5, all_passed=False,
            total_iterations=1, total_time=0.1,
            initial_score=0.5, final_score=0.5, improvement=0.0,
        )
        s = result.summary()
        assert "blackboard" not in s


# ============================================================
# C: QUALITY ESCALATION
# ============================================================

class TestQualityLevel:
    """Test QualityLevel tier definitions."""

    def test_three_levels(self):
        assert QualityLevel._ORDER == ["FAST", "STANDARD", "DEEP"]

    def test_config_for_fast(self):
        cfg = QualityLevel.config_for("FAST")
        assert cfg["n_candidates"] == 1
        assert cfg["profile"] == "fast_dev"

    def test_config_for_standard(self):
        cfg = QualityLevel.config_for("STANDARD")
        assert cfg["n_candidates"] == 3
        assert cfg["profile"] == "balanced"

    def test_config_for_deep(self):
        cfg = QualityLevel.config_for("DEEP")
        assert cfg["n_candidates"] == 5
        assert cfg["profile"] == "safe_fix"

    def test_config_for_unknown_falls_back(self):
        cfg = QualityLevel.config_for("NONEXISTENT")
        assert cfg["n_candidates"] == 3  # falls back to STANDARD

    def test_next_level_fast(self):
        assert QualityLevel.next_level("FAST") == "STANDARD"

    def test_next_level_standard(self):
        assert QualityLevel.next_level("STANDARD") == "DEEP"

    def test_next_level_deep_is_none(self):
        assert QualityLevel.next_level("DEEP") is None

    def test_next_level_unknown_is_none(self):
        assert QualityLevel.next_level("NONEXISTENT") is None


class TestPipelineConfigEscalation:
    """Test PipelineConfig escalation fields."""

    def test_default_escalation_disabled(self):
        cfg = PipelineConfig()
        assert cfg.quality_escalation is False

    def test_default_initial_level(self):
        cfg = PipelineConfig()
        assert cfg.initial_quality_level == "FAST"

    def test_custom_escalation_config(self):
        cfg = PipelineConfig(
            quality_escalation=True,
            initial_quality_level="STANDARD",
        )
        assert cfg.quality_escalation is True
        assert cfg.initial_quality_level == "STANDARD"


class TestRunWithEscalation:
    """Test the escalation async method on the pipeline."""

    @pytest.fixture
    def mock_llm(self):
        llm = MagicMock()
        llm.model_name = "test-model"
        llm.generate = AsyncMock(return_value="def f(): pass")
        return llm

    @pytest.mark.asyncio
    async def test_stops_at_fast_when_all_passed(self, mock_llm):
        """If FAST tier produces all_passed, no escalation."""
        pipeline = MultiCandidatePipeline(mock_llm)

        # Mock run() to return all_passed on first call
        result_ok = _make_pipeline_result(score=0.9, all_passed=True)
        pipeline.run = AsyncMock(return_value=result_ok)

        result = await pipeline.run_with_escalation(
            task_id="t1", query="hello"
        )
        assert result.all_passed is True
        assert pipeline.run.call_count == 1
        # Check escalation level stored
        assert getattr(result, "_escalation_level", None) == "FAST"

    @pytest.mark.asyncio
    async def test_escalates_from_fast_to_standard(self, mock_llm):
        """If FAST fails, escalates to STANDARD."""
        pipeline = MultiCandidatePipeline(mock_llm)

        result_fail = _make_pipeline_result(score=0.4, all_passed=False, errors=["err"])
        result_ok = _make_pipeline_result(score=0.9, all_passed=True)
        pipeline.run = AsyncMock(side_effect=[result_fail, result_ok])

        result = await pipeline.run_with_escalation(
            task_id="t2", query="write code"
        )
        assert result.all_passed is True
        assert pipeline.run.call_count == 2
        assert getattr(result, "_escalation_level", None) == "STANDARD"

    @pytest.mark.asyncio
    async def test_escalates_all_way_to_deep(self, mock_llm):
        """If FAST and STANDARD fail, escalates to DEEP."""
        pipeline = MultiCandidatePipeline(mock_llm)

        result_fail1 = _make_pipeline_result(score=0.3, all_passed=False)
        result_fail2 = _make_pipeline_result(score=0.5, all_passed=False)
        result_fail3 = _make_pipeline_result(score=0.6, all_passed=False)
        pipeline.run = AsyncMock(side_effect=[result_fail1, result_fail2, result_fail3])

        result = await pipeline.run_with_escalation(
            task_id="t3", query="complex task"
        )
        assert result.all_passed is False
        assert pipeline.run.call_count == 3
        # Best result should be the one with highest score
        assert result.score == 0.6

    @pytest.mark.asyncio
    async def test_returns_best_across_tiers(self, mock_llm):
        """Best result tracks highest score across all tiers."""
        pipeline = MultiCandidatePipeline(mock_llm)

        result1 = _make_pipeline_result(score=0.7, all_passed=False)
        result2 = _make_pipeline_result(score=0.5, all_passed=False)  # worse
        result3 = _make_pipeline_result(score=0.8, all_passed=False)
        pipeline.run = AsyncMock(side_effect=[result1, result2, result3])

        result = await pipeline.run_with_escalation(
            task_id="t4", query="code"
        )
        assert result.score == 0.8

    @pytest.mark.asyncio
    async def test_custom_initial_level(self, mock_llm):
        """Starting at STANDARD skips FAST."""
        pipeline = MultiCandidatePipeline(mock_llm)

        result_ok = _make_pipeline_result(score=0.95, all_passed=True)
        pipeline.run = AsyncMock(return_value=result_ok)

        result = await pipeline.run_with_escalation(
            task_id="t5", query="code", initial_level="STANDARD"
        )
        assert pipeline.run.call_count == 1
        # Check that STANDARD n=3 was used
        call_kwargs = pipeline.run.call_args
        assert call_kwargs.kwargs.get("n") == 3

    @pytest.mark.asyncio
    async def test_escalation_passes_n_candidates(self, mock_llm):
        """Each tier passes the correct n_candidates to run()."""
        pipeline = MultiCandidatePipeline(mock_llm)

        result_fail = _make_pipeline_result(score=0.4, all_passed=False)
        result_ok = _make_pipeline_result(score=0.9, all_passed=True)
        pipeline.run = AsyncMock(side_effect=[result_fail, result_ok])

        await pipeline.run_with_escalation(task_id="t6", query="code")

        # First call: FAST (n=1), Second call: STANDARD (n=3)
        calls = pipeline.run.call_args_list
        assert calls[0].kwargs["n"] == 1
        assert calls[1].kwargs["n"] == 3

    @pytest.mark.asyncio
    async def test_task_id_includes_tier(self, mock_llm):
        """task_id is suffixed with escalation tier."""
        pipeline = MultiCandidatePipeline(mock_llm)
        result_ok = _make_pipeline_result(score=0.9, all_passed=True)
        pipeline.run = AsyncMock(return_value=result_ok)

        await pipeline.run_with_escalation(task_id="myTask", query="code")

        call_kwargs = pipeline.run.call_args
        assert "myTask_esc_fast" == call_kwargs.kwargs["task_id"]


class TestRunSyncEscalation:
    """Test that run_sync respects quality_escalation config."""

    def test_run_sync_no_escalation_by_default(self):
        """Default config doesn't enable escalation."""
        llm = MagicMock()
        llm.model_name = "test"
        llm.generate = AsyncMock(return_value="def f(): pass")

        pipeline = MultiCandidatePipeline(llm)
        # Patch both methods to track which was called
        pipeline.run = AsyncMock(return_value=_make_pipeline_result())
        pipeline.run_with_escalation = AsyncMock(return_value=_make_pipeline_result())

        pipeline.run_sync(task_id="t", query="code")

        # run() should be called, not run_with_escalation()
        assert pipeline.run.call_count == 1
        assert pipeline.run_with_escalation.call_count == 0

    def test_run_sync_with_escalation_enabled(self):
        """When quality_escalation=True, run_sync delegates to run_with_escalation."""
        llm = MagicMock()
        llm.model_name = "test"

        cfg = PipelineConfig(quality_escalation=True)
        pipeline = MultiCandidatePipeline(llm, config=cfg)
        pipeline.run = AsyncMock(return_value=_make_pipeline_result())
        pipeline.run_with_escalation = AsyncMock(return_value=_make_pipeline_result())

        pipeline.run_sync(task_id="t", query="code")

        assert pipeline.run_with_escalation.call_count == 1
        assert pipeline.run.call_count == 0
