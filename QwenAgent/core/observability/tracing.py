# -*- coding: utf-8 -*-
"""
===============================================================================
TRACING MODULE - Request correlation and span tracking
===============================================================================

Lightweight distributed tracing without external dependencies.

Features:
- Trace ID propagation (correlation across services)
- Span hierarchy (parent-child relationships)
- Timing and attributes
- Context manager for easy use
- Compatible with OpenTelemetry concepts

Usage:
    from core.observability import trace, get_trace_id

    # Simple span
    with trace("process_request") as span:
        span.set_attribute("user_id", "123")
        result = process(data)
        span.set_attribute("result_size", len(result))

    # Nested spans
    with trace("handle_chat") as parent:
        with trace("classify_input") as child:
            category = classify(message)
        with trace("generate_response") as child:
            response = generate(message)

    # Get current trace ID for logging
    logger.info("Processing", trace_id=get_trace_id())
"""

import time
import uuid
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, Generator, List, Optional
from contextvars import ContextVar

# Context variables for trace propagation
_trace_context: ContextVar[Optional["TraceContext"]] = ContextVar("trace_context", default=None)


def generate_id() -> str:
    """Generate unique ID for traces/spans"""
    return uuid.uuid4().hex[:16]


@dataclass
class Span:
    """
    A span represents a unit of work.

    Attributes:
        name: Operation name
        trace_id: Trace this span belongs to
        span_id: Unique span identifier
        parent_id: Parent span ID (if any)
        start_time: Start timestamp
        end_time: End timestamp
        attributes: Key-value pairs
        events: List of timestamped events
        status: ok, error, or unset
    """
    name: str
    trace_id: str
    span_id: str = field(default_factory=generate_id)
    parent_id: Optional[str] = None
    start_time: float = field(default_factory=time.perf_counter)
    end_time: Optional[float] = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    events: List[Dict[str, Any]] = field(default_factory=list)
    status: str = "unset"
    error: Optional[str] = None

    @property
    def duration_ms(self) -> Optional[float]:
        """Get span duration in milliseconds"""
        if self.end_time is None:
            return None
        return (self.end_time - self.start_time) * 1000

    def set_attribute(self, key: str, value: Any):
        """Set span attribute"""
        self.attributes[key] = value

    def add_event(self, name: str, attributes: Optional[Dict[str, Any]] = None):
        """Add timestamped event"""
        self.events.append({
            "name": name,
            "timestamp": time.perf_counter(),
            "attributes": attributes or {},
        })

    def set_status(self, status: str, error: Optional[str] = None):
        """Set span status (ok, error)"""
        self.status = status
        self.error = error

    def end(self):
        """End the span"""
        self.end_time = time.perf_counter()
        if self.status == "unset":
            self.status = "ok"

    def to_dict(self) -> Dict[str, Any]:
        """Export span as dictionary"""
        return {
            "name": self.name,
            "trace_id": self.trace_id,
            "span_id": self.span_id,
            "parent_id": self.parent_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "attributes": self.attributes,
            "events": self.events,
            "status": self.status,
            "error": self.error,
        }


@dataclass
class TraceContext:
    """
    Context for trace propagation.

    Maintains the current trace ID and span stack.
    """
    trace_id: str = field(default_factory=generate_id)
    spans: List[Span] = field(default_factory=list)
    completed_spans: List[Span] = field(default_factory=list)

    @property
    def current_span(self) -> Optional[Span]:
        """Get current active span"""
        return self.spans[-1] if self.spans else None

    def start_span(self, name: str) -> Span:
        """Start a new span"""
        parent_id = self.current_span.span_id if self.current_span else None
        span = Span(
            name=name,
            trace_id=self.trace_id,
            parent_id=parent_id,
        )
        self.spans.append(span)
        return span

    def end_span(self):
        """End current span"""
        if self.spans:
            span = self.spans.pop()
            span.end()
            self.completed_spans.append(span)
            return span
        return None

    def to_dict(self) -> Dict[str, Any]:
        """Export trace as dictionary"""
        return {
            "trace_id": self.trace_id,
            "spans": [s.to_dict() for s in self.completed_spans],
            "active_spans": [s.to_dict() for s in self.spans],
        }


# Global trace storage (for debugging/export)
_traces: List[TraceContext] = []
_traces_lock = threading.Lock()
_max_traces = 1000


def get_trace_context() -> Optional[TraceContext]:
    """Get current trace context"""
    return _trace_context.get()


def get_trace_id() -> Optional[str]:
    """Get current trace ID"""
    ctx = _trace_context.get()
    return ctx.trace_id if ctx else None


def set_trace_id(trace_id: str):
    """Set trace ID (for propagation from incoming requests)"""
    ctx = _trace_context.get()
    if ctx:
        ctx.trace_id = trace_id
    else:
        ctx = TraceContext(trace_id=trace_id)
        _trace_context.set(ctx)


def get_current_span() -> Optional[Span]:
    """Get current active span"""
    ctx = _trace_context.get()
    return ctx.current_span if ctx else None


@contextmanager
def trace(name: str, trace_id: Optional[str] = None) -> Generator[Span, None, None]:
    """
    Context manager for creating spans.

    Args:
        name: Operation name
        trace_id: Optional trace ID (creates new if not provided)

    Yields:
        Span object

    Usage:
        with trace("my_operation") as span:
            span.set_attribute("key", "value")
            do_work()
    """
    # Get or create trace context
    ctx = _trace_context.get()

    if ctx is None:
        ctx = TraceContext(trace_id=trace_id or generate_id())
        _trace_context.set(ctx)
        is_root = True
    else:
        is_root = False
        if trace_id:
            ctx.trace_id = trace_id

    # Start span
    span = ctx.start_span(name)

    try:
        yield span
    except Exception as e:
        span.set_status("error", str(e))
        raise
    finally:
        ctx.end_span()

        # If root context, store completed trace
        if is_root:
            with _traces_lock:
                _traces.append(ctx)
                # Keep only recent traces
                while len(_traces) > _max_traces:
                    _traces.pop(0)
            _trace_context.set(None)


def get_recent_traces(limit: int = 100) -> List[Dict[str, Any]]:
    """Get recent completed traces"""
    with _traces_lock:
        return [t.to_dict() for t in _traces[-limit:]]


def clear_traces():
    """Clear stored traces"""
    with _traces_lock:
        _traces.clear()


# ============================================================================
# CONVENIENCE DECORATORS
# ============================================================================

def traced(name: Optional[str] = None):
    """
    Decorator for tracing functions.

    Usage:
        @traced()
        def my_function():
            ...

        @traced("custom_name")
        async def my_async_function():
            ...
    """
    def decorator(func):
        span_name = name or func.__name__

        # Check if async
        import asyncio
        if asyncio.iscoroutinefunction(func):
            async def async_wrapper(*args, **kwargs):
                with trace(span_name) as span:
                    span.set_attribute("function", func.__name__)
                    span.set_attribute("module", func.__module__)
                    return await func(*args, **kwargs)
            return async_wrapper
        else:
            def sync_wrapper(*args, **kwargs):
                with trace(span_name) as span:
                    span.set_attribute("function", func.__name__)
                    span.set_attribute("module", func.__module__)
                    return func(*args, **kwargs)
            return sync_wrapper

    return decorator
