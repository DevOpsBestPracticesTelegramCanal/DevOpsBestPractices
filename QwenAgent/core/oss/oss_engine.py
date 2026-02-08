# -*- coding: utf-8 -*-
"""
OSSEngine — query interface for the OSS Consciousness knowledge base.

Answers questions about open-source patterns, framework popularity,
testing tool adoption, and tech stack consensus.
"""

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.oss.pattern_store import PatternStore

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class OSSInsight:
    """Result of an OSS knowledge query."""
    question: str
    answer: str
    patterns: List[Dict[str, Any]] = field(default_factory=list)
    sample_repos: List[str] = field(default_factory=list)
    confidence: float = 0.0
    stats: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Query parsing
# ---------------------------------------------------------------------------

_CATEGORY_KEYWORDS: Dict[str, List[str]] = {
    "framework":    ["framework", "web framework", "http", "api framework", "фреймворк"],
    "testing":      ["test", "testing", "тест", "qa", "coverage", "тестирование"],
    "ci_cd":        ["ci", "cd", "ci/cd", "pipeline", "github actions", "continuous"],
    "docker":       ["docker", "container", "containerize", "докер", "контейнер"],
    "linting":      ["lint", "linting", "format", "style", "линтер", "форматирование"],
    "packaging":    ["package", "packaging", "build", "publish", "пакет", "сборка"],
    "database":     ["database", "db", "orm", "sql", "mongo", "redis", "база данных"],
    "architecture": ["architecture", "structure", "pattern", "архитектура", "паттерн"],
    "license":      ["license", "лицензия"],
}

_PATTERN_KEYWORDS: Dict[str, str] = {
    # framework
    "flask": "flask", "django": "django", "fastapi": "fastapi",
    "tornado": "tornado", "aiohttp": "aiohttp", "starlette": "starlette",
    "streamlit": "streamlit", "gradio": "gradio",
    # testing
    "pytest": "pytest", "unittest": "unittest", "tox": "tox",
    "hypothesis": "hypothesis", "coverage": "coverage",
    # ci/cd
    "github actions": "github_actions", "travis": "travis",
    "circleci": "circleci", "jenkins": "jenkins",
    # docker
    "docker-compose": "docker_compose", "dockerfile": "dockerfile",
    # linting
    "black": "black", "ruff": "ruff", "flake8": "flake8",
    "pylint": "pylint", "mypy": "mypy", "isort": "isort",
    # packaging
    "poetry": "poetry", "setuptools": "setuptools", "hatch": "hatch",
    "flit": "flit",
    # database
    "sqlalchemy": "sqlalchemy", "peewee": "peewee", "redis": "redis",
    "pymongo": "pymongo", "postgresql": "psycopg2",
}


# ---------------------------------------------------------------------------
# OSSEngine
# ---------------------------------------------------------------------------

