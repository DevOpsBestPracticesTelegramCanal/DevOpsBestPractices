# -*- coding: utf-8 -*-
"""
Tests for Neo4j Knowledge Graph — OSS pattern co-occurrence and relationships.

Covers: graceful degradation, mocked Neo4j driver, GraphBuilder,
co-occurrence logic, and optional live Neo4j tests.
"""

import math
import os
import sys
import time
from unittest.mock import MagicMock, patch, PropertyMock, call

import pytest

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from core.oss.neo4j_graph import Neo4jGraph, GraphStats, HAS_NEO4J
from core.oss.graph_builder import GraphBuilder, SyncStats, _TECH_PATTERNS
from core.oss.pattern_store import PatternStore, RepoRecord, PatternRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_repo(name="owner/repo", stars=100, forks=10, topics=None, license_="MIT", arch=""):
    return RepoRecord(
        full_name=name,
        stars=stars,
        forks=forks,
        topics=topics or [],
        license=license_,
        architecture=arch,
        collected_at=time.time(),
    )


def _make_pattern(repo_name="owner/repo", category="testing", name="pytest", confidence=0.9, evidence=""):
    return PatternRecord(
        repo_name=repo_name,
        category=category,
        pattern_name=name,
        confidence=confidence,
        evidence=evidence,
    )


def _mock_session():
    """Create a mock Neo4j session with context manager support."""
    session = MagicMock()
    session.__enter__ = MagicMock(return_value=session)
    session.__exit__ = MagicMock(return_value=False)
    return session


def _mock_driver(session=None):
    """Create a mock Neo4j driver that returns the given session."""
    driver = MagicMock()
    s = session or _mock_session()
    driver.session.return_value = s
    driver.verify_connectivity.return_value = None
    return driver, s


# ---------------------------------------------------------------------------
# TestGracefulDegradation
# ---------------------------------------------------------------------------

class TestGracefulDegradation:
    """Neo4j graph should degrade gracefully when not available."""

    def test_no_neo4j_package(self):
        """When neo4j package is missing, graph is disabled."""
        with patch("core.oss.neo4j_graph.HAS_NEO4J", False):
            g = Neo4jGraph.__new__(Neo4jGraph)
            g._uri = ""
            g._username = ""
            g._password = ""
            g._driver = None
            g._available = False
            assert not g.is_available()

    def test_no_credentials(self):
        """When no URI is provided, graph is disabled."""
        with patch.dict(os.environ, {}, clear=True):
            with patch("core.oss.neo4j_graph.HAS_NEO4J", True):
                g = Neo4jGraph(uri="", username="", password="")
                assert not g.is_available()

    def test_connection_refused(self):
        """When connection fails, graph is disabled but doesn't crash."""
        with patch("core.oss.neo4j_graph.HAS_NEO4J", True):
            mock_gd = MagicMock()
            mock_driver = MagicMock()
            mock_driver.verify_connectivity.side_effect = Exception("Connection refused")
            mock_gd.driver.return_value = mock_driver
            with patch("core.oss.neo4j_graph.GraphDatabase", mock_gd):
                g = Neo4jGraph(uri="bolt://localhost:7687")
                assert not g.is_available()

    def test_all_queries_return_empty_when_unavailable(self):
        """All query methods return empty results when graph is unavailable."""
        g = Neo4jGraph.__new__(Neo4jGraph)
        g._driver = None
        g._available = False
        g._uri = ""
        g._username = ""
        g._password = ""

        assert g.get_cooccurring_patterns("test") == []
        assert g.get_technology_stack("test") == []
        assert g.get_repos_by_technology("test") == []
        assert g.get_pattern_neighbors("test") == {"nodes": [], "edges": []}
        assert g.get_category_summary() == []
        assert g.get_stats()["available"] is False
        assert g.update_cooccurrences() == 0
        assert g.upsert_repo(_make_repo()) is False
        assert g.upsert_pattern(_make_pattern()) is False
        assert g.upsert_technology("test") is False
        assert g.link_repo_tech("r", "t") is False
        assert g.clear_all() is False


# ---------------------------------------------------------------------------
# TestNeo4jGraphMocked
# ---------------------------------------------------------------------------

