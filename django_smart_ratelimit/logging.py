"""
Structured JSON Logging for Django Smart Ratelimit.

This module provides structured JSON logging support for rate limiting events,
designed for integration with ELK stacks, Datadog, Splunk, and other log
aggregation systems.

Features:
    - JSON formatter compatible with Python's logging module
    - Structured log events for rate limit checks, backend operations,
      circuit breaker state changes, and more
    - Request context enrichment (request ID, IP, path, method)
    - Configurable via Django settings (RATELIMIT_LOGGING)
    - Backward compatible — existing text logging continues to work
    - Middleware for automatic request context injection

Configuration example::

    # settings.py
    RATELIMIT_LOGGING = {
        "ENABLED": True,
        "FORMAT": "json",            # "json" or "text" (default: "text")
        "LOGGER_NAME": "django_smart_ratelimit",
        "INCLUDE_TIMESTAMP": True,
        "INCLUDE_REQUEST_ID": True,
        "EXTRA_FIELDS": {},           # Additional static fields for all log entries
    }

    LOGGING = {
        "version": 1,
        "handlers": {
            "ratelimit_json": {
                "class": "logging.StreamHandler",
                "formatter": "ratelimit_json",
            },
        },
        "formatters": {
            "ratelimit_json": {
                "()": "django_smart_ratelimit.logging.JSONFormatter",
            },
        },
        "loggers": {
            "django_smart_ratelimit": {
                "handlers": ["ratelimit_json"],
                "level": "INFO",
            },
        },
    }
"""

import datetime
import json
import logging
import threading
import uuid
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger(__name__)

# Thread-local storage for request context
_request_context = threading.local()

# Default settings
_DEFAULT_SETTINGS: Dict[str, Any] = {
    "ENABLED": False,
    "FORMAT": "text",
    "LOGGER_NAME": "django_smart_ratelimit",
    "INCLUDE_TIMESTAMP": True,
    "INCLUDE_REQUEST_ID": True,
    "EXTRA_FIELDS": {},
}


def _get_logging_settings() -> Dict[str, Any]:
    """
    Get logging settings from Django configuration.

    Returns:
        Merged settings dict with defaults applied.
    """
    try:
        from django.conf import settings

        user_settings = getattr(settings, "RATELIMIT_LOGGING", {})
    except (ImportError, Exception):
        user_settings = {}

    merged = {**_DEFAULT_SETTINGS, **user_settings}
    return merged


def _is_json_logging_enabled() -> bool:
    """Check whether structured JSON logging is enabled."""
    settings = _get_logging_settings()
    return bool(settings.get("ENABLED")) and settings.get("FORMAT") == "json"


# ============================================================================
# Request Context Management
# ============================================================================


def set_request_context(
    request_id: Optional[str] = None,
    ip: Optional[str] = None,
    path: Optional[str] = None,
    method: Optional[str] = None,
    user: Optional[str] = None,
    **extra: Any,
) -> None:
    """
    Set request context for the current thread.

    This is typically called by ``StructuredLoggingMiddleware`` at the
    start of each request. The context is automatically attached to all
    structured log entries emitted during request processing.

    Args:
        request_id: Unique request identifier.
        ip: Client IP address.
        path: Request path.
        method: HTTP method.
        user: Authenticated user identifier.
        **extra: Additional context fields.
    """
    _request_context.data = {
        "request_id": request_id,
        "ip": ip,
        "path": path,
        "method": method,
        "user": user,
        **extra,
    }


def get_request_context() -> Dict[str, Any]:
    """
    Get the current thread's request context.

    Returns:
        Dict of request context fields. Empty dict if no context set.
    """
    return getattr(_request_context, "data", {})


def clear_request_context() -> None:
    """Clear the current thread's request context."""
    _request_context.data = {}


# ============================================================================
# Structured Log Event Builder
# ============================================================================


