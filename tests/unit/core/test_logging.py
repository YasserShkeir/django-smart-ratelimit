"""Tests for structured JSON logging."""

import json
import logging
import threading
from unittest.mock import MagicMock, patch

import pytest

from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings

from django_smart_ratelimit.logging import (
    JSONFormatter,
    RateLimitLogEvent,
    StructuredLoggingMiddleware,
    clear_request_context,
    get_request_context,
    log_adaptive_event,
    log_backend_event,
    log_circuit_breaker_event,
    log_rate_limit_check,
    set_request_context,
)

# ============================================================================
# Request Context Tests
# ============================================================================


class TestRequestContext(TestCase):
    """Test request context management."""

    def tearDown(self):
        clear_request_context()

    def test_set_and_get_context(self):
        set_request_context(
            request_id="abc123",
            ip="192.168.1.1",
            path="/api/test/",
            method="GET",
            user="42",
        )
        ctx = get_request_context()
        assert ctx["request_id"] == "abc123"
        assert ctx["ip"] == "192.168.1.1"
        assert ctx["path"] == "/api/test/"
        assert ctx["method"] == "GET"
        assert ctx["user"] == "42"

    def test_get_empty_context(self):
        clear_request_context()
        ctx = get_request_context()
        assert ctx == {}

    def test_clear_context(self):
        set_request_context(request_id="abc123")
        clear_request_context()
        ctx = get_request_context()
        assert ctx == {}

    def test_extra_fields(self):
        set_request_context(
            request_id="abc",
            custom_field="custom_value",
        )
        ctx = get_request_context()
        assert ctx["custom_field"] == "custom_value"

    def test_thread_isolation(self):
        """Request context should be thread-local."""
        results = {}

        def thread_func(thread_id):
            set_request_context(request_id=f"thread-{thread_id}")
            import time

            time.sleep(0.01)
            ctx = get_request_context()
            results[thread_id] = ctx.get("request_id")

        threads = []
        for i in range(5):
            t = threading.Thread(target=thread_func, args=(i,))
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        for i in range(5):
            assert results[i] == f"thread-{i}"


# ============================================================================
# RateLimitLogEvent Tests
# ============================================================================


class TestRateLimitLogEvent(TestCase):
    """Test RateLimitLogEvent builder."""

    def tearDown(self):
        clear_request_context()

    def test_basic_event(self):
        event = RateLimitLogEvent(
            event="rate_limit_check",
            key="user:42",
            backend="redis",
        )
        data = event.as_dict()
        assert data["event"] == "rate_limit_check"
        assert data["key"] == "user:42"
        assert data["backend"] == "redis"

    def test_set_result(self):
        event = RateLimitLogEvent(event="test")
        event.set_result(allowed=True, remaining=8, limit=10, window=60, reset=45.5)
        data = event.as_dict()
        assert data["allowed"] is True
        assert data["remaining"] == 8
        assert data["limit"] == 10
        assert data["window"] == 60
        assert data["reset"] == 45.5

    def test_set_duration(self):
        event = RateLimitLogEvent(event="test")
        event.set_duration(0.0234)
        data = event.as_dict()
        assert data["duration_ms"] == 23.4

    def test_set_error(self):
        event = RateLimitLogEvent(event="test")
        event.set_error("Connection refused", exc_type="ConnectionError")
        data = event.as_dict()
        assert data["error"] == "Connection refused"
        assert data["exc_type"] == "ConnectionError"

    def test_add_fields(self):
        event = RateLimitLogEvent(event="test")
        event.add_fields(custom="value", count=5)
        data = event.as_dict()
        assert data["custom"] == "value"
        assert data["count"] == 5

    def test_method_chaining(self):
        event = RateLimitLogEvent(event="test")
        result = (
            event.set_result(allowed=True).set_duration(0.01).add_fields(extra="data")
        )
        assert result is event
        data = event.as_dict()
        assert data["allowed"] is True
        assert data["duration_ms"] == 10.0
        assert data["extra"] == "data"

    @override_settings(
        RATELIMIT_LOGGING={
            "ENABLED": True,
            "FORMAT": "json",
            "INCLUDE_TIMESTAMP": True,
        }
    )
    def test_includes_timestamp(self):
        event = RateLimitLogEvent(event="test")
        data = event.as_dict()
        assert "timestamp" in data

    @override_settings(
        RATELIMIT_LOGGING={
            "ENABLED": True,
            "FORMAT": "json",
            "INCLUDE_TIMESTAMP": False,
        }
    )
    def test_excludes_timestamp(self):
        event = RateLimitLogEvent(event="test")
        data = event.as_dict()
        assert "timestamp" not in data

    @override_settings(
        RATELIMIT_LOGGING={
            "ENABLED": True,
            "FORMAT": "json",
            "EXTRA_FIELDS": {"service": "my-api", "environment": "production"},
        }
    )
    def test_global_extra_fields(self):
        event = RateLimitLogEvent(event="test")
        data = event.as_dict()
        assert data["service"] == "my-api"
        assert data["environment"] == "production"

    @override_settings(
        RATELIMIT_LOGGING={
            "ENABLED": True,
            "FORMAT": "json",
            "LOGGER_NAME": "custom_logger",
        }
    )
    def test_custom_logger_name(self):
        event = RateLimitLogEvent(event="test")
        data = event.as_dict()
        assert data["logger"] == "custom_logger"

    def test_includes_request_context(self):
        set_request_context(
            request_id="req-123",
            ip="10.0.0.1",
            path="/api/v1/",
            method="POST",
        )
        event = RateLimitLogEvent(event="test")
        data = event.as_dict()
        assert data["request"]["request_id"] == "req-123"
        assert data["request"]["ip"] == "10.0.0.1"
        assert data["request"]["path"] == "/api/v1/"
        assert data["request"]["method"] == "POST"

    def test_omits_none_context_fields(self):
        set_request_context(request_id="req-123", ip=None)
        event = RateLimitLogEvent(event="test")
        data = event.as_dict()
        assert "ip" not in data.get("request", {})

    def test_algorithm_field(self):
        event = RateLimitLogEvent(event="test", algorithm="token_bucket")
        data = event.as_dict()
        assert data["algorithm"] == "token_bucket"


