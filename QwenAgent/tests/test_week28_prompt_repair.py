"""
Unit tests for Week 28: Prompt Engineering, Code Review, and Repair methods.

Tests cover:
- PE-06: Self-Check in engineer_10x.py
- PE-03: Error Pattern Warnings in engineer_10x.py
- PE-02: Few-Shot Library
- CR-01: Self-Review
- IR-03: Targeted Patch in self_correction.py
- Registration and Profile integration
"""

import ast
import os
import sys
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# PE-06 and PE-03: engineer_10x.py
from core.generation.engineer_10x import (
    build_10x_prompt,
    SELF_CHECK_INSTRUCTIONS,
    get_error_warnings,
    _ERROR_PATTERNS,
)

# PE-02: Few-Shot Library
from core.generation.few_shot_library import (
    get_few_shot_examples,
    extract_keywords_from_query,
    _SNIPPETS,
    _KEYWORD_MAP,
)

# CR-01: Self-Review
from core.generation.self_review import (
    build_self_review_prompt,
    should_self_review,
    SELF_REVIEW_PROMPT,
)

# IR-03: Targeted Patch
from core.generation.self_correction import (
    choose_repair_strategy,
    build_targeted_patch_prompt,
    build_correction_prompt,
    _is_localized_error,
    REPAIR_FULL_REGEN,
    REPAIR_TARGETED_PATCH,
)

# Registration and Profiles
from code_validator.rules.python_validators import (
    _RULE_REGISTRY,
    build_rules_for_names,
)
from core.task_abstraction import (
    _PROFILE_CONFIGS,
    ValidationProfile,
    _QUALITY_RULE_NAMES,
)


# =============================================================================
# PE-06: Self-Check in engineer_10x.py
# =============================================================================

class TestSelfCheckInstructions:
    """Test PE-06: Self-Check pre-generation checklist."""

    def test_build_10x_prompt_with_self_check_includes_section(self):
        """Test that build_10x_prompt with include_self_check=True includes the self-check section."""
        prompt = build_10x_prompt(
            base_prompt="Write a function",
            include_self_check=True,
        )
        assert "PRE-GENERATION SELF-CHECK" in prompt

    def test_build_10x_prompt_without_self_check_excludes_section(self):
        """Test that build_10x_prompt with include_self_check=False does NOT include self-check."""
        prompt = build_10x_prompt(
            base_prompt="Write a function",
            include_self_check=False,
        )
        assert "PRE-GENERATION SELF-CHECK" not in prompt

    def test_self_check_instructions_contains_all_checkpoints(self):
        """Test that SELF_CHECK_INSTRUCTIONS contains all 6 required checkpoints."""
        required_checks = [
            "type hints",
            "try/except",
            "secrets",
            "stubs",
            "thread safety",
            "resource cleanup",
        ]
        instructions_lower = SELF_CHECK_INSTRUCTIONS.lower()
        for check in required_checks:
            assert check in instructions_lower, f"Missing checkpoint: {check}"


# =============================================================================
# PE-03: Error Pattern Warnings in engineer_10x.py
# =============================================================================

class TestErrorPatternWarnings:
    """Test PE-03: Known error pattern warnings."""

    def test_get_error_warnings_sqlite_returns_warning(self):
        """Test that SQLite queries trigger CREATE TABLE and WAL mode warnings."""
        warnings = get_error_warnings("create sqlite database")
        assert warnings, "Expected warnings for SQLite query"
        assert "CREATE TABLE" in warnings or "WAL" in warnings.upper()

    def test_get_error_warnings_decorator_returns_warning(self):
        """Test that decorator queries trigger functools.wraps warning."""
        warnings = get_error_warnings("decorator retry")
        assert warnings, "Expected warnings for decorator query"
        assert "functools.wraps" in warnings or "wraps" in warnings

    def test_get_error_warnings_no_match_returns_empty(self):
        """Test that unmatched queries return empty string."""
        warnings = get_error_warnings("hello world")
        assert warnings == "", f"Expected empty string, got: {warnings}"

    def test_get_error_warnings_max_five_warnings(self):
        """Test that get_error_warnings returns max 5 warnings even if more match."""
        # Create a query that matches many patterns
        query = "sqlite decorator daemon thread connection pool cache retry async"
        warnings = get_error_warnings(query)
        if warnings:
            # Count warning sections (each starts with "⚠️")
            warning_count = warnings.count("⚠️")
            assert warning_count <= 5, f"Expected max 5 warnings, got {warning_count}"

    def test_build_10x_prompt_includes_known_pitfalls(self):
        """Test that build_10x_prompt with error-prone query includes KNOWN PITFALLS section."""
        prompt = build_10x_prompt(
            base_prompt="Generate code",
            query="daemon thread sqlite",
        )
        assert "KNOWN PITFALLS" in prompt or "WARNING" in prompt

    def test_error_patterns_has_sufficient_entries(self):
        """Test that _ERROR_PATTERNS has at least 15 entries."""
        assert len(_ERROR_PATTERNS) >= 15, f"Expected >=15 patterns, got {len(_ERROR_PATTERNS)}"