class RateLimitLogEvent:
    """
    Builder for structured rate limit log events.

    Constructs a log event dict with a consistent schema, merging
    request context, event-specific fields, and global extra fields.

    Example::

        event = RateLimitLogEvent(
            event="rate_limit_check",
            key="user:42",
            backend="redis",
        )
        event.set_result(allowed=True, remaining=8, limit=10, window=60)
        event.set_duration(0.0023)
        logger.info("Rate limit check", extra={"structured": event.as_dict()})
    """

    def __init__(
        self,
        event: str,
        key: Optional[str] = None,
        backend: Optional[str] = None,
        algorithm: Optional[str] = None,
        **fields: Any,
    ) -> None:
        """
        Initialize a log event.

        Args:
            event: Event type identifier (e.g., ``"rate_limit_check"``).
            key: Rate limit key being checked.
            backend: Backend name/type.
            algorithm: Algorithm name.
            **fields: Additional event-specific fields.
        """
        self._data: Dict[str, Any] = {
            "event": event,
        }
        if key is not None:
            self._data["key"] = key
        if backend is not None:
            self._data["backend"] = backend
        if algorithm is not None:
            self._data["algorithm"] = algorithm
        self._data.update(fields)

    def set_result(
        self,
        allowed: Optional[bool] = None,
        remaining: Optional[int] = None,
        limit: Optional[int] = None,
        window: Optional[int] = None,
        reset: Optional[float] = None,
    ) -> "RateLimitLogEvent":
        """
        Set rate limit result fields.

        Args:
            allowed: Whether the request was allowed.
            remaining: Remaining requests in the window.
            limit: Maximum requests allowed.
            window: Window duration in seconds.
            reset: Time until the window resets (seconds).

        Returns:
            Self for method chaining.
        """
        if allowed is not None:
            self._data["allowed"] = allowed
        if remaining is not None:
            self._data["remaining"] = remaining
        if limit is not None:
            self._data["limit"] = limit
        if window is not None:
            self._data["window"] = window
        if reset is not None:
            self._data["reset"] = reset
        return self

    def set_duration(self, duration_seconds: float) -> "RateLimitLogEvent":
        """
        Set operation duration.

        Args:
            duration_seconds: Duration in seconds.

        Returns:
            Self for method chaining.
        """
        self._data["duration_ms"] = round(duration_seconds * 1000, 3)
        return self

    def set_error(
        self, error: str, exc_type: Optional[str] = None
    ) -> "RateLimitLogEvent":
        """
        Set error information.

        Args:
            error: Error message.
            exc_type: Exception class name.

        Returns:
            Self for method chaining.
        """
        self._data["error"] = error
        if exc_type:
            self._data["exc_type"] = exc_type
        return self

    def add_fields(self, **fields: Any) -> "RateLimitLogEvent":
        """
        Add arbitrary fields to the event.

        Args:
            **fields: Key-value pairs to add.

        Returns:
            Self for method chaining.
        """
        self._data.update(fields)
        return self

    def as_dict(self) -> Dict[str, Any]:
        """
        Build the complete log event dict.

        Merges event data with request context and global extra fields.

        Returns:
            Complete structured log event dict.
        """
        settings = _get_logging_settings()
        result: Dict[str, Any] = {}

        # Add timestamp
        if settings.get("INCLUDE_TIMESTAMP", True):
            result["timestamp"] = datetime.datetime.now(
                datetime.timezone.utc
            ).isoformat()

        # Add logger name
        result["logger"] = settings.get("LOGGER_NAME", "django_smart_ratelimit")

        # Add request context
        ctx = get_request_context()
        if ctx:
            request_fields = {k: v for k, v in ctx.items() if v is not None}
            if request_fields:
                result["request"] = request_fields

        # Add event data
        result.update(self._data)

        # Add global extra fields
        extra = settings.get("EXTRA_FIELDS", {})
        if extra:
            result.update(extra)

        return result


# ============================================================================
# JSON Formatter
# ============================================================================


