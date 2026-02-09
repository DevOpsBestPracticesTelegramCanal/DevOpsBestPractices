# -*- coding: utf-8 -*-
"""
BigQuerySync — Background daemon that periodically syncs BigQuery data
into the local PatternStore.

Runs as a daemon thread with configurable interval, thread-safe via Lock.
All discovered data flows into PatternStore.save_repo() / save_patterns().
"""

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.oss.bigquery_collector import BigQueryCollector, BigQueryConfig, BQQueryResult
from core.oss.pattern_store import PatternStore, RepoRecord, PatternRecord

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SyncConfig:
    """Configuration for BigQuery sync daemon."""
    interval_seconds: int = 3600     # 1 hour between syncs
    enabled: bool = True
    max_repos_per_sync: int = 200
    bq_config: BigQueryConfig = field(default_factory=BigQueryConfig)


@dataclass
class SyncResult:
    """Result of a single sync run."""
    repos_added: int = 0
    patterns_added: int = 0
    queries_run: int = 0
    errors: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    total_cost_usd: float = 0.0

    @property
    def success(self) -> bool:
        return len(self.errors) == 0


# ---------------------------------------------------------------------------
# Extraction helpers
# ---------------------------------------------------------------------------

def extract_repos_from_top(result: BQQueryResult) -> List[RepoRecord]:
    """Convert top_repos BQ result to RepoRecords."""
    repos = []
    for row in result.rows:
        name = row.get("repo_name", "")
        if not name or "/" not in name:
            continue
        repos.append(RepoRecord(
            full_name=name,
            stars=row.get("event_count", 0),
            description=f"BigQuery: {row.get('event_count', 0)} watch events",
            collected_at=time.time(),
        ))
    return repos


def extract_patterns_from_ci(result: BQQueryResult) -> List[PatternRecord]:
    """Convert ci_patterns BQ result to PatternRecords."""
    patterns = []
    for row in result.rows:
        repo_name = row.get("repo_name", "")
        ci_tool = row.get("ci_tool", "")
        if not repo_name or not ci_tool:
            continue
        count = row.get("push_count", 0)
        patterns.append(PatternRecord(
            repo_name=repo_name,
            category="ci_cd",
            pattern_name=ci_tool,
            confidence=min(1.0, count / 100.0),
            evidence=f"BigQuery: {count} push events mentioning {ci_tool}",
            metadata={"source": "bigquery", "push_count": count},
        ))
    return patterns


def extract_patterns_from_frameworks(result: BQQueryResult) -> List[PatternRecord]:
    """Convert framework_signals BQ result to PatternRecords."""
    patterns = []
    for row in result.rows:
        repo_name = row.get("repo_name", "")
        framework = row.get("framework", "")
        if not repo_name or not framework:
            continue
        count = row.get("mention_count", 0)
        patterns.append(PatternRecord(
            repo_name=repo_name,
            category="framework",
            pattern_name=framework,
            confidence=min(1.0, count / 50.0),
            evidence=f"BigQuery: {count} issue mentions of {framework}",
            metadata={"source": "bigquery", "mention_count": count},
        ))
    return patterns


def extract_patterns_from_languages(result: BQQueryResult) -> List[PatternRecord]:
    """Convert language_trends BQ result to PatternRecords."""
    patterns = []
    for row in result.rows:
        language = row.get("language", "")
        if not language:
            continue
        count = row.get("pr_count", 0)
        patterns.append(PatternRecord(
            repo_name="__aggregate__",
            category="language",
            pattern_name=language.lower(),
            confidence=1.0,
            evidence=f"BigQuery: {count} PRs in {language}",
            metadata={"source": "bigquery", "pr_count": count},
        ))
    return patterns


# ---------------------------------------------------------------------------
# BigQuerySync
# ---------------------------------------------------------------------------