class TestNeo4jGraphMocked:
    """Test Neo4j graph operations with mocked driver."""

    def _make_graph(self):
        """Create a Neo4jGraph with mocked driver."""
        driver, session = _mock_driver()
        g = Neo4jGraph.__new__(Neo4jGraph)
        g._driver = driver
        g._available = True
        g._uri = "bolt://mock:7687"
        g._username = "neo4j"
        g._password = "test"
        return g, driver, session

    def test_is_available(self):
        g, _, _ = self._make_graph()
        assert g.is_available()

    def test_close(self):
        g, driver, _ = self._make_graph()
        g.close()
        driver.close.assert_called_once()
        assert not g.is_available()

    def test_close_idempotent(self):
        g, _, _ = self._make_graph()
        g.close()
        g.close()  # Should not raise

    def test_create_constraints(self):
        g, _, session = self._make_graph()
        g.create_constraints()
        assert session.run.call_count == 3  # 3 constraints

    def test_upsert_repo(self):
        g, _, session = self._make_graph()
        repo = _make_repo("test/repo", stars=500)
        result = g.upsert_repo(repo)
        assert result is True
        session.run.assert_called_once()
        args = session.run.call_args
        assert "MERGE" in args[0][0]
        assert args[0][1]["name"] == "test/repo"
        assert args[0][1]["stars"] == 500

    def test_upsert_repo_error(self):
        g, _, session = self._make_graph()
        session.run.side_effect = Exception("DB error")
        result = g.upsert_repo(_make_repo())
        assert result is False

    def test_upsert_pattern(self):
        g, _, session = self._make_graph()
        p = _make_pattern("owner/repo", "testing", "pytest", 0.95, "found in setup.py")
        result = g.upsert_pattern(p)
        assert result is True
        args = session.run.call_args
        assert "MERGE" in args[0][0]
        assert args[0][1]["pattern_name"] == "pytest"
        assert args[0][1]["confidence"] == 0.95

    def test_upsert_pattern_error(self):
        g, _, session = self._make_graph()
        session.run.side_effect = Exception("DB error")
        result = g.upsert_pattern(_make_pattern())
        assert result is False

    def test_upsert_technology(self):
        g, _, session = self._make_graph()
        result = g.upsert_technology("Docker")
        assert result is True
        args = session.run.call_args
        assert args[0][1]["name"] == "Docker"

    def test_link_repo_tech(self):
        g, _, session = self._make_graph()
        result = g.link_repo_tech("owner/repo", "Docker", "pattern")
        assert result is True
        args = session.run.call_args
        assert args[0][1]["repo_name"] == "owner/repo"
        assert args[0][1]["tech_name"] == "Docker"
        assert args[0][1]["source"] == "pattern"

    def test_update_cooccurrences(self):
        g, _, session = self._make_graph()
        mock_result = MagicMock()
        mock_record = {"total": 5}
        mock_result.single.return_value = mock_record
        session.run.return_value = mock_result
        count = g.update_cooccurrences()
        assert count == 5

    def test_update_cooccurrences_error(self):
        g, _, session = self._make_graph()
        session.run.side_effect = Exception("timeout")
        count = g.update_cooccurrences()
        assert count == 0

    def test_get_stats(self):
        g, _, session = self._make_graph()
        # Mock multiple calls: 4 label counts + cooccurrence + total rels
        mock_results = []
        for val in [10, 50, 5, 3, 20, 100]:
            mr = MagicMock()
            mr.single.return_value = {"c": val}
            mock_results.append(mr)
        session.run.side_effect = mock_results

        stats = g.get_stats()
        assert stats["available"] is True
        assert stats["total_repos"] == 10
        assert stats["total_patterns"] == 50
        assert stats["total_categories"] == 5
        assert stats["total_technologies"] == 3
        assert stats["total_cooccurrences"] == 20
        assert stats["total_relationships"] == 100

    def test_get_stats_error(self):
        g, _, session = self._make_graph()
        session.run.side_effect = Exception("DB error")
        stats = g.get_stats()
        assert stats["available"] is False

    def test_clear_all(self):
        g, _, session = self._make_graph()
        result = g.clear_all()
        assert result is True
        args = session.run.call_args
        assert "DETACH DELETE" in args[0][0]

    def test_get_cooccurring_patterns(self):
        g, _, session = self._make_graph()
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([
            {"pattern_name": "flask", "category": "framework", "count": 5, "pmi": 2.3},
            {"pattern_name": "sqlalchemy", "category": "orm", "count": 3, "pmi": 1.8},
        ]))
        session.run.return_value = mock_result
        results = g.get_cooccurring_patterns("pytest", min_count=2, limit=5)
        assert len(results) == 2
        assert results[0]["pattern_name"] == "flask"

    def test_get_technology_stack(self):
        g, _, session = self._make_graph()
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([
            {"technology": "Python", "source": "topics"},
            {"technology": "Docker", "source": "pattern"},
        ]))
        session.run.return_value = mock_result
        results = g.get_technology_stack("owner/repo")
        assert len(results) == 2

    def test_get_repos_by_technology(self):
        g, _, session = self._make_graph()
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([
            {"repo_name": "pallets/flask", "stars": 60000, "source": "topics"},
        ]))
        session.run.return_value = mock_result
        results = g.get_repos_by_technology("Flask", limit=5)
        assert len(results) == 1
        assert results[0]["repo_name"] == "pallets/flask"

    def test_get_category_summary(self):
        g, _, session = self._make_graph()
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([
            {"category": "testing", "pattern_count": 10, "repo_count": 50},
            {"category": "framework", "pattern_count": 8, "repo_count": 40},
        ]))
        session.run.return_value = mock_result
        results = g.get_category_summary()
        assert len(results) == 2
        assert results[0]["category"] == "testing"

    def test_get_pattern_neighbors(self):
        g, _, session = self._make_graph()
        mock_result = MagicMock()
        mock_result.single.return_value = {
            "nodes": [
                {"id": 1, "labels": ["Pattern"], "name": "pytest"},
                {"id": 2, "labels": ["Pattern"], "name": "flask"},
            ],
            "edges": [
                {"start": 1, "end": 2, "type": "COOCCURS_WITH"},
            ],
        }
        session.run.return_value = mock_result
        result = g.get_pattern_neighbors("pytest", depth=2)
        assert len(result["nodes"]) == 2
        assert len(result["edges"]) == 1

    def test_get_pattern_neighbors_empty(self):
        g, _, session = self._make_graph()
        mock_result = MagicMock()
        mock_result.single.return_value = None
        session.run.return_value = mock_result
        result = g.get_pattern_neighbors("nonexistent")
        assert result == {"nodes": [], "edges": []}


