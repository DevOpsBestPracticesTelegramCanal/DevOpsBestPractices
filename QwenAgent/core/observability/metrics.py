# -*- coding: utf-8 -*-
"""
===============================================================================
METRICS MODULE - Counters, Gauges, Histograms
===============================================================================

Lightweight metrics collection compatible with Prometheus format.

Features:
- Counter: Monotonically increasing values (requests, errors)
- Gauge: Values that go up and down (active connections, memory)
- Histogram: Distribution of values (response times, sizes)
- Timer: Convenience wrapper for measuring durations
- Labels support for dimensional metrics
- JSON/Prometheus export

Usage:
    from core.observability import metrics

    # Counter
    metrics.counter("requests_total", labels={"method": "POST"}).inc()

    # Gauge
    metrics.gauge("active_connections").set(42)

    # Histogram
    metrics.histogram("response_time_seconds").observe(0.125)

    # Timer (context manager)
    with metrics.timer("llm_call_duration"):
        result = await llm.generate(prompt)

    # Export
    print(metrics.to_prometheus())
"""

import time
import threading
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from collections import defaultdict


@dataclass
class MetricValue:
    """Single metric value with optional labels"""
    value: float = 0.0
    labels: Dict[str, str] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)


class Counter:
    """
    Monotonically increasing counter.

    Usage:
        counter = Counter("requests_total", "Total requests")
        counter.inc()
        counter.inc(5)
        counter.labels(method="POST").inc()
    """

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self._values: Dict[Tuple, MetricValue] = {}
        self._lock = threading.Lock()

    def _key(self, labels: Dict[str, str]) -> Tuple:
        """Create hashable key from labels"""
        return tuple(sorted(labels.items()))

    def labels(self, **labels) -> "Counter":
        """Return counter with specific labels"""
        counter = Counter(self.name, self.description)
        counter._values = self._values
        counter._lock = self._lock
        counter._default_labels = labels
        return counter

    def inc(self, value: float = 1.0):
        """Increment counter"""
        labels = getattr(self, "_default_labels", {})
        key = self._key(labels)

        with self._lock:
            if key not in self._values:
                self._values[key] = MetricValue(labels=labels)
            self._values[key].value += value
            self._values[key].updated_at = time.time()

    def get(self, labels: Optional[Dict[str, str]] = None) -> float:
        """Get current value"""
        labels = labels or getattr(self, "_default_labels", {})
        key = self._key(labels)
        with self._lock:
            return self._values.get(key, MetricValue()).value

    def values(self) -> List[MetricValue]:
        """Get all values"""
        with self._lock:
            return list(self._values.values())


class Gauge:
    """
    Gauge that can go up and down.

    Usage:
        gauge = Gauge("active_connections", "Active connections")
        gauge.set(10)
        gauge.inc()
        gauge.dec()
    """

    def __init__(self, name: str, description: str = ""):
        self.name = name
        self.description = description
        self._values: Dict[Tuple, MetricValue] = {}
        self._lock = threading.Lock()

    def _key(self, labels: Dict[str, str]) -> Tuple:
        return tuple(sorted(labels.items()))

    def labels(self, **labels) -> "Gauge":
        gauge = Gauge(self.name, self.description)
        gauge._values = self._values
        gauge._lock = self._lock
        gauge._default_labels = labels
        return gauge

    def set(self, value: float):
        """Set gauge value"""
        labels = getattr(self, "_default_labels", {})
        key = self._key(labels)

        with self._lock:
            if key not in self._values:
                self._values[key] = MetricValue(labels=labels)
            self._values[key].value = value
            self._values[key].updated_at = time.time()

    def inc(self, value: float = 1.0):
        """Increment gauge"""
        labels = getattr(self, "_default_labels", {})
        key = self._key(labels)

        with self._lock:
            if key not in self._values:
                self._values[key] = MetricValue(labels=labels)
            self._values[key].value += value
            self._values[key].updated_at = time.time()

    def dec(self, value: float = 1.0):
        """Decrement gauge"""
        self.inc(-value)

    def get(self, labels: Optional[Dict[str, str]] = None) -> float:
        labels = labels or getattr(self, "_default_labels", {})
        key = self._key(labels)
        with self._lock:
            return self._values.get(key, MetricValue()).value

    def values(self) -> List[MetricValue]:
        with self._lock:
            return list(self._values.values())


class Histogram:
    """
    Histogram for measuring distributions.

    Usage:
        histogram = Histogram("response_time_seconds", buckets=[0.01, 0.05, 0.1, 0.5, 1.0])
        histogram.observe(0.125)
    """

    DEFAULT_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)

    def __init__(
        self,
        name: str,
        description: str = "",
        buckets: Tuple[float, ...] = DEFAULT_BUCKETS
    ):
        self.name = name
        self.description = description
        self.buckets = tuple(sorted(buckets)) + (float("inf"),)
        self._values: Dict[Tuple, Dict[str, Any]] = {}
        self._lock = threading.Lock()

    def _key(self, labels: Dict[str, str]) -> Tuple:
        return tuple(sorted(labels.items()))

    def _init_bucket(self, key: Tuple, labels: Dict[str, str]):
        """Initialize bucket structure"""
        self._values[key] = {
            "labels": labels,
            "buckets": {b: 0 for b in self.buckets},
            "sum": 0.0,
            "count": 0,
            "created_at": time.time(),
            "updated_at": time.time(),
        }

    def labels(self, **labels) -> "Histogram":
        histogram = Histogram(self.name, self.description, self.buckets[:-1])
        histogram._values = self._values
        histogram._lock = self._lock
        histogram._default_labels = labels
        return histogram

    def observe(self, value: float):
        """Record an observation"""
        labels = getattr(self, "_default_labels", {})
        key = self._key(labels)

        with self._lock:
            if key not in self._values:
                self._init_bucket(key, labels)

            data = self._values[key]
            data["sum"] += value
            data["count"] += 1
            data["updated_at"] = time.time()

            # Update buckets
            for bucket in self.buckets:
                if value <= bucket:
                    data["buckets"][bucket] += 1

    def get_stats(self, labels: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """Get histogram statistics"""
        labels = labels or getattr(self, "_default_labels", {})
        key = self._key(labels)

        with self._lock:
            data = self._values.get(key)
            if not data:
                return {"count": 0, "sum": 0, "buckets": {}}

            return {
                "count": data["count"],
                "sum": data["sum"],
                "avg": data["sum"] / data["count"] if data["count"] > 0 else 0,
                "buckets": dict(data["buckets"]),
            }


class Timer:
    """
    Context manager for timing operations.

    Usage:
        with Timer(histogram) as timer:
            do_something()
        # Automatically records duration to histogram
    """

    def __init__(self, histogram: Histogram):
        self.histogram = histogram
        self.start_time: Optional[float] = None
        self.duration: Optional[float] = None

    def __enter__(self) -> "Timer":
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, *args):
        self.duration = time.perf_counter() - self.start_time
        self.histogram.observe(self.duration)


