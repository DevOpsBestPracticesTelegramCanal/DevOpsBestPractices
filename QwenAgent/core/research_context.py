"""
Week 23→25: Research Context — Config, LocalSearcher, QueryDecomposer, ContextFormatter

Provides the infrastructure for ResearchAgent to search local SQLite databases
(news, releases, CVE) and format findings for LLM context injection.

Week 25: Smart aspect-based query decomposition for code generation.
Based on: ParallelSearch (arXiv:2508.09303), DecomposeRAG (UC Berkeley),
NVIDIA RAG Blueprint query decomposition pattern.

Key classes:
    ResearchConfig   — tuning knobs for the research pipeline
    LocalResult      — a single result from SQLite search
    LocalSearcher    — read-only FTS5 searcher across news + releases DBs
    QueryDecomposer  — aspect-based decomposition for code-gen, pattern-based for generic
    ContextFormatter — formats results as structured LLM context (grouped by aspect)
"""

import os
import re
import sqlite3
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_DEFAULT_NEWS_DB = os.path.join(
    os.path.expanduser("~"), "ContainerNewsLocal", "data", "news_database.db"
)
_DEFAULT_RELEASES_DB = os.path.join(
    os.path.expanduser("~"), "ContainerNewsLocal", "data", "releases_database.db"
)


@dataclass
class ResearchConfig:
    """Tuning knobs for the research pipeline."""

    max_sub_queries: int = 4
    max_web_results: int = 8
    max_local_results: int = 5
    max_context_chars: int = 4000
    web_search_timeout: float = 10.0
    local_search_enabled: bool = True
    news_db_path: str = ""
    releases_db_path: str = ""
    search_backend: str = "auto"  # "searxng" | "duckduckgo" | "auto"

    def __post_init__(self):
        if not self.news_db_path:
            self.news_db_path = _DEFAULT_NEWS_DB
        if not self.releases_db_path:
            self.releases_db_path = _DEFAULT_RELEASES_DB


# ---------------------------------------------------------------------------
# Local search result
# ---------------------------------------------------------------------------

@dataclass
class LocalResult:
    """A single result from SQLite FTS5 search."""

    table: str          # "news" | "releases" | "cve" | "events"
    title: str
    url: str
    summary: str
    relevance: float    # BM25 rank (lower = more relevant)
    db_name: str        # "news_database.db" | "releases_database.db"


# ---------------------------------------------------------------------------
# Local Searcher
# ---------------------------------------------------------------------------

