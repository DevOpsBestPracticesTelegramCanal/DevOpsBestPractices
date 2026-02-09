# -*- coding: utf-8 -*-
"""
Tests for BigQuery sync daemon — background thread that feeds PatternStore.

Covers: data classes, sync operations, extraction helpers, background thread.
"""

import os
import sys
import time
import threading
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from core.oss.bigquery_collector import BigQueryConfig, BQQueryResult
from core.oss.bigquery_sync import (
    BigQuerySync, SyncConfig, SyncResult,
    extract_repos_from_top, extract_patterns_from_ci,
    extract_patterns_from_frameworks, extract_patterns_from_languages,
)
from core.oss.pattern_store import PatternStore, RepoRecord


# ---------------------------------------------------------------------------
# TestSyncDataClasses
# ---------------------------------------------------------------------------

class TestSyncDataClasses:
    """Verify sync data class defaults."""

    def test_sync_config_defaults(self):
        cfg = SyncConfig()
        assert cfg.interval_seconds == 3600
        assert cfg.enabled is True
        assert cfg.max_repos_per_sync == 200
        assert isinstance(cfg.bq_config, BigQueryConfig)

    def test_sync_result_defaults(self):
        r = SyncResult()
        assert r.repos_added == 0
        assert r.patterns_added == 0
        assert r.errors == []
        assert r.success is True

    def test_sync_result_with_errors(self):
        r = SyncResult(errors=["something broke"])
        assert not r.success


# ---------------------------------------------------------------------------
# TestExtractionHelpers
# ---------------------------------------------------------------------------

class TestExtractionHelpers:
    """Test data extraction from BQ results."""

    def test_extract_repos_from_top(self):
        result = BQQueryResult(
            query_name="top_repos",
            rows=[
                {"repo_name": "org/repo1", "event_count": 500},
                {"repo_name": "org/repo2", "event_count": 300},
                {"repo_name": "invalid_no_slash", "event_count": 100},
            ],
        )
        repos = extract_repos_from_top(result)
        assert len(repos) == 2  # invalid_no_slash skipped
        assert repos[0].full_name == "org/repo1"
        assert repos[0].stars == 500

    def test_extract_repos_empty(self):
        result = BQQueryResult(query_name="top_repos", rows=[])
        repos = extract_repos_from_top(result)
        assert repos == []

    def test_extract_patterns_from_ci(self):
        result = BQQueryResult(
            query_name="ci_patterns",
            rows=[
                {"repo_name": "a/b", "ci_tool": "github_actions", "push_count": 42},
                {"repo_name": "c/d", "ci_tool": "travis", "push_count": 10},
            ],
        )
        patterns = extract_patterns_from_ci(result)
        assert len(patterns) == 2
        assert patterns[0].category == "ci_cd"
        assert patterns[0].pattern_name == "github_actions"
        assert patterns[0].confidence == min(1.0, 42 / 100.0)
        assert "bigquery" in patterns[0].metadata.get("source", "")

    def test_extract_patterns_from_frameworks(self):
        result = BQQueryResult(
            query_name="framework_signals",
            rows=[
                {"repo_name": "x/y", "framework": "fastapi", "mention_count": 25},
            ],
        )
        patterns = extract_patterns_from_frameworks(result)
        assert len(patterns) == 1
        assert patterns[0].category == "framework"
        assert patterns[0].pattern_name == "fastapi"
        assert patterns[0].confidence == min(1.0, 25 / 50.0)

    def test_extract_patterns_from_languages(self):
        result = BQQueryResult(
            query_name="language_trends",
            rows=[
                {"language": "Python", "pr_count": 1000},
                {"language": "Go", "pr_count": 500},
                {"language": "", "pr_count": 10},  # empty → skipped
            ],
        )
        patterns = extract_patterns_from_languages(result)
        assert len(patterns) == 2
        assert patterns[0].category == "language"
        assert patterns[0].pattern_name == "python"
        assert patterns[0].repo_name == "__aggregate__"


# ---------------------------------------------------------------------------
# TestBigQuerySync
# ---------------------------------------------------------------------------

