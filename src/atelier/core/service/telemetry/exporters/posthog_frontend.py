"""Frontend telemetry config payloads."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version
from typing import Any

from atelier.core.service.telemetry.banner import is_acknowledged
from atelier.core.service.telemetry.config import load_telemetry_config, posthog_host, posthog_key
from atelier.core.service.telemetry.identity import get_anon_id


def frontend_telemetry_config() -> dict[str, Any]:
    cfg = load_telemetry_config()
    return {
        "remote_enabled": cfg.remote_enabled,
        "lexical_frustration_enabled": cfg.lexical_frustration_enabled,
        "posthog_key": posthog_key(),
        "posthog_host": posthog_host(),
        "anon_id": get_anon_id(),
        "acknowledged": is_acknowledged(),
        "service_version": _service_version(),
    }


def _service_version() -> str:
    try:
        return version("atelier")
    except PackageNotFoundError:
        return "0.1.0"