# ---------------------------------------------------------------------------
# TestGraphBuilder
# ---------------------------------------------------------------------------

class TestGraphBuilder:
    """Test GraphBuilder sync operations."""

    def _make_builder(self, repos=None, patterns_map=None):
        """Create a GraphBuilder with mocked store and graph."""
        store = MagicMock(spec=PatternStore)
        store.list_repos.return_value = repos or []
        store.get_patterns_for_repo.side_effect = lambda name: (
            patterns_map.get(name, []) if patterns_map else []
        )

        graph = MagicMock(spec=Neo4jGraph)
        graph.is_available.return_value = True
        graph.upsert_repo.return_value = True
        graph.upsert_pattern.return_value = True
        graph.upsert_technology.return_value = True
        graph.link_repo_tech.return_value = True
        graph.create_constraints.return_value = None
        graph.update_cooccurrences.return_value = 0

        builder = GraphBuilder(store, graph)
        return builder, store, graph

    def test_full_sync_empty_store(self):
        builder, store, graph = self._make_builder(repos=[])
        stats = builder.full_sync()
        assert stats.repos_synced == 0
        assert stats.patterns_synced == 0
        assert stats.duration_seconds >= 0

    def test_full_sync_one_repo_no_patterns(self):
        repo = _make_repo("owner/simple")
        builder, store, graph = self._make_builder(repos=[repo])
        stats = builder.full_sync()
        assert stats.repos_synced == 1
        assert stats.patterns_synced == 0
        graph.upsert_repo.assert_called_once()

    def test_full_sync_repo_with_patterns(self):
        repo = _make_repo("owner/app", topics=["python", "flask"])
        patterns = [
            _make_pattern("owner/app", "framework", "flask"),
            _make_pattern("owner/app", "testing", "pytest"),
        ]
        builder, store, graph = self._make_builder(
            repos=[repo],
            patterns_map={"owner/app": patterns},
        )
        stats = builder.full_sync()
        assert stats.repos_synced == 1
        assert stats.patterns_synced == 2
        assert stats.techs_created > 0  # python, flask from topics + patterns

    def test_full_sync_multiple_repos(self):
        repos = [
            _make_repo("a/one", topics=["docker"]),
            _make_repo("b/two", topics=["kubernetes"]),
            _make_repo("c/three"),
        ]
        builder, store, graph = self._make_builder(repos=repos)
        stats = builder.full_sync()
        assert stats.repos_synced == 3

    def test_full_sync_repo_upsert_fails(self):
        repo = _make_repo("owner/fail")
        builder, store, graph = self._make_builder(repos=[repo])
        graph.upsert_repo.return_value = False
        stats = builder.full_sync()
        assert stats.repos_synced == 0
        assert len(stats.errors) == 1

    def test_full_sync_graph_unavailable(self):
        builder, store, graph = self._make_builder()
        graph.is_available.return_value = False
        stats = builder.full_sync()
        assert len(stats.errors) == 1
        assert "not available" in stats.errors[0]

    def test_incremental_sync(self):
        old_time = time.time() - 7200  # 2 hours ago
        new_time = time.time() - 100   # 100 seconds ago
        cutoff = time.time() - 3600    # 1 hour ago

        repos = [
            RepoRecord(full_name="old/repo", collected_at=old_time),
            RepoRecord(full_name="new/repo", collected_at=new_time),
        ]
        builder, store, graph = self._make_builder(repos=repos)
        stats = builder.incremental_sync(since_timestamp=cutoff)
        assert stats.repos_synced == 1  # Only new/repo

    def test_incremental_sync_no_new(self):
        old_time = time.time() - 7200
        repos = [RepoRecord(full_name="old/repo", collected_at=old_time)]
        builder, store, graph = self._make_builder(repos=repos)
        stats = builder.incremental_sync(since_timestamp=time.time() - 3600)
        assert stats.repos_synced == 0

    def test_build_cooccurrences(self):
        builder, store, graph = self._make_builder()
        graph.update_cooccurrences.return_value = 15
        count = builder.build_cooccurrences()
        assert count == 15
        graph.update_cooccurrences.assert_called_once()

    def test_build_cooccurrences_unavailable(self):
        builder, store, graph = self._make_builder()
        graph.is_available.return_value = False
        count = builder.build_cooccurrences()
        assert count == 0

    def test_is_available(self):
        builder, store, graph = self._make_builder()
        assert builder.is_available is True
        graph.is_available.return_value = False
        assert builder.is_available is False

    def test_creates_constraints_on_full_sync(self):
        builder, store, graph = self._make_builder()
        builder.full_sync()
        graph.create_constraints.assert_called_once()


