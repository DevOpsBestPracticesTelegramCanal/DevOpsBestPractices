# -*- coding: utf-8 -*-
"""
Neo4jGraph — Knowledge graph for OSS pattern co-occurrence and relationships.

Uses Neo4j Aura Free (200k nodes, 400k rels, $0/forever) as a secondary
materialized graph index. PatternStore (SQLite) remains the canonical source.

Graph Schema:
  (:Repo {name, stars, forks, license, architecture})
    -[:HAS_PATTERN {confidence}]->
  (:Pattern {name, category, evidence})
    -[:IN_CATEGORY]->
  (:Category {name})
  (:Pattern)-[:COOCCURS_WITH {count, pmi}]->(:Pattern)
  (:Repo)-[:USES_TECH {source}]->(:Technology {name})

Design constraints:
  - Standard Cypher only (no GDS plugin — unavailable on Aura Free)
  - MERGE for idempotent upserts
  - Graceful degradation if neo4j package missing or connection fails
"""

import logging
import math
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Graceful import for neo4j driver
try:
    import neo4j as _neo4j
    from neo4j import GraphDatabase
    HAS_NEO4J = True
except ImportError:
    HAS_NEO4J = False
    _neo4j = None  # type: ignore
    GraphDatabase = None  # type: ignore


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class GraphStats:
    """Statistics about the graph contents."""
    total_repos: int = 0
    total_patterns: int = 0
    total_categories: int = 0
    total_technologies: int = 0
    total_cooccurrences: int = 0
    total_relationships: int = 0


# ---------------------------------------------------------------------------
# Neo4jGraph
# ---------------------------------------------------------------------------

