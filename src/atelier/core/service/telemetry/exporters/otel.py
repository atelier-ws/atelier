"""OpenTelemetry exporter for product telemetry events."""

from __future__ import annotations

import contextlib
import json
import logging
from typing import Any

_LOGGER: logging.Logger | None = None
_PROVIDER: Any = None


def init_otel(*, endpoint: str = "http://localhost:4318", service_version: str = "0.1.0") -> bool:
    global _LOGGER, _PROVIDER
    if _LOGGER is not None:
        return True
    try:
        from opentelemetry import _logs
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.sdk.resources import Resource
    except Exception:
        return False

    resource = Resource.create(
        {
            "service.name": "atelier",
            "service.version": service_version,
        }
    )
    provider = LoggerProvider(resource=resource)
    provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter(endpoint=_logs_endpoint(endpoint))))
    _logs.set_logger_provider(provider)

    logger = logging.getLogger("atelier.product.telemetry.otel")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    if not any(isinstance(handler, LoggingHandler) for handler in logger.handlers):
        logger.addHandler(LoggingHandler(level=logging.DEBUG, logger_provider=provider))
    _LOGGER = logger
    _PROVIDER = provider
    return True


def emit_product_log(event_name: str, props: dict[str, Any]) -> bool:
    if _LOGGER is None and not init_otel():
        return False
    if _LOGGER is None:
        return False
    try:
        from opentelemetry._logs.severity import SeverityNumber
        from opentelemetry.sdk._logs import LogRecord
        from opentelemetry.trace import TraceFlags, get_current_span

        # Flatten dict values to OTel-compatible types (str, int, float, bool)
        flat_attrs = {"event.name": event_name}
        for key, value in props.items():
            if isinstance(value, (dict, list, tuple)):
                flat_attrs[key] = json.dumps(value, ensure_ascii=False)
            else:
                flat_attrs[key] = value

        # Get current span context if available
        span = get_current_span()
        span_context = span.get_span_context() if span else None

        # Create LogRecord with proper span context
        record = LogRecord(
            body=event_name,
            attributes=flat_attrs,
            span_id=span_context.span_id if span_context else 1,
            trace_id=span_context.trace_id if span_context else 1,
            trace_flags=span_context.trace_flags if span_context else TraceFlags(0),
            severity_text="DEBUG",
            severity_number=SeverityNumber.DEBUG,
        )
        _PROVIDER.get_logger("atelier.product.telemetry.otel").emit(record)
        return True
    except Exception:
        return False


def shutdown_otel() -> None:
    global _LOGGER, _PROVIDER
    provider = _PROVIDER
    _LOGGER = None
    _PROVIDER = None
    if provider is not None:
        with contextlib.suppress(Exception):
            provider.shutdown()


def _logs_endpoint(endpoint: str) -> str:
    cleaned = endpoint.rstrip("/")
    if cleaned.endswith("/v1/logs"):
        return cleaned
    return f"{cleaned}/v1/logs"
