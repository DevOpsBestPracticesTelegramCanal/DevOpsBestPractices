# -*- coding: utf-8 -*-
"""
===============================================================================
STRUCTURED LOGGING - JSON-formatted logs with context
===============================================================================

Features:
- JSON output for log aggregation (ELK, Loki, etc.)
- Context propagation (request_id, user, etc.)
- Log levels with colors for console
- Automatic caller info (file, line, function)
- Performance timing helpers

Usage:
    from core.observability import get_logger

    logger = get_logger("qwencode.server")
    logger.info("Request received", method="POST", path="/api/chat")
    logger.error("Failed to process", error=str(e), stack_trace=traceback.format_exc())
"""

import json
import logging
import sys
import traceback
from datetime import datetime
from enum import Enum
from typing import Any, Dict, Optional
from contextvars import ContextVar
import os

# Context variables for request tracking
_request_context: ContextVar[Dict[str, Any]] = ContextVar("request_context", default={})


class LogLevel(Enum):
    """Log levels"""
    DEBUG = logging.DEBUG
    INFO = logging.INFO
    WARNING = logging.WARNING
    ERROR = logging.ERROR
    CRITICAL = logging.CRITICAL


# ANSI colors for console output
class Colors:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"

    # Log level colors
    DEBUG = "\033[36m"      # Cyan
    INFO = "\033[32m"       # Green
    WARNING = "\033[33m"    # Yellow
    ERROR = "\033[31m"      # Red
    CRITICAL = "\033[35m"   # Magenta

    # Field colors
    KEY = "\033[34m"        # Blue
    VALUE = "\033[37m"      # White
    TIME = "\033[90m"       # Gray


class JsonFormatter(logging.Formatter):
    """
    JSON log formatter for structured logging.

    Output format:
    {"timestamp": "...", "level": "INFO", "logger": "qwencode", "message": "...", ...}
    """

    def __init__(self, include_caller: bool = True):
        super().__init__()
        self.include_caller = include_caller

    def format(self, record: logging.LogRecord) -> str:
        # Base log entry
        log_entry = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add caller info
        if self.include_caller:
            log_entry["caller"] = {
                "file": os.path.basename(record.pathname),
                "line": record.lineno,
                "function": record.funcName,
            }

        # Add context from ContextVar
        context = _request_context.get()
        if context:
            log_entry["context"] = context

        # Add extra fields
        extra_fields = {}
        for key, value in record.__dict__.items():
            if key not in (
                "name", "msg", "args", "created", "filename", "funcName",
                "levelname", "levelno", "lineno", "module", "msecs",
                "pathname", "process", "processName", "relativeCreated",
                "stack_info", "exc_info", "exc_text", "thread", "threadName",
                "message", "asctime"
            ):
                extra_fields[key] = value

        if extra_fields:
            log_entry["fields"] = extra_fields

        # Add exception info
        if record.exc_info:
            log_entry["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": traceback.format_exception(*record.exc_info) if record.exc_info[0] else None,
            }

        return json.dumps(log_entry, default=str, ensure_ascii=False)


class ConsoleFormatter(logging.Formatter):
    """
    Colored console formatter for development.

    Output format:
    2024-01-15 10:30:45 | INFO     | qwencode.server | Request received | method=POST path=/api/chat
    """

    LEVEL_COLORS = {
        "DEBUG": Colors.DEBUG,
        "INFO": Colors.INFO,
        "WARNING": Colors.WARNING,
        "ERROR": Colors.ERROR,
        "CRITICAL": Colors.CRITICAL,
    }

    def format(self, record: logging.LogRecord) -> str:
        # Timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Level with color
        level_color = self.LEVEL_COLORS.get(record.levelname, Colors.RESET)
        level = f"{level_color}{record.levelname:8}{Colors.RESET}"

        # Logger name (shortened)
        logger_name = record.name
        if len(logger_name) > 20:
            logger_name = "..." + logger_name[-17:]

        # Message
        message = record.getMessage()

        # Format base line
        line = f"{Colors.TIME}{timestamp}{Colors.RESET} | {level} | {Colors.DIM}{logger_name:20}{Colors.RESET} | {message}"

        # Add extra fields
        extra_parts = []
        for key, value in record.__dict__.items():
            if key not in (
                "name", "msg", "args", "created", "filename", "funcName",
                "levelname", "levelno", "lineno", "module", "msecs",
                "pathname", "process", "processName", "relativeCreated",
                "stack_info", "exc_info", "exc_text", "thread", "threadName",
                "message", "asctime"
            ):
                extra_parts.append(f"{Colors.KEY}{key}{Colors.RESET}={Colors.VALUE}{value}{Colors.RESET}")

        if extra_parts:
            line += " | " + " ".join(extra_parts)

        # Add exception
        if record.exc_info:
            line += f"\n{Colors.ERROR}{traceback.format_exception(*record.exc_info)[-1].strip()}{Colors.RESET}"

        return line


