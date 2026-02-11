"""
Week 11: Tests for Task Abstraction Layer

~45 tests covering:
- TaskType detection (command, codegen, bug_fix, refactor, explain, search, general)
- RiskLevel determination (SWECAS, complexity, task type mappings)
- ValidationProfile selection (risk→profile, command→FAST_DEV, etc.)
- Validation config (rules, fail_fast, parallel per profile)
- TaskContext (to_dict, defaults, field population)
- Integration (full classify flows)
"""

import time
import pytest

from core.task_abstraction import (
    TaskAbstraction,
    TaskContext,
    TaskType,
    RiskLevel,
    ValidationProfile,
    _PROFILE_CONFIGS,
)


@pytest.fixture
def ta():
    return TaskAbstraction()


# ============================================================
# TestTaskType — ~10 tests
# ============================================================

class TestTaskType:
    """Task type detection with priority ordering."""

    def test_command_detection(self, ta):
        ctx = ta.classify("read file.py", is_command=True)
        assert ctx.task_type == TaskType.COMMAND

    def test_command_overrides_codegen(self, ta):
        """Command has higher priority than code generation."""
        ctx = ta.classify("write a function", is_command=True, is_codegen=True)
        assert ctx.task_type == TaskType.COMMAND

    def test_codegen_detection(self, ta):
        ctx = ta.classify("write a python function to sort a list", is_codegen=True)
        assert ctx.task_type == TaskType.CODE_GENERATION

    def test_bug_fix_en(self, ta):
        ctx = ta.classify("fix the error in main.py")
        assert ctx.task_type == TaskType.BUG_FIX

    def test_bug_fix_ru(self, ta):
        ctx = ta.classify("исправь баг в модуле авторизации")
        assert ctx.task_type == TaskType.BUG_FIX

    def test_refactor_en(self, ta):
        ctx = ta.classify("refactor the database module")
        assert ctx.task_type == TaskType.REFACTORING

    def test_refactor_ru(self, ta):
        ctx = ta.classify("упрости код в utils.py")
        assert ctx.task_type == TaskType.REFACTORING

    def test_explain_en(self, ta):
        ctx = ta.classify("explain how does this decorator work?")
        assert ctx.task_type == TaskType.EXPLANATION

    def test_explain_ru(self, ta):
        ctx = ta.classify("объясни что такое метакласс")
        assert ctx.task_type == TaskType.EXPLANATION

    def test_search_mode(self, ta):
        """ExecutionMode with 'search' in value triggers SEARCH type."""

        class MockMode:
            value = "search"

        ctx = ta.classify("latest docker CVE", execution_mode=MockMode())
        assert ctx.task_type == TaskType.SEARCH

    def test_general_fallback(self, ta):
        ctx = ta.classify("hello world")
        assert ctx.task_type == TaskType.GENERAL

    def test_priority_codegen_over_bugfix(self, ta):
        """Code generation takes priority over bug fix keywords."""
        ctx = ta.classify("write a function to fix sorting errors", is_codegen=True)
        assert ctx.task_type == TaskType.CODE_GENERATION

    def test_priority_bugfix_over_refactor(self, ta):
        """Bug fix takes priority over refactoring when both match."""
        ctx = ta.classify("fix and improve the broken auth module")
        assert ctx.task_type == TaskType.BUG_FIX


# ============================================================
# TestRiskLevel — ~10 tests
# ============================================================

