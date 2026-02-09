# -*- coding: utf-8 -*-
"""
BigQueryCollector — Zero-cost BigQuery integration for OSS pattern discovery.

5-layer cost safety architecture:
  1. Per-query cap: ABORT if estimated_cost > $0.01
  2. Per-session budget: $0.10 max per sync run
  3. Monthly budget: $0.50 hard cap
  4. Monthly alert: warn at $0.30, disable at $0.50
  5. Emergency stop: BIGQUERY_ENABLED=false env var → instant disable

All queries use dry_run first, cache results in-memory for 1h,
and track costs in .qwencode/bigquery_costs.json.
"""

import hashlib
import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Graceful import for google-cloud-bigquery
try:
    from google.cloud import bigquery as bq
    from google.api_core import exceptions as gcp_exceptions
    HAS_BIGQUERY = True
except ImportError:
    HAS_BIGQUERY = False
    bq = None  # type: ignore
    gcp_exceptions = None  # type: ignore

# BigQuery pricing: $6.25 per TB scanned (on-demand)
COST_PER_BYTE = 6.25 / (1024 ** 4)  # $/byte


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class BigQueryConfig:
    """Configuration with conservative cost defaults."""
    project_id: str = ""
    max_bytes_billed: int = 104_857_600  # 100 MB (not 1 GB!)
    cost_budget_usd: float = 0.10        # per-session budget
    budget_monthly: float = 0.50         # hard monthly cap
    cost_alert_threshold: float = 0.30   # warn at this level
    max_cost_per_query: float = 0.01     # abort if single query exceeds
    dry_run_first: bool = True           # ALWAYS dry-run before real query
    cache_ttl_seconds: int = 3600        # 1 hour query cache
    emergency_stop_enabled: bool = True  # check BIGQUERY_ENABLED env var
    cost_history_path: str = os.path.join(".qwencode", "bigquery_costs.json")
    query_limit: int = 500               # LIMIT for production queries


@dataclass
class BQQueryResult:
    """Result of a BigQuery query."""
    query_name: str
    rows: List[Dict[str, Any]] = field(default_factory=list)
    bytes_processed: int = 0
    cost_usd: float = 0.0
    cached: bool = False
    error: str = ""
    duration_ms: float = 0.0


# ---------------------------------------------------------------------------
# BigQueryCollector
# ---------------------------------------------------------------------------

