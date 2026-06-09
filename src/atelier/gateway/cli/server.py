"""NDJSON backend server — emits events as JSON lines, reads commands from stdin."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
import subprocess
import sys
from pathlib import Path

from atelier.gateway.cli.events import AssistantMessage, AtelierEvent, SessionStarted
from atelier.gateway.cli.runtime import InteractiveRuntime
from atelier.gateway.cli.slash import parse_input


def _write_event(event: AtelierEvent) -> None:
    """Serialize an AtelierEvent dataclass to a JSON line on stdout."""
    payload = dataclasses.asdict(event)
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


def _build_session_started(session_id: str, project_root: str | None) -> SessionStarted:
    """Assemble an enriched ``session.started`` event with environment context."""
    git_branch: str | None = None
    try:
        git_branch = (
            subprocess.check_output(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=project_root or ".",
                stderr=subprocess.DEVNULL,
            )
            .decode()
            .strip()
        )
    except Exception:  # noqa: BLE001 - git is optional
        pass

    from atelier import __version__ as _ver
    from atelier.core.capabilities.cross_vendor_routing.configuration import (
        detect_api_key_vendors,
    )

    has_key = bool(detect_api_key_vendors())

    resolved_model: str | None = None
    resolved_provider: str | None = None
    try:
        from atelier.core.capabilities.owned_execution_routing import (
            OwnedRouteRequest,
            select_owned_route,
        )
        from atelier.core.foundation.paths import default_store_root

        decision = select_owned_route(
            default_store_root(),
            OwnedRouteRequest(
                tool_name="tui", task_text="hi", mode="auto", budget="balanced"
            ),
        )
        resolved_model = decision.model
        resolved_provider = decision.provider
    except Exception:  # noqa: BLE001 - routing is best-effort
        pass

    return SessionStarted(
        type="session.started",
        session_id=session_id,
        project_root=project_root,
        model=resolved_model,
        provider=resolved_provider,
        git_branch=git_branch,
        atelier_version=_ver,
        has_api_key=has_key,
    )


async def run_ndjson_server(
    project_root: str | None = None, session_id: str | None = None
) -> int:
    """Main NDJSON server loop.

    Reads ``user.message`` / ``user.command`` / ``permission.response`` /
    ``interrupt`` commands from stdin (one JSON object per line) and writes
    ``AtelierEvent`` objects to stdout as NDJSON.
    """
    runtime = InteractiveRuntime()

    mitm_proc = None
    mitm_flow: Path | None = None
    if os.environ.get("ATELIER_MITM") == "1":
        from atelier.gateway.cli.mitm import start_mitmdump

        mitm_flow = Path.home() / ".atelier" / "mitm" / "pending.flow"
        mitm_proc = start_mitmdump(mitm_flow)

    if session_id:
        # Resume existing session — load its message history.
        try:
            from atelier.core.capabilities.owned_agent_session.session import (
                OwnedAgentSession,
            )

            saved = OwnedAgentSession.load(session_id)
            session_id = await runtime.start_session(project_root=project_root)
            runtime._sessions[session_id] = list(saved.messages)
        except FileNotFoundError:
            session_id = await runtime.start_session(project_root=project_root)
    else:
        session_id = await runtime.start_session(project_root=project_root)

    import datetime

    from atelier.core.capabilities.analytics.store import AnalyticsStore, SessionRecord

    analytics = AnalyticsStore()
    started_at = datetime.datetime.utcnow().isoformat()

    _write_event(_build_session_started(session_id, project_root))

    if mitm_proc is not None and mitm_flow is not None:
        _write_event(
            AssistantMessage(
                type="assistant.message",
                text=(
                    f"🔍 mitmdump active — capturing to `{mitm_flow}`\n\n"
                    f"Open with: `mitmweb --flow-file {mitm_flow}`"
                ),
            )
        )

    loop = asyncio.get_event_loop()

    try:
        while True:
            try:
                line = await loop.run_in_executor(None, sys.stdin.readline)
                if not line:  # EOF — frontend closed the pipe
                    break
                line = line.strip()
                if not line:
                    continue

                try:
                    cmd = json.loads(line)
                except json.JSONDecodeError:
                    continue

                cmd_type = cmd.get("type", "")

                if cmd_type == "user.message":
                    text = str(cmd.get("text", ""))
                    async for event in runtime.handle_user_message(session_id, text):
                        _write_event(event)

                elif cmd_type == "user.command":
                    name = str(cmd.get("name", ""))
                    args = [str(a) for a in cmd.get("args", [])]
                    parsed = parse_input("/" + (name + " " + " ".join(args)).strip())
                    if parsed.kind == "slash":
                        async for event in runtime.handle_slash_command(
                            session_id, parsed.name, parsed.args
                        ):
                            _write_event(event)

                elif cmd_type == "permission.response":
                    perm_id = str(cmd.get("id", ""))
                    approved = bool(cmd.get("approved", False))
                    scope = str(cmd.get("scope", "once"))
                    async for event in runtime.respond_to_permission(
                        session_id, perm_id, approved, scope
                    ):
                        _write_event(event)

                elif cmd_type == "choice.response":
                    choice_id = str(cmd.get("id", ""))
                    response = str(cmd.get("response", ""))
                    if choice_id in runtime._pending_permissions:
                        runtime._pending_permissions[choice_id]["response"] = response

                elif cmd_type == "interrupt":
                    await runtime.interrupt(session_id)

            except KeyboardInterrupt:
                break
            except Exception:  # noqa: BLE001 - server must stay alive on per-command errors
                pass
    finally:
        if mitm_proc is not None:
            from atelier.gateway.cli.mitm import stop_mitmdump

            stop_mitmdump(mitm_proc)

        runtime.shutdown()

        messages = runtime._sessions.get(session_id, [])
        analytics.upsert_session(
            SessionRecord(
                session_id=session_id,
                started_at=started_at,
                ended_at=datetime.datetime.utcnow().isoformat(),
                model=runtime._override_model or "",
                provider="",
                mode=runtime._current_mode,
                total_cost_usd=0.0,
                total_savings_usd=0.0,
                cache_efficiency_pct=0.0,
                input_tokens=0,
                output_tokens=0,
                cache_read_tokens=0,
                cache_write_tokens=0,
                turns=len(
                    [
                        m
                        for m in messages
                        if isinstance(m, dict) and m.get("role") == "user"
                    ]
                ),
                tool_calls=len(
                    [
                        m
                        for m in messages
                        if isinstance(m, dict) and m.get("role") == "tool"
                    ]
                ),
            )
        )
        analytics.close()

    return 0
