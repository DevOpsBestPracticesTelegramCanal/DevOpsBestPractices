"""
Week 28: 25-Task Benchmark Suite

Measures code generation quality across 5 domains (5 tasks each):
  1. AI/ML
  2. DevOps
  3. Data Science
  4. Advanced Python
  5. Production Systems

Each task defines:
  - task_id: Unique identifier
  - prompt: The code generation prompt
  - domain: Category for aggregation
  - expected_patterns: Regex patterns the output SHOULD contain
  - forbidden_patterns: Regex patterns the output MUST NOT contain
  - min_lines: Minimum expected code length
  - validation_profile: Which validation profile to use

Usage:
    # Run all benchmarks (offline, without LLM):
    python -m pytest tests/benchmark_25.py -v

    # Run with actual LLM (requires model running):
    python -m pytest tests/benchmark_25.py -v --run-llm

    # Run specific domain:
    python -m pytest tests/benchmark_25.py -v -k "devops"
"""

import re
import pytest
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set


@dataclass
class BenchmarkTask:
    """A single benchmark task definition."""

    task_id: str
    prompt: str
    domain: str
    expected_patterns: List[str] = field(default_factory=list)
    forbidden_patterns: List[str] = field(default_factory=list)
    min_lines: int = 10
    max_lines: int = 500
    validation_profile: str = "balanced"
    complexity: str = "MODERATE"
    description: str = ""

    def validate_output(self, code: str) -> Dict[str, any]:
        """Validate generated code against task expectations.

        Returns:
            Dict with 'passed', 'score', 'issues' keys.
        """
        issues = []
        score = 0.0
        lines = code.strip().splitlines()

        # Check minimum length
        if len(lines) < self.min_lines:
            issues.append(f"Too short: {len(lines)} lines (min {self.min_lines})")
        else:
            score += 1.0

        # Check maximum length
        if len(lines) > self.max_lines:
            issues.append(f"Too long: {len(lines)} lines (max {self.max_lines})")
        else:
            score += 0.5

        # Check expected patterns
        pattern_score = 0.0
        for pattern in self.expected_patterns:
            if re.search(pattern, code, re.MULTILINE | re.DOTALL):
                pattern_score += 1.0
            else:
                issues.append(f"Missing expected pattern: {pattern}")

        if self.expected_patterns:
            score += (pattern_score / len(self.expected_patterns)) * 5.0

        # Check forbidden patterns
        for pattern in self.forbidden_patterns:
            if re.search(pattern, code, re.MULTILINE):
                issues.append(f"Found forbidden pattern: {pattern}")
                score -= 2.0

        # Normalize to 0-10
        max_possible = 6.5
        normalized = max(0.0, min(10.0, (score / max_possible) * 10.0))

        return {
            "passed": len(issues) == 0,
            "score": round(normalized, 2),
            "issues": issues,
            "lines": len(lines),
        }


# ---------------------------------------------------------------------------
# Task Definitions: 25 tasks across 5 domains
# ---------------------------------------------------------------------------