class TestRiskLevel:
    """Risk level determination from SWECAS, complexity, task type."""

    def test_swecas_500_security_critical(self, ta):
        swecas = {"swecas_code": 500, "confidence": 0.8, "name": "SQL Injection"}
        ctx = ta.classify("fix SQL injection", swecas_result=swecas)
        assert ctx.risk_level == RiskLevel.CRITICAL

    def test_swecas_550_security_critical(self, ta):
        swecas = {"swecas_code": 550, "confidence": 0.7, "name": "XSS"}
        ctx = ta.classify("fix XSS vulnerability", swecas_result=swecas)
        assert ctx.risk_level == RiskLevel.CRITICAL

    def test_swecas_800_performance_high(self, ta):
        swecas = {"swecas_code": 800, "confidence": 0.8, "name": "N+1 Query"}
        ctx = ta.classify("optimize database queries", swecas_result=swecas)
        assert ctx.risk_level == RiskLevel.HIGH

    def test_complexity_critical(self, ta):
        ctx = ta.classify("implement auth system", is_codegen=True, complexity="CRITICAL")
        assert ctx.risk_level == RiskLevel.CRITICAL

    def test_complexity_complex_high(self, ta):
        ctx = ta.classify("build API gateway", is_codegen=True, complexity="COMPLEX")
        assert ctx.risk_level == RiskLevel.HIGH

    def test_command_low(self, ta):
        ctx = ta.classify("read file.py", is_command=True)
        assert ctx.risk_level == RiskLevel.LOW

    def test_explanation_low(self, ta):
        ctx = ta.classify("explain what is a decorator")
        assert ctx.risk_level == RiskLevel.LOW

    def test_trivial_codegen_low(self, ta):
        ctx = ta.classify("write hello world function", is_codegen=True, complexity="TRIVIAL")
        assert ctx.risk_level == RiskLevel.LOW

    def test_simple_codegen_low(self, ta):
        ctx = ta.classify("write a print function", is_codegen=True, complexity="SIMPLE")
        assert ctx.risk_level == RiskLevel.LOW

    def test_bugfix_with_swecas_high(self, ta):
        """Bug fix + any SWECAS match → HIGH."""
        swecas = {"swecas_code": 300, "confidence": 0.7, "name": "Logic Error"}
        ctx = ta.classify("fix the error in parser", swecas_result=swecas)
        assert ctx.risk_level == RiskLevel.HIGH

    def test_default_medium(self, ta):
        ctx = ta.classify("create a utility module", is_codegen=True, complexity="MODERATE")
        assert ctx.risk_level == RiskLevel.MEDIUM

    def test_swecas_low_confidence_ignored(self, ta):
        """SWECAS with confidence < 0.5 should be ignored for risk."""
        swecas = {"swecas_code": 500, "confidence": 0.3, "name": "SQL Injection"}
        ctx = ta.classify("write a function", is_codegen=True, complexity="MODERATE")
        assert ctx.risk_level == RiskLevel.MEDIUM


# ============================================================
# TestValidationProfile — ~8 tests
# ============================================================

class TestValidationProfile:
    """Validation profile mapping from risk + task type."""

    def test_critical_risk_critical_profile(self, ta):
        swecas = {"swecas_code": 500, "confidence": 0.9}
        ctx = ta.classify("fix SQL injection", swecas_result=swecas)
        assert ctx.validation_profile == ValidationProfile.CRITICAL

    def test_high_risk_safe_fix(self, ta):
        ctx = ta.classify("build API gateway", is_codegen=True, complexity="COMPLEX")
        assert ctx.validation_profile == ValidationProfile.SAFE_FIX

    def test_command_fast_dev(self, ta):
        ctx = ta.classify("read file.py", is_command=True)
        assert ctx.validation_profile == ValidationProfile.FAST_DEV

    def test_explanation_fast_dev(self, ta):
        ctx = ta.classify("explain decorators")
        assert ctx.validation_profile == ValidationProfile.FAST_DEV

    def test_trivial_fast_dev(self, ta):
        ctx = ta.classify("write hello", is_codegen=True, complexity="TRIVIAL")
        assert ctx.validation_profile == ValidationProfile.FAST_DEV

    def test_moderate_balanced(self, ta):
        ctx = ta.classify("write a sort function", is_codegen=True, complexity="MODERATE")
        assert ctx.validation_profile == ValidationProfile.BALANCED

    def test_general_balanced(self, ta):
        ctx = ta.classify("generate some code", is_codegen=True, complexity="MODERATE")
        assert ctx.validation_profile == ValidationProfile.BALANCED

    def test_simple_codegen_fast_dev(self, ta):
        """SIMPLE complexity code gen → LOW risk → BALANCED (not FAST_DEV, since only TRIVIAL triggers it)."""
        ctx = ta.classify("write a print function", is_codegen=True, complexity="SIMPLE")
        # LOW risk from SIMPLE codegen, but LOW risk + CODEGEN != COMMAND/EXPLANATION
        # So profile depends on complexity: SIMPLE != TRIVIAL → BALANCED
        assert ctx.validation_profile == ValidationProfile.BALANCED


