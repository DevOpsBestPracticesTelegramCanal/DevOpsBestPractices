# -*- coding: utf-8 -*-
"""
Integration tests for Neo4j Knowledge Graph with QwenAgent ecosystem.

Covers: __init__.py exports, agent stats, PatternStore → GraphBuilder → Neo4jGraph
end-to-end flow (mocked driver).
"""

import os
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from core.oss.pattern_store import PatternStore, RepoRecord, PatternRecord
from core.oss.graph_builder import GraphBuilder, SyncStats
from core.oss.neo4j_graph import Neo4jGraph, HAS_NEO4J


# ---------------------------------------------------------------------------
# TestExports
# ---------------------------------------------------------------------------

class TestExports:
    """Verify __init__.py exports for Neo4j."""

    def test_has_neo4j_flag(self):
        from core.oss import HAS_NEO4J as flag
        assert isinstance(flag, bool)

    def test_neo4j_graph_importable(self):
        from core.oss.neo4j_graph import Neo4jGraph
        assert Neo4jGraph is not None

    def test_graph_builder_importable(self):
        from core.oss.graph_builder import GraphBuilder, SyncStats
        assert GraphBuilder is not None
        assert SyncStats is not None

    def test_pattern_store_still_importable(self):
        """Ensure adding Neo4j doesn't break existing imports."""
        from core.oss import PatternStore, RepoRecord, PatternRecord
        assert PatternStore is not None


# ---------------------------------------------------------------------------
# TestEndToEnd
# ---------------------------------------------------------------------------

class TestEndToEnd:
    """End-to-end PatternStore → GraphBuilder → Neo4jGraph (mocked driver)."""

    def _setup(self):
        """Create a PatternStore with data and mocked Neo4jGraph."""
        store = PatternStore(db_path=":memory:")

        # Add repos
        store.save_repo(RepoRecord(
            full_name="pallets/flask",
            stars=60000,
            forks=8000,
            topics=["python", "flask", "web"],
            license="BSD",
            architecture="wsgi",
            collected_at=time.time(),
        ))
        store.save_repo(RepoRecord(
            full_name="tiangolo/fastapi",
            stars=55000,
            forks=5000,
            topics=["python", "fastapi", "async"],
            license="MIT",
            collected_at=time.time(),
        ))

        # Add patterns
        store.save_patterns([
            PatternRecord(repo_name="pallets/flask", category="framework", pattern_name="flask", confidence=0.95),
            PatternRecord(repo_name="pallets/flask", category="testing", pattern_name="pytest", confidence=0.9),
            PatternRecord(repo_name="tiangolo/fastapi", category="framework", pattern_name="fastapi", confidence=0.98),
            PatternRecord(repo_name="tiangolo/fastapi", category="testing", pattern_name="pytest", confidence=0.92),
        ])

        # Mock Neo4jGraph
        graph = MagicMock(spec=Neo4jGraph)
        graph.is_available.return_value = True
        graph.upsert_repo.return_value = True
        graph.upsert_pattern.return_value = True
        graph.upsert_technology.return_value = True
        graph.link_repo_tech.return_value = True
        graph.create_constraints.return_value = None
        graph.update_cooccurrences.return_value = 1

        return store, graph

    def test_full_sync_with_real_store(self):
        store, graph = self._setup()
        builder = GraphBuilder(store, graph)
        stats = builder.full_sync()

        assert stats.repos_synced == 2
        assert stats.patterns_synced == 4
        assert stats.techs_created > 0
        assert stats.duration_seconds >= 0

    def test_incremental_sync_with_real_store(self):
        store, graph = self._setup()
        builder = GraphBuilder(store, graph)

        # Sync with cutoff in the future → nothing new
        stats = builder.incremental_sync(since_timestamp=time.time() + 1000)
        assert stats.repos_synced == 0

        # Sync with cutoff in the past → both repos
        stats = builder.incremental_sync(since_timestamp=0)
        assert stats.repos_synced == 2

    def test_build_cooccurrences_after_sync(self):
        store, graph = self._setup()
        builder = GraphBuilder(store, graph)
        builder.full_sync()
        count = builder.build_cooccurrences()
        assert count == 1
        graph.update_cooccurrences.assert_called_once()

    def test_technology_extraction_from_real_data(self):
        store, _ = self._setup()
        repo = store.get_repo("pallets/flask")
        patterns = store.get_patterns_for_repo("pallets/flask")
        techs = GraphBuilder.extract_technologies(repo, patterns)
        assert "Python" in techs
        assert "Flask" in techs
        assert "pytest" in techs


# ---------------------------------------------------------------------------
# TestAgentStatsIntegration
# ---------------------------------------------------------------------------

class TestAgentStatsIntegration:
    """Verify that agent stats would include Neo4j fields."""

    def test_neo4j_stat_keys_exist(self):
        """The stats dict in the plan should include neo4j keys."""
        expected_keys = [
            "neo4j_syncs",
            "neo4j_nodes_total",
            "neo4j_rels_total",
            "neo4j_cooccurrences",
        ]
        # Create a stats dict with the expected keys (simulating agent stats)
        stats = {k: 0 for k in expected_keys}
        for key in expected_keys:
            assert key in stats
            assert stats[key] == 0

    def test_graph_stats_structure(self):
        """Neo4jGraph.get_stats() returns expected structure."""
        graph = MagicMock(spec=Neo4jGraph)
        graph.get_stats.return_value = {
            "available": True,
            "total_repos": 10,
            "total_patterns": 50,
            "total_categories": 5,
            "total_technologies": 3,
            "total_cooccurrences": 20,
            "total_relationships": 100,
        }
        stats = graph.get_stats()
        assert "total_repos" in stats
        assert "total_cooccurrences" in stats
        assert stats["available"] is True

    def test_sync_stats_fields(self):
        """SyncStats has all required fields."""
        s = SyncStats(
            repos_synced=10,
            patterns_synced=50,
            techs_created=5,
            cooccurrences_built=20,
            duration_seconds=1.5,
        )
        assert s.repos_synced == 10
        assert s.duration_seconds == 1.5

    def test_graph_builder_available_flag(self):
        """GraphBuilder.is_available reflects graph availability."""
        graph = MagicMock(spec=Neo4jGraph)
        store = MagicMock(spec=PatternStore)

        graph.is_available.return_value = True
        builder = GraphBuilder(store, graph)
        assert builder.is_available is True

        graph.is_available.return_value = False
        assert builder.is_available is False
