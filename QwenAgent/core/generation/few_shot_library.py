"""
Week 28: Few-Shot Examples Library (PE-02)

A curated library of high-quality code snippets that serve as few-shot
examples during code generation.  Each snippet demonstrates a common
pattern done *correctly* — with proper error handling, type hints,
resource cleanup, and thread safety.

The library is keyed by task-pattern keywords.  During generation, the
system scans the user query for matching keywords and injects the best
matching snippet(s) into the system prompt.

Usage:
    from core.generation.few_shot_library import get_few_shot_examples

    examples_block = get_few_shot_examples(["connection_pool", "async"])
    system_prompt = f"{base_prompt}\\n\\n{examples_block}"
"""

import logging
from typing import Dict, List, Optional, Set

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Curated snippets — each demonstrates a production-grade pattern
# ---------------------------------------------------------------------------

_SNIPPETS: Dict[str, Dict[str, str]] = {
    "connection_pool": {
        "title": "Async Connection Pool with Health Check",
        "code": '''
import asyncio
import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ConnectionPool:
    """Async-safe connection pool with health checking."""

    def __init__(self, dsn: str, min_size: int = 2, max_size: int = 10) -> None:
        self._dsn = dsn
        self._min_size = min_size
        self._max_size = max_size
        self._pool: asyncio.Queue = asyncio.Queue(maxsize=max_size)
        self._size = 0
        self._lock = asyncio.Lock()

    async def acquire(self, timeout: float = 5.0) -> "Connection":
        """Acquire a connection, creating one if pool is not full."""
        try:
            return await asyncio.wait_for(self._pool.get(), timeout=timeout)
        except asyncio.TimeoutError:
            async with self._lock:
                if self._size < self._max_size:
                    conn = await self._create_connection()
                    self._size += 1
                    return conn
            raise TimeoutError(f"Pool exhausted ({self._max_size} connections)")

    async def release(self, conn: "Connection") -> None:
        """Return a connection to the pool after health check."""
        if await self._is_healthy(conn):
            await self._pool.put(conn)
        else:
            self._size -= 1
            logger.warning("Unhealthy connection discarded, pool_size=%d", self._size)

    async def _create_connection(self) -> "Connection":
        """Create a new database connection."""
        # Replace with actual connection logic
        raise NotImplementedError("Subclass must implement _create_connection")

    async def _is_healthy(self, conn: "Connection") -> bool:
        """Check if connection is still valid."""
        try:
            await conn.execute("SELECT 1")
            return True
        except Exception:
            return False

    async def close(self) -> None:
        """Close all connections in the pool."""
        while not self._pool.empty():
            conn = await self._pool.get()
            try:
                await conn.close()
            except Exception as exc:
                logger.error("Error closing connection: %s", exc)
            self._size -= 1
''',
    },
    "retry_decorator": {
        "title": "Retry Decorator with Exponential Backoff",
        "code": '''
import functools
import logging
import time
from typing import Callable, Tuple, Type, TypeVar

logger = logging.getLogger(__name__)
F = TypeVar("F", bound=Callable)


def retry(
    max_retries: int = 3,
    backoff_factor: float = 1.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
    on_retry: Callable[[int, Exception], None] | None = None,
) -> Callable[[F], F]:
    """Retry decorator with exponential backoff.

    Args:
        max_retries: Maximum number of retry attempts.
        backoff_factor: Base delay multiplier (delay = backoff_factor * 2^attempt).
        exceptions: Tuple of exception types to catch and retry.
        on_retry: Optional callback(attempt, exception) called before each retry.

    Returns:
        Decorated function that retries on specified exceptions.
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc: Exception | None = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt < max_retries:
                        delay = backoff_factor * (2 ** attempt)
                        logger.warning(
                            "Retry %d/%d for %s after %.1fs: %s",
                            attempt + 1, max_retries, func.__name__, delay, exc,
                        )
                        if on_retry:
                            on_retry(attempt + 1, exc)
                        time.sleep(delay)
            raise last_exc  # type: ignore[misc]
        return wrapper  # type: ignore[return-value]
    return decorator
''',
    },
    "sqlite_init": {
        "title": "SQLite Database Initialization with WAL Mode",
        "code": '''
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any, List, Optional, Tuple

logger = logging.getLogger(__name__)


class Database:
    """Thread-safe SQLite database wrapper with proper initialization."""

    def __init__(self, db_path: str | Path) -> None:
        self._db_path = str(db_path)
        self._local = threading.local()
        self._lock = threading.Lock()
        self._init_schema()

    def _get_conn(self) -> sqlite3.Connection:
        """Get thread-local connection."""
        if not hasattr(self._local, "conn") or self._local.conn is None:
            conn = sqlite3.connect(self._db_path)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.row_factory = sqlite3.Row
            self._local.conn = conn
        return self._local.conn

    def _init_schema(self) -> None:
        """Create tables if they don't exist."""
        conn = self._get_conn()
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                value TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE INDEX IF NOT EXISTS idx_items_name ON items(name);
        """)
        conn.commit()

    def execute(
        self, sql: str, params: Optional[Tuple[Any, ...]] = None
    ) -> sqlite3.Cursor:
        """Execute a parameterized query."""
        conn = self._get_conn()
        with self._lock:
            cursor = conn.execute(sql, params or ())
            conn.commit()
            return cursor

    def query(
        self, sql: str, params: Optional[Tuple[Any, ...]] = None
    ) -> List[sqlite3.Row]:
        """Execute a SELECT and return all rows."""
        conn = self._get_conn()
        return conn.execute(sql, params or ()).fetchall()

    def close(self) -> None:
        """Close thread-local connection."""
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None
''',
    },
    "fastapi_crud": {
        "title": "FastAPI CRUD Endpoint with Validation",
        "code": '''
import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/items", tags=["items"])


class ItemCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    price: float = Field(..., gt=0)


class ItemResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]
    price: float

    class Config:
        from_attributes = True


@router.post("/", response_model=ItemResponse, status_code=status.HTTP_201_CREATED)
async def create_item(item: ItemCreate, db=Depends(get_db)) -> ItemResponse:
    """Create a new item."""
    try:
        result = await db.execute(
            "INSERT INTO items (name, description, price) VALUES (?, ?, ?)",
            (item.name, item.description, item.price),
        )
        return ItemResponse(id=result.lastrowid, **item.model_dump())
    except Exception as exc:
        logger.error("Failed to create item: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create item",
        ) from exc


@router.get("/{item_id}", response_model=ItemResponse)
async def get_item(item_id: int, db=Depends(get_db)) -> ItemResponse:
    """Get item by ID."""
    row = await db.fetchone("SELECT * FROM items WHERE id = ?", (item_id,))
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Item {item_id} not found",
        )
    return ItemResponse(**dict(row))
''',
    },
    "thread_safe_cache": {
        "title": "Thread-Safe LRU Cache with TTL",
        "code": '''
import threading
import time
from collections import OrderedDict
from typing import Any, Hashable, Optional

class TTLCache:
    """Thread-safe LRU cache with per-entry TTL expiration.

    Args:
        max_size: Maximum number of entries.
        default_ttl: Default time-to-live in seconds.
    """

    def __init__(self, max_size: int = 256, default_ttl: float = 300.0) -> None:
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._cache: OrderedDict[Hashable, tuple[Any, float]] = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def get(self, key: Hashable) -> Optional[Any]:
        """Get value if present and not expired."""
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                return None
            value, expires_at = self._cache[key]
            if time.monotonic() > expires_at:
                del self._cache[key]
                self._misses += 1
                return None
            self._cache.move_to_end(key)
            self._hits += 1
            return value

    def put(self, key: Hashable, value: Any, ttl: Optional[float] = None) -> None:
        """Insert or update an entry."""
        expires_at = time.monotonic() + (ttl or self._default_ttl)
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                self._cache[key] = (value, expires_at)
            else:
                if len(self._cache) >= self._max_size:
                    self._cache.popitem(last=False)
                self._cache[key] = (value, expires_at)

    def invalidate(self, key: Hashable) -> bool:
        """Remove a specific key. Returns True if key existed."""
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                return True
            return False

    @property
    def stats(self) -> dict:
        """Cache hit/miss statistics."""
        total = self._hits + self._misses
        return {
            "size": len(self._cache),
            "max_size": self._max_size,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total, 3) if total > 0 else 0.0,
        }
''',
    },
    "circuit_breaker": {
        "title": "Circuit Breaker Pattern",
        "code": '''
import logging
import threading
import time
from enum import Enum
from typing import Callable, Optional, TypeVar

logger = logging.getLogger(__name__)
T = TypeVar("T")


class CircuitState(Enum):
    CLOSED = "closed"        # Normal operation
    OPEN = "open"            # Failing — reject calls
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitBreaker:
    """Circuit breaker for protecting against cascading failures.

    Args:
        failure_threshold: Failures before opening circuit.
        recovery_timeout: Seconds to wait before half-open test.
        success_threshold: Successes in half-open to close circuit.
    """

    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: float = 30.0,
        success_threshold: int = 2,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._success_threshold = success_threshold
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time: float = 0.0
        self._lock = threading.Lock()

    @property
    def state(self) -> CircuitState:
        with self._lock:
            if (
                self._state == CircuitState.OPEN
                and time.monotonic() - self._last_failure_time > self._recovery_timeout
            ):
                self._state = CircuitState.HALF_OPEN
                self._success_count = 0
            return self._state

    def call(self, func: Callable[..., T], *args, **kwargs) -> T:
        """Execute func through the circuit breaker."""
        current = self.state
        if current == CircuitState.OPEN:
            raise CircuitBreakerOpen(f"Circuit is OPEN, retry after {self._recovery_timeout}s")

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except Exception as exc:
            self._on_failure()
            raise

    def _on_success(self) -> None:
        with self._lock:
            self._failure_count = 0
            if self._state == CircuitState.HALF_OPEN:
                self._success_count += 1
                if self._success_count >= self._success_threshold:
                    self._state = CircuitState.CLOSED
                    logger.info("Circuit breaker CLOSED (recovered)")

    def _on_failure(self) -> None:
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.monotonic()
            if self._failure_count >= self._failure_threshold:
                self._state = CircuitState.OPEN
                logger.warning("Circuit breaker OPEN after %d failures", self._failure_count)


class CircuitBreakerOpen(Exception):
    """Raised when circuit is open and call is rejected."""
    pass
''',
    },
    "rate_limiter": {
        "title": "Token Bucket Rate Limiter",
        "code": '''
import threading
import time
from typing import Optional


class TokenBucketLimiter:
    """Thread-safe token bucket rate limiter.

    Args:
        rate: Tokens added per second.
        capacity: Maximum tokens in bucket.
    """

    def __init__(self, rate: float, capacity: int) -> None:
        self._rate = rate
        self._capacity = capacity
        self._tokens = float(capacity)
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, tokens: int = 1, timeout: Optional[float] = None) -> bool:
        """Try to acquire tokens. Blocks up to timeout seconds.

        Args:
            tokens: Number of tokens to consume.
            timeout: Max wait time in seconds (None = non-blocking).

        Returns:
            True if tokens acquired, False if timed out.
        """
        deadline = time.monotonic() + timeout if timeout else None

        while True:
            with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return True

            if deadline is None:
                return False
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(remaining, 1.0 / self._rate))

    def _refill(self) -> None:
        """Add tokens based on elapsed time since last refill."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
        self._last_refill = now
''',
    },
    "state_machine": {
        "title": "Finite State Machine with Transitions",
        "code": '''
import logging
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


class InvalidTransition(Exception):
    """Raised when attempting an invalid state transition."""
    pass


class StateMachine:
    """Generic finite state machine with guarded transitions.

    Args:
        initial: The starting state.
    """

    def __init__(self, initial: str) -> None:
        self._state = initial
        self._transitions: Dict[Tuple[str, str], str] = {}
        self._guards: Dict[Tuple[str, str], Callable[..., bool]] = {}
        self._on_enter: Dict[str, List[Callable]] = {}
        self._on_exit: Dict[str, List[Callable]] = {}
        self._valid_states: Set[str] = {initial}

    @property
    def state(self) -> str:
        return self._state

    def add_transition(
        self,
        trigger: str,
        source: str,
        dest: str,
        guard: Optional[Callable[..., bool]] = None,
    ) -> "StateMachine":
        """Register a state transition.

        Args:
            trigger: Event name that causes the transition.
            source: State the machine must be in.
            dest: State to transition to.
            guard: Optional condition that must return True.
        """
        self._transitions[(source, trigger)] = dest
        self._valid_states.update({source, dest})
        if guard:
            self._guards[(source, trigger)] = guard
        return self

    def on_enter(self, state: str, callback: Callable) -> "StateMachine":
        self._on_enter.setdefault(state, []).append(callback)
        return self

    def on_exit(self, state: str, callback: Callable) -> "StateMachine":
        self._on_exit.setdefault(state, []).append(callback)
        return self

    def trigger(self, event: str, **context: Any) -> str:
        """Fire an event, transitioning if valid."""
        key = (self._state, event)
        if key not in self._transitions:
            raise InvalidTransition(
                f"No transition for event '{event}' from state '{self._state}'"
            )
        guard = self._guards.get(key)
        if guard and not guard(**context):
            raise InvalidTransition(
                f"Guard blocked transition '{event}' from '{self._state}'"
            )
        old = self._state
        new = self._transitions[key]
        for cb in self._on_exit.get(old, []):
            cb(old_state=old, new_state=new, **context)
        self._state = new
        for cb in self._on_enter.get(new, []):
            cb(old_state=old, new_state=new, **context)
        logger.debug("Transition: %s -[%s]-> %s", old, event, new)
        return new
''',
    },
    "background_queue": {
        "title": "Priority Background Task Queue",
        "code": '''
import heapq
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


@dataclass(order=True)
class PriorityTask:
    priority: int
    task_id: str = field(compare=False)
    func: Callable = field(compare=False)
    args: tuple = field(default=(), compare=False)
    kwargs: dict = field(default_factory=dict, compare=False)


class TaskQueue:
    """Thread-safe priority task queue with worker pool.

    Args:
        num_workers: Number of background worker threads.
    """

    def __init__(self, num_workers: int = 2) -> None:
        self._heap: list[PriorityTask] = []
        self._lock = threading.Lock()
        self._not_empty = threading.Condition(self._lock)
        self._workers: list[threading.Thread] = []
        self._running = True

        for i in range(num_workers):
            t = threading.Thread(target=self._worker, name=f"worker-{i}", daemon=True)
            t.start()
            self._workers.append(t)

    def submit(
        self, func: Callable, *args, priority: int = 5, task_id: str = "", **kwargs
    ) -> None:
        """Add a task to the queue."""
        task = PriorityTask(
            priority=priority, task_id=task_id or str(id(func)),
            func=func, args=args, kwargs=kwargs,
        )
        with self._not_empty:
            heapq.heappush(self._heap, task)
            self._not_empty.notify()

    def _worker(self) -> None:
        """Worker loop: pick highest-priority task and execute."""
        while self._running:
            with self._not_empty:
                while not self._heap and self._running:
                    self._not_empty.wait(timeout=1.0)
                if not self._running:
                    return
                task = heapq.heappop(self._heap)
            try:
                task.func(*task.args, **task.kwargs)
            except Exception as exc:
                logger.error("Task %s failed: %s", task.task_id, exc)

    def shutdown(self, wait: bool = True) -> None:
        """Stop all workers."""
        self._running = False
        with self._not_empty:
            self._not_empty.notify_all()
        if wait:
            for t in self._workers:
                t.join(timeout=5.0)
''',
    },
    "plugin_system": {
        "title": "Plugin System with Dynamic Loading",
        "code": '''
import importlib
import inspect
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Dict, List, Optional, Type, TypeVar

logger = logging.getLogger(__name__)
T = TypeVar("T", bound="PluginBase")


class PluginBase(ABC):
    """Base class for all plugins."""

    name: str = "unnamed"
    version: str = "0.1.0"

    @abstractmethod
    def execute(self, **kwargs: Any) -> Any:
        """Run the plugin logic."""
        ...


class PluginRegistry:
    """Registry for discovering and loading plugins.

    Args:
        plugin_dir: Directory containing plugin modules.
        base_class: Base class that plugins must inherit from.
    """

    def __init__(
        self,
        plugin_dir: Optional[str] = None,
        base_class: Type[T] = PluginBase,
    ) -> None:
        self._plugins: Dict[str, Type[T]] = {}
        self._instances: Dict[str, T] = {}
        self._base_class = base_class
        if plugin_dir:
            self.discover(plugin_dir)

    def register(self, plugin_cls: Type[T]) -> None:
        """Manually register a plugin class."""
        name = getattr(plugin_cls, "name", plugin_cls.__name__)
        self._plugins[name] = plugin_cls
        logger.info("Registered plugin: %s v%s", name, getattr(plugin_cls, "version", "?"))

    def discover(self, plugin_dir: str) -> int:
        """Auto-discover plugins from a directory.

        Returns:
            Number of plugins found.
        """
        count = 0
        for path in Path(plugin_dir).glob("*.py"):
            if path.name.startswith("_"):
                continue
            module_name = path.stem
            try:
                spec = importlib.util.spec_from_file_location(module_name, path)
                if spec and spec.loader:
                    module = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(module)
                    for _, obj in inspect.getmembers(module, inspect.isclass):
                        if issubclass(obj, self._base_class) and obj is not self._base_class:
                            self.register(obj)
                            count += 1
            except Exception as exc:
                logger.error("Failed to load plugin from %s: %s", path, exc)
        return count

    def get(self, name: str) -> Optional[T]:
        """Get or create a plugin instance by name."""
        if name not in self._instances:
            cls = self._plugins.get(name)
            if cls is None:
                return None
            self._instances[name] = cls()
        return self._instances[name]

    @property
    def available(self) -> List[str]:
        return list(self._plugins.keys())
''',
    },
    "health_check": {
        "title": "Health Check Orchestrator for Microservices",
        "code": '''
import asyncio
import logging
import time
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional

logger = logging.getLogger(__name__)


class HealthStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


@dataclass
class CheckResult:
    name: str
    status: HealthStatus
    latency_ms: float
    message: str = ""
    details: Optional[Dict[str, Any]] = None


class HealthChecker:
    """Orchestrates health checks across multiple services.

    Args:
        timeout: Per-check timeout in seconds.
    """

    def __init__(self, timeout: float = 5.0) -> None:
        self._checks: Dict[str, Callable[..., Coroutine]] = {}
        self._timeout = timeout

    def register(self, name: str, check_fn: Callable[..., Coroutine]) -> None:
        """Register an async health check function."""
        self._checks[name] = check_fn

    async def run_all(self) -> Dict[str, CheckResult]:
        """Run all checks concurrently, return results by name."""
        tasks = {
            name: asyncio.create_task(self._run_single(name, fn))
            for name, fn in self._checks.items()
        }
        results = {}
        for name, task in tasks.items():
            try:
                results[name] = await asyncio.wait_for(task, timeout=self._timeout)
            except asyncio.TimeoutError:
                results[name] = CheckResult(
                    name=name, status=HealthStatus.UNHEALTHY,
                    latency_ms=self._timeout * 1000, message="Timeout",
                )
        return results

    async def _run_single(self, name: str, fn: Callable) -> CheckResult:
        t0 = time.monotonic()
        try:
            await fn()
            latency = (time.monotonic() - t0) * 1000
            return CheckResult(name=name, status=HealthStatus.HEALTHY, latency_ms=latency)
        except Exception as exc:
            latency = (time.monotonic() - t0) * 1000
            return CheckResult(
                name=name, status=HealthStatus.UNHEALTHY,
                latency_ms=latency, message=str(exc),
            )

    @property
    def overall_status(self) -> HealthStatus:
        """Aggregate status — requires run_all() first."""
        return HealthStatus.HEALTHY  # Placeholder
''',
    },
    "feature_flag": {
        "title": "Feature Flag System with Rollout Percentage",
        "code": '''
import hashlib
import logging
import threading
from dataclasses import dataclass, field
from typing import Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class FeatureFlag:
    name: str
    enabled: bool = False
    rollout_percent: int = 0  # 0-100
    description: str = ""


class FeatureFlagManager:
    """Thread-safe feature flag system with percentage rollout.

    Args:
        flags: Initial flag definitions.
    """

    def __init__(self, flags: Optional[Dict[str, FeatureFlag]] = None) -> None:
        self._flags: Dict[str, FeatureFlag] = flags or {}
        self._lock = threading.RLock()

    def register(self, flag: FeatureFlag) -> None:
        with self._lock:
            self._flags[flag.name] = flag

    def is_enabled(self, flag_name: str, user_id: Optional[str] = None) -> bool:
        """Check if flag is enabled, optionally for a specific user.

        Uses consistent hashing for deterministic rollout per user.
        """
        with self._lock:
            flag = self._flags.get(flag_name)
            if flag is None:
                return False
            if not flag.enabled:
                return False
            if flag.rollout_percent >= 100:
                return True
            if flag.rollout_percent <= 0:
                return False
            if user_id is None:
                return False
            # Consistent hash for deterministic rollout
            hash_input = f"{flag_name}:{user_id}".encode()
            hash_val = int(hashlib.md5(hash_input).hexdigest(), 16) % 100
            return hash_val < flag.rollout_percent

    def set_rollout(self, flag_name: str, percent: int) -> None:
        with self._lock:
            flag = self._flags.get(flag_name)
            if flag:
                flag.rollout_percent = max(0, min(100, percent))

    def all_flags(self) -> Dict[str, dict]:
        with self._lock:
            return {
                name: {"enabled": f.enabled, "rollout": f.rollout_percent, "desc": f.description}
                for name, f in self._flags.items()
            }
''',
    },
    "ab_test": {
        "title": "Statistical A/B Test Calculator",
        "code": '''
import math
from dataclasses import dataclass
from typing import Tuple


@dataclass
class ABTestResult:
    """Result of an A/B test significance calculation."""
    control_rate: float
    treatment_rate: float
    z_score: float
    p_value: float
    is_significant: bool
    confidence_level: float
    relative_lift: float


def calculate_ab_test(
    control_conversions: int,
    control_total: int,
    treatment_conversions: int,
    treatment_total: int,
    confidence: float = 0.95,
) -> ABTestResult:
    """Calculate A/B test statistical significance using z-test.

    Args:
        control_conversions: Number of conversions in control group.
        control_total: Total samples in control group.
        treatment_conversions: Number of conversions in treatment group.
        treatment_total: Total samples in treatment group.
        confidence: Desired confidence level (default 0.95).

    Returns:
        ABTestResult with z-score, p-value, and significance flag.

    Raises:
        ValueError: If inputs are invalid.
    """
    if control_total <= 0 or treatment_total <= 0:
        raise ValueError("Sample sizes must be positive")
    if control_conversions < 0 or treatment_conversions < 0:
        raise ValueError("Conversions cannot be negative")

    p_c = control_conversions / control_total
    p_t = treatment_conversions / treatment_total
    p_pool = (control_conversions + treatment_conversions) / (control_total + treatment_total)

    se = math.sqrt(p_pool * (1 - p_pool) * (1 / control_total + 1 / treatment_total))
    if se == 0:
        z = 0.0
    else:
        z = (p_t - p_c) / se

    p_value = 2 * (1 - _normal_cdf(abs(z)))
    z_critical = _z_score_for_confidence(confidence)
    is_sig = abs(z) > z_critical
    lift = (p_t - p_c) / p_c if p_c > 0 else 0.0

    return ABTestResult(
        control_rate=p_c, treatment_rate=p_t, z_score=z,
        p_value=p_value, is_significant=is_sig,
        confidence_level=confidence, relative_lift=lift,
    )


def _normal_cdf(x: float) -> float:
    """Approximate standard normal CDF."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _z_score_for_confidence(confidence: float) -> float:
    """Get z-score for confidence level."""
    _TABLE = {0.90: 1.645, 0.95: 1.960, 0.99: 2.576}
    return _TABLE.get(confidence, 1.960)
''',
    },
    "etl_pipeline": {
        "title": "Pandas ETL Pipeline with Validation",
        "code": '''
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    valid: bool
    errors: List[str]
    warnings: List[str]
    rows_before: int
    rows_after: int


class ETLPipeline:
    """Configurable ETL pipeline with step-level validation.

    Args:
        name: Pipeline name for logging.
    """

    def __init__(self, name: str = "etl") -> None:
        self._name = name
        self._steps: List[tuple[str, Callable]] = []
        self._validators: List[Callable] = []

    def add_step(self, name: str, transform: Callable[[pd.DataFrame], pd.DataFrame]) -> "ETLPipeline":
        """Add a transformation step."""
        self._steps.append((name, transform))
        return self

    def add_validator(self, validator: Callable[[pd.DataFrame], List[str]]) -> "ETLPipeline":
        """Add a post-step validator that returns list of error messages."""
        self._validators.append(validator)
        return self

    def run(self, df: pd.DataFrame) -> tuple[pd.DataFrame, ValidationResult]:
        """Execute all steps and validate."""
        rows_before = len(df)
        errors: List[str] = []
        warnings: List[str] = []

        for step_name, transform in self._steps:
            try:
                logger.info("[%s] Running step: %s (%d rows)", self._name, step_name, len(df))
                df = transform(df)
                if df is None or df.empty:
                    errors.append(f"Step '{step_name}' produced empty DataFrame")
                    break
            except Exception as exc:
                errors.append(f"Step '{step_name}' failed: {exc}")
                logger.error("[%s] Step %s failed: %s", self._name, step_name, exc)
                break

        for validator in self._validators:
            try:
                step_errors = validator(df)
                errors.extend(step_errors)
            except Exception as exc:
                warnings.append(f"Validator failed: {exc}")

        result = ValidationResult(
            valid=len(errors) == 0, errors=errors, warnings=warnings,
            rows_before=rows_before, rows_after=len(df),
        )
        return df, result
''',
    },
}

