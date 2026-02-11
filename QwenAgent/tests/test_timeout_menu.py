# -*- coding: utf-8 -*-
"""
Tests for UserTimeoutPreferences.update(), from_partial_dict(),
and the /api/timeout endpoint logic.
"""

import sys
import os
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from core.user_timeout_config import UserTimeoutPreferences


# ═══════════════════════════════════════════════════════════════════════════════
# update() tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestUpdate:
    def test_update_priority(self):
        prefs = UserTimeoutPreferences()
        prefs.update({"priority": "speed"})
        assert prefs.priority == "speed"

    def test_update_max_wait(self):
        prefs = UserTimeoutPreferences()
        prefs.update({"max_wait": 60})
        assert prefs.max_wait == 60.0

    def test_update_multiple_fields(self):
        prefs = UserTimeoutPreferences()
        prefs.update({"priority": "quality", "max_wait": 300, "on_timeout": "abort"})
        assert prefs.priority == "quality"
        assert prefs.max_wait == 300.0
        assert prefs.on_timeout == "abort"

    def test_update_ignores_unknown_keys(self):
        prefs = UserTimeoutPreferences()
        original_priority = prefs.priority
        prefs.update({"unknown_key": "value", "another": 42})
        assert prefs.priority == original_priority

    def test_update_type_casting_string_to_float(self):
        prefs = UserTimeoutPreferences()
        prefs.update({"max_wait": "90"})
        assert prefs.max_wait == 90.0
        assert isinstance(prefs.max_wait, float)

    def test_update_type_casting_int_to_float(self):
        prefs = UserTimeoutPreferences()
        prefs.update({"max_wait": 45})
        assert prefs.max_wait == 45.0

    def test_update_type_casting_float_to_str(self):
        prefs = UserTimeoutPreferences()
        prefs.update({"priority": 123})
        assert prefs.priority == "123"
        assert isinstance(prefs.priority, str)

    def test_update_invalid_value_skipped(self):
        prefs = UserTimeoutPreferences()
        original = prefs.max_wait
        prefs.update({"max_wait": "not_a_number"})
        assert prefs.max_wait == original

    def test_update_empty_dict_no_change(self):
        prefs = UserTimeoutPreferences(priority="quality", max_wait=200)
        prefs.update({})
        assert prefs.priority == "quality"
        assert prefs.max_wait == 200.0

    def test_update_all_fields(self):
        prefs = UserTimeoutPreferences()
        prefs.update({
            "max_wait": 500,
            "on_timeout": "ask",
            "risk_tolerance": "aggressive",
            "priority": "quality",
            "preferred_model": "qwen2.5-coder:14b",
            "fallback_model": "qwen2.5-coder:3b",
            "deep_mode_budget": 600,
            "fast_mode_budget": 60,
        })
        assert prefs.max_wait == 500.0
        assert prefs.on_timeout == "ask"
        assert prefs.risk_tolerance == "aggressive"
        assert prefs.priority == "quality"
        assert prefs.preferred_model == "qwen2.5-coder:14b"
        assert prefs.fallback_model == "qwen2.5-coder:3b"
        assert prefs.deep_mode_budget == 600.0
        assert prefs.fast_mode_budget == 60.0


# ═══════════════════════════════════════════════════════════════════════════════
# from_partial_dict() tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestFromPartialDict:
    def test_from_partial_dict_no_base(self):
        prefs = UserTimeoutPreferences.from_partial_dict({"priority": "speed"})
        assert prefs.priority == "speed"
        assert prefs.max_wait == 120.0  # default

    def test_from_partial_dict_with_base(self):
        base = UserTimeoutPreferences(priority="quality", max_wait=300)
        prefs = UserTimeoutPreferences.from_partial_dict({"max_wait": 200}, base=base)
        assert prefs.priority == "quality"  # inherited from base
        assert prefs.max_wait == 200.0  # overridden

    def test_from_partial_dict_empty_dict(self):
        prefs = UserTimeoutPreferences.from_partial_dict({})
        assert prefs.priority == "balanced"
        assert prefs.max_wait == 120.0

    def test_from_partial_dict_preserves_base_unchanged(self):
        base = UserTimeoutPreferences(priority="speed", max_wait=60)
        UserTimeoutPreferences.from_partial_dict({"priority": "quality"}, base=base)
        assert base.priority == "speed"  # base not mutated