class LocalSearcher:
    """Read-only SQLite FTS5 searcher across news + releases databases."""

    def __init__(self, db_paths: Optional[Dict[str, str]] = None):
        self.db_paths = db_paths or {}

    # ------ public API ------

    def search_news(self, query: str, limit: int = 5) -> List[LocalResult]:
        """FTS5 search in news table — returns articles with links."""
        db_path = self.db_paths.get("news", "")
        if not db_path or not os.path.isfile(db_path):
            return []

        fts_query = self._build_fts_query(query)
        if not fts_query:
            return []

        sql = """
            SELECT n.name, n.link, n.summary_en,
                   bm25(fts_unified_content) AS rank
            FROM fts_unified_content fts
            JOIN news n ON n.id = fts.rowid
            WHERE fts_unified_content MATCH ?
            ORDER BY rank
            LIMIT ?
        """
        return self._execute_search(
            db_path, sql, (fts_query, limit), "news", "news_database.db"
        )

    def search_news_like(self, query: str, limit: int = 5) -> List[LocalResult]:
        """Fallback LIKE search when FTS5 table is unavailable."""
        db_path = self.db_paths.get("news", "")
        if not db_path or not os.path.isfile(db_path):
            return []

        keywords = self._extract_keywords(query)
        if not keywords:
            return []

        conditions = " OR ".join(
            ["(name LIKE ? OR summary_en LIKE ? OR keywords LIKE ?)"] * len(keywords)
        )
        params: List[Any] = []
        for kw in keywords:
            pattern = f"%{kw}%"
            params.extend([pattern, pattern, pattern])
        params.append(limit)

        sql = f"""
            SELECT name, link, summary_en, 0.0 AS rank
            FROM news
            WHERE {conditions}
            ORDER BY pub_date DESC
            LIMIT ?
        """
        return self._execute_search(
            db_path, sql, tuple(params), "news", "news_database.db"
        )

    def search_releases(self, query: str, limit: int = 5) -> List[LocalResult]:
        """Search releases table for matching technology."""
        db_path = self.db_paths.get("releases", "")
        if not db_path or not os.path.isfile(db_path):
            return []

        keywords = self._extract_keywords(query)
        if not keywords:
            return []

        conditions = " OR ".join(
            ["(name LIKE ? OR description LIKE ?)"] * len(keywords)
        )
        params: List[Any] = []
        for kw in keywords:
            pattern = f"%{kw}%"
            params.extend([pattern, pattern])
        params.append(limit)

        sql = f"""
            SELECT name, link, summary_en, 0.0 AS rank
            FROM releases
            WHERE {conditions}
            ORDER BY published_at DESC
            LIMIT ?
        """
        return self._execute_search(
            db_path, sql, tuple(params), "releases", "releases_database.db"
        )

    def search_cve(self, query: str, limit: int = 5) -> List[LocalResult]:
        """Search CVE vulnerabilities if query is security-related."""
        db_path = self.db_paths.get("releases", "")
        if not db_path or not os.path.isfile(db_path):
            return []

        keywords = self._extract_keywords(query)
        if not keywords:
            return []

        conditions = " OR ".join(
            ["(cve_id LIKE ? OR description LIKE ?)"] * len(keywords)
        )
        params: List[Any] = []
        for kw in keywords:
            pattern = f"%{kw}%"
            params.extend([pattern, pattern])
        params.append(limit)

        sql = f"""
            SELECT cve_id, '', description, 0.0 AS rank
            FROM cve_vulnerabilities
            WHERE {conditions}
            ORDER BY published_date DESC
            LIMIT ?
        """
        results = self._execute_search(
            db_path, sql, tuple(params), "cve", "releases_database.db"
        )
        # CVE results: title = cve_id, url = empty, summary = description
        for r in results:
            r.title = r.title or "CVE"
        return results

    # ------ helpers ------

    def _execute_search(
        self, db_path: str, sql: str, params: tuple,
        table: str, db_name: str,
    ) -> List[LocalResult]:
        """Run read-only query, return LocalResult list."""
        results: List[LocalResult] = []
        try:
            conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(sql, params)
            for row in cursor.fetchall():
                cols = [desc[0] for desc in cursor.description]
                title = str(row[0] or "")
                url = str(row[1] or "")
                summary = str(row[2] or "")
                rank = float(row[3]) if row[3] else 0.0
                results.append(LocalResult(
                    table=table,
                    title=title[:200],
                    url=url,
                    summary=summary[:500],
                    relevance=rank,
                    db_name=db_name,
                ))
            conn.close()
        except Exception as exc:
            logger.warning("LocalSearcher: %s query failed: %s", table, exc)
        return results

    @staticmethod
    def _build_fts_query(query: str) -> str:
        """Convert user query to FTS5 MATCH expression."""
        # Extract meaningful words (3+ chars, alphanumeric)
        words = re.findall(r'[a-zA-Z0-9\-]{3,}', query)
        if not words:
            return ""
        # FTS5: OR-join all words for broad matching
        return " OR ".join(words[:8])

    @staticmethod
    def _extract_keywords(query: str) -> List[str]:
        """Extract search keywords from query (3+ char words)."""
        words = re.findall(r'[a-zA-Z0-9\-]{3,}', query)
        # Deduplicate, keep order, max 6
        seen = set()
        result = []
        for w in words:
            wl = w.lower()
            if wl not in seen:
                seen.add(wl)
                result.append(wl)
            if len(result) >= 6:
                break
        return result


# ---------------------------------------------------------------------------
# Query Decomposer (Week 25: Aspect-based for code-gen)
# ---------------------------------------------------------------------------