# Keyword → snippet name mapping for flexible matching
_KEYWORD_MAP: Dict[str, List[str]] = {
    "connection_pool": ["connection_pool"],
    "pool": ["connection_pool"],
    "retry": ["retry_decorator"],
    "backoff": ["retry_decorator"],
    "exponential": ["retry_decorator"],
    "sqlite": ["sqlite_init"],
    "database": ["sqlite_init"],
    "db_init": ["sqlite_init"],
    "fastapi": ["fastapi_crud"],
    "crud": ["fastapi_crud"],
    "endpoint": ["fastapi_crud"],
    "rest_api": ["fastapi_crud"],
    "cache": ["thread_safe_cache"],
    "lru": ["thread_safe_cache"],
    "ttl": ["thread_safe_cache"],
    "circuit_breaker": ["circuit_breaker"],
    "circuit": ["circuit_breaker"],
    "fallback": ["circuit_breaker"],
    "rate_limit": ["rate_limiter"],
    "token_bucket": ["rate_limiter"],
    "throttle": ["rate_limiter"],
    "state_machine": ["state_machine"],
    "fsm": ["state_machine"],
    "transition": ["state_machine"],
    "queue": ["background_queue"],
    "background_task": ["background_queue"],
    "job_queue": ["background_queue"],
    "priority_queue": ["background_queue"],
    "plugin": ["plugin_system"],
    "dynamic_loading": ["plugin_system"],
    "registry": ["plugin_system"],
    "health_check": ["health_check"],
    "health": ["health_check"],
    "microservice": ["health_check"],
    "feature_flag": ["feature_flag"],
    "rollout": ["feature_flag"],
    "ab_test": ["ab_test"],
    "a_b_test": ["ab_test"],
    "significance": ["ab_test"],
    "statistical_test": ["ab_test"],
    "etl": ["etl_pipeline"],
    "pandas": ["etl_pipeline"],
    "data_pipeline": ["etl_pipeline"],
    "transform": ["etl_pipeline"],
}