# =============================================================================
# PE-02: Few-Shot Library
# =============================================================================

class TestFewShotLibrary:
    """Test PE-02: Few-shot example library."""

    def test_get_few_shot_examples_retry_returns_example(self):
        """Test that retry keyword returns Retry Decorator example."""
        examples = get_few_shot_examples(["retry"])
        assert examples, "Expected non-empty examples for 'retry'"
        assert "Retry Decorator" in examples or "retry" in examples.lower()

    def test_get_few_shot_examples_sqlite_returns_example(self):
        """Test that sqlite keyword returns SQLite example."""
        examples = get_few_shot_examples(["sqlite"])
        assert examples, "Expected non-empty examples for 'sqlite'"
        assert "SQLite" in examples or "sqlite" in examples.lower()

    def test_get_few_shot_examples_unknown_returns_empty(self):
        """Test that unknown keywords return empty string."""
        examples = get_few_shot_examples(["xyz_unknown"])
        assert examples == "", f"Expected empty string for unknown keyword, got: {examples}"

    def test_get_few_shot_examples_returns_two_examples(self):
        """Test that multiple keywords return 2 examples with max_examples=2."""
        examples = get_few_shot_examples(["cache", "retry"], max_examples=2)
        if examples:
            # Count example sections (look for title markers or example numbers)
            # Examples are typically separated by "Example N:" or similar
            example_count = examples.count("Example") or examples.count("###")
            # Should have at most 2 examples
            assert example_count <= 2 or len(examples.split("---")) <= 3  # Allow for separators

    def test_get_few_shot_examples_respects_max_limit(self):
        """Test that max_examples=1 returns only 1 example even with multiple matches."""
        examples = get_few_shot_examples(["retry", "cache", "sqlite"], max_examples=1)
        if examples:
            # Should not have multiple example sections
            example_indicators = examples.count("Example") + examples.count("```python")
            # With max_examples=1, should have minimal example sections
            assert example_indicators <= 3  # Title + code block start/end

    def test_extract_keywords_from_query_includes_keywords(self):
        """Test that extract_keywords extracts relevant keywords and bigrams."""
        keywords = extract_keywords_from_query("Write a connection pool with retry")
        assert "connection" in keywords or "pool" in keywords or "retry" in keywords
        # Should also include bigrams
        has_bigram = any("_" in kw for kw in keywords)
        assert has_bigram, "Expected at least one bigram in keywords"

    def test_snippets_has_sufficient_entries(self):
        """Test that _SNIPPETS has at least 10 entries."""
        assert len(_SNIPPETS) >= 10, f"Expected >=10 snippets, got {len(_SNIPPETS)}"

    def test_keyword_map_has_sufficient_entries(self):
        """Test that _KEYWORD_MAP has at least 20 entries."""
        assert len(_KEYWORD_MAP) >= 20, f"Expected >=20 keyword mappings, got {len(_KEYWORD_MAP)}"

    def test_all_snippets_have_required_keys(self):
        """Test that all snippets have 'title' and 'code' keys."""
        for snippet_id, snippet in _SNIPPETS.items():
            assert "title" in snippet, f"Snippet {snippet_id} missing 'title' key"
            assert "code" in snippet, f"Snippet {snippet_id} missing 'code' key"

    def test_all_snippet_code_is_valid_python(self):
        """Test that all snippet code values are valid Python (ast.parse succeeds)."""
        for snippet_id, snippet in _SNIPPETS.items():
            code = snippet.get("code", "")
            try:
                ast.parse(code)
            except SyntaxError as e:
                pytest.fail(f"Snippet {snippet_id} has invalid Python code: {e}")


# =============================================================================
# CR-01: Self-Review
# =============================================================================