class StructuredLogger:
    """
    Wrapper around logging.Logger with structured logging support.

    Usage:
        logger = StructuredLogger("qwencode.server")
        logger.info("Processing", request_id="123", duration_ms=45.2)
    """

    def __init__(self, name: str, level: LogLevel = LogLevel.INFO):
        self._logger = logging.getLogger(name)
        self._logger.setLevel(level.value)
        self._default_fields: Dict[str, Any] = {}

    def with_fields(self, **fields) -> "StructuredLogger":
        """Create a new logger with additional default fields"""
        new_logger = StructuredLogger(self._logger.name)
        new_logger._logger = self._logger
        new_logger._default_fields = {**self._default_fields, **fields}
        return new_logger

    def _log(self, level: int, message: str, **kwargs):
        """Internal log method"""
        # Merge default fields with kwargs
        extra = {**self._default_fields, **kwargs}
        self._logger.log(level, message, extra=extra)

    def debug(self, message: str, **kwargs):
        """Log debug message"""
        self._log(logging.DEBUG, message, **kwargs)

    def info(self, message: str, **kwargs):
        """Log info message"""
        self._log(logging.INFO, message, **kwargs)

    def warning(self, message: str, **kwargs):
        """Log warning message"""
        self._log(logging.WARNING, message, **kwargs)

    def error(self, message: str, exc_info: bool = False, **kwargs):
        """Log error message"""
        if exc_info:
            self._logger.error(message, exc_info=True, extra={**self._default_fields, **kwargs})
        else:
            self._log(logging.ERROR, message, **kwargs)

    def critical(self, message: str, exc_info: bool = False, **kwargs):
        """Log critical message"""
        if exc_info:
            self._logger.critical(message, exc_info=True, extra={**self._default_fields, **kwargs})
        else:
            self._log(logging.CRITICAL, message, **kwargs)

    def exception(self, message: str, **kwargs):
        """Log exception with traceback"""
        self._logger.exception(message, extra={**self._default_fields, **kwargs})


# Global configuration
_configured = False
_loggers: Dict[str, StructuredLogger] = {}


def configure_logging(
    level: LogLevel = LogLevel.INFO,
    json_output: bool = False,
    log_file: Optional[str] = None,
):
    """
    Configure global logging settings.

    Args:
        level: Minimum log level
        json_output: Use JSON format (for production)
        log_file: Optional file path for log output
    """
    global _configured

    # Root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level.value)

    # Remove existing handlers
    root_logger.handlers.clear()

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level.value)

    if json_output:
        console_handler.setFormatter(JsonFormatter())
    else:
        console_handler.setFormatter(ConsoleFormatter())

    root_logger.addHandler(console_handler)

    # File handler
    if log_file:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setLevel(level.value)
        file_handler.setFormatter(JsonFormatter())
        root_logger.addHandler(file_handler)

    _configured = True


def get_logger(name: str) -> StructuredLogger:
    """
    Get or create a structured logger.

    Args:
        name: Logger name (e.g., "qwencode.server")

    Returns:
        StructuredLogger instance
    """
    global _configured

    # Auto-configure if not done
    if not _configured:
        configure_logging()

    # Cache loggers
    if name not in _loggers:
        _loggers[name] = StructuredLogger(name)

    return _loggers[name]


def set_context(**kwargs):
    """Set request context for all logs in current async context"""
    current = _request_context.get()
    _request_context.set({**current, **kwargs})


def clear_context():
    """Clear request context"""
    _request_context.set({})


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def log_request(logger: StructuredLogger, method: str, path: str, **kwargs):
    """Log incoming request"""
    logger.info("Request received", method=method, path=path, **kwargs)


def log_response(logger: StructuredLogger, status: int, duration_ms: float, **kwargs):
    """Log outgoing response"""
    level = logging.INFO if status < 400 else logging.WARNING if status < 500 else logging.ERROR
    logger._log(level, "Response sent", status=status, duration_ms=round(duration_ms, 2), **kwargs)


def log_llm_call(logger: StructuredLogger, model: str, tokens: int, duration_ms: float, **kwargs):
    """Log LLM call"""
    logger.info("LLM call completed", model=model, tokens=tokens, duration_ms=round(duration_ms, 2), **kwargs)