class MetricsRegistry:
    """
    Central registry for all metrics.

    Usage:
        registry = MetricsRegistry()
        counter = registry.counter("requests_total")
        gauge = registry.gauge("active_connections")
    """

    def __init__(self):
        self._counters: Dict[str, Counter] = {}
        self._gauges: Dict[str, Gauge] = {}
        self._histograms: Dict[str, Histogram] = {}
        self._lock = threading.Lock()

    def counter(self, name: str, description: str = "", labels: Optional[Dict[str, str]] = None) -> Counter:
        """Get or create counter"""
        with self._lock:
            if name not in self._counters:
                self._counters[name] = Counter(name, description)
            counter = self._counters[name]
            if labels:
                return counter.labels(**labels)
            return counter

    def gauge(self, name: str, description: str = "", labels: Optional[Dict[str, str]] = None) -> Gauge:
        """Get or create gauge"""
        with self._lock:
            if name not in self._gauges:
                self._gauges[name] = Gauge(name, description)
            gauge = self._gauges[name]
            if labels:
                return gauge.labels(**labels)
            return gauge

    def histogram(
        self,
        name: str,
        description: str = "",
        buckets: Tuple[float, ...] = Histogram.DEFAULT_BUCKETS,
        labels: Optional[Dict[str, str]] = None
    ) -> Histogram:
        """Get or create histogram"""
        with self._lock:
            if name not in self._histograms:
                self._histograms[name] = Histogram(name, description, buckets)
            histogram = self._histograms[name]
            if labels:
                return histogram.labels(**labels)
            return histogram

    def timer(self, name: str, description: str = "", labels: Optional[Dict[str, str]] = None) -> Timer:
        """Create timer for histogram"""
        histogram = self.histogram(name, description, labels=labels)
        return Timer(histogram)

    def to_dict(self) -> Dict[str, Any]:
        """Export all metrics as dictionary"""
        result = {
            "counters": {},
            "gauges": {},
            "histograms": {},
        }

        with self._lock:
            for name, counter in self._counters.items():
                result["counters"][name] = [
                    {"value": v.value, "labels": v.labels}
                    for v in counter.values()
                ]

            for name, gauge in self._gauges.items():
                result["gauges"][name] = [
                    {"value": v.value, "labels": v.labels}
                    for v in gauge.values()
                ]

            for name, histogram in self._histograms.items():
                result["histograms"][name] = histogram.get_stats()

        return result

    def to_prometheus(self) -> str:
        """Export metrics in Prometheus format"""
        lines = []

        with self._lock:
            # Counters
            for name, counter in self._counters.items():
                if counter.description:
                    lines.append(f"# HELP {name} {counter.description}")
                lines.append(f"# TYPE {name} counter")
                for v in counter.values():
                    labels_str = self._format_labels(v.labels)
                    lines.append(f"{name}{labels_str} {v.value}")

            # Gauges
            for name, gauge in self._gauges.items():
                if gauge.description:
                    lines.append(f"# HELP {name} {gauge.description}")
                lines.append(f"# TYPE {name} gauge")
                for v in gauge.values():
                    labels_str = self._format_labels(v.labels)
                    lines.append(f"{name}{labels_str} {v.value}")

            # Histograms
            for name, histogram in self._histograms.items():
                if histogram.description:
                    lines.append(f"# HELP {name} {histogram.description}")
                lines.append(f"# TYPE {name} histogram")

                for key, data in histogram._values.items():
                    labels = data["labels"]
                    labels_str = self._format_labels(labels)

                    # Buckets
                    for bucket, count in sorted(data["buckets"].items()):
                        bucket_labels = {**labels, "le": str(bucket) if bucket != float("inf") else "+Inf"}
                        lines.append(f"{name}_bucket{self._format_labels(bucket_labels)} {count}")

                    # Sum and count
                    lines.append(f"{name}_sum{labels_str} {data['sum']}")
                    lines.append(f"{name}_count{labels_str} {data['count']}")

        return "\n".join(lines)

    def _format_labels(self, labels: Dict[str, str]) -> str:
        """Format labels for Prometheus"""
        if not labels:
            return ""
        parts = [f'{k}="{v}"' for k, v in sorted(labels.items())]
        return "{" + ",".join(parts) + "}"

    def reset(self):
        """Reset all metrics"""
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()


# Global metrics registry
metrics = MetricsRegistry()