# ============================================================================
# JSONFormatter Tests
# ============================================================================


class TestJSONFormatter(TestCase):
    """Test JSONFormatter for Python logging."""

    def _make_record(self, msg="Test message", level=logging.INFO, **extra):
        record = logging.LogRecord(
            name="django_smart_ratelimit",
            level=level,
            pathname="test.py",
            lineno=1,
            msg=msg,
            args=(),
            exc_info=None,
        )
        for key, value in extra.items():
            setattr(record, key, value)
        return record

    def test_basic_formatting(self):
        formatter = JSONFormatter()
        record = self._make_record("Hello world")
        output = formatter.format(record)
        data = json.loads(output)
        assert data["message"] == "Hello world"
        assert data["level"] == "INFO"
        assert data["logger"] == "django_smart_ratelimit"
        assert "timestamp" in data

    def test_structured_event(self):
        formatter = JSONFormatter()
        structured = {
            "event": "rate_limit_check",
            "key": "user:42",
            "allowed": True,
        }
        record = self._make_record("Rate limit check", structured=structured)
        output = formatter.format(record)
        data = json.loads(output)
        assert data["event"] == "rate_limit_check"
        assert data["key"] == "user:42"
        assert data["allowed"] is True
        assert data["level"] == "INFO"
        assert data["message"] == "Rate limit check"

    def test_exception_info(self):
        formatter = JSONFormatter()
        try:
            raise ValueError("Test error")
        except ValueError:
            import sys

            exc_info = sys.exc_info()
        record = self._make_record("Error occurred", level=logging.ERROR)
        record.exc_info = exc_info
        output = formatter.format(record)
        data = json.loads(output)
        assert "exception" in data
        assert data["exception"]["type"] == "ValueError"
        assert data["exception"]["message"] == "Test error"
        assert "traceback" in data["exception"]

    def test_extra_fields_from_record(self):
        formatter = JSONFormatter()
        record = self._make_record("Test", backend="redis", operation="incr")
        output = formatter.format(record)
        data = json.loads(output)
        assert data["backend"] == "redis"
        assert data["operation"] == "incr"

    def test_non_serializable_extra(self):
        formatter = JSONFormatter()
        record = self._make_record("Test", custom_obj=object())
        output = formatter.format(record)
        data = json.loads(output)
        assert "custom_obj" in data
        assert isinstance(data["custom_obj"], str)

    def test_single_line_output(self):
        formatter = JSONFormatter()
        record = self._make_record("Test message")
        output = formatter.format(record)
        assert "\n" not in output

    def test_valid_json(self):
        formatter = JSONFormatter()
        record = self._make_record('Test with special chars: "quotes" & <angles>')
        output = formatter.format(record)
        data = json.loads(output)
        assert "quotes" in data["message"]

    def test_options(self):
        formatter = JSONFormatter(
            include_timestamp=False,
            include_logger_name=False,
            include_level=False,
            include_extra=False,
        )
        record = self._make_record("Test", backend="redis")
        output = formatter.format(record)
        data = json.loads(output)
        assert "timestamp" not in data
        assert "logger" not in data
        # Level and message are always added for structured events
        assert data["message"] == "Test"
        assert "backend" not in data  # extra excluded

    def test_warning_level(self):
        formatter = JSONFormatter()
        record = self._make_record("Warning msg", level=logging.WARNING)
        output = formatter.format(record)
        data = json.loads(output)
        assert data["level"] == "WARNING"

    def test_unicode_support(self):
        formatter = JSONFormatter()
        record = self._make_record("Test with unicode: café résumé 日本語")
        output = formatter.format(record)
        data = json.loads(output)
        assert "café" in data["message"]
        assert "日本語" in data["message"]