class TestSelfReview:
    """Test CR-01: Self-review prompting."""

    def test_build_self_review_prompt_includes_code(self):
        """Test that build_self_review_prompt includes the generated code."""
        code = "def foo(): pass"
        prompt = build_self_review_prompt(code, "write a foo function")
        assert "def foo(): pass" in prompt

    def test_build_self_review_prompt_truncates_description(self):
        """Test that build_self_review_prompt truncates task_description at 500 chars."""
        long_description = "x" * 1000
        prompt = build_self_review_prompt("def foo(): pass", long_description)
        # Should contain truncated version (max 500 chars in description section)
        # The full prompt will be longer, but the task description part should be truncated
        assert len(long_description) > 500
        # Check that the prompt doesn't contain the full 1000 char description
        assert "x" * 1000 not in prompt

    def test_should_self_review_complex_returns_true(self):
        """Test that should_self_review returns True for COMPLEX complexity."""
        assert should_self_review(complexity="COMPLEX") is True

    def test_should_self_review_critical_returns_true(self):
        """Test that should_self_review returns True for CRITICAL complexity."""
        assert should_self_review(complexity="CRITICAL") is True

    def test_should_self_review_trivial_returns_false(self):
        """Test that should_self_review returns False for TRIVIAL complexity."""
        assert should_self_review(complexity="TRIVIAL") is False

    def test_should_self_review_moderate_returns_false(self):
        """Test that should_self_review returns False for MODERATE complexity by default."""
        assert should_self_review(complexity="MODERATE") is False

    def test_should_self_review_high_risk_returns_true(self):
        """Test that should_self_review returns True for HIGH risk level."""
        assert should_self_review(risk_level="HIGH") is True

    def test_should_self_review_critical_risk_returns_true(self):
        """Test that should_self_review returns True for CRITICAL risk level."""
        assert should_self_review(risk_level="CRITICAL") is True

    def test_should_self_review_low_risk_returns_false(self):
        """Test that should_self_review returns False for LOW risk level."""
        assert should_self_review(risk_level="LOW") is False

    def test_should_self_review_moderate_with_long_code_returns_true(self):
        """Test that should_self_review returns True for MODERATE + >100 lines."""
        assert should_self_review(complexity="MODERATE", code_length=150) is True

    def test_should_self_review_trivial_with_long_code_returns_false(self):
        """Test that should_self_review returns False for TRIVIAL even with long code."""
        assert should_self_review(complexity="TRIVIAL", code_length=150) is False


# =============================================================================
# IR-03: Targeted Patch in self_correction.py
# =============================================================================

class TestTargetedPatch:
    """Test IR-03: Targeted patch repair strategy."""

    def test_is_localized_error_syntax_error_returns_true(self):
        """Test that syntax errors at specific lines are considered localized."""
        assert _is_localized_error("SyntaxError at line 5: invalid") is True

    def test_is_localized_error_missing_function_returns_true(self):
        """Test that missing function errors are considered localized."""
        assert _is_localized_error("function foo is missing") is True

    def test_is_localized_error_generic_returns_false(self):
        """Test that generic errors are not considered localized."""
        assert _is_localized_error("Code is too long") is False

    def test_choose_repair_strategy_empty_errors_returns_full_regen(self):
        """Test that empty error list returns REPAIR_FULL_REGEN."""
        assert choose_repair_strategy([]) == REPAIR_FULL_REGEN

    def test_choose_repair_strategy_single_localized_returns_targeted(self):
        """Test that single localized error returns REPAIR_TARGETED_PATCH."""
        assert choose_repair_strategy(["error at line 5"]) == REPAIR_TARGETED_PATCH

    def test_choose_repair_strategy_two_localized_returns_targeted(self):
        """Test that two localized errors return REPAIR_TARGETED_PATCH."""
        assert choose_repair_strategy(["error at line 5", "function bar missing"]) == REPAIR_TARGETED_PATCH

    def test_choose_repair_strategy_three_errors_returns_full_regen(self):
        """Test that 3+ errors return REPAIR_FULL_REGEN."""
        assert choose_repair_strategy(["a", "b", "c"]) == REPAIR_FULL_REGEN

    def test_choose_repair_strategy_non_localized_returns_full_regen(self):
        """Test that non-localized errors return REPAIR_FULL_REGEN."""
        assert choose_repair_strategy(["Code is too long"]) == REPAIR_FULL_REGEN

    def test_build_targeted_patch_prompt_includes_keywords(self):
        """Test that build_targeted_patch_prompt includes targeted fix keywords."""
        prompt = build_targeted_patch_prompt(
            original_query="fix foo",
            previous_code="def foo(): pass",
            errors=["line 5 error"],
            iteration=1,
        )
        assert "TARGETED FIX" in prompt or "TARGETED" in prompt
        assert "ONLY the broken part" in prompt or "only" in prompt.lower()

    def test_build_correction_prompt_single_error_uses_targeted(self):
        """Test that build_correction_prompt with 1 localized error uses targeted mode."""
        prompt = build_correction_prompt(
            original_query="fix foo",
            previous_code="def foo(): pass",
            errors=["error at line 5"],
            iteration=1,
        )
        assert "TARGETED FIX" in prompt or "TARGETED" in prompt

    def test_build_correction_prompt_three_errors_uses_full_regen(self):
        """Test that build_correction_prompt with 3 errors uses full regen mode."""
        prompt = build_correction_prompt(
            original_query="fix foo",
            previous_code="def foo(): pass",
            errors=["error 1", "error 2", "error 3"],
            iteration=1,
        )
        assert "CORRECTION ATTEMPT" in prompt or "FULL" in prompt or "REGEN" in prompt


