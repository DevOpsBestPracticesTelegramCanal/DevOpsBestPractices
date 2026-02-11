# -*- coding: utf-8 -*-
"""
Tests for core/execution_mode.py — ExecutionMode enum, normalize_mode, escalation chain.
"""

import pytest
from core.execution_mode import ExecutionMode, ESCALATION_CHAIN, normalize_mode


# ── Enum Values ──────────────────────────────────────────────────────────


class TestExecutionModeValues:
    """Verify each mode's string value."""

    def test_fast_value(self):
        assert ExecutionMode.FAST.value == "fast"

    def test_deep3_value(self):
        assert ExecutionMode.DEEP3.value == "deep3"

    def test_deep6_value(self):
        assert ExecutionMode.DEEP6.value == "deep6"

    def test_search_value(self):
        assert ExecutionMode.SEARCH.value == "search"

    def test_search_deep_value(self):
        assert ExecutionMode.SEARCH_DEEP.value == "search_deep"

    def test_enum_count(self):
        """There are exactly 5 execution modes."""
        assert len(ExecutionMode) == 5


# ── Icon Property ────────────────────────────────────────────────────────


class TestExecutionModeIcon:
    """Each mode maps to a bracketed icon string."""

    def test_fast_icon(self):
        assert ExecutionMode.FAST.icon == "[FAST]"

    def test_deep3_icon(self):
        assert ExecutionMode.DEEP3.icon == "[DEEP3]"

    def test_deep6_icon(self):
        assert ExecutionMode.DEEP6.icon == "[DEEP6]"

    def test_search_icon(self):
        assert ExecutionMode.SEARCH.icon == "[SEARCH]"

    def test_search_deep_icon(self):
        assert ExecutionMode.SEARCH_DEEP.icon == "[SEARCH+DEEP]"


# ── is_search Property ───────────────────────────────────────────────────


class TestIsSearch:
    """Only SEARCH and SEARCH_DEEP are search modes."""

    def test_fast_not_search(self):
        assert ExecutionMode.FAST.is_search is False

    def test_deep3_not_search(self):
        assert ExecutionMode.DEEP3.is_search is False

    def test_deep6_not_search(self):
        assert ExecutionMode.DEEP6.is_search is False

    def test_search_is_search(self):
        assert ExecutionMode.SEARCH.is_search is True

    def test_search_deep_is_search(self):
        assert ExecutionMode.SEARCH_DEEP.is_search is True


# ── Escalation Chain ─────────────────────────────────────────────────────


class TestEscalationChain:
    """ESCALATION_CHAIN maps each mode to its successor on timeout."""

    def test_fast_escalates_to_deep3(self):
        assert ESCALATION_CHAIN[ExecutionMode.FAST] == ExecutionMode.DEEP3

    def test_deep3_escalates_to_deep6(self):
        assert ESCALATION_CHAIN[ExecutionMode.DEEP3] == ExecutionMode.DEEP6

    def test_deep6_escalates_to_search(self):
        assert ESCALATION_CHAIN[ExecutionMode.DEEP6] == ExecutionMode.SEARCH

    def test_search_escalates_to_search_deep(self):
        assert ESCALATION_CHAIN[ExecutionMode.SEARCH] == ExecutionMode.SEARCH_DEEP

    def test_search_deep_is_terminal(self):
        assert ESCALATION_CHAIN[ExecutionMode.SEARCH_DEEP] is None

    def test_all_modes_present(self):
        """Every ExecutionMode appears in the chain."""
        for mode in ExecutionMode:
            assert mode in ESCALATION_CHAIN


# ── normalize_mode ───────────────────────────────────────────────────────


class TestNormalizeMode:
    """normalize_mode converts strings to ExecutionMode."""

    def test_fast(self):
        assert normalize_mode("fast") == ExecutionMode.FAST

    def test_deep_alias(self):
        """'deep' maps to DEEP3."""
        assert normalize_mode("deep") == ExecutionMode.DEEP3

    def test_deep3(self):
        assert normalize_mode("deep3") == ExecutionMode.DEEP3

    def test_deep6(self):
        assert normalize_mode("deep6") == ExecutionMode.DEEP6

    def test_search(self):
        assert normalize_mode("search") == ExecutionMode.SEARCH

    def test_deep_search(self):
        assert normalize_mode("deep_search") == ExecutionMode.SEARCH_DEEP

    def test_search_deep(self):
        assert normalize_mode("search_deep") == ExecutionMode.SEARCH_DEEP

    def test_case_insensitive(self):
        assert normalize_mode("FAST") == ExecutionMode.FAST
        assert normalize_mode("Deep3") == ExecutionMode.DEEP3

    def test_whitespace_stripped(self):
        assert normalize_mode("  fast  ") == ExecutionMode.FAST

    def test_unknown_returns_none(self):
        assert normalize_mode("turbo") is None

    def test_empty_string_returns_none(self):
        assert normalize_mode("") is None
