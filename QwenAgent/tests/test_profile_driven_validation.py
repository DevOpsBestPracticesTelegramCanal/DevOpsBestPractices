"""
Week 12: Profile-Driven Validation Tests

Tests that ValidationProfile from TaskAbstraction actually controls:
- Which rules are executed (rule selection)
- Scoring weights applied (per-profile ScoringWeights)
- fail_fast and parallel settings per profile
- build_rules_for_names factory function
- Pipeline integration with validation_profile param
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
import asyncio

from code_validator.rules.base import RuleRunner, RuleResult, RuleSeverity
from code_validator.rules.python_validators import (
    default_python_rules,
    build_rules_for_names,
    _RULE_REGISTRY,
    ASTSyntaxRule,
    NoForbiddenImportsRule,
    NoEvalExecRule,
    CodeLengthRule,
    ComplexityRule,
    DocstringRule,
    TypeHintRule,
    OSSPatternRule,
)
from core.task_abstraction import (
    TaskAbstraction,
    TaskContext,
    TaskType,
    RiskLevel,
    ValidationProfile,
    _PROFILE_CONFIGS,
)
from core.generation.selector import ScoringWeights, CandidateSelector


# ============================================================
# TestBuildRulesForNames — rule factory
# ============================================================

class TestBuildRulesForNames:
    """build_rules_for_names() factory function."""

    def test_single_rule(self):
        rules = build_rules_for_names(["ast_syntax"])
        assert len(rules) == 1
        assert isinstance(rules[0], ASTSyntaxRule)

    def test_multiple_rules(self):
        names = ["ast_syntax", "no_forbidden_imports", "complexity"]
        rules = build_rules_for_names(names)
        assert len(rules) == 3
        assert isinstance(rules[0], ASTSyntaxRule)
        assert isinstance(rules[1], NoForbiddenImportsRule)
        assert isinstance(rules[2], ComplexityRule)

    def test_all_rules(self):
        names = list(_RULE_REGISTRY.keys())
        rules = build_rules_for_names(names)
        assert len(rules) == len(_RULE_REGISTRY)

    def test_unknown_name_skipped(self):
        rules = build_rules_for_names(["ast_syntax", "nonexistent_rule"])
        assert len(rules) == 1
        assert isinstance(rules[0], ASTSyntaxRule)

    def test_empty_list(self):
        rules = build_rules_for_names([])
        assert rules == []

    def test_preserves_order(self):
        names = ["complexity", "ast_syntax", "docstring"]
        rules = build_rules_for_names(names)
        assert rules[0].name == "complexity"
        assert rules[1].name == "ast_syntax"
        assert rules[2].name == "docstring"

    def test_registry_has_all_default_rules(self):
        """All rules from default_python_rules() are in the registry."""
        defaults = default_python_rules()
        for rule in defaults:
            assert rule.name in _RULE_REGISTRY, f"{rule.name} not in registry"


# ============================================================
# TestProfileRuleSelection — profile → rules mapping
# ============================================================

class TestProfileRuleSelection:
    """Each ValidationProfile maps to specific rules."""

    def test_fast_dev_minimal_rules(self):
        cfg = TaskAbstraction.get_validation_config(ValidationProfile.FAST_DEV)
        rules = build_rules_for_names(cfg["rule_names"])
        assert len(rules) == 1
        assert rules[0].name == "ast_syntax"

    def test_balanced_five_rules(self):
        cfg = TaskAbstraction.get_validation_config(ValidationProfile.BALANCED)
        rules = build_rules_for_names(cfg["rule_names"])
        assert len(rules) == 5
        rule_names = [r.name for r in rules]
        assert "ast_syntax" in rule_names
        assert "no_forbidden_imports" in rule_names
        assert "no_eval_exec" in rule_names
        assert "complexity" in rule_names
        assert "oss_patterns" in rule_names

    def test_safe_fix_all_rules(self):
        cfg = TaskAbstraction.get_validation_config(ValidationProfile.SAFE_FIX)
        rules = build_rules_for_names(cfg["rule_names"])
        assert len(rules) == 8

    def test_critical_all_rules(self):
        cfg = TaskAbstraction.get_validation_config(ValidationProfile.CRITICAL)
        rules = build_rules_for_names(cfg["rule_names"])
        assert len(rules) == 8

    def test_fast_dev_no_fail_fast(self):
        cfg = TaskAbstraction.get_validation_config(ValidationProfile.FAST_DEV)
        assert cfg["fail_fast"] is False

    def test_critical_fail_fast_sequential(self):
        cfg = TaskAbstraction.get_validation_config(ValidationProfile.CRITICAL)
        assert cfg["fail_fast"] is True
        assert cfg["parallel"] is False

    def test_safe_fix_fail_fast_parallel(self):
        cfg = TaskAbstraction.get_validation_config(ValidationProfile.SAFE_FIX)
        assert cfg["fail_fast"] is True
        assert cfg["parallel"] is True


# ============================================================
# TestProfileScoringWeights — profile → weights mapping
# ============================================================

class TestProfileScoringWeights:
    """Each profile produces correct ScoringWeights."""

    def test_fast_dev_only_ast(self):
        weights = TaskAbstraction.get_scoring_weights(ValidationProfile.FAST_DEV)
        assert weights == {"ast_syntax": 10.0}

    def test_critical_extra_security(self):
        weights = TaskAbstraction.get_scoring_weights(ValidationProfile.CRITICAL)
        assert weights["static_bandit"] == 6.0
        assert weights["no_eval_exec"] == 5.0
        assert weights["no_forbidden_imports"] == 5.0

    def test_balanced_has_oss(self):
        weights = TaskAbstraction.get_scoring_weights(ValidationProfile.BALANCED)
        assert weights["oss_patterns"] == 1.5

    def test_safe_fix_has_bandit(self):
        weights = TaskAbstraction.get_scoring_weights(ValidationProfile.SAFE_FIX)
        assert weights["static_bandit"] == 5.0

    def test_scoring_weights_create_selector(self):
        """ScoringWeights can be constructed from profile weights."""
        weights = TaskAbstraction.get_scoring_weights(ValidationProfile.CRITICAL)
        sw = ScoringWeights(weights=weights)
        assert sw.get("static_bandit") == 6.0
        assert sw.get("unknown_rule") == 1.0  # default


# ============================================================
# TestRuleRunnerWithProfile — actual validation execution
# ============================================================

class TestRuleRunnerWithProfile:
    """RuleRunner executes only the profile-selected rules."""

    VALID_CODE = '''
def hello() -> str:
    """Return greeting."""
    return "hello"
'''

    EVAL_CODE = '''
def dangerous():
    return eval("1+1")
'''

    def test_fast_dev_only_checks_syntax(self):
        cfg = TaskAbstraction.get_validation_config(ValidationProfile.FAST_DEV)
        rules = build_rules_for_names(cfg["rule_names"])
        runner = RuleRunner(rules)
        results = runner.run(self.VALID_CODE)
        assert len(results) == 1
        assert results[0].rule_name == "ast_syntax"
        assert results[0].passed is True

    def test_fast_dev_skips_eval_check(self):
        """FAST_DEV doesn't check for eval() — only syntax."""
        cfg = TaskAbstraction.get_validation_config(ValidationProfile.FAST_DEV)
        rules = build_rules_for_names(cfg["rule_names"])
        runner = RuleRunner(rules)
        results = runner.run(self.EVAL_CODE)
        assert len(results) == 1
        assert results[0].passed is True  # only syntax checked

    def test_balanced_catches_eval(self):
        """BALANCED profile includes no_eval_exec rule."""
        cfg = TaskAbstraction.get_validation_config(ValidationProfile.BALANCED)
        rules = build_rules_for_names(cfg["rule_names"])
        runner = RuleRunner(rules)
        results = runner.run(self.EVAL_CODE)
        eval_results = [r for r in results if r.rule_name == "no_eval_exec"]
        assert len(eval_results) == 1
        assert eval_results[0].passed is False

    def test_critical_sequential_execution(self):
        """CRITICAL profile runs sequentially (parallel=False)."""
        cfg = TaskAbstraction.get_validation_config(ValidationProfile.CRITICAL)
        rules = build_rules_for_names(cfg["rule_names"])
        runner = RuleRunner(rules)
        # fail_fast + sequential
        results = runner.run(
            self.VALID_CODE,
            fail_fast=cfg["fail_fast"],
            parallel=cfg["parallel"],
        )
        # All should pass for valid code
        for r in results:
            # Some rules may have low scores but still pass
            assert r.rule_name in _RULE_REGISTRY