class Neo4jGraph:
    """Low-level Neo4j graph operations for OSS pattern knowledge graph.

    All methods use standard Cypher (no GDS plugin).
    MERGE is used for idempotent upserts.
    Gracefully degrades if neo4j is not installed or connection fails.
    """

    def __init__(
        self,
        uri: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
    ):
        self._uri = uri or os.environ.get("NEO4J_URI", "")
        self._username = username or os.environ.get("NEO4J_USERNAME", "neo4j")
        self._password = password or os.environ.get("NEO4J_PASSWORD", "")
        self._driver = None
        self._available = False

        if not HAS_NEO4J:
            logger.info("[Neo4j] neo4j package not installed — graph disabled")
            return

        if not self._uri:
            logger.info("[Neo4j] No NEO4J_URI configured — graph disabled")
            return

        try:
            self._driver = GraphDatabase.driver(
                self._uri,
                auth=(self._username, self._password),
            )
            # Verify connectivity
            self._driver.verify_connectivity()
            self._available = True
            logger.info("[Neo4j] Connected to %s", self._uri)
        except Exception as e:
            logger.warning("[Neo4j] Connection failed: %s — graph disabled", e)
            self._driver = None
            self._available = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the Neo4j driver connection."""
        if self._driver:
            try:
                self._driver.close()
            except Exception:
                pass
            self._driver = None
            self._available = False

    def is_available(self) -> bool:
        """Check if Neo4j is connected and usable."""
        return self._available and self._driver is not None

    # ------------------------------------------------------------------
    # Schema / Constraints
    # ------------------------------------------------------------------

    def create_constraints(self) -> None:
        """Create uniqueness constraints on the graph.

        Idempotent — safe to call multiple times.
        """
        if not self.is_available():
            return

        constraints = [
            "CREATE CONSTRAINT repo_name IF NOT EXISTS FOR (r:Repo) REQUIRE r.name IS UNIQUE",
            "CREATE CONSTRAINT category_name IF NOT EXISTS FOR (c:Category) REQUIRE c.name IS UNIQUE",
            "CREATE CONSTRAINT technology_name IF NOT EXISTS FOR (t:Technology) REQUIRE t.name IS UNIQUE",
        ]
        with self._driver.session() as session:
            for cypher in constraints:
                try:
                    session.run(cypher)
                except Exception as e:
                    logger.warning("[Neo4j] Constraint warning: %s", e)

    # ------------------------------------------------------------------
    # Upsert operations
    # ------------------------------------------------------------------

    def upsert_repo(self, repo) -> bool:
        """Upsert a Repo node from a PatternStore RepoRecord.

        Args:
            repo: RepoRecord dataclass (full_name, stars, forks, license, architecture)

        Returns:
            True if successful, False otherwise.
        """
        if not self.is_available():
            return False

        cypher = """
        MERGE (r:Repo {name: $name})
        SET r.stars = $stars,
            r.forks = $forks,
            r.license = $license,
            r.architecture = $architecture
        """
        try:
            with self._driver.session() as session:
                session.run(cypher, {
                    "name": repo.full_name,
                    "stars": repo.stars,
                    "forks": repo.forks,
                    "license": repo.license or "",
                    "architecture": repo.architecture or "",
                })
            return True
        except Exception as e:
            logger.error("[Neo4j] upsert_repo failed: %s", e)
            return False

    def upsert_pattern(self, pattern) -> bool:
        """Upsert a Pattern node and link it to its Repo and Category.

        Args:
            pattern: PatternRecord dataclass (repo_name, category, pattern_name,
                     confidence, evidence)

        Returns:
            True if successful, False otherwise.
        """
        if not self.is_available():
            return False

        cypher = """
        MERGE (p:Pattern {name: $pattern_name, category: $category})
        SET p.evidence = $evidence

        MERGE (c:Category {name: $category})
        MERGE (p)-[:IN_CATEGORY]->(c)

        WITH p
        MATCH (r:Repo {name: $repo_name})
        MERGE (r)-[h:HAS_PATTERN]->(p)
        SET h.confidence = $confidence
        """
        try:
            with self._driver.session() as session:
                session.run(cypher, {
                    "pattern_name": pattern.pattern_name,
                    "category": pattern.category,
                    "evidence": pattern.evidence or "",
                    "repo_name": pattern.repo_name,
                    "confidence": pattern.confidence,
                })
            return True
        except Exception as e:
            logger.error("[Neo4j] upsert_pattern failed: %s", e)
            return False

    def upsert_technology(self, name: str) -> bool:
        """Upsert a Technology node.

        Returns:
            True if successful, False otherwise.
        """
        if not self.is_available():
            return False

        try:
            with self._driver.session() as session:
                session.run("MERGE (t:Technology {name: $name})", {"name": name})
            return True
        except Exception as e:
            logger.error("[Neo4j] upsert_technology failed: %s", e)
            return False

    def link_repo_tech(self, repo_name: str, tech_name: str, source: str = "") -> bool:
        """Create a USES_TECH relationship between a Repo and a Technology.

        Returns:
            True if successful, False otherwise.
        """
        if not self.is_available():
            return False

        cypher = """
        MATCH (r:Repo {name: $repo_name})
        MERGE (t:Technology {name: $tech_name})
        MERGE (r)-[u:USES_TECH]->(t)
        SET u.source = $source
        """
        try:
            with self._driver.session() as session:
                session.run(cypher, {
                    "repo_name": repo_name,
                    "tech_name": tech_name,
                    "source": source,
                })
            return True
        except Exception as e:
            logger.error("[Neo4j] link_repo_tech failed: %s", e)
            return False

    # ------------------------------------------------------------------
    # Co-occurrence
    # ------------------------------------------------------------------

    def update_cooccurrences(self) -> int:
        """Compute co-occurrence relationships between patterns.

        For each pair of patterns that share at least one Repo,
        creates/updates a COOCCURS_WITH relationship with count and PMI.

        PMI = log2(P(A,B) / (P(A) * P(B)))
        where P(A) = repos_with_A / total_repos, etc.

        Returns:
            Number of co-occurrence relationships created/updated.
        """
        if not self.is_available():
            return 0

        cypher = """
        // Count total repos
        MATCH (r:Repo)
        WITH count(r) AS totalRepos
        WHERE totalRepos > 0

        // Find pattern pairs that share repos
        MATCH (r:Repo)-[:HAS_PATTERN]->(p1:Pattern),
              (r)-[:HAS_PATTERN]->(p2:Pattern)
        WHERE id(p1) < id(p2)
        WITH p1, p2, count(DISTINCT r) AS sharedCount, totalRepos

        // Count individual pattern frequencies
        OPTIONAL MATCH (r1:Repo)-[:HAS_PATTERN]->(p1)
        WITH p1, p2, sharedCount, totalRepos, count(DISTINCT r1) AS p1Count
        OPTIONAL MATCH (r2:Repo)-[:HAS_PATTERN]->(p2)
        WITH p1, p2, sharedCount, totalRepos, p1Count, count(DISTINCT r2) AS p2Count

        // Calculate PMI
        WITH p1, p2, sharedCount,
             CASE WHEN p1Count > 0 AND p2Count > 0 AND totalRepos > 0
                  THEN log(toFloat(sharedCount) * totalRepos / (toFloat(p1Count) * p2Count)) / log(2)
                  ELSE 0.0
             END AS pmi

        // Create/update co-occurrence
        MERGE (p1)-[c:COOCCURS_WITH]->(p2)
        SET c.count = sharedCount, c.pmi = pmi
        RETURN count(c) AS total
        """
        try:
            with self._driver.session() as session:
                result = session.run(cypher)
                record = result.single()
                count = record["total"] if record else 0
                logger.info("[Neo4j] Updated %d co-occurrence relationships", count)
                return count
        except Exception as e:
            logger.error("[Neo4j] update_cooccurrences failed: %s", e)
            return 0

    # ------------------------------------------------------------------
    # Query operations
    # ------------------------------------------------------------------

    def get_cooccurring_patterns(
        self,
        pattern_name: str,
        min_count: int = 2,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Get patterns that commonly co-occur with the given pattern.

        Args:
            pattern_name: Name of the pattern to find co-occurrences for.
            min_count: Minimum shared repo count.
            limit: Maximum results.

        Returns:
            List of dicts with keys: pattern_name, category, count, pmi.
        """
        if not self.is_available():
            return []

        cypher = """
        MATCH (p1:Pattern {name: $name})-[c:COOCCURS_WITH]-(p2:Pattern)
        WHERE c.count >= $min_count
        RETURN p2.name AS pattern_name, p2.category AS category,
               c.count AS count, c.pmi AS pmi
        ORDER BY c.pmi DESC, c.count DESC
        LIMIT $limit
        """
        try:
            with self._driver.session() as session:
                result = session.run(cypher, {
                    "name": pattern_name,
                    "min_count": min_count,
                    "limit": limit,
                })
                return [dict(record) for record in result]
        except Exception as e:
            logger.error("[Neo4j] get_cooccurring_patterns failed: %s", e)
            return []

    def get_technology_stack(self, repo_name: str) -> List[Dict[str, Any]]:
        """Get the technology stack for a given repository.

        Returns:
            List of dicts with keys: technology, source.
        """
        if not self.is_available():
            return []

        cypher = """
        MATCH (r:Repo {name: $name})-[u:USES_TECH]->(t:Technology)
        RETURN t.name AS technology, u.source AS source
        ORDER BY t.name
        """
        try:
            with self._driver.session() as session:
                result = session.run(cypher, {"name": repo_name})
                return [dict(record) for record in result]
        except Exception as e:
            logger.error("[Neo4j] get_technology_stack failed: %s", e)
            return []

    def get_repos_by_technology(self, tech_name: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Find repositories that use a given technology.

        Returns:
            List of dicts with keys: repo_name, stars, source.
        """
        if not self.is_available():
            return []

        cypher = """
        MATCH (r:Repo)-[u:USES_TECH]->(t:Technology {name: $name})
        RETURN r.name AS repo_name, r.stars AS stars, u.source AS source
        ORDER BY r.stars DESC
        LIMIT $limit
        """
        try:
            with self._driver.session() as session:
                result = session.run(cypher, {"name": tech_name, "limit": limit})
                return [dict(record) for record in result]
        except Exception as e:
            logger.error("[Neo4j] get_repos_by_technology failed: %s", e)
            return []

    def get_pattern_neighbors(self, pattern_name: str, depth: int = 2) -> Dict[str, Any]:
        """Get the neighborhood subgraph around a pattern.

        Args:
            pattern_name: Pattern to start from.
            depth: Traversal depth (1 = direct neighbors, 2 = 2-hop).

        Returns:
            Dict with 'nodes' and 'edges' lists.
        """
        if not self.is_available():
            return {"nodes": [], "edges": []}

        cypher = """
        MATCH path = (p:Pattern {name: $name})-[*1..$depth]-(neighbor)
        WITH nodes(path) AS ns, relationships(path) AS rs
        UNWIND ns AS n
        WITH collect(DISTINCT {id: id(n), labels: labels(n), name: n.name}) AS nodes,
             rs
        UNWIND rs AS r
        WITH nodes,
             collect(DISTINCT {
                 start: id(startNode(r)), end: id(endNode(r)), type: type(r)
             }) AS edges
        RETURN nodes, edges
        """
        try:
            with self._driver.session() as session:
                result = session.run(cypher, {
                    "name": pattern_name,
                    "depth": depth,
                })
                record = result.single()
                if record:
                    return {
                        "nodes": [dict(n) for n in record["nodes"]],
                        "edges": [dict(e) for e in record["edges"]],
                    }
                return {"nodes": [], "edges": []}
        except Exception as e:
            logger.error("[Neo4j] get_pattern_neighbors failed: %s", e)
            return {"nodes": [], "edges": []}

    def get_category_summary(self) -> List[Dict[str, Any]]:
        """Get a summary of patterns per category.

        Returns:
            List of dicts with keys: category, pattern_count, repo_count.
        """
        if not self.is_available():
            return []

        cypher = """
        MATCH (c:Category)<-[:IN_CATEGORY]-(p:Pattern)
        OPTIONAL MATCH (r:Repo)-[:HAS_PATTERN]->(p)
        WITH c.name AS category, count(DISTINCT p) AS pattern_count,
             count(DISTINCT r) AS repo_count
        RETURN category, pattern_count, repo_count
        ORDER BY pattern_count DESC
        """
        try:
            with self._driver.session() as session:
                result = session.run(cypher)
                return [dict(record) for record in result]
        except Exception as e:
            logger.error("[Neo4j] get_category_summary failed: %s", e)
            return []

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_stats(self) -> Dict[str, Any]:
        """Get overall graph statistics.

        Returns:
            Dict with node/relationship counts.
        """
        if not self.is_available():
            return {
                "available": False,
                "total_repos": 0,
                "total_patterns": 0,
                "total_categories": 0,
                "total_technologies": 0,
                "total_cooccurrences": 0,
                "total_relationships": 0,
            }

        try:
            stats = {"available": True}
            with self._driver.session() as session:
                # Node counts
                for label, key in [
                    ("Repo", "total_repos"),
                    ("Pattern", "total_patterns"),
                    ("Category", "total_categories"),
                    ("Technology", "total_technologies"),
                ]:
                    result = session.run(f"MATCH (n:{label}) RETURN count(n) AS c")
                    record = result.single()
                    stats[key] = record["c"] if record else 0

                # Co-occurrence count
                result = session.run(
                    "MATCH ()-[c:COOCCURS_WITH]->() RETURN count(c) AS c"
                )
                record = result.single()
                stats["total_cooccurrences"] = record["c"] if record else 0

                # Total relationships
                result = session.run("MATCH ()-[r]->() RETURN count(r) AS c")
                record = result.single()
                stats["total_relationships"] = record["c"] if record else 0

            return stats
        except Exception as e:
            logger.error("[Neo4j] get_stats failed: %s", e)
            return {
                "available": False,
                "total_repos": 0,
                "total_patterns": 0,
                "total_categories": 0,
                "total_technologies": 0,
                "total_cooccurrences": 0,
                "total_relationships": 0,
            }

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def clear_all(self) -> bool:
        """Delete all nodes and relationships. USE WITH CAUTION.

        Returns:
            True if successful, False otherwise.
        """
        if not self.is_available():
            return False

        try:
            with self._driver.session() as session:
                session.run("MATCH (n) DETACH DELETE n")
            logger.warning("[Neo4j] All graph data cleared")
            return True
        except Exception as e:
            logger.error("[Neo4j] clear_all failed: %s", e)
            return False
