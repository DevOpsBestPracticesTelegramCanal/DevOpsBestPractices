"""
Week 28: 50-Task Benchmark Suite (extends benchmark_25)

Adds 25 more tasks across 5 additional domains:
  6. Security (5 tasks)
  7. Web & API (5 tasks)
  8. Database (5 tasks)
  9. Testing & Quality (5 tasks)
  10. Integration & Advanced (5 tasks)

Combined with benchmark_25.py, provides 50 tasks across 10 domains
for comprehensive code generation quality measurement.

Usage:
    # Run all 50 tasks:
    python -m pytest tests/benchmark_50.py tests/benchmark_25.py -v

    # Run extended tasks only:
    python -m pytest tests/benchmark_50.py -v
"""

import re
import pytest
from typing import Dict, List, Optional

from .benchmark_25 import BenchmarkTask, get_all_domains as get_base_domains


# ---------------------------------------------------------------------------
# Extended Task Definitions: 25 more tasks across 5 new domains
# ---------------------------------------------------------------------------

EXTENDED_TASKS: List[BenchmarkTask] = [
    # ===== Security (5 tasks) =====
    BenchmarkTask(
        task_id="sec_01",
        domain="security",
        prompt="Write an OAuth2 authorization server with PKCE flow. Include: authorization endpoint, token endpoint, PKCE code_verifier/code_challenge validation (S256), refresh token rotation, and token revocation.",
        expected_patterns=[
            r"class\s+\w*(OAuth|Auth|Server)",
            r"code_verifier|code_challenge|PKCE|pkce",
            r"access_token|refresh_token",
            r"def\s+\w*(authorize|token|revoke)",
        ],
        forbidden_patterns=[r"eval\(", r"exec\("],
        min_lines=60,
        complexity="CRITICAL",
        description="OAuth2 with PKCE flow",
    ),
    BenchmarkTask(
        task_id="sec_02",
        domain="security",
        prompt="Write an input sanitizer class that prevents XSS and SQL injection. Support: HTML entity encoding, SQL parameterization helper, URL validation, path traversal prevention, and configurable allow-lists.",
        expected_patterns=[
            r"class\s+\w*(Sanitiz|Input|Validator)",
            r"html\.escape|escape|entity",
            r"sql|inject|parameteriz",
            r"path.*travers|\.\.\/",
        ],
        forbidden_patterns=[r"eval\(", r"exec\("],
        min_lines=40,
        complexity="COMPLEX",
        description="Input sanitizer for XSS/SQLI",
    ),
    BenchmarkTask(
        task_id="sec_03",
        domain="security",
        prompt="Write an HMAC-based API request signing class. Support: request signing with HMAC-SHA256, timestamp validation (prevent replay attacks), nonce tracking, signature verification, and multi-key support.",
        expected_patterns=[
            r"class\s+\w*(Sign|HMAC|Auth)",
            r"hmac|HMAC",
            r"sha256|SHA256",
            r"timestamp|nonce",
            r"def\s+\w*(sign|verify)",
        ],
        forbidden_patterns=[r"eval\("],
        min_lines=40,
        complexity="COMPLEX",
        description="HMAC API signing",
    ),
    BenchmarkTask(
        task_id="sec_04",
        domain="security",
        prompt="Write a secrets manager class with encryption at rest. Support: AES-GCM encryption, key derivation with PBKDF2, secure secret storage/retrieval, key rotation, and audit logging of access.",
        expected_patterns=[
            r"class\s+\w*(Secret|Vault|Encrypt)",
            r"AES|aes|GCM|gcm",
            r"PBKDF2|pbkdf2|key_deriv",
            r"encrypt|decrypt",
            r"audit|log",
        ],
        forbidden_patterns=[r"eval\(", r"ECB|ecb"],
        min_lines=50,
        complexity="CRITICAL",
        description="Secrets manager with encryption",
    ),
    BenchmarkTask(
        task_id="sec_05",
        domain="security",
        prompt="Write a rate-limiting middleware with IP blocking. Support: sliding window rate limiting, configurable limits per endpoint, automatic IP blocking after threshold, whitelist/blacklist, and Redis-backed storage.",
        expected_patterns=[
            r"class\s+\w*(Rate|Limit|Middleware)",
            r"sliding.*window|window",
            r"ip|IP|block",
            r"redis|Redis",
            r"whitelist|blacklist|allow|deny",
        ],
        forbidden_patterns=[r"eval\("],
        min_lines=40,
        complexity="COMPLEX",
        description="Rate limiter with IP blocking",
    ),

    # ===== Web & API (5 tasks) =====
    BenchmarkTask(
        task_id="web_01",
        domain="web_api",
        prompt="Write a WebSocket chat server with room support. Include: room creation/joining, message broadcasting per room, user presence tracking, message history (last N messages), and graceful disconnect handling.",
        expected_patterns=[
            r"class\s+\w*(Chat|WebSocket|Server|Room)",
            r"async\s+def",
            r"room|Room",
            r"broadcast|send",
            r"connect|disconnect",
        ],
        forbidden_patterns=[r"eval\("],
        min_lines=50,
        complexity="COMPLEX",
        description="WebSocket chat with rooms",
    ),
    BenchmarkTask(
        task_id="web_02",
        domain="web_api",
        prompt="Write a GraphQL resolver class with cursor-based pagination. Support: forward/backward pagination, total count, has_next_page/has_previous_page, cursor encoding/decoding, and N+1 query prevention with dataloader pattern.",
        expected_patterns=[
            r"class\s+\w*(Resolver|GraphQL|Query)",
            r"cursor|Cursor",
            r"pagination|page|edge",
            r"has_next|has_prev",
            r"dataloader|DataLoader|batch",
        ],
        forbidden_patterns=[r"eval\("],
        min_lines=40,
        complexity="COMPLEX",
        description="GraphQL with cursor pagination",
    ),
    BenchmarkTask(
        task_id="web_03",
        domain="web_api",
        prompt="Write a Server-Sent Events (SSE) streaming endpoint class. Support: event type routing, client connection management, heartbeat/keepalive, retry configuration, last-event-id for reconnection, and graceful shutdown.",
        expected_patterns=[
            r"class\s+\w*(SSE|Stream|Event)",
            r"text/event-stream|event-stream",
            r"data:|event:|id:",
            r"heartbeat|keepalive|ping",
            r"retry|reconnect|last.event",
        ],
        forbidden_patterns=[r"eval\("],
        min_lines=40,
        complexity="MODERATE",
        description="SSE streaming endpoint",
    ),
    BenchmarkTask(
        task_id="web_04",
        domain="web_api",
        prompt="Write a file upload handler with virus scanning hook. Support: chunked upload for large files, file type validation (magic bytes), size limits, virus scan callback interface, and temporary file cleanup.",
        expected_patterns=[
            r"class\s+\w*(Upload|File|Handler)",
            r"chunk|Chunk",
            r"magic|mime|file_type",
            r"scan|virus|callback",
            r"cleanup|temp|temporary",
        ],
        forbidden_patterns=[r"eval\(", r"exec\("],
        min_lines=40,
        complexity="COMPLEX",
        description="File upload with virus scanning",
    ),
    BenchmarkTask(
        task_id="web_05",
        domain="web_api",
        prompt="Write an API gateway class with request/response transformation. Support: path-based routing to backend services, request header injection, response body transformation, circuit breaker per backend, and request logging.",
        expected_patterns=[
            r"class\s+\w*(Gateway|Router|Proxy)",
            r"def\s+\w*(route|forward|proxy)",
            r"header|Header",
            r"transform|Transform",
            r"circuit|breaker|backend",
        ],
        forbidden_patterns=[r"eval\("],
        min_lines=50,
        complexity="COMPLEX",
        description="API gateway with transformation",
    ),

    # ===== Database (5 tasks) =====
    BenchmarkTask(
        task_id="db_01",
        domain="database",
        prompt="Write a SQLite migration system with up/down support. Include: migration file discovery, version tracking table, ordered execution, rollback support, and dry-run mode. Each migration is a Python function.",
        expected_patterns=[
            r"class\s+\w*(Migrat|Schema|Version)",
            r"def\s+\w*(up|upgrade|forward)",
            r"def\s+\w*(down|rollback|backward)",
            r"CREATE TABLE|version|migration",
            r"dry.run|simulate",
        ],
        forbidden_patterns=[r"eval\(", r"exec\("],
        min_lines=50,
        complexity="COMPLEX",
        description="SQLite migration system",
    ),
    BenchmarkTask(
        task_id="db_02",
        domain="database",
        prompt="Write a database connection pooler with read replica support. Include: primary for writes, replica selection for reads (round-robin), health checking, automatic failover, and connection lifecycle management.",
        expected_patterns=[
            r"class\s+\w*(Pool|Connection)",
            r"primary|master|write",
            r"replica|read|slave",
            r"round.robin|select|route",
            r"health|failover|check",
        ],
        forbidden_patterns=[r"eval\("],
        min_lines=50,
        complexity="COMPLEX",
        description="Connection pooler with read replicas",
    ),
    BenchmarkTask(
        task_id="db_03",
        domain="database",
        prompt="Write a full-text search engine using BM25 scoring algorithm. Include: document indexing, tokenization, inverted index, BM25 ranking with configurable k1/b parameters, and search with pagination.",
        expected_patterns=[
            r"class\s+\w*(Search|Index|BM25)",
            r"BM25|bm25|tf.idf|idf",
            r"def\s+\w*(index|search|query)",
            r"tokeniz|token",
            r"inverted|posting",
        ],
        forbidden_patterns=[r"eval\("],
        min_lines=50,
        complexity="COMPLEX",
        description="BM25 full-text search engine",
    ),
    BenchmarkTask(
        task_id="db_04",
        domain="database",
        prompt="Write an event sourcing system with snapshot support. Include: event store (append-only), event replay for state reconstruction, periodic snapshots for performance, event versioning, and projection builder.",
        expected_patterns=[
            r"class\s+\w*(Event|Store|Sourcing|Aggregate)",
            r"def\s+\w*(append|apply|replay)",
            r"snapshot|Snapshot",
            r"projection|Projection|rebuild",
            r"version|Version",
        ],
        forbidden_patterns=[r"eval\("],
        min_lines=50,
        complexity="CRITICAL",
        description="Event sourcing with snapshots",
    ),
    BenchmarkTask(
        task_id="db_05",
        domain="database",
        prompt="Write a database audit trail system using triggers (Python-simulated). Include: automatic change tracking (INSERT/UPDATE/DELETE), old/new value recording, user attribution, timestamp, and audit log querying with filters.",
        expected_patterns=[
            r"class\s+\w*(Audit|Trail|Change|Track)",
            r"INSERT|UPDATE|DELETE|insert|update|delete",
            r"old_value|new_value|before|after",
            r"user|actor|who",
            r"timestamp|when|created_at",
        ],
        forbidden_patterns=[r"eval\("],
        min_lines=40,
        complexity="MODERATE",
        description="Database audit trail",
    ),

    # ===== Testing & Quality (5 tasks) =====
    BenchmarkTask(
        task_id="test_01",
        domain="testing",
        prompt="Write a property-based test generator class. Support: generating random integers, strings, lists, dicts with configurable constraints (min/max, length, charset), shrinking failed cases to minimal example, and reproducible seeds.",
        expected_patterns=[
            r"class\s+\w*(Generator|Property|Fuzzer)",
            r"def\s+\w*(generate|random|integers|strings)",
            r"shrink|minimal|reduce",
            r"seed|reproduc",
        ],
        forbidden_patterns=[r"eval\("],
        min_lines=50,
        complexity="COMPLEX",
        description="Property-based test generator",
    ),
    BenchmarkTask(
        task_id="test_02",
        domain="testing",
        prompt="Write a mock HTTP server class for testing external API calls. Support: registering endpoint handlers, request recording, response templating (status code, headers, body), latency simulation, and assertion helpers.",
        expected_patterns=[
            r"class\s+\w*(Mock|Server|Stub)",
            r"def\s+\w*(register|add_route|handle)",
            r"request|response",
            r"status|header|body",
            r"assert|verify|record",
        ],
        forbidden_patterns=[r"eval\("],
        min_lines=40,
        complexity="MODERATE",
        description="Mock HTTP server for testing",
    ),
    BenchmarkTask(
        task_id="test_03",
        domain="testing",
        prompt="Write a load test harness class. Support: concurrent request generation (threads/async), configurable RPS target, response time percentiles (p50, p95, p99), error rate tracking, and HTML/JSON report generation.",
        expected_patterns=[
            r"class\s+\w*(Load|Stress|Harness|Bench)",
            r"concurrent|thread|async",
            r"p50|p95|p99|percentile",
            r"rps|RPS|requests_per_second",
            r"report|result|summary",
        ],
        forbidden_patterns=[r"eval\("],
        min_lines=50,
        complexity="COMPLEX",
        description="Load test harness with stats",
    ),
    BenchmarkTask(
        task_id="test_04",
        domain="testing",
        prompt="Write a mutation testing framework for Python. Support: AST-based code mutations (operator replacement, constant modification, statement deletion), test execution per mutation, survival analysis, and mutation score calculation.",
        expected_patterns=[
            r"class\s+\w*(Mutat|Mutant)",
            r"ast\.|AST",
            r"def\s+\w*(mutate|apply|generate)",
            r"surviv|kill|detect",
            r"score|ratio",
        ],
        forbidden_patterns=[],
        min_lines=50,
        complexity="CRITICAL",
        description="Mutation testing framework",
    ),
    BenchmarkTask(
        task_id="test_05",
        domain="testing",
        prompt="Write a code coverage aggregator class. Support: merging coverage data from multiple test runs, per-file and per-function coverage calculation, uncovered line identification, trend tracking over time, and coverage report generation.",
        expected_patterns=[
            r"class\s+\w*(Coverage|Aggregat|Report)",
            r"def\s+\w*(merge|aggregate|combine)",
            r"line|function|branch",
            r"uncovered|missing",
            r"report|summary|percent",
        ],
        forbidden_patterns=[r"eval\("],
        min_lines=40,
        complexity="MODERATE",
        description="Code coverage aggregator",
    ),

    # ===== Integration & Advanced (5 tasks) =====
    BenchmarkTask(
        task_id="int_01",
        domain="integration",
        prompt="Write an in-memory pub/sub message broker. Support: topic creation, subscriber registration with filters, message publishing with delivery guarantees (at-least-once), dead letter queue for failed deliveries, and message TTL.",
        expected_patterns=[
            r"class\s+\w*(Broker|PubSub|Message)",
            r"def\s+\w*(publish|subscribe|unsubscribe)",
            r"topic|Topic|channel",
            r"dead.letter|dlq|failed",
            r"ttl|TTL|expir",
        ],
        forbidden_patterns=[r"eval\("],
        min_lines=50,
        complexity="COMPLEX",
        description="In-memory pub/sub broker",
    ),
    BenchmarkTask(
        task_id="int_02",
        domain="integration",
        prompt="Write a job scheduler with cron expression parsing. Support: standard cron syntax (minute, hour, day, month, weekday), next-run calculation, job registration with callbacks, concurrent execution control, and missed job handling.",
        expected_patterns=[
            r"class\s+\w*(Scheduler|Cron|Job)",
            r"def\s+\w*(schedule|next|parse|run)",
            r"cron|minute|hour|day",
            r"callback|func|handler",
            r"concurrent|lock|running",
        ],
        forbidden_patterns=[r"eval\("],
        min_lines=50,
        complexity="COMPLEX",
        description="Job scheduler with cron",
    ),
    BenchmarkTask(
        task_id="int_03",
        domain="integration",
        prompt="Write a structured log aggregator. Support: JSON log parsing, field extraction, log level filtering, time-range queries, pattern matching across log entries, and summary statistics (error rates, latency percentiles).",
        expected_patterns=[
            r"class\s+\w*(Log|Aggregat|Collector)",
            r"json|JSON",
            r"level|severity|ERROR|WARNING",
            r"def\s+\w*(parse|query|filter|search)",
            r"percentile|p95|stats|summary",
        ],
        forbidden_patterns=[r"eval\("],
        min_lines=40,
        complexity="MODERATE",
        description="Structured log aggregator",
    ),
    BenchmarkTask(
        task_id="int_04",
        domain="integration",
        prompt="Write a health check orchestrator for microservices. Support: registering async health check functions per service, parallel execution with per-check timeout, aggregate status (healthy/degraded/unhealthy), dependency-aware checks, and status page endpoint.",
        expected_patterns=[
            r"class\s+\w*(Health|Orchestrat|Check)",
            r"async\s+def",
            r"healthy|degraded|unhealthy",
            r"timeout|asyncio\.wait_for",
            r"dependency|depends",
        ],
        forbidden_patterns=[r"eval\("],
        min_lines=50,
        complexity="COMPLEX",
        description="Health check orchestrator",
    ),
    BenchmarkTask(
        task_id="int_05",
        domain="integration",
        prompt="Write a feature flag system with percentage rollout. Support: flag registration with metadata, consistent hashing for user-based rollout, A/B experiment support, flag dependency rules, and admin API for flag management.",
        expected_patterns=[
            r"class\s+\w*(Feature|Flag|Manager)",
            r"rollout|percent",
            r"hash|consistent|deterministic",
            r"def\s+\w*(is_enabled|check|evaluate)",
            r"experiment|variant|ab",
        ],
        forbidden_patterns=[r"eval\("],
        min_lines=40,
        complexity="MODERATE",
        description="Feature flags with rollout",
    ),
]