# ---------------------------------------------------------------------------
# TestTechExtraction
# ---------------------------------------------------------------------------

class TestTechExtraction:
    """Test technology extraction from repos and patterns."""

    def test_extract_from_topics(self):
        repo = _make_repo(topics=["python", "docker", "flask"])
        techs = GraphBuilder.extract_technologies(repo, [])
        assert "Python" in techs
        assert "Docker" in techs
        assert "Flask" in techs

    def test_extract_from_pattern_name(self):
        repo = _make_repo()
        pattern = _make_pattern(name="pytest_fixtures")
        techs = GraphBuilder.extract_technologies(repo, [pattern])
        assert "pytest" in techs

    def test_extract_from_pattern_category(self):
        repo = _make_repo()
        pattern = _make_pattern(category="docker")
        techs = GraphBuilder.extract_technologies(repo, [pattern])
        assert "Docker" in techs

    def test_extract_from_architecture(self):
        repo = _make_repo(arch="kubernetes microservice")
        techs = GraphBuilder.extract_technologies(repo, [])
        assert "Kubernetes" in techs

    def test_extract_deduplicates(self):
        repo = _make_repo(topics=["flask"])
        pattern = _make_pattern(name="flask_routes")
        techs = GraphBuilder.extract_technologies(repo, [pattern])
        assert techs.count("Flask") == 1  # No duplicates

    def test_extract_empty_repo(self):
        repo = _make_repo(topics=[])
        techs = GraphBuilder.extract_technologies(repo, [])
        assert techs == []