class JSONFormatter(logging.Formatter):
    """
    JSON log formatter for Python's logging module.

    Converts log records into single-line JSON objects. If a log record
    contains a ``structured`` key in its ``extra`` dict (as produced by
    ``RateLimitLogEvent``), that dict is used as the base. Otherwise the
    formatter builds a JSON object from the standard log record fields.

    Usage in Django LOGGING config::

        LOGGING = {
            "formatters": {
                "ratelimit_json": {
                    "()": "django_smart_ratelimit.logging.JSONFormatter",
                },
            },
        }
    """

    # Fields to always exclude from extra data
    _RESERVED_ATTRS = frozenset(
        {
            "args",
            "asctime",
            "created",
            "exc_info",
            "exc_text",
            "filename",
            "funcName",
            "levelname",
            "levelno",
            "lineno",
            "message",
            "module",
            "msecs",
            "msg",
            "name",
            "pathname",
            "process",
            "processName",
            "relativeCreated",
            "stack_info",
            "taskName",
            "thread",
            "threadName",
            "structured",
        }
    )

    def __init__(
        self,
        include_timestamp: bool = True,
        include_logger_name: bool = True,
        include_level: bool = True,
        include_extra: bool = True,
        **kwargs: Any,
    ) -> None:
        """
        Initialize the JSON formatter.

        Args:
            include_timestamp: Include ISO timestamp.
            include_logger_name: Include logger name.
            include_level: Include log level.
            include_extra: Include extra fields from log record.
            **kwargs: Passed to ``logging.Formatter.__init__``.
        """
        super().__init__(**kwargs)
        self.include_timestamp = include_timestamp
        self.include_logger_name = include_logger_name
        self.include_level = include_level
        self.include_extra = include_extra

    def format(self, record: logging.LogRecord) -> str:
        """
        Format a log record as a JSON string.

        Args:
            record: The log record to format.

        Returns:
            Single-line JSON string.
        """
        # Check for structured event data
        structured = getattr(record, "structured", None)
        if isinstance(structured, dict):
            output = dict(structured)
        else:
            output = {}
            if self.include_timestamp:
                output["timestamp"] = datetime.datetime.fromtimestamp(
                    record.created, tz=datetime.timezone.utc
                ).isoformat()
            if self.include_logger_name:
                output["logger"] = record.name
            if self.include_level:
                output["level"] = record.levelname
            output["message"] = record.getMessage()

        # Ensure level is present
        if "level" not in output:
            output["level"] = record.levelname

        # Ensure message is present
        if "message" not in output:
            output["message"] = record.getMessage()

        # Add extra fields from the log record
        if self.include_extra:
            for key, value in record.__dict__.items():
                if key not in self._RESERVED_ATTRS and key not in output:
                    try:
                        json.dumps(value)  # Check serializable
                        output[key] = value
                    except (TypeError, ValueError):
                        output[key] = str(value)

        # Add exception info
        if record.exc_info and record.exc_info[1]:
            output["exception"] = {
                "type": (
                    record.exc_info[0].__name__ if record.exc_info[0] else "Unknown"
                ),
                "message": str(record.exc_info[1]),
                "traceback": self.formatException(record.exc_info),
            }

        # Add stack info
        if record.stack_info:
            output["stack_info"] = record.stack_info

        return json.dumps(output, default=str, ensure_ascii=False)


# ============================================================================
# Convenience Logging Functions
# ============================================================================


def log_rate_limit_check(
    key: str,
    backend: str,
    allowed: bool,
    remaining: Optional[int] = None,
    limit: Optional[int] = None,
    window: Optional[int] = None,
    duration_seconds: Optional[float] = None,
    algorithm: Optional[str] = None,
    **extra: Any,
) -> None:
    """
    Log a rate limit check event.

    This is the primary structured logging entry point for rate limit
    decisions. Call this after each rate limit check to produce a
    structured log entry.

    Args:
        key: Rate limit key.
        backend: Backend type/name.
        allowed: Whether the request was allowed.
        remaining: Remaining requests in the window.
        limit: Maximum requests allowed.
        window: Window duration in seconds.
        duration_seconds: Check duration in seconds.
        algorithm: Algorithm name.
        **extra: Additional fields.
    """
    if not _is_json_logging_enabled():
        return

    settings = _get_logging_settings()
    log_name = settings.get("LOGGER_NAME", "django_smart_ratelimit")
    log = logging.getLogger(log_name)

    event = RateLimitLogEvent(
        event="rate_limit_check",
        key=key,
        backend=backend,
        algorithm=algorithm,
    )
    event.set_result(
        allowed=allowed,
        remaining=remaining,
        limit=limit,
        window=window,
    )
    if duration_seconds is not None:
        event.set_duration(duration_seconds)
    if extra:
        event.add_fields(**extra)

    level = logging.INFO if allowed else logging.WARNING
    action = "allowed" if allowed else "denied"
    log.log(
        level,
        f"Rate limit {action}: key={key} backend={backend}",
        extra={"structured": event.as_dict()},
    )


def log_backend_event(
    event_type: str,
    backend: str,
    operation: Optional[str] = None,
    key: Optional[str] = None,
    success: bool = True,
    duration_seconds: Optional[float] = None,
    error: Optional[str] = None,
    **extra: Any,
) -> None:
    """
    Log a backend operation event.

    Args:
        event_type: Event identifier (e.g., ``"backend_operation"``).
        backend: Backend type/name.
        operation: Operation name (e.g., ``"incr"``, ``"get_count"``).
        key: Rate limit key.
        success: Whether the operation succeeded.
        duration_seconds: Operation duration in seconds.
        error: Error message if failed.
        **extra: Additional fields.
    """
    if not _is_json_logging_enabled():
        return

    settings = _get_logging_settings()
    log_name = settings.get("LOGGER_NAME", "django_smart_ratelimit")
    log = logging.getLogger(log_name)

    event = RateLimitLogEvent(
        event=event_type,
        backend=backend,
        key=key,
        operation=operation,
        success=success,
    )
    if duration_seconds is not None:
        event.set_duration(duration_seconds)
    if error:
        event.set_error(error)
    if extra:
        event.add_fields(**extra)

    level = logging.INFO if success else logging.ERROR
    status = "succeeded" if success else "failed"
    msg = f"Backend {operation or event_type} {status}: backend={backend}"
    if key:
        msg += f" key={key}"
    log.log(level, msg, extra={"structured": event.as_dict()})