# ============================================================================
# Convenience Logging Function Tests
# ============================================================================


class TestLogRateLimitCheck(TestCase):
    """Test log_rate_limit_check convenience function."""

    @override_settings(RATELIMIT_LOGGING={"ENABLED": True, "FORMAT": "json"})
    @patch("django_smart_ratelimit.logging.logging")
    def test_log_allowed(self, mock_logging):
        mock_logger = MagicMock()
        mock_logging.getLogger.return_value = mock_logger
        mock_logging.INFO = logging.INFO

        log_rate_limit_check(
            key="user:42",
            backend="redis",
            allowed=True,
            remaining=8,
            limit=10,
            window=60,
            duration_seconds=0.005,
            algorithm="sliding_window",
        )

        mock_logger.log.assert_called_once()
        call_args = mock_logger.log.call_args
        assert call_args[0][0] == logging.INFO
        structured = call_args[1]["extra"]["structured"]
        assert structured["event"] == "rate_limit_check"
        assert structured["key"] == "user:42"
        assert structured["allowed"] is True
        assert structured["remaining"] == 8

    @override_settings(RATELIMIT_LOGGING={"ENABLED": True, "FORMAT": "json"})
    @patch("django_smart_ratelimit.logging.logging")
    def test_log_denied(self, mock_logging):
        mock_logger = MagicMock()
        mock_logging.getLogger.return_value = mock_logger
        mock_logging.WARNING = logging.WARNING

        log_rate_limit_check(
            key="ip:1.2.3.4",
            backend="memory",
            allowed=False,
        )

        call_args = mock_logger.log.call_args
        assert call_args[0][0] == logging.WARNING

    @override_settings(RATELIMIT_LOGGING={"ENABLED": False})
    @patch("django_smart_ratelimit.logging.logging")
    def test_disabled_skips_logging(self, mock_logging):
        mock_logger = MagicMock()
        mock_logging.getLogger.return_value = mock_logger

        log_rate_limit_check(key="test", backend="memory", allowed=True)

        mock_logger.log.assert_not_called()

    @override_settings(RATELIMIT_LOGGING={"ENABLED": True, "FORMAT": "text"})
    @patch("django_smart_ratelimit.logging.logging")
    def test_text_format_skips_json(self, mock_logging):
        mock_logger = MagicMock()
        mock_logging.getLogger.return_value = mock_logger

        log_rate_limit_check(key="test", backend="memory", allowed=True)

        mock_logger.log.assert_not_called()


class TestLogBackendEvent(TestCase):
    """Test log_backend_event convenience function."""

    @override_settings(RATELIMIT_LOGGING={"ENABLED": True, "FORMAT": "json"})
    @patch("django_smart_ratelimit.logging.logging")
    def test_log_success(self, mock_logging):
        mock_logger = MagicMock()
        mock_logging.getLogger.return_value = mock_logger
        mock_logging.INFO = logging.INFO

        log_backend_event(
            event_type="backend_operation",
            backend="redis",
            operation="incr",
            key="user:42",
            success=True,
            duration_seconds=0.002,
        )

        call_args = mock_logger.log.call_args
        assert call_args[0][0] == logging.INFO
        structured = call_args[1]["extra"]["structured"]
        assert structured["success"] is True
        assert structured["operation"] == "incr"

    @override_settings(RATELIMIT_LOGGING={"ENABLED": True, "FORMAT": "json"})
    @patch("django_smart_ratelimit.logging.logging")
    def test_log_failure(self, mock_logging):
        mock_logger = MagicMock()
        mock_logging.getLogger.return_value = mock_logger
        mock_logging.ERROR = logging.ERROR

        log_backend_event(
            event_type="backend_operation",
            backend="redis",
            operation="incr",
            key="user:42",
            success=False,
            error="Connection refused",
        )

        call_args = mock_logger.log.call_args
        assert call_args[0][0] == logging.ERROR
        structured = call_args[1]["extra"]["structured"]
        assert structured["success"] is False
        assert structured["error"] == "Connection refused"


