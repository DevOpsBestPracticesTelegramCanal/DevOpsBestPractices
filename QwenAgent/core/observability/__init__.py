# -*- coding: utf-8 -*-
"""
===============================================================================
OBSERVABILITY MODULE - Structured Logging, Metrics, Tracing
===============================================================================

Phase 4 Refactoring: Comprehensive observability for QwenCode.

Components:
- Structured JSON logging with context
- Metrics collection (counters, gauges, histograms)
- Request tracing with correlation IDs
- Performance monitoring

Usage:
    from core.observability import get_logger, metrics, trace

    logger = get_logger("my_component")
    logger.info("Processing request", request_id="123", user="test")

    with trace("llm_call") as span:
        span.set_attribute("model", "qwen2.5-coder:7b")
        result = await llm.generate(prompt)

    metrics.counter("requests_total").inc()
    metrics.histogram("response_time").observe(duration)
"""

from .logging import (
    get_logger,
    configure_logging,
    LogLevel,
    StructuredLogger,
    JsonFormatter,
)

from .metrics import (
    metrics,
    MetricsRegistry,
    Counter,
    Gauge,
    Histogram,
    Timer,
)

from .tracing import (
    trace,
    Span,
    TraceContext,
    get_trace_id,
    set_trace_id,
)

__all__ = [
    # Logging
    "get_logger",
    "configure_logging",
    "LogLevel",
    "StructuredLogger",
    "JsonFormatter",
    # Metrics
    "metrics",
    "MetricsRegistry",
    "Counter",
    "Gauge",
    "Histogram",
    "Timer",
    # Tracing
    "trace",
    "Span",
    "TraceContext",
    "get_trace_id",
    "set_trace_id",
]