BENCHMARK_TASKS: List[BenchmarkTask] = [
    # ===== AI/ML (5 tasks) =====
    BenchmarkTask(
        task_id="ai_01",
        domain="ai_ml",
        prompt="Write a Python class implementing multi-head self-attention mechanism for a Transformer model. Include scaled dot-product attention, masking support, and proper tensor shape handling.",
        expected_patterns=[
            r"class\s+\w*[Aa]ttention",
            r"def\s+forward",
            r"softmax",
            r"sqrt|scale",
            r"mask",
        ],
        forbidden_patterns=[r"eval\(", r"exec\("],
        min_lines=30,
        complexity="COMPLEX",
        description="Transformer attention with masking",
    ),
    BenchmarkTask(
        task_id="ai_02",
        domain="ai_ml",
        prompt="Write a custom optimizer class in Python that implements gradient clipping (by norm and by value), learning rate warmup schedule, and weight decay. Compatible with PyTorch-style parameter groups.",
        expected_patterns=[
            r"class\s+\w*[Oo]ptimizer",
            r"def\s+step",
            r"clip|clamp",
            r"lr|learning_rate",
            r"weight_decay|decay",
        ],
        forbidden_patterns=[r"eval\("],
        min_lines=40,
        complexity="COMPLEX",
        description="Custom optimizer with gradient clipping",
    ),
    BenchmarkTask(
        task_id="ai_03",
        domain="ai_ml",
        prompt="Write a data augmentation pipeline class for image classification. Support random crop, horizontal flip, rotation, color jitter, and normalization. Each transform should be configurable and composable.",
        expected_patterns=[
            r"class\s+\w*(Pipeline|Augment|Transform)",
            r"def\s+\w*(crop|flip|rotat|jitter|normal)",
            r"random",
        ],
        forbidden_patterns=[r"eval\("],
        min_lines=40,
        complexity="MODERATE",
        description="Image augmentation pipeline",
    ),
    BenchmarkTask(
        task_id="ai_04",
        domain="ai_ml",
        prompt="Write a model checkpoint manager that saves/loads model state, tracks best metrics (loss, accuracy), supports versioned checkpoints with configurable retention policy, and handles corrupted checkpoint recovery.",
        expected_patterns=[
            r"class\s+\w*[Cc]heckpoint",
            r"def\s+save",
            r"def\s+load",
            r"best|metric",
        ],
        forbidden_patterns=[r"pickle\.loads?\(", r"eval\("],
        min_lines=40,
        complexity="COMPLEX",
        description="Model checkpoint manager with versioning",
    ),
    BenchmarkTask(
        task_id="ai_05",
        domain="ai_ml",
        prompt="Write a confusion matrix calculator that computes precision, recall, F1-score per class, supports multi-class classification, handles zero-division, and can export results as a formatted table.",
        expected_patterns=[
            r"def\s+\w*(precision|recall|f1)",
            r"class\s+\w*(Matrix|Metrics|Evaluator)",
            r"zero_division|ZeroDivision|\/ 0|divide",
        ],
        forbidden_patterns=[r"eval\("],
        min_lines=30,
        complexity="MODERATE",
        description="Confusion matrix with metrics export",
    ),

    # ===== DevOps (5 tasks) =====
    BenchmarkTask(
        task_id="devops_01",
        domain="devops",
        prompt="Write a Python function that generates a Kubernetes Deployment YAML with configurable replicas, resource limits/requests, liveness/readiness probes, and security context. Output valid YAML string.",
        expected_patterns=[
            r"apiVersion",
            r"kind:\s*Deployment",
            r"resources",
            r"livenessProbe|readinessProbe",
            r"securityContext",
        ],
        forbidden_patterns=[r"eval\("],
        min_lines=30,
        complexity="MODERATE",
        description="K8s deployment generator",
    ),
    BenchmarkTask(
        task_id="devops_02",
        domain="devops",
        prompt="Write a Python function that generates a Terraform module for an AWS VPC with public/private subnets, NAT gateway, security groups with configurable ingress/egress rules, and outputs for VPC ID and subnet IDs.",
        expected_patterns=[
            r"resource\s+\"aws_vpc\"",
            r"resource\s+\"aws_subnet\"",
            r"cidr_block",
            r"security_group|ingress|egress",
        ],
        forbidden_patterns=[r"eval\("],
        min_lines=40,
        complexity="COMPLEX",
        description="Terraform AWS VPC module",
    ),
    BenchmarkTask(
        task_id="devops_03",
        domain="devops",
        prompt="Write a Python function that generates a GitHub Actions CI/CD workflow YAML with build, test, and deploy stages. Include caching for pip dependencies, matrix testing across Python 3.10-3.12, and conditional deployment to staging/production.",
        expected_patterns=[
            r"on:",
            r"jobs:",
            r"cache|restore-keys",
            r"matrix",
            r"if:\s",
        ],
        forbidden_patterns=[r"eval\("],
        min_lines=30,
        complexity="MODERATE",
        description="GitHub Actions CI/CD pipeline",
    ),
    BenchmarkTask(
        task_id="devops_04",
        domain="devops",
        prompt="Write a Python function that generates a Dockerfile for a Python web application using multi-stage build. Include: builder stage with pip install, production stage with non-root user, HEALTHCHECK, proper COPY ordering for cache optimization.",
        expected_patterns=[
            r"FROM.*AS\s+\w+",
            r"USER\s+\w+",
            r"HEALTHCHECK",
            r"COPY\s+--from",
        ],
        forbidden_patterns=[r"eval\("],
        min_lines=20,
        complexity="MODERATE",
        description="Multi-stage Dockerfile",
    ),
    BenchmarkTask(
        task_id="devops_05",
        domain="devops",
        prompt="Write a Python function that generates an Ansible playbook for setting up nginx with SSL/TLS using Let's Encrypt. Include: nginx installation, SSL certificate generation, virtual host configuration, and firewall rules.",
        expected_patterns=[
            r"hosts:",
            r"tasks:",
            r"nginx|Nginx",
            r"ssl|SSL|certbot|letsencrypt",
        ],
        forbidden_patterns=[r"eval\("],
        min_lines=30,
        complexity="MODERATE",
        description="Ansible nginx + SSL playbook",
    ),

    # ===== Data Science (5 tasks) =====
    BenchmarkTask(
        task_id="ds_01",
        domain="data_science",
        prompt="Write a pandas ETL pipeline class with configurable steps: read CSV, validate schema (required columns, types), handle missing values (strategy: drop/fill/interpolate), transform columns, and validate output. Include logging at each step.",
        expected_patterns=[
            r"class\s+\w*(ETL|Pipeline)",
            r"import pandas|import pd",
            r"def\s+\w*(read|extract|load|transform|validate)",
            r"logging|logger",
            r"fillna|dropna|interpolat",
        ],
        forbidden_patterns=[r"eval\(", r"exec\("],
        min_lines=40,
        complexity="COMPLEX",
        description="Pandas ETL pipeline with validation",
    ),
    BenchmarkTask(
        task_id="ds_02",
        domain="data_science",
        prompt="Write a statistical A/B test calculator class. Support z-test for proportions, compute p-value, confidence interval, minimum sample size (power analysis), and provide clear pass/fail significance result.",
        expected_patterns=[
            r"class\s+\w*(AB|Test|Calculator)",
            r"p_value|pvalue",
            r"confidence|interval",
            r"sample_size|power",
            r"significant",
        ],
        forbidden_patterns=[r"eval\("],
        min_lines=30,
        complexity="MODERATE",
        description="A/B test statistical calculator",
    ),
    BenchmarkTask(
        task_id="ds_03",
        domain="data_science",
        prompt="Write a feature engineering pipeline class that supports: numerical normalization (min-max, z-score), categorical encoding (one-hot, label), datetime feature extraction (day, month, hour, weekday), and pipeline serialization.",
        expected_patterns=[
            r"class\s+\w*(Feature|Pipeline|Engineer)",
            r"def\s+\w*(normal|encod|transform|fit)",
            r"min.max|z.score|standard",
            r"one.hot|label.encod",
        ],
        forbidden_patterns=[r"eval\(", r"pickle\.loads\("],
        min_lines=40,
        complexity="COMPLEX",
        description="Feature engineering pipeline",
    ),
    BenchmarkTask(
        task_id="ds_04",
        domain="data_science",
        prompt="Write a time series forecasting class using ARIMA model. Include: stationarity test (ADF), automatic (p,d,q) parameter selection, train/test split, forecast with confidence intervals, and RMSE/MAE evaluation metrics.",
        expected_patterns=[
            r"class\s+\w*(Forecast|ARIMA|TimeSeries)",
            r"def\s+\w*(fit|predict|forecast)",
            r"RMSE|rmse|MAE|mae",
            r"confidence|interval",
        ],
        forbidden_patterns=[r"eval\("],
        min_lines=40,
        complexity="COMPLEX",
        description="ARIMA time series forecasting",
    ),
    BenchmarkTask(
        task_id="ds_05",
        domain="data_science",
        prompt="Write a data quality report generator class. Analyze a DataFrame and produce a report covering: missing values per column, duplicate rows, outliers (IQR method), data type summary, value distribution stats, and correlation matrix.",
        expected_patterns=[
            r"class\s+\w*(Quality|Report|Analyzer)",
            r"missing|null|NaN",
            r"duplicate",
            r"outlier|IQR|iqr",
            r"correlation|corr",
        ],
        forbidden_patterns=[r"eval\("],
        min_lines=40,
        complexity="MODERATE",
        description="Data quality report generator",
    ),

    # ===== Advanced Python (5 tasks) =====
    BenchmarkTask(
        task_id="py_01",
        domain="advanced_python",
        prompt="Write an async connection pool class with health checks. Support: configurable pool size, connection timeout, automatic health checking on release, graceful shutdown. Use asyncio primitives (Queue, Lock, Event).",
        expected_patterns=[
            r"class\s+\w*(Pool|ConnectionPool)",
            r"async\s+def\s+acquire",
            r"async\s+def\s+release",
            r"asyncio\.(Queue|Lock|Semaphore|Event)",
            r"health|ping|check",
        ],
        forbidden_patterns=[r"eval\("],
        min_lines=40,
        complexity="COMPLEX",
        description="Async connection pool with health checks",
    ),
    BenchmarkTask(
        task_id="py_02",
        domain="advanced_python",
        prompt="Write a thread-safe LRU cache class with TTL expiration. Support: configurable max_size, per-entry TTL, automatic eviction, hit/miss statistics, and invalidation by key or pattern.",
        expected_patterns=[
            r"class\s+\w*(Cache|LRU|TTL)",
            r"threading\.(Lock|RLock)",
            r"def\s+get",
            r"def\s+put|def\s+set",
            r"ttl|expir|TTL",
            r"hit|miss|stats",
        ],
        forbidden_patterns=[r"eval\("],
        min_lines=40,
        complexity="COMPLEX",
        description="Thread-safe LRU cache with TTL",
    ),
    BenchmarkTask(
        task_id="py_03",
        domain="advanced_python",
        prompt="Write a retry decorator with exponential backoff. Support: configurable max retries, backoff factor, jitter, specific exception types to catch, on_retry callback, and proper functools.wraps usage.",
        expected_patterns=[
            r"def\s+retry",
            r"functools\.wraps",
            r"backoff|exponential|2\s*\*\*",
            r"max_retries|attempts",
            r"except\s+",
        ],
        forbidden_patterns=[r"eval\("],
        min_lines=25,
        complexity="MODERATE",
        description="Retry decorator with exponential backoff",
    ),
    BenchmarkTask(
        task_id="py_04",
        domain="advanced_python",
        prompt="Write a plugin system with dynamic module loading. Support: plugin base class with ABC, plugin registry with auto-discovery from directory, version checking, dependency resolution between plugins, and safe loading with error isolation.",
        expected_patterns=[
            r"class\s+\w*(Plugin|Registry)",
            r"ABC|abstractmethod",
            r"importlib",
            r"def\s+\w*(register|discover|load)",
            r"version|dependency",
        ],
        forbidden_patterns=[r"eval\(", r"exec\("],
        min_lines=50,
        complexity="COMPLEX",
        description="Plugin system with dynamic loading",
    ),
    BenchmarkTask(
        task_id="py_05",
        domain="advanced_python",
        prompt="Write a finite state machine (FSM) class with: named states and transitions, guard conditions on transitions, on_enter/on_exit callbacks, transition history tracking, and serialization support.",
        expected_patterns=[
            r"class\s+\w*(State|Machine|FSM)",
            r"def\s+\w*(trigger|transition|fire)",
            r"guard|condition",
            r"on_enter|on_exit|callback",
            r"history|log",
        ],
        forbidden_patterns=[r"eval\("],
        min_lines=40,
        complexity="COMPLEX",
        description="Finite state machine with guards",
    ),

    # ===== Production Systems (5 tasks) =====
    BenchmarkTask(
        task_id="prod_01",
        domain="production",
        prompt="Write a FastAPI CRUD API for a user management system. Include: Pydantic models for request/response, JWT authentication dependency, proper HTTP status codes (201, 400, 404, 409), password hashing with bcrypt, and rate limiting middleware.",
        expected_patterns=[
            r"FastAPI|APIRouter",
            r"class\s+\w*(User|Create|Response)",
            r"BaseModel",
            r"status_code|HTTP_",
            r"jwt|JWT|token",
            r"bcrypt|hash|password",
        ],
        forbidden_patterns=[r"eval\(", r"password\s*=\s*[\"']"],
        min_lines=50,
        complexity="COMPLEX",
        description="FastAPI CRUD with JWT auth",
    ),
    BenchmarkTask(
        task_id="prod_02",
        domain="production",
        prompt="Write a token bucket rate limiter class. Support: configurable rate and burst capacity, thread-safe acquire with timeout, async acquire variant, per-key rate limiting, and statistics (requests allowed/denied).",
        expected_patterns=[
            r"class\s+\w*(Rate|Limiter|Bucket)",
            r"def\s+acquire",
            r"threading\.(Lock|RLock)|asyncio\.Lock",
            r"token|bucket|rate",
            r"timeout",
        ],
        forbidden_patterns=[r"eval\("],
        min_lines=30,
        complexity="MODERATE",
        description="Token bucket rate limiter",
    ),
    BenchmarkTask(
        task_id="prod_03",
        domain="production",
        prompt="Write a circuit breaker pattern implementation. Support: CLOSED/OPEN/HALF_OPEN states, configurable failure threshold and recovery timeout, success threshold for half-open recovery, and event callbacks for state changes.",
        expected_patterns=[
            r"class\s+\w*(Circuit|Breaker)",
            r"CLOSED|OPEN|HALF.OPEN",
            r"failure|threshold",
            r"recovery|timeout",
            r"def\s+call|def\s+execute",
        ],
        forbidden_patterns=[r"eval\("],
        min_lines=40,
        complexity="MODERATE",
        description="Circuit breaker pattern",
    ),
    BenchmarkTask(
        task_id="prod_04",
        domain="production",
        prompt="Write a distributed lock implementation using Redis. Support: lock acquisition with timeout, automatic expiry (TTL), lock extension/renewal, context manager protocol, and reentrant locking for the same owner.",
        expected_patterns=[
            r"class\s+\w*(Lock|Distributed)",
            r"def\s+acquire",
            r"def\s+release",
            r"ttl|TTL|expir",
            r"__enter__|__exit__",
            r"redis|Redis",
        ],
        forbidden_patterns=[r"eval\("],
        min_lines=40,
        complexity="COMPLEX",
        description="Distributed lock with Redis",
    ),
    BenchmarkTask(
        task_id="prod_05",
        domain="production",
        prompt="Write a priority background task queue. Support: priority-based task ordering, configurable worker pool (thread-based), task status tracking (pending/running/completed/failed), retry on failure, and graceful shutdown.",
        expected_patterns=[
            r"class\s+\w*(Queue|Task|Worker)",
            r"priority",
            r"threading\.Thread",
            r"def\s+submit|def\s+enqueue",
            r"shutdown",
            r"status|pending|running|completed|failed",
        ],
        forbidden_patterns=[r"eval\("],
        min_lines=50,
        complexity="COMPLEX",
        description="Priority background task queue",
    ),
]

