# -*- coding: utf-8 -*-
"""
Tests for core/deep6_minsky.py — Deep6Minsky 6-step pipeline.
"""

import pytest
from core.deep6_minsky import (
    TaskType, Deep6Result, Deep6Minsky,
    STEP_NAMES, STEP_LABELS, STEP_DESCRIPTIONS,
)


# ── TaskType Enum ────────────────────────────────────────────────────────


class TestTaskType:
    def test_code(self):
        assert TaskType.CODE.value == "code"

    def test_analysis(self):
        assert TaskType.ANALYSIS.value == "analysis"

    def test_devops(self):
        assert TaskType.DEVOPS.value == "devops"

    def test_unknown(self):
        assert TaskType.UNKNOWN.value == "unknown"

    def test_count(self):
        assert len(TaskType) == 4


# ── Step Constants ───────────────────────────────────────────────────────


class TestStepConstants:
    def test_step_names_count(self):
        assert len(STEP_NAMES) == 6

    def test_step_labels_match_names(self):
        for name in STEP_NAMES:
            assert name in STEP_LABELS

    def test_step_descriptions_match_names(self):
        for name in STEP_NAMES:
            assert name in STEP_DESCRIPTIONS

    def test_step_order(self):
        assert STEP_NAMES == [
            "understanding", "challenges", "approaches",
            "constraints", "choose", "solution",
        ]


# ── Deep6Result Dataclass ────────────────────────────────────────────────


class TestDeep6Result:
    def test_defaults(self):
        r = Deep6Result()
        assert r.final_code is None
        assert r.final_explanation is None
        assert r.call_sequence == []
        assert r.rollback_reasons == []
        assert r.task_type == TaskType.UNKNOWN
        assert r.total_time == 0.0

    def test_summary_default(self):
        s = Deep6Result().summary()
        assert s["task_type"] == "unknown"
        assert s["steps_completed"] == 0
        assert s["rollbacks"] == 0
        assert s["has_code"] is False

    def test_summary_with_code(self):
        r = Deep6Result(final_code="print(1)", task_type=TaskType.CODE,
                        call_sequence=["understanding", "challenges"])
        s = r.summary()
        assert s["has_code"] is True
        assert s["task_type"] == "code"
        assert s["steps_completed"] == 2


# ── Step 1: Understanding ────────────────────────────────────────────────


class TestStepUnderstanding:
    def setup_method(self):
        self.engine = Deep6Minsky()

    def test_code_task(self):
        result = self.engine._step_understanding("write a function to sort", "")
        assert result["task_type"] == TaskType.CODE

    def test_devops_task(self):
        result = self.engine._step_understanding("deploy kubernetes cluster", "")
        assert result["task_type"] == TaskType.DEVOPS

    def test_analysis_task(self):
        result = self.engine._step_understanding("explain this algorithm", "")
        assert result["task_type"] == TaskType.ANALYSIS

    def test_unknown_task(self):
        result = self.engine._step_understanding("hello", "")
        assert result["task_type"] == TaskType.UNKNOWN

    def test_has_context_true(self):
        result = self.engine._step_understanding("test", "some context")
        assert result["has_context"] is True

    def test_has_context_false(self):
        result = self.engine._step_understanding("test", "")
        assert result["has_context"] is False

    def test_query_length(self):
        result = self.engine._step_understanding("hello world", "")
        assert result["query_length"] == 11

    def test_terraform_is_devops(self):
        result = self.engine._step_understanding("configure terraform module", "")
        assert result["task_type"] == TaskType.DEVOPS

    def test_docker_is_devops(self):
        result = self.engine._step_understanding("build docker image", "")
        assert result["task_type"] == TaskType.DEVOPS

    def test_implement_is_code(self):
        result = self.engine._step_understanding("implement binary search", "")
        assert result["task_type"] == TaskType.CODE

    def test_class_keyword_is_code(self):
        result = self.engine._step_understanding("create a class for users", "")
        assert result["task_type"] == TaskType.CODE

    def test_review_is_analysis(self):
        result = self.engine._step_understanding("review this code", "")
        assert result["task_type"] == TaskType.ANALYSIS