class TestBigQuerySync:
    """Test sync operations with mocked collector."""

    def _make_sync(self, collector_enabled=False):
        """Create BigQuerySync with mocked collector."""
        store = PatternStore(db_path=":memory:")
        config = SyncConfig(enabled=True)
        sync = BigQuerySync(store, config)
        # Replace collector with mock
        sync._collector = MagicMock()
        sync._collector.enabled = collector_enabled
        sync._collector.get_stats.return_value = {"queries_total": 0}
        return sync, store

    def test_disabled_when_collector_disabled(self):
        sync, _ = self._make_sync(collector_enabled=False)
        assert not sync.enabled

    def test_enabled_when_collector_enabled(self):
        sync, _ = self._make_sync(collector_enabled=True)
        assert sync.enabled

    def test_sync_once_collector_disabled(self):
        sync, _ = self._make_sync(collector_enabled=False)
        result = sync.sync_once()
        assert not result.success
        assert "not enabled" in result.errors[0].lower()

    def test_sync_once_no_data(self):
        sync, _ = self._make_sync(collector_enabled=True)
        sync._collector.run_all_queries.return_value = [
            BQQueryResult(query_name="top_repos", rows=[]),
            BQQueryResult(query_name="language_trends", rows=[]),
            BQQueryResult(query_name="ci_patterns", rows=[]),
            BQQueryResult(query_name="framework_signals", rows=[]),
        ]
        result = sync.sync_once()
        assert result.success
        assert result.repos_added == 0
        assert result.patterns_added == 0

    def test_sync_once_with_repos(self):
        sync, store = self._make_sync(collector_enabled=True)
        sync._collector.run_all_queries.return_value = [
            BQQueryResult(
                query_name="top_repos",
                rows=[
                    {"repo_name": "org/repo1", "event_count": 100},
                    {"repo_name": "org/repo2", "event_count": 50},
                ],
            ),
            BQQueryResult(query_name="language_trends", rows=[]),
            BQQueryResult(query_name="ci_patterns", rows=[]),
            BQQueryResult(query_name="framework_signals", rows=[]),
        ]
        result = sync.sync_once()
        assert result.success
        assert result.repos_added == 2
        assert store.count_repos() == 2

    def test_sync_once_with_errors(self):
        sync, _ = self._make_sync(collector_enabled=True)
        sync._collector.run_all_queries.return_value = [
            BQQueryResult(query_name="top_repos", error="budget exceeded"),
        ]
        result = sync.sync_once()
        assert not result.success
        assert "budget exceeded" in result.errors[0]

    def test_sync_once_cost_tracked(self):
        sync, _ = self._make_sync(collector_enabled=True)
        sync._collector.run_all_queries.return_value = [
            BQQueryResult(query_name="top_repos", rows=[], cost_usd=0.001),
            BQQueryResult(query_name="language_trends", rows=[], cost_usd=0.002),
            BQQueryResult(query_name="ci_patterns", rows=[]),
            BQQueryResult(query_name="framework_signals", rows=[]),
        ]
        result = sync.sync_once()
        assert result.total_cost_usd == pytest.approx(0.003, abs=0.0001)

    def test_sync_count_increments(self):
        sync, _ = self._make_sync(collector_enabled=True)
        sync._collector.run_all_queries.return_value = [
            BQQueryResult(query_name="top_repos", rows=[]),
            BQQueryResult(query_name="language_trends", rows=[]),
            BQQueryResult(query_name="ci_patterns", rows=[]),
            BQQueryResult(query_name="framework_signals", rows=[]),
        ]
        sync.sync_once()
        sync.sync_once()
        assert sync._sync_count == 2

    def test_last_sync_populated(self):
        sync, _ = self._make_sync(collector_enabled=True)
        assert sync.last_sync is None
        sync._collector.run_all_queries.return_value = [
            BQQueryResult(query_name="top_repos", rows=[]),
            BQQueryResult(query_name="language_trends", rows=[]),
            BQQueryResult(query_name="ci_patterns", rows=[]),
            BQQueryResult(query_name="framework_signals", rows=[]),
        ]
        sync.sync_once()
        assert sync.last_sync is not None
        assert sync.last_sync.duration_seconds > 0

    def test_get_stats(self):
        sync, _ = self._make_sync(collector_enabled=True)
        sync._collector.run_all_queries.return_value = [
            BQQueryResult(query_name="top_repos", rows=[]),
            BQQueryResult(query_name="language_trends", rows=[]),
            BQQueryResult(query_name="ci_patterns", rows=[]),
            BQQueryResult(query_name="framework_signals", rows=[]),
        ]
        sync.sync_once()
        stats = sync.get_stats()
        assert "enabled" in stats
        assert "sync_count" in stats
        assert stats["sync_count"] == 1
        assert stats["last_sync"] is not None

    def test_max_repos_per_sync_respected(self):
        sync, store = self._make_sync(collector_enabled=True)
        sync._config.max_repos_per_sync = 2
        rows = [{"repo_name": f"org/repo{i}", "event_count": i}
                for i in range(10)]
        sync._collector.run_all_queries.return_value = [
            BQQueryResult(query_name="top_repos", rows=rows),
            BQQueryResult(query_name="language_trends", rows=[]),
            BQQueryResult(query_name="ci_patterns", rows=[]),
            BQQueryResult(query_name="framework_signals", rows=[]),
        ]
        result = sync.sync_once()
        assert result.repos_added == 2  # capped at max_repos_per_sync

    def test_sync_with_ci_patterns(self):
        sync, store = self._make_sync(collector_enabled=True)
        # Add repo first so patterns can reference it
        store.save_repo(RepoRecord(full_name="a/b", stars=100))
        sync._collector.run_all_queries.return_value = [
            BQQueryResult(query_name="top_repos", rows=[]),
            BQQueryResult(query_name="language_trends", rows=[]),
            BQQueryResult(query_name="ci_patterns", rows=[
                {"repo_name": "a/b", "ci_tool": "github_actions", "push_count": 42},
            ]),
            BQQueryResult(query_name="framework_signals", rows=[]),
        ]
        result = sync.sync_once()
        assert result.patterns_added >= 1

    def test_sync_with_framework_signals(self):
        sync, store = self._make_sync(collector_enabled=True)
        store.save_repo(RepoRecord(full_name="x/y", stars=200))
        sync._collector.run_all_queries.return_value = [
            BQQueryResult(query_name="top_repos", rows=[]),
            BQQueryResult(query_name="language_trends", rows=[]),
            BQQueryResult(query_name="ci_patterns", rows=[]),
            BQQueryResult(query_name="framework_signals", rows=[
                {"repo_name": "x/y", "framework": "django", "mention_count": 30},
            ]),
        ]
        result = sync.sync_once()
        assert result.patterns_added >= 1

    def test_sync_duration_recorded(self):
        sync, _ = self._make_sync(collector_enabled=True)
        sync._collector.run_all_queries.return_value = [
            BQQueryResult(query_name="top_repos", rows=[]),
            BQQueryResult(query_name="language_trends", rows=[]),
            BQQueryResult(query_name="ci_patterns", rows=[]),
            BQQueryResult(query_name="framework_signals", rows=[]),
        ]
        result = sync.sync_once()
        assert result.duration_seconds >= 0

    def test_queries_run_count(self):
        sync, _ = self._make_sync(collector_enabled=True)
        sync._collector.run_all_queries.return_value = [
            BQQueryResult(query_name="top_repos", rows=[]),
            BQQueryResult(query_name="language_trends", rows=[]),
        ]
        result = sync.sync_once()
        assert result.queries_run == 2


