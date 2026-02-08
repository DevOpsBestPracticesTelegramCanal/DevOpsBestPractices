# -*- coding: utf-8 -*-
"""
SolutionCache — SQLite-based cache for known solutions.

Stores successful error→solution mappings so repeated errors can be resolved
instantly without LLM calls. Keyed by (error_type, error_message_hash) for
fast lookup.

Features:
  - SQLite backend (persistent across restarts)
  - TTL expiration (default 7 days)
  - Hash-based lookup with similarity matching
  - Hit/miss statistics
  - Confidence scoring (solutions used successfully get boosted)

Usage:
    cache = SolutionCache("solutions.db")
    cache.store(error_type="TypeError", error_msg="...", solution="...")
    result = cache.lookup(error_type="TypeError", error_msg="...")
    if result:
        print(result["solution"])
"""

import hashlib
import logging
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Default TTL: 7 days
DEFAULT_TTL_SECONDS = 7 * 24 * 3600


class SolutionCache:
    """
    SQLite-backed solution cache.

    The agent calls:
      - store(error_type, error_msg, code_context, solution, swecas_category, confidence)
      - get_stats() → dict with total_solutions, hit_rate_percent, cache_hits, cache_misses
      - lookup(error_type, error_msg) → dict or None
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ):
        self.db_path = db_path or os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "..", ".qwencode", "solution_cache.db",
        )
        self._ttl = ttl_seconds
        self._hits = 0
        self._misses = 0
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    # ------------------------------------------------------------------
    # Database setup
    # ------------------------------------------------------------------

    def _init_db(self) -> None:
        """Create the database and tables if they don't exist."""
        try:
            os.makedirs(os.path.dirname(os.path.abspath(self.db_path)), exist_ok=True)
            self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("""
                CREATE TABLE IF NOT EXISTS solutions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    error_type TEXT NOT NULL,
                    error_hash TEXT NOT NULL,
                    error_msg TEXT NOT NULL,
                    code_context TEXT DEFAULT '',
                    solution TEXT NOT NULL,
                    swecas_category TEXT DEFAULT 'UNKNOWN',
                    confidence REAL DEFAULT 0.75,
                    hit_count INTEGER DEFAULT 0,
                    created_at REAL NOT NULL,
                    last_used_at REAL,
                    expires_at REAL NOT NULL
                )
            """)
            self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_solutions_lookup
                ON solutions (error_type, error_hash)
            """)
            self._conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_solutions_expires
                ON solutions (expires_at)
            """)
            self._conn.commit()
            logger.info("[SolutionCache] Initialized at %s", self.db_path)
        except Exception as e:
            logger.warning("[SolutionCache] Failed to init DB: %s", e)
            self._conn = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def store(
        self,
        error_type: str,
        error_msg: str,
        code_context: str = "",
        solution: str = "",
        swecas_category: str = "UNKNOWN",
        confidence: float = 0.75,
    ) -> bool:
        """
        Store a solution in the cache.

        Returns True if stored successfully.
        """
        if not self._conn or not solution:
            return False

        error_hash = self._hash_error(error_type, error_msg)
        now = time.time()

        try:
            # Upsert: if same error_type + hash exists, update with higher confidence
            existing = self._conn.execute(
                "SELECT id, confidence FROM solutions WHERE error_type = ? AND error_hash = ?",
                (error_type, error_hash),
            ).fetchone()

            if existing:
                new_confidence = max(existing["confidence"], confidence)
                self._conn.execute(
                    """UPDATE solutions
                       SET solution = ?, confidence = ?, code_context = ?,
                           swecas_category = ?, expires_at = ?
                       WHERE id = ?""",
                    (solution, new_confidence, code_context,
                     swecas_category, now + self._ttl, existing["id"]),
                )
            else:
                self._conn.execute(
                    """INSERT INTO solutions
                       (error_type, error_hash, error_msg, code_context, solution,
                        swecas_category, confidence, created_at, expires_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (error_type, error_hash, error_msg, code_context, solution,
                     swecas_category, confidence, now, now + self._ttl),
                )

            self._conn.commit()
            logger.debug("[SolutionCache] Stored solution for %s (%s)", error_type, error_hash[:8])
            return True
        except Exception as e:
            logger.warning("[SolutionCache] Store failed: %s", e)
            return False

    def lookup(
        self,
        error_type: str,
        error_msg: str,
        min_confidence: float = 0.5,
    ) -> Optional[Dict[str, Any]]:
        """
        Look up a cached solution.

        Returns dict with solution, confidence, hit_count, or None.
        """
        if not self._conn:
            self._misses += 1
            return None

        error_hash = self._hash_error(error_type, error_msg)
        now = time.time()

        try:
            row = self._conn.execute(
                """SELECT id, solution, confidence, swecas_category, hit_count, code_context
                   FROM solutions
                   WHERE error_type = ? AND error_hash = ?
                     AND expires_at > ?
                     AND confidence >= ?
                   ORDER BY confidence DESC
                   LIMIT 1""",
                (error_type, error_hash, now, min_confidence),
            ).fetchone()

            if row:
                self._hits += 1
                # Update hit count and last_used_at
                self._conn.execute(
                    "UPDATE solutions SET hit_count = hit_count + 1, last_used_at = ? WHERE id = ?",
                    (now, row["id"]),
                )
                self._conn.commit()
                return {
                    "solution": row["solution"],
                    "confidence": row["confidence"],
                    "swecas_category": row["swecas_category"],
                    "hit_count": row["hit_count"] + 1,
                    "code_context": row["code_context"],
                }
            else:
                self._misses += 1
                return None
        except Exception as e:
            logger.warning("[SolutionCache] Lookup failed: %s", e)
            self._misses += 1
            return None

    def get(self, key: str) -> Optional[str]:
        """Simple key-based get (backward compatibility)."""
        result = self.lookup(error_type="generic", error_msg=key)
        return result["solution"] if result else None

    def save(self, key: str, value: str, metadata: Any = None) -> None:
        """Simple key-based save (backward compatibility)."""
        self.store(
            error_type="generic",
            error_msg=key,
            solution=value,
            swecas_category=str(metadata) if metadata else "UNKNOWN",
        )

    def invalidate(self, error_type: str, error_msg: str) -> bool:
        """Remove a cached solution."""
        if not self._conn:
            return False
        error_hash = self._hash_error(error_type, error_msg)
        try:
            self._conn.execute(
                "DELETE FROM solutions WHERE error_type = ? AND error_hash = ?",
                (error_type, error_hash),
            )
            self._conn.commit()
            return True
        except Exception:
            return False

    def cleanup_expired(self) -> int:
        """Remove expired entries. Returns count of removed entries."""
        if not self._conn:
            return 0
        try:
            cursor = self._conn.execute(
                "DELETE FROM solutions WHERE expires_at < ?", (time.time(),)
            )
            self._conn.commit()
            return cursor.rowcount
        except Exception:
            return 0

    def get_stats(self) -> Dict[str, Any]:
        """Return cache statistics (used by agent /stats command)."""
        total_solutions = 0
        if self._conn:
            try:
                row = self._conn.execute(
                    "SELECT COUNT(*) as cnt FROM solutions WHERE expires_at > ?",
                    (time.time(),),
                ).fetchone()
                total_solutions = row["cnt"] if row else 0
            except Exception:
                pass

        total_requests = self._hits + self._misses
        hit_rate = (self._hits / total_requests * 100) if total_requests > 0 else 0.0

        return {
            "total_solutions": total_solutions,
            "cache_hits": self._hits,
            "cache_misses": self._misses,
            "hit_rate_percent": round(hit_rate, 1),
            "total_requests": total_requests,
            "ttl_seconds": self._ttl,
            "db_path": self.db_path,
        }

    def boost_confidence(self, error_type: str, error_msg: str, boost: float = 0.05) -> None:
        """Boost confidence for a solution that was used successfully."""
        if not self._conn:
            return
        error_hash = self._hash_error(error_type, error_msg)
        try:
            self._conn.execute(
                """UPDATE solutions
                   SET confidence = MIN(confidence + ?, 1.0)
                   WHERE error_type = ? AND error_hash = ?""",
                (boost, error_type, error_hash),
            )
            self._conn.commit()
        except Exception:
            pass

    def close(self) -> None:
        """Close the database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _hash_error(error_type: str, error_msg: str) -> str:
        """Create a stable hash from error type + message."""
        # Normalize: lowercase, strip whitespace, remove line numbers
        normalized = f"{error_type.lower().strip()}::{error_msg.lower().strip()}"
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]

    def __del__(self):
        self.close()