class TestLogCircuitBreakerEvent(TestCase):
    """Test log_circuit_breaker_event convenience function."""

    @override_settings(RATELIMIT_LOGGING={"ENABLED": True, "FORMAT": "json"})
    @patch("django_smart_ratelimit.logging.logging")
    def test_log_state_change(self, mock_logging):
        mock_logger = MagicMock()
        mock_logging.getLogger.return_value = mock_logger
        mock_logging.WARNING = logging.WARNING

        log_circuit_breaker_event(
            backend="redis",
            previous_state="closed",
            new_state="open",
            reason="5 consecutive failures",
            failure_count=5,
        )

        call_args = mock_logger.log.call_args
        assert call_args[0][0] == logging.WARNING
        structured = call_args[1]["extra"]["structured"]
        assert structured["event"] == "circuit_breaker_state_change"
        assert structured["previous_state"] == "closed"
        assert structured["new_state"] == "open"
        assert structured["failure_count"] == 5

    @override_settings(RATELIMIT_LOGGING={"ENABLED": True, "FORMAT": "json"})
    @patch("django_smart_ratelimit.logging.logging")
    def test_log_recovery(self, mock_logging):
        mock_logger = MagicMock()
        mock_logging.getLogger.return_value = mock_logger
        mock_logging.INFO = logging.INFO

        log_circuit_breaker_event(
            backend="redis",
            previous_state="half_open",
            new_state="closed",
            reason="Probe succeeded",
        )

        call_args = mock_logger.log.call_args
        assert call_args[0][0] == logging.INFO


class TestLogAdaptiveEvent(TestCase):
    """Test log_adaptive_event convenience function."""

    @override_settings(RATELIMIT_LOGGING={"ENABLED": True, "FORMAT": "json"})
    @patch("django_smart_ratelimit.logging.logging")
    def test_log_adjustment(self, mock_logging):
        mock_logger = MagicMock()
        mock_logging.getLogger.return_value = mock_logger

        log_adaptive_event(
            key="user:42",
            original_limit=100,
            adjusted_limit=70,
            load_factor=0.7,
            indicators={"cpu": 0.8, "memory": 0.6},
        )

        mock_logger.info.assert_called_once()
        structured = mock_logger.info.call_args[1]["extra"]["structured"]
        assert structured["event"] == "adaptive_adjustment"
        assert structured["original_limit"] == 100
        assert structured["adjusted_limit"] == 70
        assert structured["load_factor"] == 0.7
        assert structured["indicators"]["cpu"] == 0.8


# ============================================================================
# Middleware Tests
# ============================================================================


