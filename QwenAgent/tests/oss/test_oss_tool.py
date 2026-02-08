# -*- coding: utf-8 -*-
"""Tests for core.oss.oss_tool — tool integration."""

import os
import sys
import re
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.oss.oss_tool import OSSTool, OSS_ROUTER_PATTERNS
from core.oss.pattern_store import PatternStore, RepoRecord, PatternRecord


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tool():
    t = OSSTool(db_path=":memory:")
    # Populate
    store = t.store
    repos = [
        RepoRecord(full_name="pallets/flask", stars=65000),
        RepoRecord(full_name="django/django", stars=72000),
        RepoRecord(full_name="tiangolo/fastapi", stars=68000),
    ]
    for r in repos:
        store.save_repo(r)
    patterns = [
        PatternRecord(repo_name="pallets/flask", category="framework", pattern_name="flask"),
        PatternRecord(repo_name="django/django", category="framework", pattern_name="django"),
        PatternRecord(repo_name="tiangolo/fastapi", category="framework", pattern_name="fastapi"),
        PatternRecord(repo_name="pallets/flask", category="testing", pattern_name="pytest"),
        PatternRecord(repo_name="django/django", category="testing", pattern_name="pytest"),
        PatternRecord(repo_name="tiangolo/fastapi", category="testing", pattern_name="pytest"),
    ]
    store.save_patterns(patterns)
    store.refresh_pattern_stats()
    return t


@pytest.fixture
def empty_tool():
    return OSSTool(db_path=":memory:")


# =========================================================================
# Test: Execute Actions
# =========================================================================

class TestExecuteActions:
    def test_query_action(self, tool):
        result = tool.execute("query", question="flask usage")
        assert result["success"]
        assert "flask" in result["answer"].lower()

    def test_query_no_question(self, tool):
        result = tool.execute("query")
        assert not result["success"]
        assert "error" in result

    def test_stats_action(self, tool):
        result = tool.execute("stats")
        assert result["success"]
        assert result["stats"]["total_repos"] == 3

    def test_report_action(self, tool):
        result = tool.execute("report")
        assert result["success"]
        assert "OSS Consciousness Report" in result["report"]

    def test_frameworks_action(self, tool):
        result = tool.execute("frameworks")
        assert result["success"]
        assert len(result["data"]) > 0

    def test_testing_action(self, tool):
        result = tool.execute("testing")
        assert result["success"]
        assert len(result["data"]) > 0

    def test_ci_action(self, empty_tool):
        result = empty_tool.execute("ci")
        assert result["success"]
        assert result["data"] == []

    def test_docker_action(self, empty_tool):
        result = empty_tool.execute("docker")
        assert result["success"]

    def test_linting_action(self, empty_tool):
        result = empty_tool.execute("linting")
        assert result["success"]

    def test_packaging_action(self, empty_tool):
        result = empty_tool.execute("packaging")
        assert result["success"]

    def test_databases_action(self, empty_tool):
        result = empty_tool.execute("databases")
        assert result["success"]

    def test_architecture_action(self, empty_tool):
        result = empty_tool.execute("architecture")
        assert result["success"]

    def test_pattern_action(self, tool):
        result = tool.execute("pattern", pattern_name="flask")
        assert result["success"]
        assert result["count"] > 0

    def test_pattern_no_name(self, tool):
        result = tool.execute("pattern")
        assert not result["success"]

    def test_unknown_action(self, tool):
        result = tool.execute("nonexistent_action")
        assert not result["success"]
        assert "Unknown action" in result["error"]


# =========================================================================
# Test: Get Stats
# =========================================================================

class TestGetStats:
    def test_get_stats(self, tool):
        stats = tool.get_stats()
        assert stats["total_repos"] == 3
        assert stats["total_patterns"] == 6


# =========================================================================
# Test: Router Patterns
# =========================================================================

class TestRouterPatterns:
    def test_patterns_list(self):
        assert len(OSS_ROUTER_PATTERNS) > 0

    def test_oss_report_match(self):
        pattern = OSS_ROUTER_PATTERNS[0]
        regex = re.compile(pattern[0], re.IGNORECASE)
        assert regex.search("oss pattern analysis")
        assert regex.search("open source stats")

    def test_how_do_projects_match(self):
        pattern = OSS_ROUTER_PATTERNS[1]
        regex = re.compile(pattern[0], re.IGNORECASE)
        assert regex.search("how do python projects implement auth")
        assert regex.search("how do repos use celery")

    def test_popular_match(self):
        pattern = OSS_ROUTER_PATTERNS[2]
        regex = re.compile(pattern[0], re.IGNORECASE)
        assert regex.search("popular frameworks")
        assert regex.search("top python testing tools")
        assert regex.search("common libraries")

    def test_tech_stack_match(self):
        pattern = OSS_ROUTER_PATTERNS[3]
        regex = re.compile(pattern[0], re.IGNORECASE)
        assert regex.search("tech stack report")
        assert regex.search("tech-stack analysis")

    def test_vs_match(self):
        pattern = OSS_ROUTER_PATTERNS[4]
        regex = re.compile(pattern[0], re.IGNORECASE)
        assert regex.search("flask vs django")
        assert regex.search("pytest vs. unittest")

    def test_russian_pattern(self):
        pattern = OSS_ROUTER_PATTERNS[5]
        regex = re.compile(pattern[0], re.IGNORECASE)
        assert regex.search("какие фреймворки")
        assert regex.search("популярные инструменты")

    def test_all_patterns_return_oss_tool(self):
        for pattern_tuple in OSS_ROUTER_PATTERNS:
            assert pattern_tuple[1] == "oss"

    def test_all_patterns_have_param_extractor(self):
        for pattern_tuple in OSS_ROUTER_PATTERNS:
            assert callable(pattern_tuple[2])


# =========================================================================
# Test: Property Access
# =========================================================================

class TestPropertyAccess:
    def test_store_property(self, tool):
        assert isinstance(tool.store, PatternStore)

    def test_engine_property(self, tool):
        from core.oss.oss_engine import OSSEngine
        assert isinstance(tool.engine, OSSEngine)