# ---------------------------------------------------------------------------
# TestCooccurrenceLogic
# ---------------------------------------------------------------------------

class TestCooccurrenceLogic:
    """Test co-occurrence query and PMI calculation logic."""

    def _make_graph(self):
        driver, session = _mock_driver()
        g = Neo4jGraph.__new__(Neo4jGraph)
        g._driver = driver
        g._available = True
        g._uri = "bolt://mock:7687"
        g._username = "neo4j"
        g._password = "test"
        return g, session

    def test_cooccurrence_min_count_filter(self):
        g, session = self._make_graph()
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([
            {"pattern_name": "flask", "category": "framework", "count": 5, "pmi": 2.0},
        ]))
        session.run.return_value = mock_result

        results = g.get_cooccurring_patterns("pytest", min_count=3)
        args = session.run.call_args
        assert args[0][1]["min_count"] == 3

    def test_cooccurrence_limit(self):
        g, session = self._make_graph()
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([]))
        session.run.return_value = mock_result

        g.get_cooccurring_patterns("pytest", limit=5)
        args = session.run.call_args
        assert args[0][1]["limit"] == 5

    def test_cooccurrence_returns_pmi(self):
        g, session = self._make_graph()
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([
            {"pattern_name": "flask", "category": "framework", "count": 10, "pmi": 3.14},
        ]))
        session.run.return_value = mock_result

        results = g.get_cooccurring_patterns("pytest")
        assert results[0]["pmi"] == 3.14

    def test_cooccurrence_empty_result(self):
        g, session = self._make_graph()
        mock_result = MagicMock()
        mock_result.__iter__ = MagicMock(return_value=iter([]))
        session.run.return_value = mock_result

        results = g.get_cooccurring_patterns("unknown_pattern")
        assert results == []

    def test_update_cooccurrences_cypher_uses_pmi(self):
        g, session = self._make_graph()
        mock_result = MagicMock()
        mock_result.single.return_value = {"total": 3}
        session.run.return_value = mock_result

        count = g.update_cooccurrences()
        assert count == 3
        cypher = session.run.call_args[0][0]
        assert "pmi" in cypher.lower() or "PMI" in cypher or "log" in cypher


# ---------------------------------------------------------------------------
# TestSyncStats
# ---------------------------------------------------------------------------

class TestSyncStats:
    """Test SyncStats dataclass."""

    def test_defaults(self):
        s = SyncStats()
        assert s.repos_synced == 0
        assert s.patterns_synced == 0
        assert s.techs_created == 0
        assert s.cooccurrences_built == 0
        assert s.duration_seconds == 0.0
        assert s.errors == []

    def test_error_list(self):
        s = SyncStats(errors=["err1", "err2"])
        assert len(s.errors) == 2


# ---------------------------------------------------------------------------
# TestLiveNeo4j (skipped if no live connection)
# ---------------------------------------------------------------------------

# Detect live Neo4j availability
_HAS_NEO4J_LIVE = bool(os.environ.get("NEO4J_URI")) and HAS_NEO4J


@pytest.mark.skipif(not _HAS_NEO4J_LIVE, reason="No live Neo4j connection")
class TestLiveNeo4j:
    """Integration tests against a real Neo4j instance."""

    def test_connect_and_stats(self):
        g = Neo4jGraph()
        assert g.is_available()
        stats = g.get_stats()
        assert stats["available"] is True
        g.close()

    def test_upsert_and_query_repo(self):
        g = Neo4jGraph()
        repo = _make_repo("test/live-repo", stars=42)
        assert g.upsert_repo(repo) is True
        g.close()

    def test_upsert_pattern_and_cooccurrence(self):
        g = Neo4jGraph()
        g.upsert_repo(_make_repo("test/co-repo"))
        g.upsert_pattern(_make_pattern("test/co-repo", "testing", "pytest"))
        g.upsert_pattern(_make_pattern("test/co-repo", "framework", "flask"))
        count = g.update_cooccurrences()
        assert count >= 0
        g.close()

    def test_clear_all(self):
        g = Neo4jGraph()
        g.upsert_repo(_make_repo("test/clearme"))
        assert g.clear_all() is True
        stats = g.get_stats()
        assert stats["total_repos"] == 0
        g.close()