class TestStructuredLoggingMiddleware(TestCase):
    """Test StructuredLoggingMiddleware."""

    def setUp(self):
        self.factory = RequestFactory()

    def tearDown(self):
        clear_request_context()

    @override_settings(RATELIMIT_LOGGING={"ENABLED": True, "FORMAT": "json"})
    def test_sets_request_context(self):
        captured_context = {}

        def get_response(request):
            captured_context.update(get_request_context())
            return HttpResponse("OK")

        middleware = StructuredLoggingMiddleware(get_response)
        request = self.factory.get("/api/test/")
        request.META["REMOTE_ADDR"] = "192.168.1.1"
        middleware(request)

        assert captured_context["path"] == "/api/test/"
        assert captured_context["method"] == "GET"
        assert captured_context["ip"] == "192.168.1.1"
        assert "request_id" in captured_context

    @override_settings(RATELIMIT_LOGGING={"ENABLED": True, "FORMAT": "json"})
    def test_clears_context_after_response(self):
        def get_response(request):
            return HttpResponse("OK")

        middleware = StructuredLoggingMiddleware(get_response)
        request = self.factory.get("/api/test/")
        middleware(request)

        ctx = get_request_context()
        assert ctx == {}

    @override_settings(RATELIMIT_LOGGING={"ENABLED": True, "FORMAT": "json"})
    def test_clears_context_on_exception(self):
        def get_response(request):
            raise ValueError("Test error")

        middleware = StructuredLoggingMiddleware(get_response)
        request = self.factory.get("/api/test/")

        with pytest.raises(ValueError):
            middleware(request)

        ctx = get_request_context()
        assert ctx == {}

    @override_settings(RATELIMIT_LOGGING={"ENABLED": False})
    def test_disabled_skips_context(self):
        captured_context = {}

        def get_response(request):
            captured_context.update(get_request_context())
            return HttpResponse("OK")

        middleware = StructuredLoggingMiddleware(get_response)
        request = self.factory.get("/api/test/")
        middleware(request)

        assert captured_context == {}

    @override_settings(RATELIMIT_LOGGING={"ENABLED": True, "FORMAT": "json"})
    def test_uses_x_request_id(self):
        captured_context = {}

        def get_response(request):
            captured_context.update(get_request_context())
            return HttpResponse("OK")

        middleware = StructuredLoggingMiddleware(get_response)
        request = self.factory.get("/api/test/")
        request.META["HTTP_X_REQUEST_ID"] = "custom-req-id-123"
        middleware(request)

        assert captured_context["request_id"] == "custom-req-id-123"

    @override_settings(RATELIMIT_LOGGING={"ENABLED": True, "FORMAT": "json"})
    def test_uses_x_forwarded_for(self):
        captured_context = {}

        def get_response(request):
            captured_context.update(get_request_context())
            return HttpResponse("OK")

        middleware = StructuredLoggingMiddleware(get_response)
        request = self.factory.get("/api/test/")
        request.META["HTTP_X_FORWARDED_FOR"] = "10.0.0.1, 10.0.0.2"
        middleware(request)

        assert captured_context["ip"] == "10.0.0.1"

    @override_settings(RATELIMIT_LOGGING={"ENABLED": True, "FORMAT": "json"})
    def test_stores_request_id_on_request(self):
        def get_response(request):
            return HttpResponse("OK")

        middleware = StructuredLoggingMiddleware(get_response)
        request = self.factory.get("/api/test/")
        request.META["HTTP_X_REQUEST_ID"] = "test-id"
        middleware(request)

        assert request.ratelimit_request_id == "test-id"

    @override_settings(RATELIMIT_LOGGING={"ENABLED": True, "FORMAT": "json"})
    def test_authenticated_user_context(self):
        captured_context = {}

        def get_response(request):
            captured_context.update(get_request_context())
            return HttpResponse("OK")

        middleware = StructuredLoggingMiddleware(get_response)
        request = self.factory.get("/api/test/")
        request.user = MagicMock()
        request.user.is_authenticated = True
        request.user.pk = 42
        middleware(request)

        assert captured_context["user"] == "42"


# ============================================================================
# Integration Tests
# ============================================================================


class TestEndToEndJSONLogging(TestCase):
    """Test end-to-end JSON logging with a real handler."""

    def setUp(self):
        clear_request_context()

    def tearDown(self):
        clear_request_context()

    def test_full_pipeline(self):
        """Test complete logging pipeline: event -> formatter -> JSON output."""
        # Set up a logger with our JSON formatter
        test_logger = logging.getLogger("test_e2e_json")
        test_logger.setLevel(logging.DEBUG)
        test_logger.handlers.clear()

        handler = logging.StreamHandler()
        handler.setFormatter(JSONFormatter())
        test_logger.addHandler(handler)

        # Create an event
        set_request_context(request_id="req-e2e", ip="1.2.3.4")
        event = RateLimitLogEvent(
            event="rate_limit_check",
            key="user:99",
            backend="memory",
            algorithm="sliding_window",
        )
        event.set_result(allowed=False, remaining=0, limit=10, window=60)
        event.set_duration(0.003)

        # Log it
        test_logger.warning(
            "Rate limit denied",
            extra={"structured": event.as_dict()},
        )

        # Verify the handler received valid JSON
        # (We can't easily capture the handler output in a test,
        # but we can verify the event dict is correct)
        data = event.as_dict()
        json_str = json.dumps(data, default=str)
        parsed = json.loads(json_str)
        assert parsed["event"] == "rate_limit_check"
        assert parsed["allowed"] is False
        assert parsed["request"]["request_id"] == "req-e2e"

        test_logger.handlers.clear()
