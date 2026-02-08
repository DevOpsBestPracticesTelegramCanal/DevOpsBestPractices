# -*- coding: utf-8 -*-
"""Tests for core.oss.oss_engine — query engine."""

import os
import sys
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.oss.pattern_store import PatternStore, RepoRecord, PatternRecord
from core.oss.oss_engine import OSSEngine, OSSInsight


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def store():
    s = PatternStore(db_path=":memory:")
    # Populate with sample data
    repos = [
        RepoRecord(full_name="pallets/flask", stars=65000),
        RepoRecord(full_name="django/django", stars=72000),
        RepoRecord(full_name="tiangolo/fastapi", stars=68000),
        RepoRecord(full_name="psf/requests", stars=50000),
        RepoRecord(full_name="pytest-dev/pytest", stars=10000),
    ]
    for r in repos:
        s.save_repo(r)

    patterns = [
        PatternRecord(repo_name="pallets/flask", category="framework", pattern_name="flask"),
        PatternRecord(repo_name="django/django", category="framework", pattern_name="django"),
        PatternRecord(repo_name="tiangolo/fastapi", category="framework", pattern_name="fastapi"),
        PatternRecord(repo_name="psf/requests", category="framework", pattern_name="requests"),
        PatternRecord(repo_name="pallets/flask", category="testing", pattern_name="pytest"),
        PatternRecord(repo_name="django/django", category="testing", pattern_name="pytest"),
        PatternRecord(repo_name="tiangolo/fastapi", category="testing", pattern_name="pytest"),
        PatternRecord(repo_name="psf/requests", category="testing", pattern_name="pytest"),
        PatternRecord(repo_name="pytest-dev/pytest", category="testing", pattern_name="pytest"),
        PatternRecord(repo_name="pallets/flask", category="ci_cd", pattern_name="github_actions"),
        PatternRecord(repo_name="django/django", category="ci_cd", pattern_name="github_actions"),
        PatternRecord(repo_name="tiangolo/fastapi", category="ci_cd", pattern_name="github_actions"),
        PatternRecord(repo_name="tiangolo/fastapi", category="linting", pattern_name="ruff"),
        PatternRecord(repo_name="django/django", category="linting", pattern_name="black"),
        PatternRecord(repo_name="pallets/flask", category="docker", pattern_name="dockerfile"),
        PatternRecord(repo_name="pallets/flask", category="license", pattern_name="bsd-3-clause"),
        PatternRecord(repo_name="tiangolo/fastapi", category="license", pattern_name="mit"),
    ]
    s.save_patterns(patterns)
    s.refresh_pattern_stats()
    return s


@pytest.fixture
def engine(store):
    return OSSEngine(store)


@pytest.fixture
def empty_engine():
    return OSSEngine(PatternStore(db_path=":memory:"))


# =========================================================================
# Test: Pattern Queries
# =========================================================================

class TestPatternQueries:
    def test_query_flask(self, engine):
        result = engine.query("how many repos use flask?")
        assert result.confidence > 0
        assert "flask" in result.answer.lower()
        assert len(result.sample_repos) > 0

    def test_query_pytest(self, engine):
        result = engine.query("pytest usage statistics")
        assert result.confidence > 0
        assert "pytest" in result.answer.lower()

    def test_query_django(self, engine):
        result = engine.query("tell me about django")
        assert result.confidence > 0
        assert len(result.sample_repos) > 0

    def test_query_unknown_pattern(self, engine):
        result = engine.query("how about nonexistent_tool_xyz?")
        # Falls through to full overview since no keyword matched
        assert isinstance(result, OSSInsight)


# =========================================================================
# Test: Category Queries
# =========================================================================

class TestCategoryQueries:
    def test_query_framework_category(self, engine):
        result = engine.query("what frameworks are popular?")
        assert result.confidence > 0
        assert "framework" in result.answer.lower() or "pattern" in result.answer.lower()

    def test_query_testing_category(self, engine):
        result = engine.query("show me testing tools")
        assert result.confidence > 0

    def test_query_ci_category(self, engine):
        result = engine.query("CI/CD tools used in projects")
        assert result.confidence > 0

    def test_query_docker_category(self, engine):
        result = engine.query("docker adoption in python projects")
        assert result.confidence > 0

    def test_query_linting_category(self, engine):
        result = engine.query("what linting tools are common?")
        assert result.confidence > 0


# =========================================================================
# Test: Comparison Queries
# =========================================================================

class TestComparisonQueries:
    def test_flask_vs_django(self, engine):
        result = engine.query("flask vs django")
        assert result.confidence > 0
        assert "flask" in result.answer.lower()
        assert "django" in result.answer.lower()

    def test_ruff_vs_black(self, engine):
        result = engine.query("ruff vs black")
        assert isinstance(result, OSSInsight)
        assert result.confidence > 0


# =========================================================================
# Test: Stats Methods
# =========================================================================

class TestStatsMethods:
    def test_framework_stats(self, engine):
        stats = engine.get_framework_stats()
        assert len(stats) > 0
        names = {s["pattern_name"] for s in stats}
        assert "flask" in names

    def test_testing_stats(self, engine):
        stats = engine.get_testing_stats()
        assert len(stats) > 0
        assert stats[0]["pattern_name"] == "pytest"

    def test_ci_stats(self, engine):
        stats = engine.get_ci_stats()
        assert len(stats) > 0

    def test_docker_stats(self, engine):
        stats = engine.get_docker_stats()
        assert len(stats) > 0

    def test_linting_stats(self, engine):
        stats = engine.get_linting_stats()
        assert len(stats) > 0

    def test_architecture_distribution(self, engine):
        # No architecture patterns in fixture, so empty
        stats = engine.get_architecture_distribution()
        assert isinstance(stats, list)


# =========================================================================
# Test: Full Report
# =========================================================================

class TestFullReport:
    def test_report_format(self, engine):
        report = engine.get_full_report()
        assert "# OSS Consciousness Report" in report
        assert "framework" in report.lower() or "Framework" in report
        assert "pytest" in report.lower()

    def test_report_has_tables(self, engine):
        report = engine.get_full_report()
        assert "|" in report  # markdown table
        assert "Repos" in report

    def test_empty_report(self, empty_engine):
        report = empty_engine.get_full_report()
        assert "0" in report  # 0 repos


# =========================================================================
# Test: Engine Stats
# =========================================================================

class TestEngineStats:
    def test_get_stats(self, engine):
        stats = engine.get_stats()
        assert stats["total_repos"] == 5
        assert stats["total_patterns"] == 17

    def test_empty_stats(self, empty_engine):
        stats = empty_engine.get_stats()
        assert stats["total_repos"] == 0


# =========================================================================
# Test: Full Overview Fallback
# =========================================================================

class TestFullOverview:
    def test_generic_query(self, engine):
        result = engine.query("tell me everything")
        assert result.confidence > 0
        assert "OSS Consciousness Report" in result.answer

    def test_empty_store_query(self, empty_engine):
        result = empty_engine.query("what frameworks?")
        assert result.confidence == 0

    def test_russian_query(self, engine):
        result = engine.query("какие фреймворки популярные?")
        assert isinstance(result, OSSInsight)


# =========================================================================
# Test: OSSInsight Dataclass
# =========================================================================

class TestOSSInsight:
    def test_defaults(self):
        i = OSSInsight(question="test", answer="test answer")
        assert i.patterns == []
        assert i.sample_repos == []
        assert i.confidence == 0.0
        assert i.stats == {}