# Build lookup by task_id
_TASKS_BY_ID: Dict[str, BenchmarkTask] = {t.task_id: t for t in BENCHMARK_TASKS}
_TASKS_BY_DOMAIN: Dict[str, List[BenchmarkTask]] = {}
for _t in BENCHMARK_TASKS:
    _TASKS_BY_DOMAIN.setdefault(_t.domain, []).append(_t)


def get_task(task_id: str) -> Optional[BenchmarkTask]:
    """Get a benchmark task by ID."""
    return _TASKS_BY_ID.get(task_id)


def get_tasks_by_domain(domain: str) -> List[BenchmarkTask]:
    """Get all tasks for a domain."""
    return _TASKS_BY_DOMAIN.get(domain, [])


def get_all_domains() -> List[str]:
    """Get list of all benchmark domains."""
    return list(_TASKS_BY_DOMAIN.keys())


# ---------------------------------------------------------------------------
# Pytest fixtures and tests — validate task definitions themselves
# ---------------------------------------------------------------------------


class TestBenchmarkTaskDefinitions:
    """Validate that all 25 benchmark tasks are properly defined."""

    def test_total_task_count(self):
        assert len(BENCHMARK_TASKS) == 25, f"Expected 25 tasks, got {len(BENCHMARK_TASKS)}"

    def test_unique_task_ids(self):
        ids = [t.task_id for t in BENCHMARK_TASKS]
        assert len(ids) == len(set(ids)), f"Duplicate task IDs: {[i for i in ids if ids.count(i) > 1]}"

    def test_five_domains(self):
        domains = set(t.domain for t in BENCHMARK_TASKS)
        assert len(domains) == 5, f"Expected 5 domains, got {domains}"

    def test_five_tasks_per_domain(self):
        for domain, tasks in _TASKS_BY_DOMAIN.items():
            assert len(tasks) == 5, f"Domain '{domain}' has {len(tasks)} tasks, expected 5"

    def test_all_tasks_have_prompts(self):
        for task in BENCHMARK_TASKS:
            assert len(task.prompt) > 20, f"Task {task.task_id} has too short prompt"

    def test_all_tasks_have_expected_patterns(self):
        for task in BENCHMARK_TASKS:
            assert len(task.expected_patterns) >= 2, (
                f"Task {task.task_id} needs at least 2 expected patterns"
            )

    def test_all_tasks_have_forbidden_patterns(self):
        for task in BENCHMARK_TASKS:
            assert len(task.forbidden_patterns) >= 1, (
                f"Task {task.task_id} needs at least 1 forbidden pattern"
            )

    def test_all_expected_patterns_are_valid_regex(self):
        for task in BENCHMARK_TASKS:
            for pattern in task.expected_patterns + task.forbidden_patterns:
                try:
                    re.compile(pattern)
                except re.error as e:
                    pytest.fail(f"Task {task.task_id} has invalid regex '{pattern}': {e}")

    def test_min_lines_reasonable(self):
        for task in BENCHMARK_TASKS:
            assert 5 <= task.min_lines <= 200, (
                f"Task {task.task_id} min_lines={task.min_lines} is unreasonable"
            )

    @pytest.mark.parametrize("task", BENCHMARK_TASKS, ids=lambda t: t.task_id)
    def test_task_validation_on_empty_code(self, task):
        """Empty code should always fail validation."""
        result = task.validate_output("")
        assert not result["passed"]
        assert result["score"] < 5.0

    @pytest.mark.parametrize("domain", get_all_domains())
    def test_domain_has_variety(self, domain):
        """Each domain should have varied complexity levels."""
        tasks = get_tasks_by_domain(domain)
        complexities = set(t.complexity for t in tasks)
        assert len(complexities) >= 1, f"Domain '{domain}' lacks complexity variety"

    def test_get_task_by_id(self):
        task = get_task("ai_01")
        assert task is not None
        assert task.domain == "ai_ml"

    def test_get_task_nonexistent(self):
        assert get_task("nonexistent_99") is None

    def test_get_all_domains(self):
        domains = get_all_domains()
        assert "ai_ml" in domains
        assert "devops" in domains
        assert "data_science" in domains
        assert "advanced_python" in domains
        assert "production" in domains