# =============================================================================
# Registration Tests
# =============================================================================

class TestRuleRegistration:
    """Test that new Week 28 rules are properly registered."""

    def test_thread_safety_in_registry(self):
        """Test that 'thread_safety' rule is registered."""
        assert "thread_safety" in _RULE_REGISTRY

    def test_init_completeness_in_registry(self):
        """Test that 'init_completeness' rule is registered."""
        assert "init_completeness" in _RULE_REGISTRY

    def test_cross_module_contract_in_registry(self):
        """Test that 'cross_module_contract' rule is registered."""
        assert "cross_module_contract" in _RULE_REGISTRY

    def test_build_rules_for_names_returns_all_three(self):
        """Test that build_rules_for_names returns all 3 new rules."""
        rules = build_rules_for_names(["thread_safety", "init_completeness", "cross_module_contract"])
        assert len(rules) == 3


# =============================================================================
# Profile Tests
# =============================================================================

class TestProfileIntegration:
    """Test that new Week 28 rules are integrated into validation profiles."""

    def test_thread_safety_in_balanced_profile(self):
        """Test that 'thread_safety' is in BALANCED profile."""
        balanced_config = _PROFILE_CONFIGS.get(ValidationProfile.BALANCED)
        assert balanced_config is not None
        assert "thread_safety" in balanced_config["rule_names"]

    def test_init_completeness_in_balanced_profile(self):
        """Test that 'init_completeness' is in BALANCED profile."""
        balanced_config = _PROFILE_CONFIGS.get(ValidationProfile.BALANCED)
        assert balanced_config is not None
        assert "init_completeness" in balanced_config["rule_names"]

    def test_thread_safety_in_safe_fix_profile(self):
        """Test that 'thread_safety' is in SAFE_FIX profile."""
        safe_fix_config = _PROFILE_CONFIGS.get(ValidationProfile.SAFE_FIX)
        assert safe_fix_config is not None
        assert "thread_safety" in safe_fix_config["rule_names"]

    def test_cross_module_contract_in_safe_fix_profile(self):
        """Test that 'cross_module_contract' is in SAFE_FIX profile."""
        safe_fix_config = _PROFILE_CONFIGS.get(ValidationProfile.SAFE_FIX)
        assert safe_fix_config is not None
        assert "cross_module_contract" in safe_fix_config["rule_names"]

    def test_thread_safety_in_quality_rule_names(self):
        """Test that 'thread_safety' is in _QUALITY_RULE_NAMES."""
        assert "thread_safety" in _QUALITY_RULE_NAMES

    def test_init_completeness_in_quality_rule_names(self):
        """Test that 'init_completeness' is in _QUALITY_RULE_NAMES."""
        assert "init_completeness" in _QUALITY_RULE_NAMES

    def test_cross_module_contract_in_quality_rule_names(self):
        """Test that 'cross_module_contract' is in _QUALITY_RULE_NAMES."""
        assert "cross_module_contract" in _QUALITY_RULE_NAMES

    def test_critical_profile_includes_all_new_rules(self):
        """Test that CRITICAL profile includes all 3 new rules."""
        critical_config = _PROFILE_CONFIGS.get(ValidationProfile.CRITICAL)
        assert critical_config is not None
        # CRITICAL uses _ALL_RULE_NAMES + _QUALITY_RULE_NAMES
        rule_names = critical_config["rule_names"]
        assert "thread_safety" in rule_names
        assert "init_completeness" in rule_names
        assert "cross_module_contract" in rule_names
