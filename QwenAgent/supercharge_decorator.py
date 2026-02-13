"""
Universal decorator: caching + logging + retry + timeout.

Production-ready: thread-safe TTL+LRU cache, real timeout via threads,
exponential backoff with jitter, async support, metrics, ParamSpec typing.

Usage:
    @supercharge(cache_ttl=60, max_cache=256, retries=3, timeout=5.0)
    def fetch_data(url):
        return requests.get(url).json()

    @supercharge(retries=2, timeout=10.0)
    async def async_fetch(url):
        async with aiohttp.ClientSession() as s:
            return await (await s.get(url)).json()
"""

import asyncio
import functools
import hashlib
import inspect
import json
import logging
import pickle
import random
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Optional, ParamSpec, TypeVar

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")


# ---------------------------------------------------------------------------
# Timeout
# ---------------------------------------------------------------------------

class DeadlineExceeded(Exception):
    """Raised when a function exceeds its time limit."""


def _run_with_timeout(func: Callable, seconds: float, args: tuple, kwargs: dict) -> Any:
    """Execute *func* in a daemon thread; raise DeadlineExceeded if it takes too long."""
    result_box: list = []
    error_box: list = []

    def target():
        try:
            result_box.append(func(*args, **kwargs))
        except BaseException as e:
            error_box.append(e)

    t = threading.Thread(target=target, daemon=True)
    t.start()
    t.join(seconds)

    if t.is_alive():
        raise DeadlineExceeded(f"{func.__qualname__} exceeded {seconds}s deadline")
    if error_box:
        raise error_box[0]
    return result_box[0]


# ---------------------------------------------------------------------------
# Thread-safe TTL + LRU cache
# ---------------------------------------------------------------------------

class _Cache:
    """Thread-safe cache with TTL expiry and LRU eviction."""

    def __init__(self, ttl: int, maxsize: int):
        self._ttl = ttl
        self._maxsize = maxsize
        self._store: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = threading.Lock()

    @staticmethod
    def _make_key(args: tuple, kwargs: dict) -> str:
        try:
            raw = json.dumps((args, kwargs), sort_keys=True, default=str)
        except (TypeError, ValueError):
            # Fallback: pickle handles arbitrary objects (sets, custom classes, etc.)
            raw = pickle.dumps((args, sorted(kwargs.items())), protocol=pickle.HIGHEST_PROTOCOL).hex()
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, args: tuple, kwargs: dict) -> tuple[bool, Any]:
        key = self._make_key(args, kwargs)
        with self._lock:
            if key not in self._store:
                return False, None
            ts, value = self._store[key]
            if time.time() - ts >= self._ttl:
                del self._store[key]
                return False, None
            # Move to end (most recently used)
            self._store.move_to_end(key)
            return True, value

    def put(self, args: tuple, kwargs: dict, value: Any) -> None:
        key = self._make_key(args, kwargs)
        with self._lock:
            if key in self._store:
                self._store.move_to_end(key)
            self._store[key] = (time.time(), value)
            # Evict least recently used if over limit
            while len(self._store) > self._maxsize:
                self._store.popitem(last=False)

    def clear(self) -> None:
        """Remove all entries from cache."""
        with self._lock:
            self._store.clear()

    def info(self) -> dict:
        """Return cache size / capacity snapshot."""
        with self._lock:
            # Purge expired entries while we're here
            now = time.time()
            expired = [k for k, (ts, _) in self._store.items() if now - ts >= self._ttl]
            for k in expired:
                del self._store[k]
            return {"size": len(self._store), "maxsize": self._maxsize, "ttl": self._ttl}


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