class OSSEngine:
    """Answers questions about open-source patterns."""

    def __init__(self, store: PatternStore):
        self._store = store

    # ------------------------------------------------------------------
    # Main query
    # ------------------------------------------------------------------

    def query(self, question: str) -> OSSInsight:
        """
        Parse a natural-language question and return an insight.

        Strategies:
        1. Detect if asking about a specific pattern → repo lookup
        2. Detect if asking about a category → category stats
        3. Detect if comparing patterns → comparison
        4. Default → full report summary
        """
        q_lower = question.lower()

        # 1. Comparison (e.g., "flask vs django") — check first to avoid
        #    matching just the first keyword
        vs_match = re.search(r"(\w+)\s+vs\.?\s+(\w+)", q_lower)
        if vs_match:
            a, b = vs_match.group(1), vs_match.group(2)
            return self._compare_patterns(question, a, b)

        # 2. Specific pattern query
        for kw, pattern_name in _PATTERN_KEYWORDS.items():
            if kw in q_lower:
                return self._query_pattern(question, pattern_name)

        # 3. Category query
        for cat, keywords in _CATEGORY_KEYWORDS.items():
            for kw in keywords:
                if kw in q_lower:
                    return self._query_category(question, cat)

        # 4. Fallback: full overview
        return self._full_overview(question)

    # ------------------------------------------------------------------
    # Category stats
    # ------------------------------------------------------------------

    def get_framework_stats(self) -> List[Dict[str, Any]]:
        return self._store.get_top_patterns("framework", limit=20)

    def get_testing_stats(self) -> List[Dict[str, Any]]:
        return self._store.get_top_patterns("testing", limit=20)

    def get_ci_stats(self) -> List[Dict[str, Any]]:
        return self._store.get_top_patterns("ci_cd", limit=10)

    def get_docker_stats(self) -> List[Dict[str, Any]]:
        return self._store.get_top_patterns("docker", limit=10)

    def get_linting_stats(self) -> List[Dict[str, Any]]:
        return self._store.get_top_patterns("linting", limit=10)

    def get_packaging_stats(self) -> List[Dict[str, Any]]:
        return self._store.get_top_patterns("packaging", limit=10)

    def get_database_stats(self) -> List[Dict[str, Any]]:
        return self._store.get_top_patterns("database", limit=10)

    def get_architecture_distribution(self) -> List[Dict[str, Any]]:
        return self._store.get_top_patterns("architecture", limit=10)

    # ------------------------------------------------------------------
    # Full report
    # ------------------------------------------------------------------

    def get_full_report(self) -> str:
        """Generate a formatted markdown report of all pattern statistics."""
        store_stats = self._store.get_stats()
        lines = [
            "# OSS Consciousness Report",
            "",
            f"**Repos analyzed:** {store_stats['total_repos']}",
            f"**Patterns extracted:** {store_stats['total_patterns']}",
            f"**Categories:** {', '.join(store_stats.get('categories', []))}",
            "",
        ]

        categories = [
            ("framework", "Web Frameworks"),
            ("testing", "Testing"),
            ("ci_cd", "CI/CD"),
            ("docker", "Docker"),
            ("linting", "Linting & Formatting"),
            ("packaging", "Packaging"),
            ("database", "Database"),
            ("architecture", "Architecture"),
            ("license", "License"),
        ]

        for cat_key, cat_title in categories:
            top = self._store.get_top_patterns(cat_key, limit=10)
            if not top:
                continue
            lines.append(f"## {cat_title}")
            lines.append("")
            lines.append("| Pattern | Repos | Avg Stars | Top Repo |")
            lines.append("|---------|-------|-----------|----------|")
            for p in top:
                lines.append(
                    f"| {p['pattern_name']} | {p['repo_count']} | "
                    f"{p['avg_stars']:.0f} | {p['top_repo']} |"
                )
            lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        return self._store.get_stats()

    # ------------------------------------------------------------------
    # Private query strategies
    # ------------------------------------------------------------------

    def _query_pattern(self, question: str, pattern_name: str) -> OSSInsight:
        repos = self._store.query_repos_by_pattern(pattern_name, limit=10)
        stats = self._store.get_top_patterns(limit=100)
        # Find stats for this pattern
        pat_stat = next((s for s in stats if s["pattern_name"] == pattern_name), None)

        if not repos and not pat_stat:
            return OSSInsight(
                question=question,
                answer=f"No data found for pattern '{pattern_name}'. "
                       "Try collecting repos first.",
                confidence=0.0,
            )

        count = pat_stat["repo_count"] if pat_stat else len(repos)
        total = self._store.count_repos() or 1
        pct = (count / total) * 100

        answer_lines = [
            f"**{pattern_name}** is used by {count} repos ({pct:.1f}% of analyzed repos).",
        ]
        if pat_stat:
            answer_lines.append(f"Average stars: {pat_stat['avg_stars']:.0f}")
            answer_lines.append(f"Top repo: {pat_stat['top_repo']}")
        if repos:
            answer_lines.append("\nTop repos using this pattern:")
            for r in repos[:5]:
                answer_lines.append(f"- **{r['full_name']}** ({r['stars']} stars)")

        return OSSInsight(
            question=question,
            answer="\n".join(answer_lines),
            patterns=[pat_stat] if pat_stat else [],
            sample_repos=[r["full_name"] for r in repos[:10]],
            confidence=0.9 if repos else 0.3,
            stats={"repo_count": count, "percentage": pct},
        )

    def _query_category(self, question: str, category: str) -> OSSInsight:
        top = self._store.get_top_patterns(category, limit=10)
        if not top:
            return OSSInsight(
                question=question,
                answer=f"No data for category '{category}'. Try collecting repos first.",
                confidence=0.0,
            )

        total = self._store.count_repos() or 1

        answer_lines = [f"## {category.replace('_', ' ').title()} — Top Patterns\n"]
        answer_lines.append("| Pattern | Repos | % | Avg Stars |")
        answer_lines.append("|---------|-------|---|-----------|")
        for p in top:
            pct = (p["repo_count"] / total) * 100
            answer_lines.append(
                f"| {p['pattern_name']} | {p['repo_count']} | {pct:.1f}% | {p['avg_stars']:.0f} |"
            )

        return OSSInsight(
            question=question,
            answer="\n".join(answer_lines),
            patterns=top,
            confidence=0.85,
            stats={"category": category, "total_patterns": len(top)},
        )

    def _compare_patterns(self, question: str, a: str, b: str) -> OSSInsight:
        a_key = _PATTERN_KEYWORDS.get(a, a)
        b_key = _PATTERN_KEYWORDS.get(b, b)

        a_repos = self._store.query_repos_by_pattern(a_key, limit=5)
        b_repos = self._store.query_repos_by_pattern(b_key, limit=5)

        stats_all = self._store.get_top_patterns(limit=200)
        a_stat = next((s for s in stats_all if s["pattern_name"] == a_key), None)
        b_stat = next((s for s in stats_all if s["pattern_name"] == b_key), None)

        a_count = a_stat["repo_count"] if a_stat else len(a_repos)
        b_count = b_stat["repo_count"] if b_stat else len(b_repos)
        total = max(a_count + b_count, 1)

        winner = a_key if a_count >= b_count else b_key
        loser = b_key if winner == a_key else a_key
        w_count = max(a_count, b_count)
        l_count = min(a_count, b_count)

        answer_lines = [
            f"## {a_key} vs {b_key}\n",
            f"| Metric | {a_key} | {b_key} |",
            f"|--------|{'---' * len(a_key)}--|{'---' * len(b_key)}--|",
            f"| Repos | {a_count} | {b_count} |",
        ]

        if a_stat and b_stat:
            answer_lines.append(
                f"| Avg Stars | {a_stat['avg_stars']:.0f} | {b_stat['avg_stars']:.0f} |"
            )
            answer_lines.append(
                f"| Top Repo | {a_stat['top_repo']} | {b_stat['top_repo']} |"
            )

        answer_lines.append("")
        pct = (w_count / total * 100) if total else 50
        answer_lines.append(
            f"**{winner}** leads with {w_count} repos ({pct:.0f}%) vs "
            f"**{loser}** with {l_count} repos ({100 - pct:.0f}%)."
        )

        return OSSInsight(
            question=question,
            answer="\n".join(answer_lines),
            patterns=[s for s in (a_stat, b_stat) if s],
            sample_repos=[r["full_name"] for r in a_repos[:3] + b_repos[:3]],
            confidence=0.8 if (a_repos or b_repos) else 0.2,
            stats={"a": a_key, "a_count": a_count, "b": b_key, "b_count": b_count},
        )

    def _full_overview(self, question: str) -> OSSInsight:
        report = self.get_full_report()
        stats = self._store.get_stats()
        return OSSInsight(
            question=question,
            answer=report,
            confidence=0.7 if stats.get("total_repos", 0) > 0 else 0.0,
            stats=stats,
        )