# ── Step 2: Challenges ───────────────────────────────────────────────────


class TestStepChallenges:
    def setup_method(self):
        self.engine = Deep6Minsky()
        self.s1 = {"task_type": TaskType.CODE}

    def test_security_challenge(self):
        result = self.engine._step_challenges("handle password hashing", self.s1)
        types = [c["type"] for c in result["challenges"]]
        assert "security" in types

    def test_data_challenge(self):
        result = self.engine._step_challenges("migrate database schema", self.s1)
        types = [c["type"] for c in result["challenges"]]
        assert "data" in types

    def test_concurrency_challenge(self):
        result = self.engine._step_challenges("async parallel processing", self.s1)
        types = [c["type"] for c in result["challenges"]]
        assert "concurrency" in types

    def test_no_special_risks(self):
        result = self.engine._step_challenges("simple hello world", self.s1)
        assert result["challenges"][0]["type"] == "general"

    def test_max_severity_high(self):
        result = self.engine._step_challenges("security token auth", self.s1)
        assert result["max_severity"] == "high"

    def test_max_severity_low(self):
        result = self.engine._step_challenges("print hello", self.s1)
        assert result["max_severity"] == "low"

    def test_risk_count(self):
        result = self.engine._step_challenges("async database security", self.s1)
        assert result["risk_count"] >= 2


# ── Step 3: Approaches ──────────────────────────────────────────────────


class TestStepApproaches:
    def setup_method(self):
        self.engine = Deep6Minsky()

    def test_code_has_3_approaches(self):
        s1 = {"task_type": TaskType.CODE}
        result = self.engine._step_approaches("write code", s1, {})
        assert result["count"] == 3

    def test_devops_has_3_approaches(self):
        s1 = {"task_type": TaskType.DEVOPS}
        result = self.engine._step_approaches("k8s config", s1, {})
        assert result["count"] == 3

    def test_analysis_has_2_approaches(self):
        s1 = {"task_type": TaskType.ANALYSIS}
        result = self.engine._step_approaches("explain", s1, {})
        assert result["count"] == 2

    def test_unknown_has_2_approaches(self):
        s1 = {"task_type": TaskType.UNKNOWN}
        result = self.engine._step_approaches("something", s1, {})
        assert result["count"] == 2

    def test_each_approach_has_name(self):
        s1 = {"task_type": TaskType.CODE}
        result = self.engine._step_approaches("write", s1, {})
        for a in result["approaches"]:
            assert "name" in a
            assert "pros" in a
            assert "cons" in a


# ── Step 4: Constraints ──────────────────────────────────────────────────


class TestStepConstraints:
    def setup_method(self):
        self.engine = Deep6Minsky()

    def test_evaluates_all_approaches(self):
        s3 = {"approaches": [
            {"name": "A", "risk": "low", "complexity": "low"},
            {"name": "B", "risk": "high", "complexity": "high"},
        ]}
        s2 = {"challenges": []}
        result = self.engine._step_constraints(s3, s2)
        assert len(result["evaluated"]) == 2

    def test_feasibility_clamped(self):
        s3 = {"approaches": [{"name": "X", "risk": "low", "complexity": "low"}]}
        s2 = {"challenges": []}
        result = self.engine._step_constraints(s3, s2)
        f = result["evaluated"][0]["feasibility"]
        assert 0.1 <= f <= 1.0

    def test_high_risk_reduces_feasibility(self):
        s3_low = {"approaches": [{"name": "A", "risk": "low", "complexity": "low"}]}
        s3_high = {"approaches": [{"name": "B", "risk": "high", "complexity": "high"}]}
        s2 = {"challenges": []}
        f_low = self.engine._step_constraints(s3_low, s2)["evaluated"][0]["feasibility"]
        f_high = self.engine._step_constraints(s3_high, s2)["evaluated"][0]["feasibility"]
        assert f_low > f_high

    def test_all_feasible_flag(self):
        s3 = {"approaches": [{"name": "A", "risk": "low", "complexity": "low"}]}
        s2 = {"challenges": []}
        result = self.engine._step_constraints(s3, s2)
        assert result["all_feasible"] is True