@dataclass
class DecoratorMetrics:
    """Per-function call statistics."""
    calls: int = 0
    successes: int = 0
    failures: int = 0
    retries_total: int = 0
    timeouts: int = 0
    cache_hits: int = 0
    cache_misses: int = 0
    total_duration: float = 0.0

    @property
    def hit_rate(self) -> float:
        total = self.cache_hits + self.cache_misses
        return self.cache_hits / total if total else 0.0

    def to_dict(self) -> dict:
        return {
            "calls": self.calls,
            "successes": self.successes,
            "failures": self.failures,
            "retries_total": self.retries_total,
            "timeouts": self.timeouts,
            "cache_hits": self.cache_hits,
            "cache_misses": self.cache_misses,
            "cache_hit_rate": round(self.hit_rate, 4),
            "avg_duration": round(self.total_duration / self.calls, 4) if self.calls else 0,
        }


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------

def supercharge(
    *,
    cache_ttl: int = 0,
    max_cache: int = 256,
    retries: int = 0,
    retry_delay: float = 1.0,
    retry_backoff: float = 2.0,
    retry_max_delay: float = 60.0,
    retry_jitter: float = 0.25,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
    timeout: float = 0.0,
    log_level: str = "DEBUG",
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """
    Decorator combining caching, logging, retry and timeout.

    Args:
        cache_ttl:       Cache results for N seconds (0 = disabled).
        max_cache:       Max cached entries per function (LRU eviction).
        retries:         Max retry attempts on failure (0 = no retry).
        retry_delay:     Initial delay between retries in seconds.
        retry_backoff:   Multiply delay by this after each retry.
        retry_max_delay: Upper bound for delay (prevents unbounded growth).
        retry_jitter:    Random jitter factor (0.25 = +/-25% of delay).
        retry_on:        Exception types that trigger a retry.
        timeout:         Max execution time in seconds (0 = no limit).
        log_level:       Logging level for call/result messages.
    """
    level = getattr(logging, log_level.upper(), logging.DEBUG)

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        cache = _Cache(cache_ttl, max_cache) if cache_ttl > 0 else None
        metrics = DecoratorMetrics()
        is_async = inspect.iscoroutinefunction(func)

        # --- SYNC wrapper ---
        @functools.wraps(func)
        def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            return _execute(func, args, kwargs, cache, metrics, level,
                            retries, retry_delay, retry_backoff, retry_max_delay,
                            retry_jitter, retry_on, timeout, is_async=False)

        # --- ASYNC wrapper ---
        @functools.wraps(func)
        async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            return await _execute_async(func, args, kwargs, cache, metrics, level,
                                        retries, retry_delay, retry_backoff,
                                        retry_max_delay, retry_jitter,
                                        retry_on, timeout)

        wrapper = async_wrapper if is_async else sync_wrapper
        wrapper.metrics = metrics          # type: ignore[attr-defined]
        wrapper.cache = cache              # type: ignore[attr-defined]
        # Convenience methods
        wrapper.cache_clear = cache.clear if cache else (lambda: None)   # type: ignore[attr-defined]
        wrapper.cache_info = cache.info if cache else (lambda: {})       # type: ignore[attr-defined]
        return wrapper  # type: ignore[return-value]

    return decorator  # type: ignore[return-value]


def _execute(
    func, args, kwargs, cache, metrics, level,
    retries, retry_delay, retry_backoff, retry_max_delay,
    retry_jitter, retry_on, timeout, *, is_async,
) -> Any:
    fname = func.__qualname__
    metrics.calls += 1

    logger.log(level, "[CALL] %s(args=%s, kwargs=%s)", fname, args, kwargs)
    t0 = time.perf_counter()

    # Cache check
    if cache:
        hit, cached_value = cache.get(args, kwargs)
        if hit:
            metrics.cache_hits += 1
            logger.log(level, "[CACHE HIT] %s -> %.4fs", fname, time.perf_counter() - t0)
            return cached_value
        metrics.cache_misses += 1

    # Retry loop
    last_error: Optional[BaseException] = None
    attempts = max(retries, 0) + 1
    delay = retry_delay

    for attempt in range(1, attempts + 1):
        try:
            if timeout > 0:
                result = _run_with_timeout(func, timeout, args, kwargs)
            else:
                result = func(*args, **kwargs)

            # Cache store
            if cache:
                cache.put(args, kwargs, result)

            elapsed = time.perf_counter() - t0
            metrics.successes += 1
            metrics.total_duration += elapsed
            logger.log(level, "[OK] %s -> %.4fs", fname, elapsed)
            return result

        except DeadlineExceeded as exc:
            metrics.timeouts += 1
            logger.warning("[TIMEOUT] %s attempt %d/%d after %.1fs",
                           fname, attempt, attempts, timeout)
            last_error = exc

        except retry_on as exc:
            logger.warning("[ERROR] %s attempt %d/%d: %s",
                           fname, attempt, attempts, exc)
            last_error = exc

        except BaseException:
            # Non-retryable exception — don't retry, re-raise immediately
            metrics.failures += 1
            metrics.total_duration += time.perf_counter() - t0
            raise

        if attempt < attempts:
            metrics.retries_total += 1
            capped = min(delay, retry_max_delay)
            jittered = capped * (1 + random.uniform(-retry_jitter, retry_jitter))
            logger.log(level, "[RETRY] %s waiting %.2fs before attempt %d",
                       fname, jittered, attempt + 1)
            time.sleep(jittered)
            delay *= retry_backoff

    # All attempts exhausted
    metrics.failures += 1
    metrics.total_duration += time.perf_counter() - t0
    logger.error("[FAILED] %s after %d attempts", fname, attempts, exc_info=True)
    raise last_error  # type: ignore[misc]


async def _execute_async(
    func, args, kwargs, cache, metrics, level,
    retries, retry_delay, retry_backoff, retry_max_delay,
    retry_jitter, retry_on, timeout,
) -> Any:
    fname = func.__qualname__
    metrics.calls += 1

    logger.log(level, "[CALL] %s(args=%s, kwargs=%s)", fname, args, kwargs)
    t0 = time.perf_counter()

    # Cache check
    if cache:
        hit, cached_value = cache.get(args, kwargs)
        if hit:
            metrics.cache_hits += 1
            logger.log(level, "[CACHE HIT] %s -> %.4fs", fname, time.perf_counter() - t0)
            return cached_value
        metrics.cache_misses += 1

    # Retry loop
    last_error: Optional[BaseException] = None
    attempts = max(retries, 0) + 1
    delay = retry_delay

    for attempt in range(1, attempts + 1):
        try:
            if timeout > 0:
                result = await asyncio.wait_for(func(*args, **kwargs), timeout=timeout)
            else:
                result = await func(*args, **kwargs)

            if cache:
                cache.put(args, kwargs, result)

            elapsed = time.perf_counter() - t0
            metrics.successes += 1
            metrics.total_duration += elapsed
            logger.log(level, "[OK] %s -> %.4fs", fname, elapsed)
            return result

        except asyncio.TimeoutError:
            metrics.timeouts += 1
            logger.warning("[TIMEOUT] %s attempt %d/%d after %.1fs",
                           fname, attempt, attempts, timeout)
            last_error = DeadlineExceeded(f"{fname} exceeded {timeout}s deadline")

        except retry_on as exc:
            logger.warning("[ERROR] %s attempt %d/%d: %s",
                           fname, attempt, attempts, exc)
            last_error = exc

        except BaseException:
            metrics.failures += 1
            metrics.total_duration += time.perf_counter() - t0
            raise

        if attempt < attempts:
            metrics.retries_total += 1
            capped = min(delay, retry_max_delay)
            jittered = capped * (1 + random.uniform(-retry_jitter, retry_jitter))
            logger.log(level, "[RETRY] %s waiting %.2fs before attempt %d",
                       fname, jittered, attempt + 1)
            await asyncio.sleep(jittered)
            delay *= retry_backoff

    metrics.failures += 1
    metrics.total_duration += time.perf_counter() - t0
    logger.error("[FAILED] %s after %d attempts", fname, attempts, exc_info=True)
    raise last_error  # type: ignore[misc]


# ============================================================================
# DEMO
# ============================================================================

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    # --- 1. Cache + Logging ---
    @supercharge(cache_ttl=10, log_level="INFO")
    def expensive_calc(x, y):
        time.sleep(0.3)
        return x ** y

    print("=== Cache + Logging ===")
    print(expensive_calc(2, 10))   # computes
    print(expensive_calc(2, 10))   # cached
    print(f"Metrics: {expensive_calc.metrics.to_dict()}")

    # --- 2. Retry with jitter ---
    call_count = 0

    @supercharge(retries=3, retry_delay=0.3, retry_jitter=0.2, log_level="INFO")
    def flaky_api():
        global call_count
        call_count += 1
        if call_count < 3:
            raise ConnectionError(f"Attempt {call_count} failed")
        return {"status": "ok"}

    print("\n=== Retry with Jitter ===")
    print(flaky_api())
    print(f"Metrics: {flaky_api.metrics.to_dict()}")

    # --- 3. Timeout ---
    @supercharge(timeout=0.5, log_level="INFO")
    def slow_function():
        time.sleep(10)
        return "done"

    print("\n=== Timeout ===")
    try:
        slow_function()
    except DeadlineExceeded as e:
        print(f"Caught: {e}")
    print(f"Metrics: {slow_function.metrics.to_dict()}")

    # --- 4. All combined ---
    @supercharge(cache_ttl=30, max_cache=100, retries=2, retry_delay=0.2, timeout=2.0, log_level="INFO")
    def robust_fetch(key):
        time.sleep(0.05)
        return f"data_for_{key}"

    print("\n=== All Combined ===")
    print(robust_fetch("abc"))
    print(robust_fetch("abc"))  # cached
    print(robust_fetch("xyz"))
    print(f"Metrics: {robust_fetch.metrics.to_dict()}")

    # --- 5. Async support ---
    @supercharge(cache_ttl=5, retries=1, timeout=2.0, log_level="INFO")
    async def async_fetch(url):
        await asyncio.sleep(0.1)
        return f"response_from_{url}"

    print("\n=== Async ===")
    print(asyncio.run(async_fetch("https://example.com")))
    print(asyncio.run(async_fetch("https://example.com")))  # cached
    print(f"Metrics: {async_fetch.metrics.to_dict()}")

    # --- 6. LRU eviction + cache_clear / cache_info ---
    @supercharge(cache_ttl=60, max_cache=3, log_level="INFO")
    def limited_cache(n):
        return n * 2

    print("\n=== LRU Eviction (max_cache=3) ===")
    limited_cache(1)  # cache: {1}
    limited_cache(2)  # cache: {1, 2}
    limited_cache(3)  # cache: {1, 2, 3}
    limited_cache(4)  # cache: {2, 3, 4} — evicts 1
    hit_1, _ = limited_cache.cache.get((1,), {})
    hit_4, _ = limited_cache.cache.get((4,), {})
    print(f"Key 1 in cache: {hit_1}")  # False (evicted)
    print(f"Key 4 in cache: {hit_4}")  # True
    print(f"cache_info: {limited_cache.cache_info()}")
    print(f"Metrics: {limited_cache.metrics.to_dict()}")
    limited_cache.cache_clear()
    print(f"After cache_clear: {limited_cache.cache_info()}")

    # --- 7. retry_max_delay cap ---
    retry_count = 0

    @supercharge(retries=4, retry_delay=1.0, retry_backoff=10.0, retry_max_delay=3.0,
                 retry_jitter=0.0, log_level="INFO")
    def capped_retry():
        global retry_count
        retry_count += 1
        raise ConnectionError(f"fail #{retry_count}")

    print("\n=== Retry Max Delay Cap (max=3s, backoff=10x) ===")
    t_start = time.perf_counter()
    try:
        capped_retry()
    except ConnectionError:
        pass
    total = time.perf_counter() - t_start
    # Without cap: delays would be 1, 10, 100, 1000 = 1111s
    # With cap=3: delays are 1, 3, 3, 3 = 10s max
    print(f"Total time: {total:.1f}s (capped at 3s per retry)")
    print(f"Metrics: {capped_retry.metrics.to_dict()}")
