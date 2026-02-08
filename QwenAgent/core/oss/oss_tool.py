# -*- coding: utf-8 -*-
"""
OSS Tool — integrates OSS Consciousness into the QwenAgent tool system.

Registers an "oss" tool that can be invoked via pattern router or directly.
"""

import logging
import os
from typing import Any, Dict, Optional

from core.oss.pattern_store import PatternStore
from core.oss.oss_engine import OSSEngine

logger = logging.getLogger(__name__)


class OSSTool:
    """Tool wrapper for OSS Consciousness engine."""

    def __init__(self, db_path: Optional[str] = None):
        self._store = PatternStore(db_path=db_path)
        self._engine = OSSEngine(self._store)

    @property
    def store(self) -> PatternStore:
        return self._store

    @property
    def engine(self) -> OSSEngine:
        return self._engine

    def execute(self, action: str = "query", **kwargs) -> Dict[str, Any]:
        """
        Execute an OSS tool action.

        Actions:
            query       — answer a question about OSS patterns
            stats       — return overall statistics
            report      — generate full markdown report
            frameworks  — framework popularity stats
            testing     — testing tool stats
            ci          — CI/CD stats
            docker      — docker stats
            linting     — linting stats
            packaging   — packaging stats
            databases   — database ORM stats
            architecture — architecture distribution
            pattern     — repos using a specific pattern
        """
        try:
            if action == "query":
                question = kwargs.get("question", kwargs.get("q", ""))
                if not question:
                    return {"error": "No question provided", "success": False}
                insight = self._engine.query(question)
                return {
                    "answer": insight.answer,
                    "confidence": insight.confidence,
                    "patterns": insight.patterns,
                    "sample_repos": insight.sample_repos,
                    "stats": insight.stats,
                    "success": True,
                }

            elif action == "stats":
                return {"stats": self._engine.get_stats(), "success": True}

            elif action == "report":
                return {"report": self._engine.get_full_report(), "success": True}

            elif action == "frameworks":
                return {"data": self._engine.get_framework_stats(), "success": True}

            elif action == "testing":
                return {"data": self._engine.get_testing_stats(), "success": True}

            elif action == "ci":
                return {"data": self._engine.get_ci_stats(), "success": True}

            elif action == "docker":
                return {"data": self._engine.get_docker_stats(), "success": True}

            elif action == "linting":
                return {"data": self._engine.get_linting_stats(), "success": True}

            elif action == "packaging":
                return {"data": self._engine.get_packaging_stats(), "success": True}

            elif action == "databases":
                return {"data": self._engine.get_database_stats(), "success": True}

            elif action == "architecture":
                return {"data": self._engine.get_architecture_distribution(), "success": True}

            elif action == "pattern":
                name = kwargs.get("pattern_name", kwargs.get("name", ""))
                if not name:
                    return {"error": "No pattern_name provided", "success": False}
                repos = self._store.query_repos_by_pattern(name, limit=20)
                return {"repos": repos, "count": len(repos), "success": True}

            else:
                return {"error": f"Unknown action: {action}", "success": False}

        except Exception as exc:
            logger.error("[OSSTool] Error in action %s: %s", action, exc)
            return {"error": str(exc), "success": False}

    def get_stats(self) -> Dict[str, Any]:
        """For /api/stats endpoint."""
        return self._engine.get_stats()


# ---------------------------------------------------------------------------
# Pattern Router integration patterns
# ---------------------------------------------------------------------------

OSS_ROUTER_PATTERNS = [
    # English
    (r"(?:oss|open[\s-]?source)\s+(?:pattern|insight|analysis|stats|report)",
     "oss", lambda m: {"action": "report"}),
    (r"(?:how\s+do|how\s+are)\s+(?:python\s+)?(?:projects?|repos?)\s+(?:implement|use|handle)\s+(.+)",
     "oss", lambda m: {"action": "query", "question": m.group(0)}),
    (r"(?:popular|common|top)\s+(?:python\s+)?(?:frameworks?|librar(?:y|ies)|tools?|testing|ci)",
     "oss", lambda m: {"action": "query", "question": m.group(0)}),
    (r"tech[\s-]?stack\s+(?:report|stats|analysis|consensus)",
     "oss", lambda m: {"action": "report"}),
    (r"(?:flask|django|fastapi|pytest|github.actions)\s+vs\.?\s+(\w+)",
     "oss", lambda m: {"action": "query", "question": m.group(0)}),
    # Russian
    (r"(?:какие|популярные|топ)\s+(?:фреймворки|библиотеки|инструменты)",
     "oss", lambda m: {"action": "query", "question": m.group(0)}),
    (r"(?:анализ|статистика|отчет)\s+(?:open[\s-]?source|oss|репозиториев)",
     "oss", lambda m: {"action": "report"}),
]
