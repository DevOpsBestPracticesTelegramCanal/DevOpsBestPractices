# -*- coding: utf-8 -*-
"""Tests for core.oss.pattern_store — SQLite backend."""

import os
import sys
import time
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.oss.pattern_store import PatternStore, RepoRecord, PatternRecord


@pytest.fixture
def store():
    """Fresh in-memory PatternStore."""
    return PatternStore(db_path=":memory:")


@pytest.fixture
def populated_store(store):
    """Store with sample repos and patterns."""
    repos = [
        RepoRecord(full_name="pallets/flask", stars=65000, forks=16000,
                    description="Web framework", topics=["python", "web"],
                    license="BSD-3-Clause"),
        RepoRecord(full_name="django/django", stars=72000, forks=29000,
                    description="Django framework", topics=["python", "web", "django"],
                    license="BSD-3-Clause"),
        RepoRecord(full_name="tiangolo/fastapi", stars=68000, forks=5800,
                    description="Fast API framework", topics=["python", "fastapi"],
                    license="MIT"),
        RepoRecord(full_name="psf/requests", stars=50000, forks=9200,
                    description="HTTP library", topics=["python", "http"],
                    license="Apache-2.0"),
        RepoRecord(full_name="pytest-dev/pytest", stars=10000, forks=2200,
                    description="Testing framework", topics=["python", "testing"],
                    license="MIT"),
    ]
    for r in repos:
        store.save_repo(r)

    patterns = [
        # Flask
        PatternRecord(repo_name="pallets/flask", category="framework", pattern_name="flask",
                      confidence=1.0, evidence="core framework"),
        PatternRecord(repo_name="pallets/flask", category="testing", pattern_name="pytest",
                      confidence=0.95, evidence="in requirements"),
        PatternRecord(repo_name="pallets/flask", category="ci_cd", pattern_name="github_actions",
                      confidence=0.9, evidence=".github/workflows"),
        PatternRecord(repo_name="pallets/flask", category="license", pattern_name="bsd-3-clause",
                      confidence=1.0),
        # Django
        PatternRecord(repo_name="django/django", category="framework", pattern_name="django",
                      confidence=1.0, evidence="core framework"),
        PatternRecord(repo_name="django/django", category="testing", pattern_name="pytest",
                      confidence=0.95),
        PatternRecord(repo_name="django/django", category="ci_cd", pattern_name="github_actions",
                      confidence=0.9),
        # FastAPI
        PatternRecord(repo_name="tiangolo/fastapi", category="framework", pattern_name="fastapi",
                      confidence=1.0),
        PatternRecord(repo_name="tiangolo/fastapi", category="testing", pattern_name="pytest",
                      confidence=0.95),
        PatternRecord(repo_name="tiangolo/fastapi", category="linting", pattern_name="ruff",
                      confidence=0.9),
        # Requests
        PatternRecord(repo_name="psf/requests", category="framework", pattern_name="requests",
                      confidence=0.8),
        PatternRecord(repo_name="psf/requests", category="testing", pattern_name="pytest",
                      confidence=0.95),
        # Pytest
        PatternRecord(repo_name="pytest-dev/pytest", category="testing", pattern_name="pytest",
                      confidence=1.0),
        PatternRecord(repo_name="pytest-dev/pytest", category="packaging", pattern_name="setuptools",
                      confidence=0.9),
    ]
    store.save_patterns(patterns)
    store.refresh_pattern_stats()
    return store


# =========================================================================
# Test: Schema & Init
# =========================================================================

class TestSchemaInit:
    def test_creates_tables(self, store):
        stats = store.get_stats()
        assert stats["total_repos"] == 0
        assert stats["total_patterns"] == 0

    def test_memory_mode(self):
        s = PatternStore(db_path=":memory:")
        assert s.count_repos() == 0

    def test_idempotent_init(self, store):
        store._init_db()
        store._init_db()
        assert store.count_repos() == 0


# =========================================================================
# Test: Repos CRUD
# =========================================================================

