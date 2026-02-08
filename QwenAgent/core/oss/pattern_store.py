# -*- coding: utf-8 -*-
"""
PatternStore — SQLite backend for OSS repo metadata and extracted patterns.

Tables:
  repos          – repository metadata (stars, topics, license, etc.)
  patterns       – extracted patterns (framework, testing, ci_cd, …)
  pattern_stats  – aggregated per-pattern statistics (materialized)
"""

import json
import logging
import os
import sqlite3
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RepoRecord:
    full_name: str
    stars: int = 0
    forks: int = 0
    description: str = ""
    topics: List[str] = field(default_factory=list)
    license: str = ""
    architecture: str = ""
    collected_at: float = 0.0
    analyzed_at: float = 0.0
    id: Optional[int] = None


@dataclass
class PatternRecord:
    repo_name: str
    category: str          # framework, testing, ci_cd, docker, …
    pattern_name: str      # flask, pytest, github_actions, …
    confidence: float = 1.0
    evidence: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)
    id: Optional[int] = None
    repo_id: Optional[int] = None


# ---------------------------------------------------------------------------
# PatternStore
# ---------------------------------------------------------------------------

class PatternStore:
    """SQLite-backed store for repos and their extracted patterns."""

    DEFAULT_PATH = os.path.join(".qwencode", "oss_patterns.db")

    def __init__(self, db_path: Optional[str] = None):
        self._db_path = db_path or self.DEFAULT_PATH
        self._is_memory = self._db_path == ":memory:"

        # Ensure parent dir exists for file-based DBs
        if not self._is_memory:
            os.makedirs(os.path.dirname(self._db_path) or ".", exist_ok=True)

        # Persistent connection for :memory: DBs
        if self._is_memory:
            self._persistent_conn = sqlite3.connect(":memory:")
        else:
            self._persistent_conn = None

        self._init_db()

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------

    def _get_conn(self) -> sqlite3.Connection:
        if self._persistent_conn:
            return self._persistent_conn
        return sqlite3.connect(self._db_path)

    def _close_conn(self, conn: sqlite3.Connection) -> None:
        if conn is not self._persistent_conn:
            conn.close()

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        conn = self._get_conn()
        try:
            if not self._is_memory:
                conn.execute("PRAGMA journal_mode=WAL")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS repos (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    full_name TEXT UNIQUE NOT NULL,
                    stars INTEGER DEFAULT 0,
                    forks INTEGER DEFAULT 0,
                    description TEXT DEFAULT '',
                    topics TEXT DEFAULT '[]',
                    license TEXT DEFAULT '',
                    architecture TEXT DEFAULT '',
                    collected_at REAL DEFAULT 0,
                    analyzed_at REAL DEFAULT 0
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS patterns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    repo_id INTEGER NOT NULL REFERENCES repos(id),
                    category TEXT NOT NULL,
                    pattern_name TEXT NOT NULL,
                    confidence REAL DEFAULT 1.0,
                    evidence TEXT DEFAULT '',
                    metadata TEXT DEFAULT '{}',
                    UNIQUE(repo_id, category, pattern_name)
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS pattern_stats (
                    pattern_name TEXT NOT NULL,
                    category TEXT NOT NULL,
                    repo_count INTEGER DEFAULT 0,
                    avg_stars REAL DEFAULT 0,
                    top_repo TEXT DEFAULT '',
                    updated_at REAL DEFAULT 0,
                    PRIMARY KEY(pattern_name, category)
                )
            """)

            # Indices
            conn.execute("CREATE INDEX IF NOT EXISTS idx_patterns_category ON patterns(category)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_patterns_name ON patterns(pattern_name)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_repos_stars ON repos(stars DESC)")

            conn.commit()
        finally:
            self._close_conn(conn)

    # ------------------------------------------------------------------
    # Repos CRUD
    # ------------------------------------------------------------------

    def save_repo(self, repo: RepoRecord) -> int:
        """Insert or update a repo. Returns repo id."""
        conn = self._get_conn()
        try:
            conn.execute("""
                INSERT INTO repos (full_name, stars, forks, description, topics,
                                   license, architecture, collected_at, analyzed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(full_name) DO UPDATE SET
                    stars=excluded.stars, forks=excluded.forks,
                    description=excluded.description, topics=excluded.topics,
                    license=excluded.license, architecture=excluded.architecture,
                    collected_at=excluded.collected_at, analyzed_at=excluded.analyzed_at
            """, (
                repo.full_name, repo.stars, repo.forks, repo.description,
                json.dumps(repo.topics), repo.license, repo.architecture,
                repo.collected_at or time.time(), repo.analyzed_at,
            ))
            conn.commit()
            row = conn.execute(
                "SELECT id FROM repos WHERE full_name = ?", (repo.full_name,)
            ).fetchone()
            return row[0] if row else 0
        finally:
            self._close_conn(conn)

    def get_repo(self, full_name: str) -> Optional[RepoRecord]:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM repos WHERE full_name = ?", (full_name,)
            ).fetchone()
            if not row:
                return None
            return self._row_to_repo(row)
        finally:
            self._close_conn(conn)

    def get_repo_by_id(self, repo_id: int) -> Optional[RepoRecord]:
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT * FROM repos WHERE id = ?", (repo_id,)
            ).fetchone()
            if not row:
                return None
            return self._row_to_repo(row)
        finally:
            self._close_conn(conn)

    def list_repos(self, limit: int = 100, offset: int = 0) -> List[RepoRecord]:
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT * FROM repos ORDER BY stars DESC LIMIT ? OFFSET ?",
                (limit, offset)
            ).fetchall()
            return [self._row_to_repo(r) for r in rows]
        finally:
            self._close_conn(conn)

    def count_repos(self) -> int:
        conn = self._get_conn()
        try:
            return conn.execute("SELECT COUNT(*) FROM repos").fetchone()[0]
        finally:
            self._close_conn(conn)

    # ------------------------------------------------------------------
    # Patterns CRUD
    # ------------------------------------------------------------------

    def save_patterns(self, patterns: List[PatternRecord]) -> int:
        """Save patterns for a repo. Returns count saved."""
        if not patterns:
            return 0
        conn = self._get_conn()
        saved = 0
        try:
            for p in patterns:
                # Resolve repo_id from repo_name if not set
                repo_id = p.repo_id
                if not repo_id:
                    row = conn.execute(
                        "SELECT id FROM repos WHERE full_name = ?", (p.repo_name,)
                    ).fetchone()
                    if not row:
                        logger.warning("[PatternStore] Repo %s not found, skipping pattern", p.repo_name)
                        continue
                    repo_id = row[0]

                conn.execute("""
                    INSERT INTO patterns (repo_id, category, pattern_name, confidence, evidence, metadata)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(repo_id, category, pattern_name) DO UPDATE SET
                        confidence=excluded.confidence, evidence=excluded.evidence,
                        metadata=excluded.metadata
                """, (
                    repo_id, p.category, p.pattern_name,
                    p.confidence, p.evidence, json.dumps(p.metadata),
                ))
                saved += 1
            conn.commit()
            return saved
        finally:
            self._close_conn(conn)

    def get_patterns_for_repo(self, full_name: str) -> List[PatternRecord]:
        conn = self._get_conn()
        try:
            rows = conn.execute("""
                SELECT p.*, r.full_name FROM patterns p
                JOIN repos r ON p.repo_id = r.id
                WHERE r.full_name = ?
                ORDER BY p.category, p.pattern_name
            """, (full_name,)).fetchall()
            return [self._row_to_pattern(r) for r in rows]
        finally:
            self._close_conn(conn)

    def count_patterns(self) -> int:
        conn = self._get_conn()
        try:
            return conn.execute("SELECT COUNT(*) FROM patterns").fetchone()[0]
        finally:
            self._close_conn(conn)

    # ------------------------------------------------------------------
    # Aggregation / Statistics
    # ------------------------------------------------------------------

    def refresh_pattern_stats(self) -> int:
        """Recompute pattern_stats from raw data. Returns count of stat rows."""
        conn = self._get_conn()
        try:
            conn.execute("DELETE FROM pattern_stats")
            conn.execute("""
                INSERT INTO pattern_stats (pattern_name, category, repo_count, avg_stars, top_repo, updated_at)
                SELECT
                    p.pattern_name,
                    p.category,
                    COUNT(DISTINCT p.repo_id) AS repo_count,
                    AVG(r.stars) AS avg_stars,
                    (SELECT r2.full_name FROM repos r2
                     JOIN patterns p2 ON p2.repo_id = r2.id
                     WHERE p2.pattern_name = p.pattern_name AND p2.category = p.category
                     ORDER BY r2.stars DESC LIMIT 1) AS top_repo,
                    ? AS updated_at
                FROM patterns p
                JOIN repos r ON p.repo_id = r.id
                GROUP BY p.pattern_name, p.category
            """, (time.time(),))
            conn.commit()
            count = conn.execute("SELECT COUNT(*) FROM pattern_stats").fetchone()[0]
            return count
        finally:
            self._close_conn(conn)

    def get_top_patterns(self, category: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
        """Get most popular patterns, optionally filtered by category."""
        conn = self._get_conn()
        try:
            if category:
                rows = conn.execute("""
                    SELECT * FROM pattern_stats
                    WHERE category = ?
                    ORDER BY repo_count DESC
                    LIMIT ?
                """, (category, limit)).fetchall()
            else:
                rows = conn.execute("""
                    SELECT * FROM pattern_stats
                    ORDER BY repo_count DESC
                    LIMIT ?
                """, (limit,)).fetchall()
            return [self._stat_row_to_dict(r) for r in rows]
        finally:
            self._close_conn(conn)

    def get_categories(self) -> List[str]:
        """Return all distinct pattern categories."""
        conn = self._get_conn()
        try:
            rows = conn.execute(
                "SELECT DISTINCT category FROM patterns ORDER BY category"
            ).fetchall()
            return [r[0] for r in rows]
        finally:
            self._close_conn(conn)

    def query_repos_by_pattern(self, pattern_name: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Find repos that use a given pattern, sorted by stars."""
        conn = self._get_conn()
        try:
            rows = conn.execute("""
                SELECT r.full_name, r.stars, r.description, p.confidence, p.evidence
                FROM patterns p
                JOIN repos r ON p.repo_id = r.id
                WHERE p.pattern_name = ?
                ORDER BY r.stars DESC
                LIMIT ?
            """, (pattern_name, limit)).fetchall()
            return [
                {"full_name": r[0], "stars": r[1], "description": r[2],
                 "confidence": r[3], "evidence": r[4]}
                for r in rows
            ]
        finally:
            self._close_conn(conn)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        conn = self._get_conn()
        try:
            total_repos = conn.execute("SELECT COUNT(*) FROM repos").fetchone()[0]
            total_patterns = conn.execute("SELECT COUNT(*) FROM patterns").fetchone()[0]
            total_stats = conn.execute("SELECT COUNT(*) FROM pattern_stats").fetchone()[0]
            analyzed = conn.execute(
                "SELECT COUNT(*) FROM repos WHERE analyzed_at > 0"
            ).fetchone()[0]
            categories = conn.execute(
                "SELECT DISTINCT category FROM patterns"
            ).fetchall()
            return {
                "total_repos": total_repos,
                "analyzed_repos": analyzed,
                "total_patterns": total_patterns,
                "total_pattern_stats": total_stats,
                "categories": [c[0] for c in categories],
            }
        finally:
            self._close_conn(conn)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _row_to_repo(row) -> RepoRecord:
        return RepoRecord(
            id=row[0],
            full_name=row[1],
            stars=row[2],
            forks=row[3],
            description=row[4],
            topics=json.loads(row[5]) if row[5] else [],
            license=row[6],
            architecture=row[7],
            collected_at=row[8],
            analyzed_at=row[9],
        )

    @staticmethod
    def _row_to_pattern(row) -> PatternRecord:
        # row: id, repo_id, category, pattern_name, confidence, evidence, metadata, full_name
        return PatternRecord(
            id=row[0],
            repo_id=row[1],
            category=row[2],
            pattern_name=row[3],
            confidence=row[4],
            evidence=row[5],
            metadata=json.loads(row[6]) if row[6] else {},
            repo_name=row[7] if len(row) > 7 else "",
        )

    @staticmethod
    def _stat_row_to_dict(row) -> Dict[str, Any]:
        return {
            "pattern_name": row[0],
            "category": row[1],
            "repo_count": row[2],
            "avg_stars": row[3],
            "top_repo": row[4],
            "updated_at": row[5],
        }