# Build lookup by task_id
_EXT_TASKS_BY_ID: Dict[str, BenchmarkTask] = {t.task_id: t for t in EXTENDED_TASKS}
_EXT_TASKS_BY_DOMAIN: Dict[str, List[BenchmarkTask]] = {}
for _t in EXTENDED_TASKS:
    _EXT_TASKS_BY_DOMAIN.setdefault(_t.domain, []).append(_t)

# Combined tasks (all 50)
ALL_50_TASKS: List[BenchmarkTask] = []
try:
    from .benchmark_25 import BENCHMARK_TASKS as BASE_TASKS
    ALL_50_TASKS = list(BASE_TASKS) + list(EXTENDED_TASKS)
except ImportError:
    ALL_50_TASKS = list(EXTENDED_TASKS)


def get_extended_task(task_id: str) -> Optional[BenchmarkTask]:
    return _EXT_TASKS_BY_ID.get(task_id)


def get_extended_domains() -> List[str]:
    return list(_EXT_TASKS_BY_DOMAIN.keys())


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestExtendedBenchmarkDefinitions:
    """Validate extended benchmark task definitions."""

    def test_extended_task_count(self):
        assert len(EXTENDED_TASKS) == 25, f"Expected 25 extended tasks, got {len(EXTENDED_TASKS)}"

    def test_combined_total_is_50(self):
        assert len(ALL_50_TASKS) == 50, f"Expected 50 total tasks, got {len(ALL_50_TASKS)}"

    def test_unique_task_ids_across_all(self):
        ids = [t.task_id for t in ALL_50_TASKS]
        duplicates = [i for i in ids if ids.count(i) > 1]
        assert len(ids) == len(set(ids)), f"Duplicate IDs: {duplicates}"

    def test_five_new_domains(self):
        domains = set(t.domain for t in EXTENDED_TASKS)
        assert len(domains) == 5, f"Expected 5 new domains, got {domains}"

    def test_no_overlap_with_base_domains(self):
        ext_domains = set(t.domain for t in EXTENDED_TASKS)
        base_domains = set(get_base_domains())
        overlap = ext_domains & base_domains
        assert not overlap, f"Domain overlap with base: {overlap}"

    def test_ten_domains_total(self):
        all_domains = set(t.domain for t in ALL_50_TASKS)
        assert len(all_domains) == 10, f"Expected 10 total domains, got {all_domains}"

    def test_five_tasks_per_extended_domain(self):
        for domain, tasks in _EXT_TASKS_BY_DOMAIN.items():
            assert len(tasks) == 5, f"Domain '{domain}' has {len(tasks)} tasks"

    @pytest.mark.parametrize("task", EXTENDED_TASKS, ids=lambda t: t.task_id)
    def test_task_has_patterns(self, task):
        assert len(task.expected_patterns) >= 2
        assert len(task.prompt) > 20

    @pytest.mark.parametrize("task", EXTENDED_TASKS, ids=lambda t: t.task_id)
    def test_task_validation_on_empty(self, task):
        result = task.validate_output("")
        assert not result["passed"]

    def test_all_regex_valid(self):
        import re
        for task in EXTENDED_TASKS:
            for pattern in task.expected_patterns + task.forbidden_patterns:
                try:
                    re.compile(pattern)
                except re.error as e:
                    pytest.fail(f"{task.task_id}: invalid regex '{pattern}': {e}")

    def test_get_extended_task(self):
        task = get_extended_task("sec_01")
        assert task is not None
        assert task.domain == "security"

    def test_get_extended_domains(self):
        domains = get_extended_domains()
        assert "security" in domains
        assert "web_api" in domains
        assert "database" in domains
        assert "testing" in domains
        assert "integration" in domains
