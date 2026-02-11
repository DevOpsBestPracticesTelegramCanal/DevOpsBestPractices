"""
Week 13: Outcome Feedback Loop

Unified outcome tracker that records every pipeline run with full context
(task type, risk level, validation profile, rules passed/failed, scores, timing).

Provides analytics:
- Per-profile effectiveness (avg score, time, success rate)
- Per-rule catch rate (how often each rule fails, avg score impact)
- Per-task-type outcomes
- Profile suggestion based on historical data
- Learning summary across all feedback layers

Storage: SQLite with WAL mode (same pattern as SolutionCache).
"""

import hashlib
import logging
import sqlite3
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DEFAULT_DB = ":memory:"
_DEFAULT_TTL = 30 * 86400  # 30 days


@dataclass
class OutcomeRecord:
    """Full context of a single pipeline run."""

    # Identity
    query_hash: str = ""
    timestamp: float = field(default_factory=time.time)

    # Task classification (from Week 11)
    task_type: str = "general"          # TaskType.value
    risk_level: str = "medium"          # RiskLevel.value
    validation_profile: str = "balanced"  # ValidationProfile.value
    complexity: str = "MODERATE"

    # Pipeline results
    n_candidates: int = 1
    best_score: float = 0.0
    all_passed: bool = False
    generation_time: float = 0.0
    validation_time: float = 0.0
    total_time: float = 0.0

    # Rule details (comma-separated names)
    rules_run: str = ""
    rules_passed: str = ""
    rules_failed: str = ""
    n_rules_run: int = 0
    n_rules_passed: int = 0
    n_rules_failed: int = 0

    # SWECAS context
    swecas_code: Optional[int] = None


def _query_hash(query: str) -> str:
    """Short hash for grouping similar queries."""
    return hashlib.sha256(query.encode("utf-8", errors="replace")).hexdigest()[:12]