# ── Step 5: Choose ───────────────────────────────────────────────────────


class TestStepChoose:
    def setup_method(self):
        self.engine = Deep6Minsky()

    def test_chooses_highest_feasibility(self):
        s3 = {"approaches": [{"name": "A"}, {"name": "B"}, {"name": "C"}]}
        s4 = {"evaluated": [
            {"name": "A", "feasibility": 0.5, "constraints_met": True},
            {"name": "B", "feasibility": 0.9, "constraints_met": True},
            {"name": "C", "feasibility": 0.7, "constraints_met": True},
        ]}
        result = self.engine._step_choose(s3, s4)
        assert result["chosen_index"] == 1
        assert result["chosen_name"] == "B"

    def test_rejected_list(self):
        s3 = {"approaches": [{"name": "A"}, {"name": "B"}]}
        s4 = {"evaluated": [
            {"name": "A", "feasibility": 0.9, "constraints_met": True},
            {"name": "B", "feasibility": 0.5, "constraints_met": True},
        ]}
        result = self.engine._step_choose(s3, s4)
        assert "B" in result["rejected"]

    def test_empty_evaluated(self):
        result = self.engine._step_choose({"approaches": []}, {"evaluated": []})
        assert result["chosen_name"] == "default"


# ── Step 6: Solution ─────────────────────────────────────────────────────


class TestStepSolution:
    def setup_method(self):
        self.engine = Deep6Minsky()

    def test_solution_contains_approach_name(self):
        s5 = {"chosen_name": "Defensive Implementation"}
        result = self.engine._step_solution("test query", s5)
        assert "Defensive Implementation" in result["explanation"]

    def test_code_is_none(self):
        result = self.engine._step_solution("test", {"chosen_name": "X"})
        assert result["code"] is None

    def test_verified_true(self):
        result = self.engine._step_solution("test", {"chosen_name": "X"})
        assert result["verified"] is True


# ── Full Execute Pipeline ────────────────────────────────────────────────


class TestDeep6Execute:
    def setup_method(self):
        self.engine = Deep6Minsky()

    def test_execute_returns_deep6_result(self):
        result = self.engine.execute("write a function")
        assert isinstance(result, Deep6Result)

    def test_all_6_steps_called(self):
        result = self.engine.execute("implement binary search")
        assert len(result.call_sequence) == 6

    def test_step_data_populated(self):
        result = self.engine.execute("analyze code")
        for name in STEP_NAMES:
            assert name in result.step_data

    def test_task_type_set(self):
        result = self.engine.execute("write a class")
        assert result.task_type == TaskType.CODE

    def test_total_time_positive(self):
        result = self.engine.execute("test")
        assert result.total_time > 0

    def test_callback_invoked(self):
        calls = []
        def on_step(step_num, name, status, data):
            calls.append((step_num, name, status))
        self.engine.execute("test", on_step=on_step)
        # 6 steps × 2 (starting + complete) = 12 calls
        assert len(calls) == 12

    def test_callback_exception_ignored(self):
        def bad_callback(*args):
            raise RuntimeError("oops")
        # Should not raise
        result = self.engine.execute("test", on_step=bad_callback)
        assert len(result.call_sequence) == 6


# ── Statistics ───────────────────────────────────────────────────────────


class TestDeep6Statistics:
    def test_initial_stats(self):
        engine = Deep6Minsky()
        stats = engine.get_statistics()
        assert stats["total_runs"] == 0
        assert stats["total_duration_ms"] == 0.0

    def test_stats_after_run(self):
        engine = Deep6Minsky()
        engine.execute("test")
        stats = engine.get_statistics()
        assert stats["total_runs"] == 1
        assert stats["total_duration_ms"] > 0

    def test_stats_after_multiple_runs(self):
        engine = Deep6Minsky()
        engine.execute("test1")
        engine.execute("test2")
        stats = engine.get_statistics()
        assert stats["total_runs"] == 2

    def test_avg_duration(self):
        engine = Deep6Minsky()
        engine.execute("test")
        stats = engine.get_statistics()
        assert stats["avg_duration_ms"] == stats["total_duration_ms"]