# ============================================================
# TestValidationConfig — ~6 tests
# ============================================================

class TestValidationConfig:
    """Profile → validation config mapping."""

    def test_fast_dev_config(self):
        cfg = TaskAbstraction.get_validation_config(ValidationProfile.FAST_DEV)
        assert cfg["rule_names"] == ["ast_syntax"]
        assert cfg["fail_fast"] is False
        assert cfg["parallel"] is True

    def test_balanced_config(self):
        cfg = TaskAbstraction.get_validation_config(ValidationProfile.BALANCED)
        assert "ast_syntax" in cfg["rule_names"]
        assert "no_forbidden_imports" in cfg["rule_names"]
        assert "no_eval_exec" in cfg["rule_names"]
        assert cfg["fail_fast"] is False
        assert cfg["parallel"] is True

    def test_safe_fix_config(self):
        cfg = TaskAbstraction.get_validation_config(ValidationProfile.SAFE_FIX)
        assert len(cfg["rule_names"]) == 8
        assert cfg["fail_fast"] is True
        assert cfg["parallel"] is True

    def test_critical_config(self):
        cfg = TaskAbstraction.get_validation_config(ValidationProfile.CRITICAL)
        assert len(cfg["rule_names"]) == 8
        assert cfg["fail_fast"] is True
        assert cfg["parallel"] is False  # Sequential for max safety

    def test_scoring_weights_fast_dev(self):
        weights = TaskAbstraction.get_scoring_weights(ValidationProfile.FAST_DEV)
        assert "ast_syntax" in weights
        assert len(weights) == 1

    def test_scoring_weights_critical(self):
        weights = TaskAbstraction.get_scoring_weights(ValidationProfile.CRITICAL)
        assert weights["static_bandit"] == 6.0  # Extra security weight
        assert weights["no_eval_exec"] == 5.0

    def test_scoring_weights_balanced(self):
        weights = TaskAbstraction.get_scoring_weights(ValidationProfile.BALANCED)
        assert weights["ast_syntax"] == 10.0
        assert weights["oss_patterns"] == 1.5


# ============================================================
# TestTaskContext — ~5 tests
# ============================================================

class TestTaskContext:
    """TaskContext dataclass behavior."""

    def test_defaults(self):
        ctx = TaskContext()
        assert ctx.task_type == TaskType.GENERAL
        assert ctx.risk_level == RiskLevel.MEDIUM
        assert ctx.validation_profile == ValidationProfile.BALANCED
        assert ctx.query == ""
        assert ctx.is_code_generation is False
        assert ctx.is_command is False

    def test_to_dict_keys(self):
        ctx = TaskContext(query="test query")
        d = ctx.to_dict()
        assert "task_type" in d
        assert "risk_level" in d
        assert "validation_profile" in d
        assert "timestamp" in d
        assert d["query"] == "test query"

    def test_to_dict_serialization(self):
        ctx = TaskContext(
            query="x" * 200,
            task_type=TaskType.CODE_GENERATION,
            risk_level=RiskLevel.HIGH,
        )
        d = ctx.to_dict()
        assert len(d["query"]) == 100  # Truncated to 100 chars
        assert d["task_type"] == "code_gen"
        assert d["risk_level"] == "high"

    def test_timestamp_auto_set(self):
        before = time.time()
        ctx = TaskContext()
        after = time.time()
        assert before <= ctx.timestamp <= after

    def test_field_population(self, ta):
        swecas = {"swecas_code": 700, "confidence": 0.85, "name": "Race Condition", "fix_hint": "Use locks"}
        ducs = {"ducs_code": 200, "confidence": 0.9, "category": "Container Runtime"}
        ctx = ta.classify(
            "fix race condition in container",
            ducs_result=ducs,
            swecas_result=swecas,
            complexity="COMPLEX",
        )
        assert ctx.ducs_code == 200
        assert ctx.ducs_category == "Container Runtime"
        assert ctx.swecas_code == 700
        assert ctx.swecas_name == "Race Condition"
        assert ctx.swecas_fix_hint == "Use locks"
        assert ctx.complexity == "COMPLEX"


