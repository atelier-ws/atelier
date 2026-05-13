"""Convenience entry-point shims.

These wrap stable command names such as ``atelier-context`` and translate them
to the current Click subcommands exposed by the main ``atelier`` CLI.
"""

from __future__ import annotations

import sys
import time

from atelier import __version__ as atelier_version
from atelier.gateway.adapters.cli import cli


def _invoke(subcommand: str, *, wrapper_name: str | None = None) -> None:
    from atelier.core.foundation.identity import (
        get_anon_id,
        new_session_id,
        platform_payload,
    )
    from atelier.core.service.telemetry import emit_product
    from atelier.core.service.telemetry.schema import bucket_duration_ms, bucket_duration_s

    # OTel is initialized lazily on first emit_product_log call.
    session_id = new_session_id()
    started_at = time.perf_counter()
    payload = platform_payload()
    emit_product(
        "session_start",
        agent_host="cli-wrapper",
        atelier_version=atelier_version,
        anon_id=get_anon_id(),
        session_id=session_id,
        **payload,
    )
    command_name = (wrapper_name or subcommand).replace("-", "_")

    emit_product(
        "cli_command_invoked",
        command_name=command_name,
        session_id=session_id,
        anon_id=get_anon_id(),
    )
    args = sys.argv[1:]
    prefix: list[str] = []
    while args[:1] == ["--root"] and len(args) >= 2:
        prefix.extend(args[:2])
        args = args[2:]
    sys.argv = [f"atelier-{wrapper_name or subcommand}", *prefix, subcommand, *args]
    try:
        try:
            cli(obj={"_telemetry_session_id": session_id, "_telemetry_command_name": subcommand})
        except SystemExit as exc:
            code = exc.code if isinstance(exc.code, int) else 1
            elapsed = time.perf_counter() - started_at
            emit_product(
                "cli_command_completed",
                command_name=command_name,
                session_id=session_id,
                duration_ms_bucket=bucket_duration_ms(elapsed * 1000),
                ok=code == 0,
            )
            emit_product(
                "session_end",
                session_id=session_id,
                duration_s_bucket=bucket_duration_s(elapsed),
                exit_reason="success" if code == 0 else "error",
            )
            raise
        else:
            elapsed = time.perf_counter() - started_at
            emit_product(
                "cli_command_completed",
                command_name=command_name,
                session_id=session_id,
                duration_ms_bucket=bucket_duration_ms(elapsed * 1000),
                ok=True,
            )
            emit_product(
                "session_end",
                session_id=session_id,
                duration_s_bucket=bucket_duration_s(elapsed),
                exit_reason="success",
            )
    finally:
        from atelier.core.service.telemetry import shutdown_otel

        shutdown_otel()


def task_main() -> None:
    sys.stderr.write(
        "atelier-task was removed during CLI consolidation; use atelier-context, "
        "atelier-check-plan, or the MCP reasoning/lint tools instead.\n"
    )
    raise SystemExit(2)


def context_main() -> None:
    _invoke("reasoning", wrapper_name="context")


def check_plan_main() -> None:
    _invoke("lint", wrapper_name="check-plan")


def rescue_main() -> None:
    _invoke("rescue")