class OutcomeTracker:
    """
    SQLite-backed pipeline outcome tracker.

    Records every pipeline run and provides analytics for
    improving future task classification and validation.
    """

    def __init__(self, db_path: str = _DEFAULT_DB, ttl: int = _DEFAULT_TTL):
        self._db_path = db_path
        self._ttl = ttl
        self._conn: Optional[sqlite3.Connection] = None
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is not None:
            return self._conn
        conn = sqlite3.connect(self._db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        if self._db_path == ":memory:":
            self._conn = conn  # persistent for in-memory
        return conn

    def _init_db(self) -> None:
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS outcomes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query_hash TEXT NOT NULL,
                timestamp REAL NOT NULL,
                task_type TEXT NOT NULL,
                risk_level TEXT NOT NULL,
                validation_profile TEXT NOT NULL,
                complexity TEXT NOT NULL,
                n_candidates INTEGER DEFAULT 1,
                best_score REAL DEFAULT 0.0,
                all_passed INTEGER DEFAULT 0,
                generation_time REAL DEFAULT 0.0,
                validation_time REAL DEFAULT 0.0,
                total_time REAL DEFAULT 0.0,
                rules_run TEXT DEFAULT '',
                rules_passed TEXT DEFAULT '',
                rules_failed TEXT DEFAULT '',
                n_rules_run INTEGER DEFAULT 0,
                n_rules_passed INTEGER DEFAULT 0,
                n_rules_failed INTEGER DEFAULT 0,
                swecas_code INTEGER
            );

            CREATE INDEX IF NOT EXISTS idx_outcomes_profile
                ON outcomes(validation_profile);
            CREATE INDEX IF NOT EXISTS idx_outcomes_task_type
                ON outcomes(task_type);
            CREATE INDEX IF NOT EXISTS idx_outcomes_timestamp
                ON outcomes(timestamp);
        """)
        conn.commit()

    # ------------------------------------------------------------------
    # Record
    # ------------------------------------------------------------------

    def record(self, outcome: OutcomeRecord) -> int:
        """Store a pipeline outcome. Returns the row ID."""
        conn = self._get_conn()
        cur = conn.execute(
            """INSERT INTO outcomes (
                query_hash, timestamp, task_type, risk_level,
                validation_profile, complexity, n_candidates,
                best_score, all_passed,
                generation_time, validation_time, total_time,
                rules_run, rules_passed, rules_failed,
                n_rules_run, n_rules_passed, n_rules_failed,
                swecas_code
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                outcome.query_hash,
                outcome.timestamp,
                outcome.task_type,
                outcome.risk_level,
                outcome.validation_profile,
                outcome.complexity,
                outcome.n_candidates,
                outcome.best_score,
                1 if outcome.all_passed else 0,
                outcome.generation_time,
                outcome.validation_time,
                outcome.total_time,
                outcome.rules_run,
                outcome.rules_passed,
                outcome.rules_failed,
                outcome.n_rules_run,
                outcome.n_rules_passed,
                outcome.n_rules_failed,
                outcome.swecas_code,
            ),
        )
        conn.commit()
        return cur.lastrowid

    # ------------------------------------------------------------------
    # Analytics
    # ------------------------------------------------------------------

    def get_profile_stats(self) -> Dict[str, Dict[str, Any]]:
        """Per-profile effectiveness: avg score, time, success rate."""
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT
                validation_profile,
                COUNT(*) as count,
                AVG(best_score) as avg_score,
                AVG(total_time) as avg_time,
                AVG(validation_time) as avg_val_time,
                SUM(CASE WHEN all_passed = 1 THEN 1 ELSE 0 END) as pass_count,
                AVG(n_rules_run) as avg_rules
            FROM outcomes
            GROUP BY validation_profile
        """).fetchall()

        result = {}
        for r in rows:
            count = r["count"]
            result[r["validation_profile"]] = {
                "count": count,
                "avg_score": round(r["avg_score"], 4),
                "avg_time": round(r["avg_time"], 3),
                "avg_validation_time": round(r["avg_val_time"], 3),
                "success_rate": round(r["pass_count"] / count, 4) if count else 0.0,
                "avg_rules": round(r["avg_rules"], 1),
            }
        return result

    def get_rule_effectiveness(self) -> Dict[str, Dict[str, Any]]:
        """Per-rule: how often it runs, passes, fails."""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT rules_run, rules_passed, rules_failed FROM outcomes"
        ).fetchall()

        rule_stats: Dict[str, Dict[str, int]] = {}

        for row in rows:
            for name in (row["rules_run"] or "").split(","):
                name = name.strip()
                if not name:
                    continue
                if name not in rule_stats:
                    rule_stats[name] = {"run": 0, "passed": 0, "failed": 0}
                rule_stats[name]["run"] += 1

            for name in (row["rules_passed"] or "").split(","):
                name = name.strip()
                if name and name in rule_stats:
                    rule_stats[name]["passed"] += 1

            for name in (row["rules_failed"] or "").split(","):
                name = name.strip()
                if name and name in rule_stats:
                    rule_stats[name]["failed"] += 1

        result = {}
        for name, stats in rule_stats.items():
            run = stats["run"]
            result[name] = {
                "times_run": run,
                "times_passed": stats["passed"],
                "times_failed": stats["failed"],
                "fail_rate": round(stats["failed"] / run, 4) if run else 0.0,
            }
        return result

    def get_task_type_stats(self) -> Dict[str, Dict[str, Any]]:
        """Per-task-type outcomes."""
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT
                task_type,
                COUNT(*) as count,
                AVG(best_score) as avg_score,
                AVG(total_time) as avg_time,
                SUM(CASE WHEN all_passed = 1 THEN 1 ELSE 0 END) as pass_count
            FROM outcomes
            GROUP BY task_type
        """).fetchall()

        result = {}
        for r in rows:
            count = r["count"]
            result[r["task_type"]] = {
                "count": count,
                "avg_score": round(r["avg_score"], 4),
                "avg_time": round(r["avg_time"], 3),
                "success_rate": round(r["pass_count"] / count, 4) if count else 0.0,
            }
        return result

    def suggest_profile(self, task_type: str, complexity: str) -> Optional[str]:
        """Suggest the best validation profile based on historical outcomes.

        Returns the profile with the highest avg_score for similar tasks,
        or None if insufficient data (< 3 outcomes).
        """
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT
                validation_profile,
                COUNT(*) as count,
                AVG(best_score) as avg_score,
                AVG(total_time) as avg_time
            FROM outcomes
            WHERE task_type = ? AND complexity = ?
            GROUP BY validation_profile
            HAVING count >= 3
            ORDER BY avg_score DESC
            LIMIT 1
        """, (task_type, complexity)).fetchall()

        if rows:
            return rows[0]["validation_profile"]
        return None

    def get_risk_accuracy(self) -> Dict[str, Dict[str, Any]]:
        """How well risk levels predict actual outcomes.

        High-risk tasks should have lower scores (harder problems),
        low-risk tasks should have higher scores (easier problems).
        """
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT
                risk_level,
                COUNT(*) as count,
                AVG(best_score) as avg_score,
                SUM(CASE WHEN all_passed = 1 THEN 1 ELSE 0 END) as pass_count,
                AVG(n_rules_failed) as avg_failures
            FROM outcomes
            GROUP BY risk_level
        """).fetchall()

        result = {}
        for r in rows:
            count = r["count"]
            result[r["risk_level"]] = {
                "count": count,
                "avg_score": round(r["avg_score"], 4),
                "success_rate": round(r["pass_count"] / count, 4) if count else 0.0,
                "avg_rule_failures": round(r["avg_failures"], 2),
            }
        return result

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def cleanup_old(self, max_age_seconds: Optional[int] = None) -> int:
        """Remove outcomes older than TTL. Returns count deleted."""
        ttl = max_age_seconds if max_age_seconds is not None else self._ttl
        cutoff = time.time() - ttl
        conn = self._get_conn()
        cur = conn.execute(
            "DELETE FROM outcomes WHERE timestamp < ?", (cutoff,)
        )
        conn.commit()
        return cur.rowcount

    def get_stats(self) -> Dict[str, Any]:
        """Overall tracker statistics."""
        conn = self._get_conn()
        row = conn.execute("""
            SELECT
                COUNT(*) as total,
                AVG(best_score) as avg_score,
                AVG(total_time) as avg_time,
                SUM(CASE WHEN all_passed = 1 THEN 1 ELSE 0 END) as total_passed,
                MIN(timestamp) as oldest,
                MAX(timestamp) as newest
            FROM outcomes
        """).fetchone()

        total = row["total"] or 0
        return {
            "total_outcomes": total,
            "avg_score": round(row["avg_score"] or 0, 4),
            "avg_time": round(row["avg_time"] or 0, 3),
            "success_rate": round((row["total_passed"] or 0) / total, 4) if total else 0.0,
            "oldest_timestamp": row["oldest"],
            "newest_timestamp": row["newest"],
            "ttl_days": self._ttl // 86400,
            "db_path": self._db_path,
        }

    def get_total_outcomes(self) -> int:
        """Quick count of total stored outcomes."""
        conn = self._get_conn()
        row = conn.execute("SELECT COUNT(*) as c FROM outcomes").fetchone()
        return row["c"]

    def get_profile_confidence(self, task_type: str, complexity: str) -> Dict[str, Any]:
        """How confident is the profile suggestion for this task_type+complexity?

        Returns a dict with:
        - suggested_profile: str or None
        - total_outcomes: how many matching outcomes exist
        - confidence: 0.0-1.0 based on sample size and score variance
        - avg_score: average score of best profile
        - alternatives: other profiles tried and their avg scores
        """
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT
                validation_profile,
                COUNT(*) as count,
                AVG(best_score) as avg_score,
                AVG(total_time) as avg_time
            FROM outcomes
            WHERE task_type = ? AND complexity = ?
            GROUP BY validation_profile
            ORDER BY avg_score DESC
        """, (task_type, complexity)).fetchall()

        if not rows:
            return {
                "suggested_profile": None,
                "total_outcomes": 0,
                "confidence": 0.0,
                "avg_score": 0.0,
                "alternatives": [],
            }

        total = sum(r["count"] for r in rows)
        best = rows[0]

        # Confidence scales with sample size: 3→0.3, 5→0.5, 10→0.8, 20+→1.0
        sample_confidence = min(1.0, best["count"] / 20.0)
        # Bonus if best profile clearly beats alternatives
        margin_bonus = 0.0
        if len(rows) > 1:
            score_gap = best["avg_score"] - rows[1]["avg_score"]
            margin_bonus = min(0.2, score_gap * 2.0)

        confidence = min(1.0, sample_confidence + margin_bonus)

        alternatives = []
        for r in rows[1:]:
            alternatives.append({
                "profile": r["validation_profile"],
                "count": r["count"],
                "avg_score": round(r["avg_score"], 4),
            })

        return {
            "suggested_profile": best["validation_profile"] if best["count"] >= 3 else None,
            "total_outcomes": total,
            "confidence": round(confidence, 4),
            "avg_score": round(best["avg_score"], 4),
            "alternatives": alternatives,
        }

    def get_learning_summary(self) -> Dict[str, Any]:
        """Comprehensive summary of what the system has learned.

        Aggregates profile stats, rule effectiveness, task type patterns,
        and actionable insights.
        """
        profile_stats = self.get_profile_stats()
        rule_eff = self.get_rule_effectiveness()
        task_stats = self.get_task_type_stats()
        risk_acc = self.get_risk_accuracy()
        overall = self.get_stats()

        # Derive insights
        insights = []

        # Best performing profile
        if profile_stats:
            best_profile = max(profile_stats.items(), key=lambda x: x[1]["avg_score"])
            insights.append(
                f"Best profile: {best_profile[0]} "
                f"(avg score: {best_profile[1]['avg_score']}, "
                f"success rate: {best_profile[1]['success_rate']})"
            )

        # Most problematic rules (highest fail rate)
        problematic_rules = [
            (name, stats)
            for name, stats in rule_eff.items()
            if stats["fail_rate"] > 0.2 and stats["times_run"] >= 3
        ]
        if problematic_rules:
            problematic_rules.sort(key=lambda x: x[1]["fail_rate"], reverse=True)
            top_fail = problematic_rules[0]
            insights.append(
                f"Most failing rule: {top_fail[0]} "
                f"(fail rate: {top_fail[1]['fail_rate']}, "
                f"runs: {top_fail[1]['times_run']})"
            )

        # Task type with lowest success rate
        if task_stats:
            worst_task = min(task_stats.items(), key=lambda x: x[1]["success_rate"])
            if worst_task[1]["success_rate"] < 0.8:
                insights.append(
                    f"Weakest task type: {worst_task[0]} "
                    f"(success rate: {worst_task[1]['success_rate']})"
                )

        return {
            "total_outcomes": overall["total_outcomes"],
            "overall_success_rate": overall["success_rate"],
            "overall_avg_score": overall["avg_score"],
            "profiles": profile_stats,
            "rules": rule_eff,
            "task_types": task_stats,
            "risk_levels": risk_acc,
            "insights": insights,
        }

    def get_recent_outcomes(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return recent pipeline outcomes for the timeline widget."""
        conn = self._get_conn()
        rows = conn.execute("""
            SELECT
                id, query_hash, timestamp, task_type, risk_level,
                validation_profile, complexity, n_candidates,
                best_score, all_passed, generation_time, validation_time,
                total_time, n_rules_run, n_rules_passed, n_rules_failed,
                swecas_code
            FROM outcomes
            ORDER BY timestamp DESC
            LIMIT ?
        """, (limit,)).fetchall()

        return [
            {
                "id": r["id"],
                "timestamp": r["timestamp"],
                "task_type": r["task_type"],
                "risk_level": r["risk_level"],
                "validation_profile": r["validation_profile"],
                "complexity": r["complexity"],
                "n_candidates": r["n_candidates"],
                "best_score": round(r["best_score"], 4),
                "all_passed": bool(r["all_passed"]),
                "total_time": round(r["total_time"], 3),
                "n_rules_run": r["n_rules_run"],
                "n_rules_passed": r["n_rules_passed"],
                "n_rules_failed": r["n_rules_failed"],
            }
            for r in rows
        ]

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get aggregated cache performance stats from outcome data."""
        conn = self._get_conn()
        row = conn.execute("""
            SELECT
                COUNT(*) as total,
                AVG(validation_time) as avg_val_time,
                AVG(generation_time) as avg_gen_time,
                AVG(total_time) as avg_total_time,
                MIN(validation_time) as min_val_time,
                MAX(validation_time) as max_val_time
            FROM outcomes
        """).fetchone()

        total = row["total"] or 0
        return {
            "total_outcomes": total,
            "avg_validation_time": round(row["avg_val_time"] or 0, 3),
            "avg_generation_time": round(row["avg_gen_time"] or 0, 3),
            "avg_total_time": round(row["avg_total_time"] or 0, 3),
            "min_validation_time": round(row["min_val_time"] or 0, 3),
            "max_validation_time": round(row["max_val_time"] or 0, 3),
        }

    def close(self) -> None:
        """Close persistent connection (for cleanup)."""
        if self._conn:
            self._conn.close()
            self._conn = None