# ═══════════════════════════════════════════════════════════════════════════════
# to_timeout_config recomputation after update
# ═══════════════════════════════════════════════════════════════════════════════

class TestRecomputation:
    def test_config_changes_after_update_priority(self):
        prefs = UserTimeoutPreferences(priority="balanced", max_wait=120)
        cfg_before = prefs.to_timeout_config()
        prefs.update({"priority": "speed"})
        cfg_after = prefs.to_timeout_config()
        assert cfg_after.ttft_timeout != cfg_before.ttft_timeout or \
               cfg_after.absolute_max != cfg_before.absolute_max

    def test_speed_config_values(self):
        prefs = UserTimeoutPreferences(priority="speed", max_wait=120)
        cfg = prefs.to_timeout_config()
        assert cfg.ttft_timeout == 10
        assert cfg.idle_timeout == 8
        assert cfg.absolute_max == 60  # min(120, 60)

    def test_quality_config_values(self):
        prefs = UserTimeoutPreferences(priority="quality", max_wait=1000)
        cfg = prefs.to_timeout_config()
        assert cfg.ttft_timeout == 45
        assert cfg.idle_timeout == 30
        assert cfg.absolute_max == 600  # min(1000, 600)

    def test_balanced_config_values(self):
        prefs = UserTimeoutPreferences(priority="balanced", max_wait=200)
        cfg = prefs.to_timeout_config()
        assert cfg.ttft_timeout == 45
        assert cfg.idle_timeout == 25
        assert cfg.absolute_max == 200  # min(200, 300)

    def test_max_wait_caps_absolute_max(self):
        prefs = UserTimeoutPreferences(priority="balanced", max_wait=50)
        cfg = prefs.to_timeout_config()
        assert cfg.absolute_max == 50  # min(50, 300)


# ═══════════════════════════════════════════════════════════════════════════════
# to_dict roundtrip
# ═══════════════════════════════════════════════════════════════════════════════

class TestToDict:
    def test_to_dict_contains_all_fields(self):
        prefs = UserTimeoutPreferences()
        d = prefs.to_dict()
        assert "max_wait" in d
        assert "priority" in d
        assert "on_timeout" in d
        assert "computed_timeout_config" in d

    def test_to_dict_computed_matches(self):
        prefs = UserTimeoutPreferences(priority="speed", max_wait=60)
        d = prefs.to_dict()
        assert d["computed_timeout_config"]["ttft_timeout"] == 10
        assert d["computed_timeout_config"]["idle_timeout"] == 8
        assert d["computed_timeout_config"]["absolute_max"] == 60

    def test_to_dict_after_update(self):
        prefs = UserTimeoutPreferences()
        prefs.update({"priority": "quality", "max_wait": 500})
        d = prefs.to_dict()
        assert d["priority"] == "quality"
        assert d["max_wait"] == 500.0
        assert d["computed_timeout_config"]["absolute_max"] == 500  # min(500, 600)


# ═══════════════════════════════════════════════════════════════════════════════
# get_mode_budget
# ═══════════════════════════════════════════════════════════════════════════════

class TestGetModeBudget:
    def test_fast_mode_budget(self):
        prefs = UserTimeoutPreferences(fast_mode_budget=30, max_wait=120)
        assert prefs.get_mode_budget("fast") == 30

    def test_deep_mode_budget(self):
        prefs = UserTimeoutPreferences(deep_mode_budget=300, max_wait=500)
        assert prefs.get_mode_budget("deep") == 300

    def test_mode_budget_capped_by_max_wait(self):
        prefs = UserTimeoutPreferences(deep_mode_budget=300, max_wait=100)
        assert prefs.get_mode_budget("deep") == 100

    def test_search_mode_budget(self):
        prefs = UserTimeoutPreferences(fast_mode_budget=30, max_wait=500)
        assert prefs.get_mode_budget("search") == 60  # fast * 2

    def test_budget_after_update(self):
        prefs = UserTimeoutPreferences()
        prefs.update({"fast_mode_budget": 45, "max_wait": 200})
        assert prefs.get_mode_budget("fast") == 45
