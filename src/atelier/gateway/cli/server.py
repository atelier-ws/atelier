"""NDJSON backend server — emits events as JSON lines, reads commands from stdin."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import sys

from atelier.gateway.cli.events import AtelierEvent, SessionStarted
from atelier.gateway.cli.runtime import InteractiveRuntime
from atelier.gateway.cli.slash import parse_input


def _write_event(event: AtelierEvent) -> None:
    """Serialize an AtelierEvent dataclass to a JSON line on stdout."""
    payload = dataclasses.asdict(event)
    sys.stdout.write(json.dumps(payload) + "\n")
    sys.stdout.flush()


async def run_ndjson_server(
    project_root: str | None = None, session_id: str | None = None
) -> int:
    """Main NDJSON server loop.

    Reads ``user.message`` / ``user.command`` / ``permission.response`` /
    ``interrupt`` commands from stdin (one JSON object per line) and writes
    ``AtelierEvent`` objects to stdout as NDJSON.
    """
    runtime = InteractiveRuntime()
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

    _write_event(
        SessionStarted(
            type="session.started",
            session_id=session_id,
            project_root=project_root,
        )
    )

    loop = asyncio.get_event_loop()

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

            elif cmd_type == "interrupt":
                await runtime.interrupt(session_id)

        except KeyboardInterrupt:
            break
        except Exception:  # noqa: BLE001 - server must stay alive on per-command errors
            pass

    return 0
