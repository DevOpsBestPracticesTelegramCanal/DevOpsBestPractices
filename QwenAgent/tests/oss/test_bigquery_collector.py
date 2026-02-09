# -*- coding: utf-8 -*-
"""
Tests for BigQuery collector — zero-cost OSS pattern discovery.

Covers: data classes, graceful degradation, cost safety (5 layers),
query cache, retry logic, mocked queries, and live integration.
"""

import json
import os
import sys
import tempfile
import time
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from core.oss.bigquery_collector import (
    BigQueryCollector, BigQueryConfig, BQQueryResult,
    COST_PER_BYTE, HAS_BIGQUERY,
)


# ---------------------------------------------------------------------------
# TestBQDataClasses
# ---------------------------------------------------------------------------

class TestBQDataClasses:
    """Verify config defaults reflect zero-cost constraints."""

    def test_config_defaults_max_bytes(self):
        cfg = BigQueryConfig()
        assert cfg.max_bytes_billed == 104_857_600  # 100 MB

    def test_config_defaults_session_budget(self):
        cfg = BigQueryConfig()
        assert cfg.cost_budget_usd == 0.10

    def test_config_defaults_monthly_budget(self):
        cfg = BigQueryConfig()
        assert cfg.budget_monthly == 0.50

    def test_config_defaults_per_query_cap(self):
        cfg = BigQueryConfig()
        assert cfg.max_cost_per_query == 0.01

    def test_bq_result_defaults(self):
        r = BQQueryResult(query_name="test")
        assert r.rows == []
        assert r.bytes_processed == 0
        assert r.cost_usd == 0.0
        assert not r.cached
        assert r.error == ""

    def test_cost_per_byte_reasonable(self):
        # 1 TB should cost $6.25
        cost_per_tb = COST_PER_BYTE * (1024 ** 4)
        assert abs(cost_per_tb - 6.25) < 0.001


# ---------------------------------------------------------------------------
# TestGracefulDegradation
# ---------------------------------------------------------------------------

class TestGracefulDegradation:
    """Collector works safely when BigQuery is unavailable."""

    def test_no_bigquery_library(self):
        with patch("core.oss.bigquery_collector.HAS_BIGQUERY", False):
            c = BigQueryCollector.__new__(BigQueryCollector)
            c._config = BigQueryConfig()
            c._client = None
            c._session_cost = 0.0
            c._query_cache = {}
            c._cost_history = {"entries": [], "monthly_total": 0.0}
            c._enabled = False
            c._stats = {"queries_total": 0, "queries_cached": 0,
                         "queries_refused": 0, "bytes_processed": 0,
                         "total_cost_usd": 0.0, "dry_runs": 0, "errors": 0}
            assert not c.enabled
            result = c.query_top_repos()
            assert result.error
            assert result.rows == []

    def test_emergency_stop_env(self):
        with patch.dict(os.environ, {"BIGQUERY_ENABLED": "false"}):
            cfg = BigQueryConfig(emergency_stop_enabled=True)
            c = BigQueryCollector(config=cfg)
            assert not c.enabled

    def test_emergency_stop_disabled(self):
        cfg = BigQueryConfig(emergency_stop_enabled=False)
        # Without BQ library it still won't be enabled, but the env check is skipped
        c = BigQueryCollector.__new__(BigQueryCollector)
        c._config = cfg
        c._client = None
        c._session_cost = 0.0
        c._query_cache = {}
        c._cost_history = {"entries": [], "monthly_total": 0.0}
        c._enabled = False
        c._stats = {"queries_total": 0, "queries_cached": 0,
                     "queries_refused": 0, "bytes_processed": 0,
                     "total_cost_usd": 0.0, "dry_runs": 0, "errors": 0}
        # _safe_query should still return error for disabled
        result = c._safe_query("test", "SELECT 1")
        assert "not enabled" in result.error.lower() or result.error != ""

    def test_disabled_returns_empty_stats(self):
        c = BigQueryCollector.__new__(BigQueryCollector)
        c._config = BigQueryConfig()
        c._client = None
        c._session_cost = 0.0
        c._query_cache = {}
        c._cost_history = {"entries": [], "monthly_total": 0.0}
        c._enabled = False
        c._stats = {"queries_total": 0, "queries_cached": 0,
                     "queries_refused": 0, "bytes_processed": 0,
                     "total_cost_usd": 0.0, "dry_runs": 0, "errors": 0}
        stats = c.get_stats()
        assert stats["enabled"] is False
        assert stats["total_cost_usd"] == 0.0


