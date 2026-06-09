"""Interactive runtime: streaming agent loop wiring the Atelier core to the CLI."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from atelier.gateway.cli.events import (
    AssistantDelta,
    AssistantMessage,
    AtelierEvent,
    MemoryHit,
    PermissionRequested,
    RouteSelected,
    RuntimeErrorEvent,
    ToolFinished,
    ToolOutput,
    ToolRequested,
    ToolStarted,
)


class InteractiveRuntime:
    """Own the agent loop, sessions, routing, and tool supervision for the CLI."""

    def __init__(self, *, root: Path | None = None, yolo: bool = False) -> None:
        self._root = root or Path.home() / ".atelier"
        self._yolo = yolo
        self._sessions: dict[str, list[dict[str, Any]]] = {}
        self._pending_permissions: dict[str, dict[str, Any]] = {}
        self._override_model: str | None = None

    async def start_session(self, project_root: str | None = None) -> str:
        session_id = uuid.uuid4().hex
        self._sessions[session_id] = []
        if project_root:
            os.environ["CLAUDE_WORKSPACE_ROOT"] = project_root
        return session_id

    @property
    def session_ids(self) -> list[str]:
        return list(self._sessions.keys())

    async def handle_user_message(
        self,
        session_id: str,
        text: str,
    ) -> AsyncIterator[AtelierEvent]:
        messages = self._sessions.setdefault(session_id, [])
        messages.append({"role": "user", "content": text})

        if self._override_model:
            model = self._override_model
            yield RouteSelected(
                type="route.selected",
                provider=None,
                model=model,
                reason="user override (/set-model)",
            )
            async for event in self._agent_loop(session_id, messages, model=model):
                yield event
            return

        try:
            from atelier.core.capabilities.owned_execution_routing import (
                OwnedRouteRequest,
                select_owned_route,
            )
            from atelier.gateway.cli.commands.run import _resolve_litellm_model

            decision = select_owned_route(
                self._root,
                OwnedRouteRequest(tool_name="tui", task_text=text, mode="auto", budget="balanced"),
            )
            model = _resolve_litellm_model(decision.provider, decision.model)
            yield RouteSelected(
                type="route.selected",
                provider=decision.provider,
                model=decision.model,
                reason=decision.reason,
            )
        except Exception:  # noqa: BLE001 - fall back gracefully
            model = os.environ.get("ATELIER_LITELLM_MODEL", "gpt-4o-mini")

        async for event in self._agent_loop(session_id, messages, model=model):
            yield event

    async def _agent_loop(
        self,
        session_id: str,
        messages: list[dict[str, Any]],
        *,
        model: str,
        max_iterations: int = 20,
    ) -> AsyncIterator[AtelierEvent]:
        import litellm

        tools = _get_litellm_tools()

        total_input = total_output = total_cache_read = total_cache_write = 0

        for _ in range(max_iterations):
            accumulated_text = ""
            tool_calls_acc: dict[int, dict[str, Any]] = {}
            finish_reason = ""

            try:
                stream = await asyncio.to_thread(
                    litellm.completion,
                    model=model,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    stream=True,
                    stream_options={"include_usage": True},
                )
            except Exception as exc:  # noqa: BLE001 - fall back gracefully
                err_str = str(exc)
                if "API_KEY_SERVICE_BLOCKED" in err_str or "PERMISSION_DENIED" in err_str or "403" in err_str:
                    from atelier.core.capabilities.cross_vendor_routing.configuration import (
                        detect_api_key_vendors,
                    )

                    other_vendors = [v for v in detect_api_key_vendors() if "google" not in v.lower()]
                    fallback_model = os.environ.get("ATELIER_LITELLM_MODEL", "gpt-4o-mini")
                    if other_vendors and model != fallback_model:
                        yield RuntimeErrorEvent(
                            type="error",
                            message=(
                                f"Provider {model!r} blocked (API_KEY_SERVICE_BLOCKED). "
                                f"Retrying with {fallback_model!r}."
                            ),
                        )
                        async for event in self._agent_loop(
                            session_id,
                            messages,
                            model=fallback_model,
                            max_iterations=max_iterations - 1,
                        ):
                            yield event
                    else:
                        yield RuntimeErrorEvent(type="error", message=f"LLM call failed: {exc}")
                else:
                    yield RuntimeErrorEvent(type="error", message=f"LLM call failed: {exc}")
                return

            for chunk in stream:
                usage = getattr(chunk, "usage", None)
                if usage is not None:
                    total_input += int(getattr(usage, "prompt_tokens", 0) or 0)
                    total_output += int(getattr(usage, "completion_tokens", 0) or 0)
                    details = getattr(usage, "prompt_tokens_details", None)
                    cached = int(getattr(details, "cached_tokens", 0) or 0) if details else 0
                    total_cache_read += cached
                    total_input -= cached
                choice = chunk.choices[0] if chunk.choices else None
                if choice is None:
                    continue
                delta = choice.delta
                finish_reason = choice.finish_reason or finish_reason

                if delta.content:
                    accumulated_text += delta.content
                    yield AssistantDelta(type="assistant.delta", text=delta.content)

                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        idx = tc.index
                        if idx not in tool_calls_acc:
                            tool_calls_acc[idx] = {
                                "id": tc.id or "",
                                "type": "function",
                                "function": {
                                    "name": (tc.function.name if tc.function else "") or "",
                                    "arguments": "",
                                },
                            }
                        if tc.id:
                            tool_calls_acc[idx]["id"] = tc.id
                        if tc.function:
                            if tc.function.name:
                                tool_calls_acc[idx]["function"]["name"] = tc.function.name
                            if tc.function.arguments:
                                tool_calls_acc[idx]["function"]["arguments"] += tc.function.arguments

            if accumulated_text:
                yield AssistantMessage(type="assistant.message", text=accumulated_text)
                messages.append({"role": "assistant", "content": accumulated_text})

            if not tool_calls_acc or finish_reason == "stop":
                break

            tool_calls_list = [tool_calls_acc[i] for i in sorted(tool_calls_acc)]
            messages.append({"role": "assistant", "content": None, "tool_calls": tool_calls_list})

            for tc in tool_calls_list:
                tool_id = tc["id"]
                tool_name = tc["function"]["name"]
                try:
                    tool_args = json.loads(tc["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    tool_args = {}

                yield ToolRequested(type="tool.requested", id=tool_id, name=tool_name, args=tool_args)

                if not self._yolo and tool_name in ("edit", "shell"):
                    self._pending_permissions[tool_id] = {"approved": None}
                    yield PermissionRequested(
                        type="permission.requested",
                        id=tool_id,
                        action=f"{tool_name}: {json.dumps(tool_args)[:120]}",
                        risk="high" if tool_name == "shell" else "medium",
                    )
                    for _ in range(300):
                        await asyncio.sleep(0.1)
                        if self._pending_permissions.get(tool_id, {}).get("approved") is not None:
                            break
                    if not self._pending_permissions.get(tool_id, {}).get("approved", False):
                        result_str = "[denied by user]"
                        messages.append({"role": "tool", "tool_call_id": tool_id, "content": result_str})
                        yield ToolFinished(
                            type="tool.finished",
                            id=tool_id,
                            name=tool_name,
                            ok=False,
                            result=result_str,
                        )
                        continue

                yield ToolStarted(type="tool.started", id=tool_id, name=tool_name)

                try:
                    result = await asyncio.to_thread(_dispatch_tool, tool_name, tool_args)
                    result_str = str(result)
                    ok = True
                except Exception as exc:  # noqa: BLE001 - fall back gracefully
                    result_str = f"Error: {exc}"
                    ok = False

                output_preview = result_str[:2000] + ("…" if len(result_str) > 2000 else "")
                yield ToolOutput(type="tool.output", id=tool_id, chunk=output_preview)
                yield ToolFinished(
                    type="tool.finished",
                    id=tool_id,
                    name=tool_name,
                    ok=ok,
                    result=result_str[:500],
                )
                messages.append({"role": "tool", "tool_call_id": tool_id, "content": result_str})

                if tool_name == "edit" and ok:
                    try:
                        diff = subprocess.check_output(
                            ["git", "diff", "--no-color"],
                            cwd=os.getcwd(),
                            stderr=subprocess.DEVNULL,
                        ).decode(errors="replace")[:5000]
                        if diff.strip():
                            from atelier.gateway.cli.events import PatchProposed

                            yield PatchProposed(
                                type="patch.proposed",
                                id=tool_id,
                                files=[
                                    str(e.get("file_path", "?"))
                                    for e in tool_args.get("edits", [])
                                ],
                                diff=diff,
                            )
                    except Exception:  # noqa: BLE001 - diff is best-effort
                        pass

        total_input = max(0, total_input)
        denom = total_cache_read + total_cache_write + total_input
        if denom > 0:
            from atelier.core.capabilities.savings_summary import estimate_cost_usd
            from atelier.gateway.cli.events import CacheStats

            efficiency = round(total_cache_read / denom * 100, 1)
            cost = estimate_cost_usd(
                model_id=model,
                input_tokens=total_input,
                output_tokens=total_output,
                cache_read_tokens=total_cache_read,
                cache_write_tokens=total_cache_write,
            )
            naive = estimate_cost_usd(
                model_id=model,
                input_tokens=denom,
                output_tokens=total_output,
                cache_read_tokens=0,
                cache_write_tokens=0,
            )
            yield CacheStats(
                type="cache.stats",
                session_id=session_id,
                cache_efficiency_pct=efficiency,
                cost_usd=cost,
                savings_usd=max(0.0, naive - cost),
                cache_read_tokens=total_cache_read,
                cache_write_tokens=total_cache_write,
                fresh_tokens=total_input,
            )

        self._sessions[session_id] = messages

    async def handle_slash_command(
        self,
        session_id: str,
        name: str,
        args: list[str],
    ) -> AsyncIterator[AtelierEvent]:
        if name == "help":
            yield AssistantMessage(type="assistant.message", text=_HELP_TEXT)
        elif name in ("tools", "tool"):
            tools = _get_litellm_tools()
            lines = [f"**{t['function']['name']}** — {t['function']['description'][:80]}" for t in tools]
            yield AssistantMessage(type="assistant.message", text="\n".join(lines))
        elif name == "sessions":
            ids = list(self._sessions.keys())
            past: list[str] = []
            runs_dir = self._root / "runs"
            if runs_dir.is_dir():
                past = sorted(p.stem for p in runs_dir.glob("*.jsonl"))
            lines = []
            if ids:
                lines.append("Active sessions:")
                lines.extend(f"  {s}" for s in ids)
            if past:
                lines.append("Saved sessions (resume with --resume <id>):")
                lines.extend(f"  {s}" for s in past)
            text = "\n".join(lines) if lines else "No sessions."
            yield AssistantMessage(type="assistant.message", text=text)
        elif name == "session":
            target = args[0] if args else ""
            if target in self._sessions:
                yield AssistantMessage(type="assistant.message", text=f"Switched to session {target}")
            else:
                yield RuntimeErrorEvent(type="error", message=f"Session {target!r} not found")
        elif name == "memory":
            async for event in self._run_memory_search(" ".join(args)):
                yield event
        elif name == "route":
            async for event in self._run_route(" ".join(args)):
                yield event
        elif name == "approve":
            pending = list(self._pending_permissions.keys())
            if pending:
                self._pending_permissions[pending[-1]]["approved"] = True
                yield AssistantMessage(type="assistant.message", text=f"Approved: {pending[-1]}")
            else:
                yield AssistantMessage(type="assistant.message", text="No pending permission requests.")
        elif name == "deny":
            pending = list(self._pending_permissions.keys())
            if pending:
                self._pending_permissions[pending[-1]]["approved"] = False
                yield AssistantMessage(type="assistant.message", text=f"Denied: {pending[-1]}")
            else:
                yield AssistantMessage(type="assistant.message", text="No pending permission requests.")
        elif name == "set-model":
            model = args[0] if args else ""
            if model:
                self._override_model = model
                yield AssistantMessage(
                    type="assistant.message",
                    text=f"Model set to `{model}`. Type a message to start.",
                )
            else:
                yield RuntimeErrorEvent(type="error", message="Usage: /set-model <model>")
        elif name == "model":
            if args and args[0]:
                model_str = args[0]
                self._override_model = model_str
                yield AssistantMessage(
                    type="assistant.message",
                    text=f"Model switched to `{model_str}`. Changes take effect on your next message.",
                )
            else:
                current = self._override_model or "(auto-routed)"
                yield AssistantMessage(
                    type="assistant.message",
                    text=(
                        f"Current model: `{current}`\n\n"
                        "Usage: `/model <model-string>`\n\n"
                        "Examples:\n"
                        "- `/model anthropic/claude-opus-4-8`\n"
                        "- `/model openrouter/anthropic/claude-opus-4-8`\n"
                        "- `/model bedrock/anthropic.claude-sonnet-4-5-v1:0`\n"
                        "- `/model azure/gpt-4o`"
                    ),
                )
        elif name == "context":
            messages = self._sessions.get(session_id, [])
            turns = len(messages) // 2
            total_chars = sum(
                len(str(m.get("content", ""))) for m in messages if isinstance(m, dict)
            )
            approx_tokens = total_chars // 4
            tool_results = len(
                [m for m in messages if isinstance(m, dict) and m.get("role") == "tool"]
            )
            yield AssistantMessage(
                type="assistant.message",
                text=(
                    "**Context stats**\n\n"
                    f"- Turns: {turns}\n"
                    f"- Messages: {len(messages)}\n"
                    f"- Estimated tokens: ~{approx_tokens:,}\n"
                    f"- Tool results: {tool_results}\n"
                ),
            )
        elif name in ("verify", "background", "diff"):
            yield AssistantMessage(
                type="assistant.message",
                text=f"/{name} not yet wired. Use plain message instead.",
            )
        else:
            yield RuntimeErrorEvent(
                type="error",
                message=f"Unknown command: /{name}. Type /help for commands.",
            )

    async def _run_memory_search(self, query: str) -> AsyncIterator[AtelierEvent]:
        if not query:
            yield RuntimeErrorEvent(type="error", message="Usage: /memory <query>")
            return
        try:
            from atelier.gateway.adapters.mcp_server import tool_memory

            result = await asyncio.to_thread(tool_memory, {"op": "recall", "query": query, "top_k": 5})
            yield MemoryHit(type="memory.hit", key=query, summary=str(result)[:2000])
        except Exception as exc:  # noqa: BLE001 - fall back gracefully
            yield RuntimeErrorEvent(type="error", message=f"Memory search failed: {exc}")

    async def _run_route(self, task: str) -> AsyncIterator[AtelierEvent]:
        if not task:
            yield RuntimeErrorEvent(type="error", message="Usage: /route <task description>")
            return
        try:
            from atelier.core.capabilities.owned_execution_routing import (
                OwnedRouteRequest,
                select_owned_route,
            )

            decision = select_owned_route(
                self._root,
                OwnedRouteRequest(tool_name="tui", task_text=task, mode="auto", budget="balanced"),
            )
            yield RouteSelected(
                type="route.selected",
                provider=decision.provider,
                model=decision.model,
                reason=decision.reason,
            )
        except Exception as exc:  # noqa: BLE001 - fall back gracefully
            yield RuntimeErrorEvent(type="error", message=f"Route selection failed: {exc}")

    async def respond_to_permission(
        self,
        session_id: str,
        permission_id: str,
        approved: bool,
        scope: str = "once",
    ) -> AsyncIterator[AtelierEvent]:
        self._pending_permissions[permission_id] = {"approved": approved}
        yield AssistantMessage(
            type="assistant.message",
            text=f"Permission {'approved' if approved else 'denied'}: {permission_id}",
        )

    async def interrupt(self, session_id: str) -> None:
        return None


_HELP_TEXT = """
**Atelier Interactive CLI**