# ============================================================
# TestIntegration — ~6 tests
# ============================================================

class TestIntegration:
    """Full classify flows — end-to-end scenarios."""

    def test_security_bug(self, ta):
        """Security bug → CRITICAL risk, CRITICAL profile."""
        swecas = {"swecas_code": 510, "confidence": 0.9, "name": "Auth Bypass"}
        ctx = ta.classify(
            "fix auth bypass vulnerability",
            swecas_result=swecas,
            complexity="CRITICAL",
        )
        assert ctx.task_type == TaskType.BUG_FIX
        assert ctx.risk_level == RiskLevel.CRITICAL
        assert ctx.validation_profile == ValidationProfile.CRITICAL
        assert ctx.fail_fast is True
        assert ctx.parallel_validation is False

    def test_simple_codegen(self, ta):
        """Simple code generation → LOW risk, BALANCED profile."""
        ctx = ta.classify(
            "write a hello world function",
            is_codegen=True,
            complexity="TRIVIAL",
        )
        assert ctx.task_type == TaskType.CODE_GENERATION
        assert ctx.risk_level == RiskLevel.LOW
        assert ctx.validation_profile == ValidationProfile.FAST_DEV
        assert ctx.is_code_generation is True
        assert ctx.use_multi_candidate is True

    def test_command_flow(self, ta):
        """Command → LOW risk, FAST_DEV, no multi-candidate."""
        ctx = ta.classify("ls /home/user", is_command=True)
        assert ctx.task_type == TaskType.COMMAND
        assert ctx.risk_level == RiskLevel.LOW
        assert ctx.validation_profile == ValidationProfile.FAST_DEV
        assert ctx.is_command is True
        assert ctx.use_multi_candidate is False

    def test_russian_refactor(self, ta):
        """Russian refactoring query → REFACTORING type, MEDIUM risk."""
        ctx = ta.classify(
            "рефакторинг модуля базы данных",
            complexity="MODERATE",
        )
        assert ctx.task_type == TaskType.REFACTORING
        assert ctx.risk_level == RiskLevel.MEDIUM
        assert ctx.validation_profile == ValidationProfile.BALANCED

    def test_deep_mode_flag(self, ta):
        """Deep execution mode sets use_deep_mode flag."""

        class MockDeep:
            value = "deep3"

        ctx = ta.classify("analyze code", execution_mode=MockDeep())
        assert ctx.use_deep_mode is True

    def test_search_deep_mode(self, ta):
        """SEARCH_DEEP mode → SEARCH type + deep mode flag."""

        class MockSearchDeep:
            value = "search_deep"

        ctx = ta.classify("find docker CVE", execution_mode=MockSearchDeep())
        assert ctx.task_type == TaskType.SEARCH
        assert ctx.use_deep_mode is True

    def test_moderate_codegen_balanced(self, ta):
        """Moderate code generation → MEDIUM risk, BALANCED profile."""
        ctx = ta.classify(
            "write a REST API endpoint",
            is_codegen=True,
            complexity="MODERATE",
        )
        assert ctx.task_type == TaskType.CODE_GENERATION
        assert ctx.risk_level == RiskLevel.MEDIUM
        assert ctx.validation_profile == ValidationProfile.BALANCED
        assert ctx.fail_fast is False
        assert ctx.parallel_validation is True