# ---------------------------------------------------------------------------
# TestCostSafety
# ---------------------------------------------------------------------------

class TestCostSafety:
    """Test all 5 cost safety layers."""

    def _make_collector(self, **config_overrides):
        """Create a collector with mocked BQ client."""
        c = BigQueryCollector.__new__(BigQueryCollector)
        config_overrides.setdefault("cost_history_path",
                                    os.path.join(tempfile.mkdtemp(), "costs.json"))
        c._config = BigQueryConfig(**config_overrides)
        c._client = MagicMock()
        c._session_cost = 0.0
        c._query_cache = {}
        c._cost_history = {"entries": [], "monthly_total": 0.0}
        c._enabled = True
        c._stats = {"queries_total": 0, "queries_cached": 0,
                     "queries_refused": 0, "bytes_processed": 0,
                     "total_cost_usd": 0.0, "dry_runs": 0, "errors": 0}
        # Mock _make_job_config so it doesn't need real bq module
        c._make_job_config = MagicMock(return_value=MagicMock())
        # Prevent _load_cost_history from overwriting test values
        c._load_cost_history = lambda: None
        c._save_cost_history = lambda: None
        return c

    def test_monthly_budget_exceeded(self):
        c = self._make_collector(budget_monthly=0.50)
        c._cost_history["monthly_total"] = 0.55
        result = c._safe_query("test", "SELECT 1")
        assert "monthly budget" in result.error.lower()
        assert c._stats["queries_refused"] == 1

    def test_monthly_budget_within_limit(self):
        c = self._make_collector(budget_monthly=0.50, dry_run_first=False)
        c._cost_history["monthly_total"] = 0.01
        # Mock query execution
        mock_job = MagicMock()
        mock_job.total_bytes_processed = 1000
        mock_job.result.return_value = []
        c._client.query.return_value = mock_job
        result = c._safe_query("test", "SELECT 1")
        assert result.error == ""

    def test_session_budget_exceeded(self):
        c = self._make_collector(cost_budget_usd=0.10)
        c._session_cost = 0.15
        result = c._safe_query("test", "SELECT 1")
        assert "session budget" in result.error.lower()
        assert c._stats["queries_refused"] == 1

    def test_per_query_cap_exceeded(self):
        c = self._make_collector(max_cost_per_query=0.01)
        # Mock dry-run returning huge bytes
        mock_job = MagicMock()
        mock_job.total_bytes_processed = 10 * (1024 ** 4)  # 10 TB
        c._client.query.return_value = mock_job
        result = c._safe_query("test", "SELECT 1")
        assert "estimated cost" in result.error.lower()

    def test_per_query_cap_within_limit(self):
        c = self._make_collector(max_cost_per_query=0.01, dry_run_first=True)
        # Mock dry-run returning small bytes
        mock_dry_job = MagicMock()
        mock_dry_job.total_bytes_processed = 1000  # tiny
        mock_real_job = MagicMock()
        mock_real_job.total_bytes_processed = 1000
        mock_real_job.result.return_value = []
        c._client.query.side_effect = [mock_dry_job, mock_real_job]
        result = c._safe_query("test", "SELECT 1")
        assert result.error == ""

    def test_dry_run_failure(self):
        c = self._make_collector(dry_run_first=True)
        c._client.query.side_effect = Exception("Connection refused")
        result = c._safe_query("test", "SELECT 1")
        assert "dry-run failed" in result.error.lower()

    def test_emergency_stop_recheck(self):
        c = self._make_collector(emergency_stop_enabled=True)
        with patch.dict(os.environ, {"BIGQUERY_ENABLED": "false"}):
            result = c._safe_query("test", "SELECT 1")
            assert "disabled" in result.error.lower()

    def test_cost_alert_threshold_logged(self):
        c = self._make_collector(cost_alert_threshold=0.30,
                                 budget_monthly=0.50,
                                 dry_run_first=False)
        c._cost_history["monthly_total"] = 0.35
        mock_job = MagicMock()
        mock_job.total_bytes_processed = 100
        mock_job.result.return_value = []
        c._client.query.return_value = mock_job
        # Should still execute (below hard cap) but log a warning
        result = c._safe_query("test", "SELECT 1")
        assert result.error == ""