class TestReposCRUD:
    def test_save_and_get(self, store):
        repo = RepoRecord(full_name="owner/repo", stars=100, description="test")
        rid = store.save_repo(repo)
        assert rid > 0

        fetched = store.get_repo("owner/repo")
        assert fetched is not None
        assert fetched.full_name == "owner/repo"
        assert fetched.stars == 100

    def test_upsert(self, store):
        store.save_repo(RepoRecord(full_name="a/b", stars=10))
        store.save_repo(RepoRecord(full_name="a/b", stars=20))
        assert store.count_repos() == 1
        fetched = store.get_repo("a/b")
        assert fetched.stars == 20

    def test_get_nonexistent(self, store):
        assert store.get_repo("nonexistent/repo") is None

    def test_get_by_id(self, store):
        rid = store.save_repo(RepoRecord(full_name="x/y", stars=5))
        fetched = store.get_repo_by_id(rid)
        assert fetched is not None
        assert fetched.full_name == "x/y"

    def test_list_repos(self, populated_store):
        repos = populated_store.list_repos(limit=3)
        assert len(repos) == 3
        assert repos[0].stars >= repos[1].stars  # ordered by stars DESC

    def test_list_repos_offset(self, populated_store):
        all_repos = populated_store.list_repos(limit=100)
        offset_repos = populated_store.list_repos(limit=2, offset=2)
        assert len(offset_repos) == 2
        assert offset_repos[0].full_name == all_repos[2].full_name

    def test_count_repos(self, populated_store):
        assert populated_store.count_repos() == 5

    def test_topics_stored_as_json(self, store):
        store.save_repo(RepoRecord(full_name="t/t", topics=["a", "b", "c"]))
        fetched = store.get_repo("t/t")
        assert fetched.topics == ["a", "b", "c"]


# =========================================================================
# Test: Patterns CRUD
# =========================================================================

class TestPatternsCRUD:
    def test_save_patterns(self, store):
        store.save_repo(RepoRecord(full_name="a/b"))
        saved = store.save_patterns([
            PatternRecord(repo_name="a/b", category="framework", pattern_name="flask"),
        ])
        assert saved == 1
        assert store.count_patterns() == 1

    def test_save_patterns_upsert(self, store):
        store.save_repo(RepoRecord(full_name="a/b"))
        store.save_patterns([
            PatternRecord(repo_name="a/b", category="testing", pattern_name="pytest",
                          confidence=0.5),
        ])
        store.save_patterns([
            PatternRecord(repo_name="a/b", category="testing", pattern_name="pytest",
                          confidence=0.9),
        ])
        assert store.count_patterns() == 1

    def test_save_patterns_unknown_repo(self, store):
        saved = store.save_patterns([
            PatternRecord(repo_name="unknown/repo", category="framework",
                          pattern_name="flask"),
        ])
        assert saved == 0

    def test_save_empty(self, store):
        assert store.save_patterns([]) == 0

    def test_get_patterns_for_repo(self, populated_store):
        patterns = populated_store.get_patterns_for_repo("pallets/flask")
        names = {p.pattern_name for p in patterns}
        assert "flask" in names
        assert "pytest" in names

    def test_get_patterns_for_nonexistent(self, populated_store):
        patterns = populated_store.get_patterns_for_repo("nonexistent/repo")
        assert patterns == []

    def test_count_patterns(self, populated_store):
        assert populated_store.count_patterns() == 14


# =========================================================================
# Test: Aggregation & Stats
# =========================================================================

class TestAggregation:
    def test_refresh_pattern_stats(self, populated_store):
        count = populated_store.refresh_pattern_stats()
        assert count > 0

    def test_get_top_patterns(self, populated_store):
        top = populated_store.get_top_patterns("testing", limit=5)
        assert len(top) > 0
        assert top[0]["pattern_name"] == "pytest"
        assert top[0]["repo_count"] == 5  # all 5 repos have pytest

    def test_get_top_patterns_all(self, populated_store):
        top = populated_store.get_top_patterns(limit=5)
        assert len(top) > 0
        assert top[0]["repo_count"] >= top[-1]["repo_count"]

    def test_get_categories(self, populated_store):
        cats = populated_store.get_categories()
        assert "framework" in cats
        assert "testing" in cats

    def test_query_repos_by_pattern(self, populated_store):
        repos = populated_store.query_repos_by_pattern("pytest")
        assert len(repos) == 5
        assert repos[0]["stars"] >= repos[1]["stars"]

    def test_query_repos_by_unknown_pattern(self, populated_store):
        repos = populated_store.query_repos_by_pattern("nonexistent")
        assert repos == []

    def test_get_stats(self, populated_store):
        stats = populated_store.get_stats()
        assert stats["total_repos"] == 5
        assert stats["total_patterns"] == 14
        assert "framework" in stats["categories"]

    def test_top_repo_in_stats(self, populated_store):
        top = populated_store.get_top_patterns("framework", limit=1)
        assert len(top) == 1
        assert top[0]["top_repo"]  # not empty
        assert top[0]["avg_stars"] > 0