class QueryDecomposer:
    """Smart query decomposition — aspect-based for code-gen, pattern-based for generic.

    For code generation tasks (decorator, API, middleware, etc.), decomposes the
    query by *feature aspects* (caching, retry, timeout...), generating one focused
    sub-query per aspect with relevant library names.  Each search targets a
    specific technical concern without overlap, following the ParallelSearch
    pattern (arXiv:2508.09303).

    For generic tasks (infra, DevOps, etc.), falls back to tech+action decomposition.
    """

    # --- Generic patterns (tech / action / security detection) ---

    _TECH_PATTERNS = re.compile(
        r'\b('
        r'kubernetes|k8s|docker|terraform|helm|ansible|'
        r'fastapi|flask|django|react|vue|angular|'
        r'postgres|mysql|redis|kafka|rabbitmq|'
        r'nginx|envoy|istio|linkerd|'
        r'grafana|prometheus|datadog|'
        r'aws|gcp|azure|'
        r'jenkins|gitlab|github.actions|argocd|argo.cd|'
        r'python|golang|rust|java|typescript|'
        r'containerd|podman|buildah|kaniko|'
        r'vault|consul|etcd|'
        r'elasticsearch|opensearch|kibana'
        r')\b',
        re.IGNORECASE,
    )

    _ACTION_PATTERNS = re.compile(
        r'\b('
        r'deploy|configure|setup|install|migrate|upgrade|'
        r'fix|debug|troubleshoot|resolve|'
        r'optimize|performance|scale|'
        r'secure|harden|vulnerability|'
        r'monitor|alert|log|trace|'
        r'test|benchmark|validate|'
        r'create|build|implement|write|develop'
        r')\b',
        re.IGNORECASE,
    )

    _SECURITY_MARKERS = re.compile(
        r'\b(CVE|security|vuln|exploit|injection|XSS|CSRF|auth)\b',
        re.IGNORECASE,
    )

    # --- Code-gen: feature aspect detection (word-boundary safe) ---

    _FEATURE_PATTERNS: List = [
        (re.compile(r'\bcach(?:e|ing|ed)?\b', re.I), "caching"),
        (re.compile(r'\bmemoiz(?:e|ation|ing)?\b', re.I), "caching"),
        (re.compile(r'\bretr(?:y|ies|ying)\b', re.I), "retry"),
        (re.compile(r'\bbackoff\b', re.I), "retry"),
        (re.compile(r'\btimeout\b', re.I), "timeout"),
        (re.compile(r'\blog(?:ging|ger)?\b', re.I), "logging"),
        (re.compile(r'\bauth(?:entication|orization)?\b', re.I), "auth"),
        (re.compile(r'\bjwt\b', re.I), "auth"),
        (re.compile(r'\boauth2?\b', re.I), "auth"),
        (re.compile(r'\brate[\s_-]?limit', re.I), "rate_limit"),
        (re.compile(r'\bthrottl(?:e|ing)\b', re.I), "rate_limit"),
        (re.compile(r'\bvalid(?:at(?:e|ion|or|ing))?\b', re.I), "validation"),
        (re.compile(r'\bmiddleware\b', re.I), "middleware"),
        (re.compile(r'\basync\b', re.I), "async"),
        (re.compile(r'\bconcurren(?:t|cy)\b', re.I), "concurrency"),
        (re.compile(r'\bthread[\s_-]?safe', re.I), "concurrency"),
        (re.compile(r'\bencrypt(?:ion|ing)?\b', re.I), "security"),
        (re.compile(r'\bcircuit[\s_-]?break', re.I), "resilience"),
        (re.compile(r'\bfallback\b', re.I), "resilience"),
        (re.compile(r'\bmetric(?:s)?\b', re.I), "observability"),
        (re.compile(r'\binstrument', re.I), "observability"),
        (re.compile(r'\bdatabas(?:e|es)?\b', re.I), "database"),
        (re.compile(r'\borm\b', re.I), "database"),
        (re.compile(r'\bpool(?:ing)?\b', re.I), "pooling"),
        (re.compile(r'\bqueue\b', re.I), "queue"),
    ]

    # Focused search template per aspect.
    # {tech} = detected context (decorator, API, middleware, etc.)
    # Each query targets one concern with specific library/pattern names.
    _ASPECT_QUERIES: Dict[str, str] = {
        "caching":       "python {tech} cachetools TTLCache vs lru_cache unhashable args thread-safe example",
        "retry":         "python retry {tech} tenacity backoff exponential jitter callback logging best practices",
        "timeout":       "python function timeout {tech} signal.alarm vs asyncio.wait_for concurrent.futures example",
        "logging":       "python logging {tech} structlog functools.wraps signature preservation decorator example",
        "auth":          "python authentication {tech} JWT decorator flask best practices",
        "rate_limit":    "python rate limiting {tech} token bucket decorator example",
        "validation":    "python input validation {tech} pydantic decorator example",
        "middleware":    "python {tech} middleware chain-of-responsibility pattern example",
        "async":         "python async {tech} asyncio decorator event loop example",
        "concurrency":   "python thread safety {tech} lock ThreadPoolExecutor GIL example",
        "security":      "python {tech} security encryption OWASP cryptography best practices",
        "resilience":    "python circuit breaker {tech} pybreaker tenacity fallback example",
        "observability": "python metrics tracing {tech} prometheus OpenTelemetry decorator example",
        "database":      "python {tech} database connection pool SQLAlchemy context manager example",
        "pooling":       "python {tech} connection pool resource management context manager example",
        "queue":         "python {tech} queue producer consumer threading asyncio example",
    }

    # Main tech context detectors — what is being built (decorator, API, ...)
    _CONTEXT_PATTERNS: List = [
        (re.compile(r'\bdecor(?:ator|ating)?\b', re.I), "decorator"),
        (re.compile(r'\bmiddleware\b', re.I), "middleware"),
        (re.compile(r'\b(?:api|endpoint)\b', re.I), "API"),
        (re.compile(r'\bwrapper\b', re.I), "wrapper"),
        (re.compile(r'\bplugin\b', re.I), "plugin"),
        (re.compile(r'\bclass(?:es)?\b', re.I), "class"),
        (re.compile(r'\bfunc(?:tion)?(?:s)?\b', re.I), "function"),
        (re.compile(r'\bserver\b', re.I), "server"),
        (re.compile(r'\bclient\b', re.I), "client"),
        (re.compile(r'\bcli\b', re.I), "CLI"),
        (re.compile(r'\bpipeline\b', re.I), "pipeline"),
        (re.compile(r'\bservice\b', re.I), "service"),
    ]

    # ---- Public API ----

    def decompose(self, query: str, task_type: str = "",
                  complexity: str = "") -> List[str]:
        """Split complex query into 2-4 focused search sub-queries.

        For code generation tasks, uses **aspect-based decomposition**: each
        requested feature (caching, retry, timeout, ...) gets its own focused
        search query with relevant library names and best practices keywords.

        For other tasks, falls back to generic tech+action decomposition.

        Returns:
            List of 1-4 search query strings, each targeting a distinct concern.
        """
        # Code generation: aspect-based decomposition
        if task_type in ("code_gen", "bug_fix", "refactor"):
            aspects = self._extract_aspects(query)
            if len(aspects) >= 2:
                result = self._decompose_codegen(query, aspects)
                if result:
                    logger.info(
                        "[QueryDecomposer] codegen decomposition: %d aspects %s -> %d queries",
                        len(aspects), aspects, len(result),
                    )
                    return result

        # Generic decomposition (infra, commands, non-code, single-aspect)
        return self._decompose_generic(query, task_type)

    # ---- Aspect-based decomposition (code-gen) ----

    def _decompose_codegen(self, query: str, aspects: List[str]) -> List[str]:
        """Generate one focused sub-query per feature aspect.

        Example for "write decorator with caching, retry, timeout":
          aspects = ["caching", "retry", "timeout"]
          ->
          [
            "python decorator caching thread-safe lru_cache cachetools TTLCache example",
            "python retry decorator tenacity backoff exponential logging best practices",
            "python function timeout decorator concurrent.futures ThreadPoolExecutor example",
            "python decorator caching retry timeout combined production example",
          ]
        """
        tech = self._detect_tech_context(query) or "function"
        sub_queries: List[str] = []

        for aspect in aspects[:3]:
            template = self._ASPECT_QUERIES.get(aspect)
            if template:
                sub_queries.append(template.replace("{tech}", tech))

        # Composition query: how to combine all aspects together
        if len(aspects) >= 2:
            sub_queries.append(
                f"composing multiple python {tech}s execution order functools.wraps signature preservation"
            )

        # Universality query: sync + async support
        if tech in ("decorator", "wrapper", "function"):
            sub_queries.append(
                f"python universal {tech} sync async iscoroutinefunction inspect"
            )

        return self._deduplicate(sub_queries)[:5]

    def _extract_aspects(self, query: str) -> List[str]:
        """Extract feature aspects from query (preserves order, deduplicates)."""
        found: Dict[str, bool] = {}
        for pattern, aspect in self._FEATURE_PATTERNS:
            if pattern.search(query) and aspect not in found:
                found[aspect] = True
        return list(found.keys())

    def _detect_tech_context(self, query: str) -> str:
        """Detect the main technology context (decorator, middleware, API, etc.)."""
        for pattern, context in self._CONTEXT_PATTERNS:
            if pattern.search(query):
                return context
        return ""

    # ---- Generic decomposition (non-code-gen / single-aspect) ----

    def _decompose_generic(self, query: str, task_type: str = "") -> List[str]:
        """Generic tech+action decomposition for non-code-gen tasks."""
        techs = list(set(m.lower() for m in self._TECH_PATTERNS.findall(query)))
        actions = list(set(m.lower() for m in self._ACTION_PATTERNS.findall(query)))
        is_security = bool(self._SECURITY_MARKERS.search(query))

        sub_queries: List[str] = []

        # Primary query: full original (cleaned)
        clean = re.sub(r'\[DEEP\]|\[SEARCH\]|--deep|--search', '', query).strip()
        if clean:
            sub_queries.append(f"{clean} best practices")

        # Tech-specific queries
        for tech in techs[:2]:
            if actions:
                sub_queries.append(f"{tech} {actions[0]} example python")
            else:
                sub_queries.append(f"{tech} best practices python")

        # Security-specific query
        if is_security and techs:
            sub_queries.append(f"{techs[0]} security vulnerability fix")

        # Bug fix pattern
        if task_type == "bug_fix" and techs:
            sub_queries.append(f"{techs[0]} common errors solutions")

        # Infrastructure pattern
        if task_type == "infra" and techs:
            sub_queries.append(f"{techs[0]} production configuration")

        return self._deduplicate(sub_queries)[:4]

    # ---- Helpers ----

    @staticmethod
    def _deduplicate(queries: List[str]) -> List[str]:
        """Remove duplicate queries (case-insensitive)."""
        seen: set = set()
        unique: List[str] = []
        for q in queries:
            ql = q.lower()
            if ql not in seen:
                seen.add(ql)
                unique.append(q)
        return unique