# ---------------------------------------------------------------------------
# TestQueryCache
# ---------------------------------------------------------------------------

class TestQueryCache:
    """Test in-memory query cache."""

    def _make_collector(self):
        c = BigQueryCollector.__new__(BigQueryCollector)
        c._config = BigQueryConfig(cache_ttl_seconds=3600, dry_run_first=False,
                                   cost_history_path=os.path.join(
                                       tempfile.mkdtemp(), "costs.json"))
        c._client = MagicMock()
        c._session_cost = 0.0
        c._query_cache = {}
        c._cost_history = {"entries": [], "monthly_total": 0.0}
        c._enabled = True
        c._stats = {"queries_total": 0, "queries_cached": 0,
                     "queries_refused": 0, "bytes_processed": 0,
                     "total_cost_usd": 0.0, "dry_runs": 0, "errors": 0}
        c._make_job_config = MagicMock(return_value=MagicMock())
        c._load_cost_history = lambda: None
        return c

    def test_cache_miss_then_hit(self):
        c = self._make_collector()
        mock_job = MagicMock()
        mock_job.total_bytes_processed = 500
        mock_job.result.return_value = [{"repo": "a/b"}]
        c._client.query.return_value = mock_job

        # First call: cache miss
        r1 = c._safe_query("test", "SELECT 1")
        assert not r1.cached
        assert c._stats["queries_cached"] == 0

        # Second call: cache hit
        r2 = c._safe_query("test", "SELECT 1")
        assert r2.cached
        assert r2.cost_usd == 0.0
        assert c._stats["queries_cached"] == 1

    def test_cache_ttl_expiry(self):
        c = self._make_collector()
        c._config.cache_ttl_seconds = 1  # 1 second TTL

        mock_job = MagicMock()
        mock_job.total_bytes_processed = 100
        mock_job.result.return_value = []
        c._client.query.return_value = mock_job

        # First call
        c._safe_query("test", "SELECT 1")

        # Wait for TTL to expire
        time.sleep(1.1)

        # Should be a cache miss now
        r2 = c._safe_query("test", "SELECT 1")
        assert not r2.cached

    def test_different_queries_not_cached(self):
        c = self._make_collector()
        mock_job = MagicMock()
        mock_job.total_bytes_processed = 100
        mock_job.result.return_value = []
        c._client.query.return_value = mock_job

        c._safe_query("q1", "SELECT 1")
        c._safe_query("q2", "SELECT 2")
        assert c._stats["queries_cached"] == 0

    def test_cache_key_deterministic(self):
        k1 = BigQueryCollector._cache_key("SELECT 1")
        k2 = BigQueryCollector._cache_key("SELECT 1")
        k3 = BigQueryCollector._cache_key("SELECT 2")
        assert k1 == k2
        assert k1 != k3

    def test_cached_result_zero_cost(self):
        c = self._make_collector()
        mock_job = MagicMock()
        mock_job.total_bytes_processed = 10000
        mock_job.result.return_value = [{"x": 1}]
        c._client.query.return_value = mock_job

        r1 = c._safe_query("test", "SELECT 1")
        assert r1.cost_usd > 0

        r2 = c._safe_query("test", "SELECT 1")
        assert r2.cached
        assert r2.cost_usd == 0.0