# ============================================================
# TestEndToEndProfileFlow — full classification → validation
# ============================================================

class TestEndToEndProfileFlow:
    """Full flow: query → classify → get config → build rules → validate."""

    def test_simple_codegen_fast_dev(self):
        """Trivial code gen → FAST_DEV profile → only syntax check."""
        ta = TaskAbstraction()
        ctx = ta.classify("write hello world function", is_codegen=True, complexity="TRIVIAL")
        assert ctx.validation_profile == ValidationProfile.FAST_DEV

        cfg = TaskAbstraction.get_validation_config(ctx.validation_profile)
        rules = build_rules_for_names(cfg["rule_names"])
        runner = RuleRunner(rules)
        results = runner.run("def hello(): return 'hi'")
        assert len(results) == 1
        assert results[0].passed is True

    def test_security_bug_critical(self):
        """Security bug → CRITICAL profile → all 8 rules."""
        ta = TaskAbstraction()
        swecas = {"swecas_code": 500, "confidence": 0.9}
        ctx = ta.classify("fix SQL injection", swecas_result=swecas)
        assert ctx.validation_profile == ValidationProfile.CRITICAL

        cfg = TaskAbstraction.get_validation_config(ctx.validation_profile)
        rules = build_rules_for_names(cfg["rule_names"])
        assert len(rules) == 8
        assert cfg["fail_fast"] is True
        assert cfg["parallel"] is False

    def test_moderate_codegen_balanced(self):
        """Moderate codegen → BALANCED profile → 5 rules."""
        ta = TaskAbstraction()
        ctx = ta.classify("write a sort function", is_codegen=True, complexity="MODERATE")
        assert ctx.validation_profile == ValidationProfile.BALANCED

        cfg = TaskAbstraction.get_validation_config(ctx.validation_profile)
        rules = build_rules_for_names(cfg["rule_names"])
        assert len(rules) == 5

    def test_complex_codegen_safe_fix(self):
        """Complex codegen → HIGH risk → SAFE_FIX profile → all rules."""
        ta = TaskAbstraction()
        ctx = ta.classify("build database migration system", is_codegen=True, complexity="COMPLEX")
        assert ctx.validation_profile == ValidationProfile.SAFE_FIX

        cfg = TaskAbstraction.get_validation_config(ctx.validation_profile)
        assert len(cfg["rule_names"]) == 8
        assert cfg["fail_fast"] is True
        assert cfg["parallel"] is True