def get_few_shot_examples(
    keywords: List[str],
    max_examples: int = 2,
) -> str:
    """Find matching few-shot examples for the given task keywords.

    Scans keywords against the library and returns formatted code blocks
    for injection into the generation prompt.

    Args:
        keywords: List of lowercase keywords extracted from the user query.
        max_examples: Maximum number of examples to include (to limit prompt size).

    Returns:
        Formatted string with example code blocks, or empty string.
    """
    matched: List[str] = []  # snippet keys, deduplicated

    for kw in keywords:
        kw_lower = kw.lower().replace(" ", "_").replace("-", "_")
        # Direct lookup
        if kw_lower in _KEYWORD_MAP:
            for name in _KEYWORD_MAP[kw_lower]:
                if name not in matched:
                    matched.append(name)
        # Substring match
        else:
            for map_key, names in _KEYWORD_MAP.items():
                if map_key in kw_lower or kw_lower in map_key:
                    for name in names:
                        if name not in matched:
                            matched.append(name)

    if not matched:
        return ""

    # Take top N
    selected = matched[:max_examples]

    parts = ["\n## REFERENCE EXAMPLES (follow these patterns):"]
    for snippet_key in selected:
        snippet = _SNIPPETS.get(snippet_key)
        if snippet:
            parts.append(f"\n### {snippet['title']}")
            parts.append(f"```python{snippet['code']}```")

    result = "\n".join(parts)
    logger.debug("Few-shot: matched %d snippets for keywords %s", len(selected), keywords)
    return result


def extract_keywords_from_query(query: str) -> List[str]:
    """Extract potential keywords from a user query for snippet matching.

    Simple keyword extraction: split on spaces/punctuation, filter short words,
    normalize to lowercase with underscores.

    Args:
        query: User's code generation request.

    Returns:
        List of normalized keywords.
    """
    import re
    # Split on non-alphanumeric (keep underscores)
    tokens = re.split(r'[^a-zA-Z0-9_]+', query.lower())
    # Filter: keep tokens >= 3 chars
    keywords = [t for t in tokens if len(t) >= 3]
    # Also generate bigrams for compound terms
    bigrams = []
    for i in range(len(keywords) - 1):
        bigrams.append(f"{keywords[i]}_{keywords[i+1]}")
    return keywords + bigrams
