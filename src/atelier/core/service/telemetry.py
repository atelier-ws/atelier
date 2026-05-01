"""Minimal telemetry stubs — structured logging hooks for the service.

These are intentionally lightweight. In production, replace the
``_emit`` implementation with your observability backend.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger("atelier.service")


def emit_audit(
    *,
    actor: str,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    store: Any = None,
) -> None:
    """Write an audit entry.

    If the store supports ``write_audit_log``, calls it. Otherwise falls
    back to a structured log line. Never logs credential values.
    """
    entry: dict[str, Any] = {
        "actor": actor,
        "action": action,
        "resource_type": resource_type,
        "resource_id": resource_id,
    }
    if store is not None and hasattr(store, "write_audit_log"):
        try:
            store.write_audit_log(**entry)
        except Exception:  # pragma: no cover
            logger.warning("audit_log write failed; falling back to log", extra=entry)
    else:
        logger.info("audit", extra=entry)


@contextmanager
def timed_request(endpoint: str) -> Generator[None, None, None]:
    """Context manager that logs request duration."""
    t0 = time.perf_counter()
    try:
        yield
    finally:
        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.debug("request", extra={"endpoint": endpoint, "elapsed_ms": round(elapsed_ms, 1)})