# ---------------------------------------------------------------------------
# Context Formatter (Week 25: aspect-grouped output)
# ---------------------------------------------------------------------------

class ContextFormatter:
    """Format research results as structured LLM context.

    When web results carry ``sub_query`` tags (from aspect-based decomposition),
    groups them by aspect for section-based context.  This gives the LLM
    clear, per-feature reference material instead of a flat noisy list.
    """

    def format(
        self,
        query: str,
        web_results: list,
        local_results: List[LocalResult],
        max_chars: int = 4000,
    ) -> str:
        """Build structured context string for pipeline injection."""
        parts: List[str] = []
        parts.append(f"## Research Context for: {query[:100]}")
        remaining = max_chars - len(parts[0]) - 50

        # Check if results carry sub_query tags (aspect decomposition)
        has_tags = any(
            getattr(r, "sub_query", "")
            for r in web_results
            if not isinstance(r, dict)
        )

        # Web sources section — grouped by aspect if tags present
        if web_results:
            if has_tags:
                web_section = self._format_web_grouped(web_results, remaining // 2)
            else:
                web_section = self._format_web_flat(web_results, remaining // 2)
            parts.append(web_section)
            remaining -= len(web_section)

        # Local knowledge section
        if local_results:
            local_section = self._format_local_results(
                local_results, max(remaining, 500)
            )
            parts.append(local_section)

        # Code snippets extracted from web results
        code_section = self._extract_code_snippets(web_results, 800)
        if code_section:
            parts.append(code_section)

        result = "\n\n".join(parts)
        if len(result) > max_chars:
            result = result[:max_chars - 3] + "..."
        return result

    # ---- Grouped web results (aspect-based) ----

    def _format_web_grouped(self, results: list, max_chars: int) -> str:
        """Group web results by sub_query aspect for structured context."""
        groups: Dict[str, list] = {}
        for r in results:
            tag = getattr(r, "sub_query", "") or "general"
            if isinstance(r, dict):
                tag = r.get("sub_query", "general")
            groups.setdefault(tag, []).append(r)

        lines: List[str] = []
        char_count = 0

        for tag, items in groups.items():
            label = self._aspect_label(tag)
            header = f"### {label} ({len(items)} sources)"
            if char_count + len(header) + 2 > max_chars:
                break
            lines.append(header)
            char_count += len(header) + 1

            for i, r in enumerate(items, 1):
                title = self._get_attr(r, "title", "")
                url = self._get_attr(r, "url", "")
                snippet = self._get_attr(r, "snippet", "")
                line = f"  {i}. [{title[:70]}]({url}) - {snippet[:120]}"
                if char_count + len(line) + 1 > max_chars:
                    break
                lines.append(line)
                char_count += len(line) + 1

        return "\n".join(lines)

    # ---- Flat web results (no tags) ----

    def _format_web_flat(self, results: list, max_chars: int) -> str:
        """Flat list of web results (no sub_query tags available)."""
        lines = [f"### Web Sources ({len(results)} found)"]
        char_count = len(lines[0])
        for i, r in enumerate(results, 1):
            title = self._get_attr(r, "title", "")
            url = self._get_attr(r, "url", "")
            snippet = self._get_attr(r, "snippet", "")
            line = f"{i}. [{title[:80]}]({url}) - {snippet[:150]}"
            if char_count + len(line) + 1 > max_chars:
                break
            lines.append(line)
            char_count += len(line) + 1
        return "\n".join(lines)

    # ---- Aspect label extraction ----

    @staticmethod
    def _aspect_label(sub_query: str) -> str:
        """Extract a readable section label from a search sub-query string."""
        aspect_keywords = [
            "caching", "retry", "timeout", "logging", "auth",
            "rate limiting", "validation", "middleware", "async",
            "thread safety", "security", "circuit breaker",
            "observability", "database", "pooling", "queue",
            "combined",
        ]
        sq_lower = sub_query.lower()
        for kw in aspect_keywords:
            if kw in sq_lower:
                return kw.replace("_", " ").title()
        # Fallback: first 40 chars
        return sub_query[:40] if sub_query != "general" else "General"

    # ---- Local results ----

    def _format_local_results(
        self, results: List[LocalResult], max_chars: int
    ) -> str:
        lines = [f"### Local Knowledge ({len(results)} matches)"]
        char_count = len(lines[0])
        for i, r in enumerate(results, 1):
            line = f"{i}. [{r.table}] {r.title[:80]} - {r.summary[:120]}"
            if r.url:
                line += f" ({r.url})"
            if char_count + len(line) + 1 > max_chars:
                break
            lines.append(line)
            char_count += len(line) + 1
        return "\n".join(lines)

    # ---- Code snippet extraction ----

    def _extract_code_snippets(self, web_results: list, max_chars: int) -> str:
        """Extract code blocks from web result snippets."""
        snippets: List[str] = []
        for r in web_results:
            code_blocks = getattr(r, "code_snippets", [])
            if isinstance(r, dict):
                code_blocks = r.get("code_snippets", [])
            for block in code_blocks:
                if block and len(block) > 20:
                    snippets.append(block)

        if not snippets:
            return ""

        parts = ["### Code Patterns Found"]
        char_count = len(parts[0])
        for snip in snippets[:3]:
            chunk = f"```\n{snip[:400]}\n```"
            if char_count + len(chunk) + 2 > max_chars:
                break
            parts.append(chunk)
            char_count += len(chunk) + 2

        return "\n".join(parts) if len(parts) > 1 else ""

    # ---- Helper ----

    @staticmethod
    def _get_attr(obj, name: str, default: str = "") -> str:
        """Get attribute from object or dict."""
        if isinstance(obj, dict):
            return obj.get(name, default)
        return getattr(obj, name, default)