# ---------------------------------------------------------------------------
# TestRetryLogic
# ---------------------------------------------------------------------------

class TestRetryLogic:
    """Test retry with exponential backoff."""

    def test_transient_error_retried(self):
        c = BigQueryCollector.__new__(BigQueryCollector)
        c._config = BigQueryConfig()
        c._client = MagicMock()
        c._make_job_config = MagicMock(return_value=MagicMock())
        c._stats = {"queries_total": 0, "queries_cached": 0,
                     "queries_refused": 0, "bytes_processed": 0,
                     "total_cost_usd": 0.0, "dry_runs": 0, "errors": 0}

        # First call fails with 503, second succeeds
        mock_job = MagicMock()
        mock_job.total_bytes_processed = 100
        mock_job.result.return_value = []

        call_count = 0
        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise Exception("503 Service Unavailable")
            return mock_job

        c._client.query.side_effect = side_effect
        result = c._execute_with_retry("test", "SELECT 1", max_retries=3)
        assert result.error == ""
        assert call_count == 2

    def test_non_transient_error_not_retried(self):
        c = BigQueryCollector.__new__(BigQueryCollector)
        c._config = BigQueryConfig()
        c._client = MagicMock()
        c._make_job_config = MagicMock(return_value=MagicMock())
        c._stats = {"queries_total": 0, "queries_cached": 0,
                     "queries_refused": 0, "bytes_processed": 0,
                     "total_cost_usd": 0.0, "dry_runs": 0, "errors": 0}

        c._client.query.side_effect = Exception("Invalid query syntax")
        result = c._execute_with_retry("test", "BAD SQL", max_retries=3)
        assert result.error != ""
        assert c._client.query.call_count == 1

    def test_max_retries_exhausted(self):
        c = BigQueryCollector.__new__(BigQueryCollector)
        c._config = BigQueryConfig()
        c._client = MagicMock()
        c._make_job_config = MagicMock(return_value=MagicMock())
        c._stats = {"queries_total": 0, "queries_cached": 0,
                     "queries_refused": 0, "bytes_processed": 0,
                     "total_cost_usd": 0.0, "dry_runs": 0, "errors": 0}

        c._client.query.side_effect = Exception("503 Service Unavailable")
        result = c._execute_with_retry("test", "SELECT 1", max_retries=2)
        assert result.error != ""
        assert c._client.query.call_count == 2

    def test_is_transient_detection(self):
        assert BigQueryCollector._is_transient(Exception("503 error"))
        assert BigQueryCollector._is_transient(Exception("429 rate limited"))
        assert BigQueryCollector._is_transient(Exception("connectionerror"))
        assert not BigQueryCollector._is_transient(Exception("invalid query"))
        assert not BigQueryCollector._is_transient(Exception("permission denied"))


# ---------------------------------------------------------------------------
# TestBigQueryCollectorMocked
# ---------------------------------------------------------------------------

