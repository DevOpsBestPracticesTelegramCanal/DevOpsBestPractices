# -*- coding: utf-8 -*-
"""
OSS Consciousness — Collective intelligence from open-source repositories.

Analyzes top Python GitHub repos to extract architectural patterns,
framework usage, and best practices.
"""

from core.oss.pattern_store import PatternStore, RepoRecord, PatternRecord
from core.oss.repo_analyzer import RepoAnalyzer, RepoPattern
from core.oss.github_collector import GitHubCollector, RepoMeta
from core.oss.oss_engine import OSSEngine, OSSInsight

# BigQuery integration (optional, requires google-cloud-bigquery)
try:
    from core.oss.bigquery_collector import BigQueryCollector, BigQueryConfig, BQQueryResult
    from core.oss.bigquery_sync import BigQuerySync, SyncConfig, SyncResult
    HAS_BIGQUERY = True
except ImportError:
    HAS_BIGQUERY = False

__all__ = [
    "PatternStore", "RepoRecord", "PatternRecord",
    "RepoAnalyzer", "RepoPattern",
    "GitHubCollector", "RepoMeta",
    "OSSEngine", "OSSInsight",
    "HAS_BIGQUERY",
]