Commands:
- `/help` — show this help
- `/exit`, `/quit` — exit
- `/clear` — clear screen
- `/tools` — list available tools
- `/sessions` — list sessions
- `/session <id>` — switch session
- `/memory <query>` — search Atelier memory
- `/route <task>` — show routing decision for task
- `/approve` — approve latest permission request
- `/deny` — deny latest permission request

Type any message to start a coding session.
""".strip()


def _get_litellm_tools() -> list[dict[str, Any]]:
    """Return litellm-compatible tool definitions for core Atelier tools."""
    return [
        {
            "type": "function",
            "function": {
                "name": "read",
                "description": (
                    "Read a file from the workspace. Returns file contents, with "
                    "automatic outline mode for large files."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {
                            "type": "string",
                            "description": "Workspace-relative file path",
                        },
                        "range": {
                            "type": "string",
                            "description": "Line range, e.g. '10-50'",
                        },
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "edit",
                "description": ("Apply edits to files. Use {file_path, old_string, new_string} " "descriptors."),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "edits": {
                            "type": "array",
                            "items": {"type": "object"},
                            "description": ("List of edit descriptors. Each: " "{file_path, old_string, new_string}"),
                        },
                    },
                    "required": ["edits"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "shell",
                "description": ("Run a shell command. Use sparingly — prefer read/grep/edit " "where possible."),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "Shell command to run",
                        },
                        "timeout": {"type": "integer", "default": 30},
                    },
                    "required": ["command"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "grep",
                "description": "Search for a pattern in the workspace codebase.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {
                            "type": "string",
                            "description": "Regex pattern to search",
                        },
                        "path": {
                            "type": "string",
                            "description": "Directory or file to search in",
                        },
                        "glob": {
                            "type": "string",
                            "description": "File glob filter, e.g. '*.py'",
                        },
                    },
                    "required": ["pattern"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "explore",
                "description": ("Explore a symbol or module: source, callers, callees, " "related symbols."),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "Symbol name or concept to explore",
                        },
                        "path": {
                            "type": "string",
                            "description": "Optional file to scope exploration",
                        },
                    },
                    "required": ["query"],
                },
            },
        },
    ]


def _dispatch_tool(name: str, args: dict[str, Any]) -> Any:
    """Dispatch a tool call to the corresponding Atelier MCP tool handler.

    The MCP tool functions are ``@mcp_tool``-decorated handlers that take a
    single ``dict`` argument and validate it internally.
    """
    from atelier.gateway.adapters.mcp_server import (
        tool_explore,
        tool_grep,
        tool_shell,
        tool_smart_edit,
        tool_smart_read,
    )

    if name == "read":
        payload = {k: v for k, v in args.items() if k in ("path", "range", "expand", "max_lines")}
        return tool_smart_read(payload)
    if name == "edit":
        return tool_smart_edit({"edits": args.get("edits", [])})
    if name == "shell":
        return tool_shell({"command": args["command"], "timeout": args.get("timeout", 30)})
    if name == "grep":
        payload = {"content_regex": args["pattern"]}
        if args.get("path"):
            payload["path"] = args["path"]
        if args.get("glob"):
            payload["file_glob_patterns"] = [args["glob"]]
        return tool_grep(payload)
    if name == "explore":
        return tool_explore({"query": args["query"]})
    raise ValueError(f"Unknown tool: {name!r}")