class TestBigQueryCollectorMocked:
    """Test all 4 queries with mocked BQ client."""

    def _make_collector(self):
        c = BigQueryCollector.__new__(BigQueryCollector)
        c._config = BigQueryConfig(dry_run_first=False,
                                   cost_history_path=os.path.join(
                                       tempfile.mkdtemp(), "costs.json"))
        c._client = MagicMock()
        c._session_cost = 0.0
        c._query_cache = {}
        c._cost_history = {"entries": [], "monthly_total": 0.0}
        c._enabled = True
        c._stats = {"queries_total": 0, "queries_cached": 0,
                     "queries_refused": 0, "bytes_processed": 0,
                     "total_cost_usd": 0.0, "dry_runs": 0, "errors": 0}
        c._make_job_config = MagicMock(return_value=MagicMock())
        return c

    def _mock_job(self, rows=None, bytes_processed=1000):
        job = MagicMock()
        job.total_bytes_processed = bytes_processed
        job.result.return_value = rows or []
        return job

    def test_query_top_repos(self):
        c = self._make_collector()
        c._client.query.return_value = self._mock_job(
            [{"repo_name": "org/repo", "event_count": 500}])
        result = c.query_top_repos()
        assert result.error == ""
        assert result.query_name == "top_repos"
        assert len(result.rows) == 1

    def test_query_language_trends(self):
        c = self._make_collector()
        c._client.query.return_value = self._mock_job(
            [{"language": "Python", "pr_count": 1000}])
        result = c.query_language_trends()
        assert result.error == ""
        assert result.query_name == "language_trends"

    def test_query_ci_patterns(self):
        c = self._make_collector()
        c._client.query.return_value = self._mock_job(
            [{"repo_name": "a/b", "ci_tool": "github_actions", "push_count": 42}])
        result = c.query_ci_patterns()
        assert result.error == ""
        assert result.query_name == "ci_patterns"

    def test_query_framework_signals(self):
        c = self._make_collector()
        c._client.query.return_value = self._mock_job(
            [{"repo_name": "a/b", "framework": "fastapi", "mention_count": 10}])
        result = c.query_framework_signals()
        assert result.error == ""
        assert result.query_name == "framework_signals"

    def test_run_all_queries(self):
        c = self._make_collector()
        c._client.query.return_value = self._mock_job(bytes_processed=500)
        results = c.run_all_queries()
        assert len(results) == 4
        for r in results:
            assert r.error == ""

    def test_run_all_stops_on_budget(self):
        c = self._make_collector()
        c._config.cost_budget_usd = 0.0  # Zero budget → immediate stop
        c._session_cost = 0.01
        results = c.run_all_queries()
        # All should have budget error
        assert all(r.error for r in results)

    def test_stats_updated_after_query(self):
        c = self._make_collector()
        c._client.query.return_value = self._mock_job(bytes_processed=5000)
        c.query_top_repos()
        assert c._stats["queries_total"] == 1
        assert c._stats["bytes_processed"] == 5000
        assert c._stats["total_cost_usd"] > 0

    def test_cost_report(self):
        c = self._make_collector()
        c._client.query.return_value = self._mock_job(bytes_processed=1000)
        c.query_top_repos()
        report = c.get_cost_report()
        assert "monthly_total" in report
        assert "daily_breakdown" in report
        assert report["entry_count"] >= 1

    def test_cost_history_persisted(self):
        c = self._make_collector()
        c._client.query.return_value = self._mock_job(bytes_processed=2000)
        c.query_top_repos()

        # Verify file was written
        assert os.path.exists(c._config.cost_history_path)
        with open(c._config.cost_history_path) as f:
            data = json.load(f)
        assert len(data["entries"]) == 1
        assert data["entries"][0]["query"] == "top_repos"

    def test_query_limit_in_sql(self):
        c = self._make_collector()
        c._config.query_limit = 100
        c._client.query.return_value = self._mock_job()
        c.query_top_repos()
        sql_arg = c._client.query.call_args[0][0]
        assert "LIMIT 100" in sql_arg


# ---------------------------------------------------------------------------
# TestLiveBigQuery (skipped without credentials)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.environ.get("GOOGLE_APPLICATION_CREDENTIALS") or not HAS_BIGQUERY,
    reason="BigQuery credentials not available",
)
class TestLiveBigQuery:
    """Live integration tests — only run with real credentials."""

    def test_live_top_repos(self):
        c = BigQueryCollector(BigQueryConfig(query_limit=5))
        result = c.query_top_repos()
        assert result.error == ""
        assert len(result.rows) > 0
        assert result.cost_usd < 0.01

    def test_live_cost_report(self):
        c = BigQueryCollector(BigQueryConfig(query_limit=5))
        c.query_top_repos()
        report = c.get_cost_report()
        assert report["monthly_total"] < 0.50