def log_circuit_breaker_event(
    backend: str,
    previous_state: str,
    new_state: str,
    reason: Optional[str] = None,
    failure_count: Optional[int] = None,
    **extra: Any,
) -> None:
    """
    Log a circuit breaker state transition.

    Args:
        backend: Backend name.
        previous_state: Previous circuit breaker state.
        new_state: New circuit breaker state.
        reason: Reason for the transition.
        failure_count: Current failure count.
        **extra: Additional fields.
    """
    if not _is_json_logging_enabled():
        return

    settings = _get_logging_settings()
    log_name = settings.get("LOGGER_NAME", "django_smart_ratelimit")
    log = logging.getLogger(log_name)

    event = RateLimitLogEvent(
        event="circuit_breaker_state_change",
        backend=backend,
        previous_state=previous_state,
        new_state=new_state,
    )
    if reason:
        event.add_fields(reason=reason)
    if failure_count is not None:
        event.add_fields(failure_count=failure_count)
    if extra:
        event.add_fields(**extra)

    level = logging.WARNING if new_state == "open" else logging.INFO
    log.log(
        level,
        f"Circuit breaker {previous_state} -> {new_state}: backend={backend}",
        extra={"structured": event.as_dict()},
    )


def log_adaptive_event(
    key: str,
    original_limit: int,
    adjusted_limit: int,
    load_factor: float,
    indicators: Optional[Dict[str, float]] = None,
    **extra: Any,
) -> None:
    """
    Log an adaptive rate limit adjustment.

    Args:
        key: Rate limit key.
        original_limit: Original rate limit.
        adjusted_limit: Adjusted rate limit after load factor.
        load_factor: Load factor applied (0.0 to 1.0).
        indicators: Individual load indicator values.
        **extra: Additional fields.
    """
    if not _is_json_logging_enabled():
        return

    settings = _get_logging_settings()
    log_name = settings.get("LOGGER_NAME", "django_smart_ratelimit")
    log = logging.getLogger(log_name)

    event = RateLimitLogEvent(
        event="adaptive_adjustment",
        key=key,
        original_limit=original_limit,
        adjusted_limit=adjusted_limit,
        load_factor=round(load_factor, 4),
    )
    if indicators:
        event.add_fields(indicators=indicators)
    if extra:
        event.add_fields(**extra)

    log.info(
        f"Adaptive limit adjusted: {original_limit} -> {adjusted_limit} "
        f"(load_factor={load_factor:.2f})",
        extra={"structured": event.as_dict()},
    )


# ============================================================================
# Middleware
# ============================================================================


class StructuredLoggingMiddleware:
    """
    Django middleware that injects request context for structured logging.

    Adds a unique request ID and request metadata to the thread-local
    context so that all structured log entries emitted during request
    processing include this information automatically.

    Add to ``MIDDLEWARE``::

        MIDDLEWARE = [
            "django_smart_ratelimit.logging.StructuredLoggingMiddleware",
            # ... other middleware ...
        ]
    """

    def __init__(self, get_response: Callable) -> None:
        """
        Initialize the middleware.

        Args:
            get_response: The next middleware or view callable.
        """
        self.get_response = get_response

    def __call__(self, request: Any) -> Any:
        """
        Process a request, injecting logging context.

        Args:
            request: Django HttpRequest.

        Returns:
            HttpResponse from the view.
        """
        settings = _get_logging_settings()
        if not settings.get("ENABLED"):
            return self.get_response(request)

        # Generate or retrieve request ID
        request_id = (
            request.META.get("HTTP_X_REQUEST_ID")
            or request.META.get("HTTP_X_CORRELATION_ID")
            or uuid.uuid4().hex[:16]
        )

        # Extract client IP
        ip = request.META.get("HTTP_X_FORWARDED_FOR", "").split(",")[
            0
        ].strip() or request.META.get("REMOTE_ADDR", "")

        # Extract user identifier
        user = None
        if hasattr(request, "user") and hasattr(request.user, "is_authenticated"):
            try:
                if request.user.is_authenticated:
                    user = str(getattr(request.user, "pk", request.user))
            except Exception:  # nosec B110 - intentional: resilient error handling
                pass

        # Set thread-local context
        set_request_context(
            request_id=request_id,
            ip=ip,
            path=request.path,
            method=request.method,
            user=user,
        )

        # Store request ID on the request object for other middleware
        request.ratelimit_request_id = request_id

        try:
            response = self.get_response(request)
            return response
        finally:
            clear_request_context()