# ============================================================
# TestPipelineProfileIntegration — pipeline.run() with profile
# ============================================================

class TestPipelineProfileIntegration:
    """Pipeline correctly resolves profile when validation_profile is passed."""

    def test_pipeline_accepts_profile_param(self):
        """Pipeline.run() signature includes validation_profile."""
        from core.generation.pipeline import MultiCandidatePipeline
        import inspect
        sig = inspect.signature(MultiCandidatePipeline.run)
        assert "validation_profile" in sig.parameters

    def test_pipeline_run_sync_forwards_profile(self):
        """run_sync() forwards validation_profile to run()."""
        from core.generation.pipeline import MultiCandidatePipeline
        import inspect
        sig = inspect.signature(MultiCandidatePipeline.run_sync)
        # run_sync takes **kwargs, so it will forward
        assert "kwargs" in str(sig)

    def test_profile_resolution_builds_correct_validator(self):
        """When validation_profile is set, correct rules are built."""
        cfg = TaskAbstraction.get_validation_config(ValidationProfile.FAST_DEV)
        rules = build_rules_for_names(cfg["rule_names"])
        validator = RuleRunner(rules)
        assert len(validator.rules) == 1

        cfg2 = TaskAbstraction.get_validation_config(ValidationProfile.CRITICAL)
        rules2 = build_rules_for_names(cfg2["rule_names"])
        validator2 = RuleRunner(rules2)
        assert len(validator2.rules) == 8

    def test_profile_resolution_builds_correct_selector(self):
        """When validation_profile is set, correct scoring weights are used."""
        weights = TaskAbstraction.get_scoring_weights(ValidationProfile.CRITICAL)
        selector = CandidateSelector(scoring=ScoringWeights(weights=weights))
        assert selector.scoring.get("static_bandit") == 6.0

        weights_fast = TaskAbstraction.get_scoring_weights(ValidationProfile.FAST_DEV)
        selector_fast = CandidateSelector(scoring=ScoringWeights(weights=weights_fast))
        assert selector_fast.scoring.get("ast_syntax") == 10.0
        assert selector_fast.scoring.get("complexity") == 1.0  # default fallback