class BigQueryCollector:
    """Collects OSS pattern data from BigQuery with multi-layer cost safety."""

    def __init__(self, config: Optional[BigQueryConfig] = None):
        self._config = config or BigQueryConfig()
        self._client: Any = None
        self._session_cost: float = 0.0
        self._query_cache: Dict[str, Tuple[float, BQQueryResult]] = {}
        self._cost_history: Dict[str, Any] = {"entries": [], "monthly_total": 0.0}
        self._enabled: bool = False
        self._stats = {
            "queries_total": 0,
            "queries_cached": 0,
            "queries_refused": 0,
            "bytes_processed": 0,
            "total_cost_usd": 0.0,
            "dry_runs": 0,
            "errors": 0,
        }

        # Layer 5: Emergency stop
        if self._config.emergency_stop_enabled:
            env_val = os.environ.get("BIGQUERY_ENABLED", "true").lower()
            if env_val == "false":
                logger.info("[BigQuery] Disabled via BIGQUERY_ENABLED=false")
                return

        if not HAS_BIGQUERY:
            logger.info("[BigQuery] google-cloud-bigquery not installed, disabled")
            return

        # Try to initialize client
        try:
            kwargs: Dict[str, Any] = {}
            if self._config.project_id:
                kwargs["project"] = self._config.project_id
            self._client = bq.Client(**kwargs)
            self._enabled = True
            logger.info("[BigQuery] Client initialized (project=%s)",
                        self._client.project if self._client else "none")
        except Exception as exc:
            logger.warning("[BigQuery] Client init failed: %s", exc)
            return

        # Load cost history
        self._load_cost_history()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    def get_stats(self) -> Dict[str, Any]:
        return {**self._stats, "enabled": self._enabled,
                "session_cost_usd": self._session_cost}

    def get_cost_report(self) -> Dict[str, Any]:
        """Return daily/monthly cost breakdown."""
        self._load_cost_history()
        daily: Dict[str, float] = {}
        for entry in self._cost_history.get("entries", []):
            day = entry.get("date", "unknown")
            daily[day] = daily.get(day, 0.0) + entry.get("cost_usd", 0.0)
        return {
            "monthly_total": self._cost_history.get("monthly_total", 0.0),
            "daily_breakdown": daily,
            "entry_count": len(self._cost_history.get("entries", [])),
            "session_cost": self._session_cost,
        }

    def query_top_repos(self) -> BQQueryResult:
        """Query top Python repos by stars from GitHub Archive."""
        sql = """
        -- Expected: ~5-20 MB scan, cost < $0.001
        SELECT
            repo_name,
            COUNT(*) AS event_count,
            MIN(created_at) AS first_seen,
            MAX(created_at) AS last_seen
        FROM `githubarchive.day.20*`
        WHERE _TABLE_SUFFIX BETWEEN '240101' AND '240131'
          AND type = 'WatchEvent'
          AND repo_name LIKE '%/%'
        GROUP BY repo_name
        ORDER BY event_count DESC
        LIMIT {limit}
        """.format(limit=self._config.query_limit)
        return self._safe_query("top_repos", sql)

    def query_language_trends(self) -> BQQueryResult:
        """Query language popularity trends from push events."""
        sql = """
        -- Expected: ~10-30 MB scan, cost < $0.001
        SELECT
            JSON_EXTRACT_SCALAR(payload, '$.pull_request.base.repo.language') AS language,
            COUNT(*) AS pr_count
        FROM `githubarchive.day.20*`
        WHERE _TABLE_SUFFIX BETWEEN '240101' AND '240131'
          AND type = 'PullRequestEvent'
          AND JSON_EXTRACT_SCALAR(payload, '$.action') = 'opened'
          AND JSON_EXTRACT_SCALAR(payload, '$.pull_request.base.repo.language') IS NOT NULL
        GROUP BY language
        ORDER BY pr_count DESC
        LIMIT {limit}
        """.format(limit=self._config.query_limit)
        return self._safe_query("language_trends", sql)

    def query_ci_patterns(self) -> BQQueryResult:
        """Query CI/CD tool usage from push events."""
        sql = """
        -- Expected: ~5-15 MB scan, cost < $0.001
        SELECT
            repo_name,
            CASE
                WHEN REGEXP_CONTAINS(
                    JSON_EXTRACT_SCALAR(payload, '$.commits[0].message'),
                    r'(?i)(github.actions|ci:|\\[ci\\])')
                THEN 'github_actions'
                WHEN REGEXP_CONTAINS(
                    JSON_EXTRACT_SCALAR(payload, '$.commits[0].message'),
                    r'(?i)(travis|travisci)')
                THEN 'travis'
                WHEN REGEXP_CONTAINS(
                    JSON_EXTRACT_SCALAR(payload, '$.commits[0].message'),
                    r'(?i)(circleci|circle.ci)')
                THEN 'circleci'
                ELSE 'other'
            END AS ci_tool,
            COUNT(*) AS push_count
        FROM `githubarchive.day.20*`
        WHERE _TABLE_SUFFIX BETWEEN '240101' AND '240131'
          AND type = 'PushEvent'
          AND JSON_EXTRACT_SCALAR(payload, '$.commits[0].message') IS NOT NULL
        GROUP BY repo_name, ci_tool
        HAVING ci_tool != 'other'
        ORDER BY push_count DESC
        LIMIT {limit}
        """.format(limit=self._config.query_limit)
        return self._safe_query("ci_patterns", sql)

    def query_framework_signals(self) -> BQQueryResult:
        """Query framework usage signals from issue/PR titles."""
        sql = """
        -- Expected: ~5-15 MB scan, cost < $0.001
        SELECT
            repo_name,
            CASE
                WHEN REGEXP_CONTAINS(
                    JSON_EXTRACT_SCALAR(payload, '$.issue.title'),
                    r'(?i)(flask|django|fastapi|tornado|starlette)')
                THEN REGEXP_EXTRACT(
                    LOWER(JSON_EXTRACT_SCALAR(payload, '$.issue.title')),
                    r'(flask|django|fastapi|tornado|starlette)')
                ELSE 'unknown'
            END AS framework,
            COUNT(*) AS mention_count
        FROM `githubarchive.day.20*`
        WHERE _TABLE_SUFFIX BETWEEN '240101' AND '240131'
          AND type = 'IssuesEvent'
          AND JSON_EXTRACT_SCALAR(payload, '$.action') = 'opened'
          AND REGEXP_CONTAINS(
              COALESCE(JSON_EXTRACT_SCALAR(payload, '$.issue.title'), ''),
              r'(?i)(flask|django|fastapi|tornado|starlette)')
        GROUP BY repo_name, framework
        HAVING framework != 'unknown'
        ORDER BY mention_count DESC
        LIMIT {limit}
        """.format(limit=self._config.query_limit)
        return self._safe_query("framework_signals", sql)

    def run_all_queries(self) -> List[BQQueryResult]:
        """Execute all 4 domain queries with full safety checks."""
        results = []
        for query_fn in [self.query_top_repos, self.query_language_trends,
                         self.query_ci_patterns, self.query_framework_signals]:
            result = query_fn()
            results.append(result)
            if result.error and "budget" in result.error.lower():
                logger.warning("[BigQuery] Budget exceeded, stopping further queries")
                break
        return results

    # ------------------------------------------------------------------
    # Safety flow
    # ------------------------------------------------------------------

    def _safe_query(self, query_name: str, sql: str) -> BQQueryResult:
        """Execute query with full 5-layer safety checks."""
        self._stats["queries_total"] += 1

        # Layer 5: Emergency stop (re-check)
        if self._config.emergency_stop_enabled:
            env_val = os.environ.get("BIGQUERY_ENABLED", "true").lower()
            if env_val == "false":
                return BQQueryResult(query_name=query_name,
                                     error="Disabled via BIGQUERY_ENABLED=false")

        if not self._enabled or not self._client:
            return BQQueryResult(query_name=query_name,
                                 error="BigQuery not enabled")

        # Layer 3: Monthly budget check
        self._load_cost_history()
        monthly = self._cost_history.get("monthly_total", 0.0)
        if monthly >= self._config.budget_monthly:
            self._stats["queries_refused"] += 1
            return BQQueryResult(query_name=query_name,
                                 error=f"Monthly budget exceeded: ${monthly:.4f} >= ${self._config.budget_monthly:.2f}")

        # Layer 4: Monthly alert
        if monthly >= self._config.cost_alert_threshold:
            logger.warning("[BigQuery] COST ALERT: monthly total $%.4f approaching limit $%.2f",
                           monthly, self._config.budget_monthly)

        # Layer 2: Session budget check
        if self._session_cost >= self._config.cost_budget_usd:
            self._stats["queries_refused"] += 1
            return BQQueryResult(query_name=query_name,
                                 error=f"Session budget exceeded: ${self._session_cost:.4f} >= ${self._config.cost_budget_usd:.2f}")

        # Check cache first (layer 6: optimization)
        cache_key = self._cache_key(sql)
        cached = self._check_cache(cache_key)
        if cached is not None:
            self._stats["queries_cached"] += 1
            return cached

        # Layer 1: Dry-run to estimate cost
        if self._config.dry_run_first:
            estimated_bytes = self._dry_run(sql)
            if estimated_bytes < 0:
                self._stats["errors"] += 1
                return BQQueryResult(query_name=query_name,
                                     error="Dry-run failed")

            estimated_cost = estimated_bytes * COST_PER_BYTE
            if estimated_cost > self._config.max_cost_per_query:
                self._stats["queries_refused"] += 1
                return BQQueryResult(
                    query_name=query_name,
                    error=f"Estimated cost ${estimated_cost:.6f} > per-query cap ${self._config.max_cost_per_query:.2f}",
                    bytes_processed=estimated_bytes,
                    cost_usd=estimated_cost,
                )

        # Execute real query with retry
        start = time.time()
        result = self._execute_with_retry(query_name, sql)
        result.duration_ms = (time.time() - start) * 1000

        if not result.error:
            # Update costs
            self._session_cost += result.cost_usd
            self._record_cost(query_name, sql, result.bytes_processed, result.cost_usd)
            self._stats["bytes_processed"] += result.bytes_processed
            self._stats["total_cost_usd"] += result.cost_usd
            # Cache the result
            self._query_cache[cache_key] = (time.time(), result)
        else:
            self._stats["errors"] += 1

        return result

    # ------------------------------------------------------------------
    # Dry run
    # ------------------------------------------------------------------

    def _make_job_config(self, **kwargs):
        """Create a BigQuery QueryJobConfig. Separated for testability."""
        return bq.QueryJobConfig(**kwargs)

    def _dry_run(self, sql: str) -> int:
        """Dry-run a query to estimate bytes. Returns -1 on error."""
        self._stats["dry_runs"] += 1
        try:
            job_config = self._make_job_config(
                dry_run=True,
                use_query_cache=False,
            )
            job = self._client.query(sql, job_config=job_config)
            return job.total_bytes_processed or 0
        except Exception as exc:
            logger.error("[BigQuery] Dry-run error: %s", exc)
            return -1

    # ------------------------------------------------------------------
    # Execute with retry
    # ------------------------------------------------------------------

    def _execute_with_retry(self, query_name: str, sql: str,
                            max_retries: int = 3) -> BQQueryResult:
        """Execute query with exponential backoff on transient errors."""
        last_error = ""
        for attempt in range(max_retries):
            try:
                job_config = self._make_job_config(
                    maximum_bytes_billed=self._config.max_bytes_billed,
                )
                job = self._client.query(sql, job_config=job_config)
                rows = list(job.result())
                bytes_processed = job.total_bytes_processed or 0
                cost = bytes_processed * COST_PER_BYTE

                result_rows = []
                for row in rows:
                    result_rows.append(dict(row))

                return BQQueryResult(
                    query_name=query_name,
                    rows=result_rows,
                    bytes_processed=bytes_processed,
                    cost_usd=cost,
                )
            except Exception as exc:
                last_error = str(exc)
                if self._is_transient(exc) and attempt < max_retries - 1:
                    wait = 2 ** attempt  # 1s, 2s, 4s
                    logger.warning("[BigQuery] Transient error (attempt %d/%d), "
                                   "retrying in %ds: %s",
                                   attempt + 1, max_retries, wait, exc)
                    time.sleep(wait)
                else:
                    break

        return BQQueryResult(query_name=query_name, error=last_error)

    @staticmethod
    def _is_transient(exc: Exception) -> bool:
        """Check if an exception is transient and retryable."""
        if gcp_exceptions is not None:
            transient_types = (
                gcp_exceptions.ServiceUnavailable,
                gcp_exceptions.TooManyRequests,
            )
            if isinstance(exc, transient_types):
                return True
        # Fallback: check error string for transient indicators
        err_str = str(exc).lower()
        return any(t in err_str for t in ("503", "429", "connectionerror", "connection reset"))

    # ------------------------------------------------------------------
    # Cache
    # ------------------------------------------------------------------

    @staticmethod
    def _cache_key(sql: str) -> str:
        return hashlib.sha256(sql.encode()).hexdigest()[:16]

    def _check_cache(self, key: str) -> Optional[BQQueryResult]:
        """Return cached result if within TTL."""
        if key not in self._query_cache:
            return None
        ts, result = self._query_cache[key]
        if time.time() - ts > self._config.cache_ttl_seconds:
            del self._query_cache[key]
            return None
        # Return a copy marked as cached
        cached = BQQueryResult(
            query_name=result.query_name,
            rows=result.rows,
            bytes_processed=result.bytes_processed,
            cost_usd=0.0,  # no cost for cached
            cached=True,
            duration_ms=0.0,
        )
        return cached

    # ------------------------------------------------------------------
    # Cost tracking
    # ------------------------------------------------------------------

    def _load_cost_history(self) -> None:
        """Load cost history from JSON file."""
        path = self._config.cost_history_path
        if not os.path.exists(path):
            self._cost_history = {"entries": [], "monthly_total": 0.0}
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                self._cost_history = json.load(f)
            # Cleanup old entries (>30 days)
            self._cleanup_old_entries()
        except (json.JSONDecodeError, IOError) as exc:
            logger.warning("[BigQuery] Failed to load cost history: %s", exc)
            self._cost_history = {"entries": [], "monthly_total": 0.0}

    def _save_cost_history(self) -> None:
        """Persist cost history to disk."""
        path = self._config.cost_history_path
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._cost_history, f, indent=2)
        except IOError as exc:
            logger.error("[BigQuery] Failed to save cost history: %s", exc)

    def _record_cost(self, query_name: str, sql: str,
                     bytes_processed: int, cost_usd: float) -> None:
        """Record a query cost entry and save."""
        today = time.strftime("%Y-%m-%d")
        entry = {
            "date": today,
            "query": query_name,
            "bytes": bytes_processed,
            "cost_usd": cost_usd,
        }
        entries = self._cost_history.get("entries", [])
        entries.append(entry)
        # Recalculate monthly total from current month entries
        current_month = time.strftime("%Y-%m")
        monthly = sum(
            e.get("cost_usd", 0.0) for e in entries
            if e.get("date", "").startswith(current_month)
        )
        self._cost_history["entries"] = entries
        self._cost_history["monthly_total"] = monthly
        self._save_cost_history()

    def _cleanup_old_entries(self) -> None:
        """Remove entries older than 30 days."""
        cutoff = time.strftime("%Y-%m-%d",
                               time.localtime(time.time() - 30 * 86400))
        entries = self._cost_history.get("entries", [])
        fresh = [e for e in entries if e.get("date", "") >= cutoff]
        if len(fresh) < len(entries):
            self._cost_history["entries"] = fresh
            # Recalculate monthly
            current_month = time.strftime("%Y-%m")
            self._cost_history["monthly_total"] = sum(
                e.get("cost_usd", 0.0) for e in fresh
                if e.get("date", "").startswith(current_month)
            )
