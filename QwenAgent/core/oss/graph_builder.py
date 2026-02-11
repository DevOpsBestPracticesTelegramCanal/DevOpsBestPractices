# -*- coding: utf-8 -*-
"""
GraphBuilder — Syncs PatternStore (SQLite) data into Neo4j knowledge graph.

PatternStore is the canonical source of truth. GraphBuilder materializes
repos, patterns, categories, and technologies into Neo4j for relationship
queries (co-occurrence, tech stacks, pattern neighborhoods).

Usage:
    store = PatternStore()
    graph = Neo4jGraph()
    builder = GraphBuilder(store, graph)
    stats = builder.full_sync()
    builder.build_cooccurrences()
"""

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from core.oss.pattern_store import PatternStore, RepoRecord, PatternRecord
from core.oss.neo4j_graph import Neo4jGraph

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Technology extraction patterns
# ---------------------------------------------------------------------------

# Map pattern_name / category / topic keywords → Technology nodes
_TECH_PATTERNS = {
    # Frameworks
    "flask": "Flask",
    "django": "Django",
    "fastapi": "FastAPI",
    "starlette": "Starlette",
    "tornado": "Tornado",
    "aiohttp": "aiohttp",
    "express": "Express",
    "react": "React",
    "vue": "Vue",
    "angular": "Angular",
    # Testing
    "pytest": "pytest",
    "unittest": "unittest",
    "jest": "Jest",
    "mocha": "Mocha",
    # CI/CD
    "github_actions": "GitHub Actions",
    "gitlab_ci": "GitLab CI",
    "jenkins": "Jenkins",
    "circleci": "CircleCI",
    "travis": "Travis CI",
    # Containerization
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "helm": "Helm",
    "compose": "Docker Compose",
    # Databases
    "postgresql": "PostgreSQL",
    "postgres": "PostgreSQL",
    "mysql": "MySQL",
    "mongodb": "MongoDB",
    "redis": "Redis",
    "sqlite": "SQLite",
    # Languages
    "python": "Python",
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "go": "Go",
    "rust": "Rust",
    "java": "Java",
    # Others
    "graphql": "GraphQL",
    "rest": "REST API",
    "grpc": "gRPC",
    "celery": "Celery",
    "sqlalchemy": "SQLAlchemy",
    "pydantic": "Pydantic",
    "mypy": "mypy",
    "ruff": "Ruff",
    "black": "Black",
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class SyncStats:
    """Statistics from a sync operation."""
    repos_synced: int = 0
    patterns_synced: int = 0
    techs_created: int = 0
    cooccurrences_built: int = 0
    duration_seconds: float = 0.0
    errors: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# GraphBuilder
# ---------------------------------------------------------------------------

class GraphBuilder:
    """Sync PatternStore data into Neo4j graph.

    PatternStore (SQLite) is the canonical source.
    Neo4j is a secondary materialized index for relationship queries.
    """

    def __init__(self, store: PatternStore, graph: Neo4jGraph):
        self._store = store
        self._graph = graph

    @property
    def is_available(self) -> bool:
        """Check if both store and graph are ready."""
        return self._graph.is_available()

    def full_sync(self) -> SyncStats:
        """Sync all repos and patterns from PatternStore to Neo4j.

        Returns:
            SyncStats with counts and timing.
        """
        start = time.time()
        stats = SyncStats()

        if not self._graph.is_available():
            stats.errors.append("Neo4j graph not available")
            return stats

        # Create constraints first
        self._graph.create_constraints()

        # Sync repos
        repos = self._store.list_repos(limit=10000)
        for repo in repos:
            if self._graph.upsert_repo(repo):
                stats.repos_synced += 1

                # Extract and link technologies from repo
                techs = self.extract_technologies(repo, [])
                for tech in techs:
                    self._graph.upsert_technology(tech)
                    self._graph.link_repo_tech(repo.full_name, tech, source="repo_topics")
                    stats.techs_created += 1

                # Get patterns for this repo
                patterns = self._store.get_patterns_for_repo(repo.full_name)
                for pattern in patterns:
                    if self._graph.upsert_pattern(pattern):
                        stats.patterns_synced += 1

                    # Extract techs from pattern
                    pattern_techs = self.extract_technologies(repo, [pattern])
                    for tech in pattern_techs:
                        if tech not in techs:  # Avoid duplicate links
                            self._graph.upsert_technology(tech)
                            self._graph.link_repo_tech(
                                repo.full_name, tech, source="pattern"
                            )
                            stats.techs_created += 1
            else:
                stats.errors.append(f"Failed to upsert repo: {repo.full_name}")

        stats.duration_seconds = time.time() - start
        logger.info(
            "[GraphBuilder] full_sync: %d repos, %d patterns, %d techs in %.1fs",
            stats.repos_synced, stats.patterns_synced, stats.techs_created,
            stats.duration_seconds,
        )
        return stats

    def incremental_sync(self, since_timestamp: float) -> SyncStats:
        """Sync only repos collected after since_timestamp.

        Args:
            since_timestamp: Unix timestamp. Only repos with
                collected_at > since_timestamp will be synced.

        Returns:
            SyncStats with counts and timing.
        """
        start = time.time()
        stats = SyncStats()

        if not self._graph.is_available():
            stats.errors.append("Neo4j graph not available")
            return stats

        # Get all repos and filter by timestamp
        repos = self._store.list_repos(limit=10000)
        new_repos = [r for r in repos if r.collected_at > since_timestamp]

        for repo in new_repos:
            if self._graph.upsert_repo(repo):
                stats.repos_synced += 1

                techs = self.extract_technologies(repo, [])
                for tech in techs:
                    self._graph.upsert_technology(tech)
                    self._graph.link_repo_tech(repo.full_name, tech, source="repo_topics")
                    stats.techs_created += 1

                patterns = self._store.get_patterns_for_repo(repo.full_name)
                for pattern in patterns:
                    if self._graph.upsert_pattern(pattern):
                        stats.patterns_synced += 1

                    pattern_techs = self.extract_technologies(repo, [pattern])
                    for tech in pattern_techs:
                        if tech not in techs:
                            self._graph.upsert_technology(tech)
                            self._graph.link_repo_tech(
                                repo.full_name, tech, source="pattern"
                            )
                            stats.techs_created += 1

        stats.duration_seconds = time.time() - start
        logger.info(
            "[GraphBuilder] incremental_sync: %d repos, %d patterns in %.1fs",
            stats.repos_synced, stats.patterns_synced, stats.duration_seconds,
        )
        return stats

    def build_cooccurrences(self) -> int:
        """Build co-occurrence relationships between patterns.

        Returns:
            Number of co-occurrence relationships created/updated.
        """
        if not self._graph.is_available():
            return 0
        return self._graph.update_cooccurrences()

    @staticmethod
    def extract_technologies(
        repo: RepoRecord,
        patterns: List[PatternRecord],
    ) -> List[str]:
        """Extract technology names from repo metadata and patterns.

        Sources:
          - repo.topics (e.g., ["flask", "python", "docker"])
          - repo.architecture (e.g., "microservice")
          - pattern.pattern_name (e.g., "pytest_fixtures")
          - pattern.category (e.g., "testing")

        Returns:
            Deduplicated list of technology names.
        """
        found: Set[str] = set()

        # From repo topics
        for topic in (repo.topics or []):
            topic_lower = topic.lower().strip()
            if topic_lower in _TECH_PATTERNS:
                found.add(_TECH_PATTERNS[topic_lower])

        # From repo architecture
        if repo.architecture:
            arch_lower = repo.architecture.lower()
            for key, tech in _TECH_PATTERNS.items():
                if key in arch_lower:
                    found.add(tech)

        # From patterns
        for p in patterns:
            pname = p.pattern_name.lower()
            cat = p.category.lower()

            # Check pattern_name
            for key, tech in _TECH_PATTERNS.items():
                if key in pname:
                    found.add(tech)

            # Check category
            if cat in _TECH_PATTERNS:
                found.add(_TECH_PATTERNS[cat])

        return sorted(found)