class BigQuerySync:
    """Background daemon that syncs BigQuery data into PatternStore."""

    def __init__(self, store: PatternStore,
                 config: Optional[SyncConfig] = None):
        self._store = store
        self._config = config or SyncConfig()
        self._collector = BigQueryCollector(self._config.bq_config)
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._last_sync: Optional[SyncResult] = None
        self._sync_count = 0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._config.enabled and self._collector.enabled

    @property
    def running(self) -> bool:
        return self._running

    @property
    def last_sync(self) -> Optional[SyncResult]:
        with self._lock:
            return self._last_sync

    def get_stats(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "enabled": self.enabled,
                "running": self._running,
                "sync_count": self._sync_count,
                "last_sync": {
                    "repos_added": self._last_sync.repos_added,
                    "patterns_added": self._last_sync.patterns_added,
                    "duration_seconds": self._last_sync.duration_seconds,
                    "cost_usd": self._last_sync.total_cost_usd,
                    "success": self._last_sync.success,
                } if self._last_sync else None,
                "collector": self._collector.get_stats(),
            }

    def sync_once(self) -> SyncResult:
        """Run a single sync cycle. Thread-safe."""
        with self._lock:
            return self._do_sync()

    def start(self) -> bool:
        """Start background sync daemon thread."""
        if not self.enabled:
            logger.info("[BigQuerySync] Not enabled, skipping start")
            return False
        if self._running:
            logger.info("[BigQuerySync] Already running")
            return True

        self._running = True
        self._thread = threading.Thread(
            target=self._daemon_loop,
            name="bigquery-sync",
            daemon=True,
        )
        self._thread.start()
        logger.info("[BigQuerySync] Daemon started (interval=%ds)",
                    self._config.interval_seconds)
        return True

    def stop(self) -> None:
        """Stop the background daemon."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._thread = None
        logger.info("[BigQuerySync] Daemon stopped")

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _daemon_loop(self) -> None:
        """Main daemon loop."""
        while self._running:
            try:
                with self._lock:
                    self._do_sync()
            except Exception as exc:
                logger.error("[BigQuerySync] Sync error: %s", exc)

            # Sleep in small increments so stop() is responsive
            for _ in range(self._config.interval_seconds):
                if not self._running:
                    break
                time.sleep(1)

    def _do_sync(self) -> SyncResult:
        """Execute one full sync cycle."""
        start = time.time()
        result = SyncResult()

        if not self._collector.enabled:
            result.errors.append("BigQuery collector not enabled")
            self._last_sync = result
            return result

        # Run all queries
        bq_results = self._collector.run_all_queries()
        result.queries_run = len(bq_results)

        for bq_result in bq_results:
            if bq_result.error:
                result.errors.append(f"{bq_result.query_name}: {bq_result.error}")
                continue
            result.total_cost_usd += bq_result.cost_usd

        # Extract and save repos from top_repos
        top_result = next((r for r in bq_results if r.query_name == "top_repos"
                           and not r.error), None)
        if top_result:
            repos = extract_repos_from_top(top_result)
            for repo in repos[:self._config.max_repos_per_sync]:
                try:
                    self._store.save_repo(repo)
                    result.repos_added += 1
                except Exception as exc:
                    logger.warning("[BigQuerySync] Failed to save repo %s: %s",
                                   repo.full_name, exc)

        # Extract and save patterns
        all_patterns: List[PatternRecord] = []

        ci_result = next((r for r in bq_results if r.query_name == "ci_patterns"
                          and not r.error), None)
        if ci_result:
            all_patterns.extend(extract_patterns_from_ci(ci_result))

        fw_result = next((r for r in bq_results if r.query_name == "framework_signals"
                          and not r.error), None)
        if fw_result:
            all_patterns.extend(extract_patterns_from_frameworks(fw_result))

        lang_result = next((r for r in bq_results if r.query_name == "language_trends"
                            and not r.error), None)
        if lang_result:
            all_patterns.extend(extract_patterns_from_languages(lang_result))

        if all_patterns:
            try:
                saved = self._store.save_patterns(all_patterns)
                result.patterns_added = saved
            except Exception as exc:
                result.errors.append(f"save_patterns: {exc}")

        result.duration_seconds = time.time() - start
        self._last_sync = result
        self._sync_count += 1

        logger.info("[BigQuerySync] Sync #%d complete: %d repos, %d patterns, "
                    "$%.6f, %.1fs",
                    self._sync_count, result.repos_added, result.patterns_added,
                    result.total_cost_usd, result.duration_seconds)
        return result