# ---------------------------------------------------------------------------
# TestBackgroundThread
# ---------------------------------------------------------------------------

class TestBackgroundThread:
    """Test daemon thread start/stop."""

    def test_start_when_disabled(self):
        store = PatternStore(db_path=":memory:")
        sync = BigQuerySync(store, SyncConfig(enabled=True))
        sync._collector = MagicMock()
        sync._collector.enabled = False
        assert not sync.start()
        assert not sync.running

    def test_start_and_stop(self):
        store = PatternStore(db_path=":memory:")
        sync = BigQuerySync(store, SyncConfig(enabled=True, interval_seconds=1))
        sync._collector = MagicMock()
        sync._collector.enabled = True
        sync._collector.run_all_queries.return_value = [
            BQQueryResult(query_name="top_repos", rows=[]),
            BQQueryResult(query_name="language_trends", rows=[]),
            BQQueryResult(query_name="ci_patterns", rows=[]),
            BQQueryResult(query_name="framework_signals", rows=[]),
        ]

        assert sync.start()
        assert sync.running
        time.sleep(0.5)  # Let daemon do at least one loop iteration
        sync.stop()
        assert not sync.running

    def test_double_start_idempotent(self):
        store = PatternStore(db_path=":memory:")
        sync = BigQuerySync(store, SyncConfig(enabled=True, interval_seconds=60))
        sync._collector = MagicMock()
        sync._collector.enabled = True
        sync._collector.run_all_queries.return_value = []

        sync.start()
        thread1 = sync._thread
        sync.start()  # should return True without creating new thread
        assert sync._thread is thread1
        sync.stop()
