"""Interactive runtime: streaming agent loop wiring the Atelier core to the CLI."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import subprocess
import uuid
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from atelier.core.capabilities.mcp_integration.loader import (
    MCPServerProcess,
    MCPTool,
)
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

logger = logging.getLogger(__name__)


class InteractiveRuntime:
    """Own the agent loop, sessions, routing, and tool supervision for the CLI."""

    def __init__(self, *, root: Path | None = None, yolo: bool = False) -> None:
        self._root = root or Path.home() / ".atelier"
        self._yolo = yolo
        self._sessions: dict[str, list[dict[str, Any]]] = {}
        self._pending_permissions: dict[str, dict[str, Any]] = {}
        self._override_model: str | None = None
        self._active_tools: list[str] | None = None
        self._current_mode: str = "code"
        self._mcp_servers: list[MCPServerProcess] = []
        self._mcp_tools: list[MCPTool] = []
        self._background_tasks: list[dict[str, Any]] = []  # {id, name, status, result}

    async def start_session(self, project_root: str | None = None) -> str:
        session_id = uuid.uuid4().hex
        self._sessions[session_id] = []
        if project_root:
            os.environ["CLAUDE_WORKSPACE_ROOT"] = project_root
        self._start_mcp_servers()
        return session_id

    def _start_mcp_servers(self) -> None:
        from atelier.core.capabilities.mcp_integration.loader import (
            MCPServerProcess,
            discover_mcp_configs,
        )

        configs = discover_mcp_configs()
        for cfg in configs:
            proc = MCPServerProcess(cfg)
            if proc.start():
                tools = proc.list_tools()
                self._mcp_servers.append(proc)
                self._mcp_tools.extend(tools)
                logger.info("Started MCP server %s with %d tools", cfg.name, len(tools))

    def shutdown(self) -> None:
        for server in self._mcp_servers:
            server.stop()
        self._mcp_servers.clear()
        self._mcp_tools.clear()

    def _dispatch_mcp_tool(self, tool_name: str, tool_args: dict[str, Any]) -> str:
        """Route an ``mcp__<server>__<tool>`` call to the right MCP server."""
        parts = tool_name.split("__", 2)
        if len(parts) != 3:
            return f"Error: malformed MCP tool name '{tool_name}'"
        _, server_name, actual_tool = parts
        for server in self._mcp_servers:
            if server.config.name == server_name:
                return server.call_tool(actual_tool, tool_args)
        return f"Error: MCP server '{server_name}' not found"

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

        tools = [
            t
            for t in _get_litellm_tools()
            if self._active_tools is None or t["function"]["name"] in self._active_tools
        ]

        # Add MCP tools as litellm-compatible tool defs
        mcp_litellm_tools = [
            {
                "type": "function",
                "function": {
                    "name": f"mcp__{t.server_name}__{t.name}",
                    "description": f"[MCP:{t.server_name}] {t.description}",
                    "parameters": t.input_schema or {"type": "object", "properties": {}},
                },
            }
            for t in self._mcp_tools
        ]
        tools = tools + mcp_litellm_tools

        total_input = total_output = total_cache_read = total_cache_write = 0
        tool_call_counts: dict[str, int] = {}  # name -> count

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

            looping = False
            for tc in tool_calls_list:
                tool_name = tc["function"]["name"]
                tool_call_counts[tool_name] = tool_call_counts.get(tool_name, 0) + 1
                if tool_call_counts[tool_name] > 3:
                    yield RuntimeErrorEvent(
                        type="error",
                        message=(
                            f"⚠ Loop detected: '{tool_name}' called "
                            f"{tool_call_counts[tool_name]} times. "
                            "Consider interrupting with Ctrl+C."
                        ),
                    )
                    if tool_call_counts[tool_name] > 6:
                        looping = True
            if looping:
                break

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
                    if tool_name.startswith("mcp__"):
                        result_str = await asyncio.to_thread(
                            self._dispatch_mcp_tool, tool_name, tool_args
                        )
                        ok = not result_str.startswith("Error:")
                    else:
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
            from atelier.gateway.cli.events import ContextUsageUpdated

            yield ContextUsageUpdated(
                type="context.usage.updated",
                session_id=session_id,
                input_tokens=total_input,
                cache_read_tokens=total_cache_read,
                cache_write_tokens=total_cache_write,
                output_tokens=total_output,
                cache_efficiency_pct=efficiency,
                cost_usd=cost,
            )

        self._sessions[session_id] = messages

        # Warm-cache prompt suggestions: when most of the input was served from
        # cache, surface a few low-cost follow-up prompts.
        if total_cache_read > total_input // 2 and total_input > 0:
            last_assistant = next(
                (
                    m["content"]
                    for m in reversed(messages)
                    if isinstance(m, dict)
                    and m.get("role") == "assistant"
                    and isinstance(m.get("content"), str)
                ),
                "",
            )
            if last_assistant:
                suggestions = []
                lowered = last_assistant.lower()
                if "error" in lowered or "failed" in lowered:
                    suggestions.append("fix the error")
                if "implement" in lowered or "edit" in lowered:
                    suggestions.append("write tests for this")
                suggestions.append("explain how this works")
                from atelier.gateway.cli.events import (
                    PromptSuggestion as PromptSuggestionEvent,
                )

                for s in suggestions[:3]:
                    yield PromptSuggestionEvent(type="prompt.suggestion", text=s)

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
            import datetime

            from atelier.core.foundation.paths import default_store_root

            runs_dir = default_store_root() / "runs"
            sessions: list[dict[str, Any]] = []
            if runs_dir.exists():
                for f in sorted(
                    runs_dir.glob("*.jsonl"),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )[:20]:
                    sessions.append(
                        {
                            "id": f.stem,
                            "mtime": f.stat().st_mtime,
                            "size_kb": round(f.stat().st_size / 1024, 1),
                        }
                    )
            if sessions:
                lines = ["**Recent sessions:**\n"]
                for s in sessions:
                    dt = datetime.datetime.fromtimestamp(s["mtime"]).strftime("%Y-%m-%d %H:%M")
                    lines.append(f"- `{s['id']}` — {dt} ({s['size_kb']}KB)")
                lines.append("\nResume: `atelier-tui --resume <session-id>`")
                yield AssistantMessage(type="assistant.message", text="\n".join(lines))
            else:
                yield AssistantMessage(
                    type="assistant.message", text="No saved sessions found."
                )
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
        elif name == "usage":
            messages = self._sessions.get(session_id, [])
            total_chars = sum(
                len(str(m.get("content", ""))) for m in messages if isinstance(m, dict)
            )
            approx_tokens = total_chars // 4
            user_msgs = [
                m
                for m in messages
                if isinstance(m, dict) and m.get("role") == "user"
            ]
            asst_msgs = [
                m
                for m in messages
                if isinstance(m, dict) and m.get("role") == "assistant"
            ]
            tool_msgs = [
                m
                for m in messages
                if isinstance(m, dict) and m.get("role") == "tool"
            ]
            yield AssistantMessage(
                type="assistant.message",
                text=(
                    "**Token Usage**\n\n"
                    "| Category | Count |\n"
                    "|----------|-------|\n"
                    f"| User turns | {len(user_msgs)} |\n"
                    f"| Assistant turns | {len(asst_msgs)} |\n"
                    f"| Tool results | {len(tool_msgs)} |\n"
                    f"| ~Total chars | {total_chars:,} |\n"
                    f"| ~Total tokens | {approx_tokens:,} |\n"
                    f"| Model | `{self._override_model or '(auto)'}` |\n"
                    f"| Mode | `{self._current_mode}` |\n"
                    "\nTo see cost and savings: `/analytics`"
                ),
            )
        elif name == "permissions":
            mode = self._current_mode
            perm_tools = self._active_tools or [
                "read",
                "edit",
                "shell",
                "grep",
                "explore",
            ]
            perm_map = {
                "edit": "ask" if not self._yolo else "allow",
                "shell": "ask" if not self._yolo else "allow",
                "read": "allow",
                "grep": "allow",
                "explore": "allow",
            }
            lines = [f"**Permissions** (mode: {mode})\n"]
            for perm_tool in perm_tools:
                perm = perm_map.get(perm_tool, "allow")
                icon = "✓" if perm == "allow" else "?"
                lines.append(f"- `{perm_tool}` {icon} {perm}")
            lines.append(f"\nYOLO mode: {'on' if self._yolo else 'off'}")
            lines.append("Use `--yolo` to skip all approval prompts.")
            yield AssistantMessage(
                type="assistant.message", text="\n".join(lines)
            )
        elif name == "yolo":
            self._yolo = not self._yolo
            yield AssistantMessage(
                type="assistant.message",
                text=(
                    f"✓ YOLO mode {'enabled' if self._yolo else 'disabled'}. "
                    + (
                        "Tool calls auto-approved."
                        if self._yolo
                        else "Tool calls will ask for approval."
                    )
                ),
            )
        elif name == "mode":
            mode_name = args[0].lower() if args else ""
            mode_name = args[0].lower() if args else ""
            tools_by_mode = {
                "code": ["read", "edit", "shell", "grep", "explore"],
                "explore": ["read", "grep", "explore"],
                "research": ["read", "grep", "explore"],
                "plan": ["read", "grep"],
            }
            if mode_name in tools_by_mode:
                self._active_tools = tools_by_mode[mode_name]
                self._current_mode = mode_name
                yield AssistantMessage(
                    type="assistant.message",
                    text=(
                        f"Switched to **{mode_name.upper()}** mode. "
                        f"Tools: {', '.join(self._active_tools)}"
                    ),
                )
            else:
                yield AssistantMessage(
                    type="assistant.message",
                    text="Available modes: code, explore, research, plan",
                )
        elif name == "analytics":
            try:
                from atelier.core.capabilities.analytics.store import AnalyticsStore

                store = AnalyticsStore()
                stats = store.summary_stats()
                recent_sessions = store.recent_sessions(5)
                store.close()

                lines = ["**Session Analytics**\n"]
                lines.append("| Metric | Value |")
                lines.append("|--------|-------|")
                lines.append(f"| Total sessions | {stats.get('total_sessions', 0)} |")
                lines.append(f"| Total cost | ${stats.get('total_cost_usd', 0):.4f} |")
                lines.append(
                    f"| Total savings | ${stats.get('total_savings_usd', 0):.4f} |"
                )
                lines.append(
                    f"| Avg cache efficiency | {stats.get('avg_cache_efficiency_pct', 0):.1f}% |"
                )
                lines.append(f"| Total turns | {stats.get('total_turns', 0)} |")
                lines.append("")
                if recent_sessions:
                    lines.append("**Recent sessions:**")
                    for sess in recent_sessions:
                        lines.append(
                            f"- `{sess.session_id}` — {sess.mode} — ${sess.total_cost_usd:.4f}"
                        )
                yield AssistantMessage(
                    type="assistant.message", text="\n".join(lines)
                )
            except Exception as exc:  # noqa: BLE001 - analytics is best-effort
                yield AssistantMessage(
                    type="assistant.message", text=f"Analytics unavailable: {exc}"
                )
        elif name == "mcp":
            import json as _json

            mcp_files = [
                Path.cwd() / ".mcp.json",
                Path.cwd() / ".claude" / "mcp.json",
                Path.home() / ".atelier" / "tui" / ".mcp.json",
                Path.home() / ".claude" / "claude_mcp_settings.json",
            ]
            all_servers: dict[str, dict[str, Any]] = {}
            for mcp_file in mcp_files:
                if mcp_file.exists():
                    try:
                        data = _json.loads(mcp_file.read_text())
                        servers = data.get("mcpServers") or data.get("servers") or {}
                        for name_key, cfg in servers.items():
                            all_servers[name_key] = {"config": cfg, "source": str(mcp_file)}
                    except Exception:  # noqa: BLE001 - config is best-effort
                        pass

            if all_servers:
                lines = [f"**MCP Servers** ({len(all_servers)} configured)\n"]
                for srv_name, info in all_servers.items():
                    cfg = info["config"]
                    cmd = cfg.get("command", "?")
                    cmd_args = " ".join(str(a) for a in cfg.get("args", []))
                    lines.append(
                        f"- **{srv_name}** — `{cmd} {cmd_args}` _(from {info['source']})_"
                    )
                lines.append(
                    "\nTo use MCP tools in conversations, start the server and reference its tools."
                )
                yield AssistantMessage(type="assistant.message", text="\n".join(lines))
            else:
                yield AssistantMessage(
                    type="assistant.message",
                    text=(
                        "**No MCP servers configured.**\n\n"
                        "Add servers to one of:\n"
                        "- `.mcp.json` in your project root\n"
                        "- `~/.atelier/tui/.mcp.json` (global)\n\n"
                        "Format:\n```json\n"
                        '{"mcpServers": {"my-server": {"command": "npx", '
                        '"args": ["my-mcp-package"]}}}\n```'
                    ),
                )
        elif name == "compact":
            messages = self._sessions.get(session_id, [])
            msg_count = len(messages)
            summary_lines = [
                "**Conversation compacted**\n",
                f"(Previous: {msg_count} messages)\n",
            ]
            recent = messages[-4:] if len(messages) > 4 else messages
            self._sessions[session_id] = list(recent)
            yield AssistantMessage(type="assistant.message", text="\n".join(summary_lines))
        elif name == "cost":
            yield AssistantMessage(
                type="assistant.message",
                text=(
                    "**Session cost**\n\n"
                    f"Model: `{self._override_model or '(auto-routed)'}`\n"
                    f"Mode: `{self._current_mode}`\n\n"
                    "Use `/analytics` for detailed breakdown."
                ),
            )
        elif name == "doctor":
            from atelier.core.capabilities.cross_vendor_routing.configuration import (
                detect_api_key_vendors,
            )

            vendors = detect_api_key_vendors()
            lines = ["**Atelier Health Check**\n"]
            lines.append(
                f"- API keys: {', '.join(vendors) if vendors else 'none configured ⚠'}"
            )
            try:
                from atelier import __version__

                lines.append(f"- Version: `{__version__}`")
            except Exception:  # noqa: BLE001 - version is best-effort
                lines.append("- Version: unknown")
            import shutil

            tools_status = {
                "git": bool(shutil.which("git")),
                "uv": bool(shutil.which("uv")),
                "cargo": bool(shutil.which("cargo")),
                "mitmdump": bool(shutil.which("mitmdump")),
                "cloudflared": bool(shutil.which("cloudflared")),
            }
            for tool, ok in tools_status.items():
                lines.append(f"- {tool}: {'✓' if ok else '✗ not found'}")
            yield AssistantMessage(type="assistant.message", text="\n".join(lines))
        elif name == "allowed-tools":
            tools = _get_litellm_tools()
            active = self._active_tools
            lines = [f"**Available tools** (mode: {self._current_mode})\n"]
            for t in tools:
                fn = t["function"]
                is_active = active is None or fn["name"] in active
                status = "✓" if is_active else "○ (inactive in this mode)"
                lines.append(f"- `{fn['name']}` {status} — {fn['description'][:60]}")
            yield AssistantMessage(type="assistant.message", text="\n".join(lines))
        elif name == "version":
            try:
                from atelier import __version__

                yield AssistantMessage(
                    type="assistant.message", text=f"Atelier `{__version__}`"
                )
            except Exception:  # noqa: BLE001 - version is best-effort
                yield AssistantMessage(
                    type="assistant.message", text="Atelier (version unknown)"
                )
        elif name == "newtask":
            self._sessions[session_id] = []
            yield AssistantMessage(
                type="assistant.message",
                text="✓ New task started. Conversation cleared.",
            )
        elif name == "resume":
            async for ev in self.handle_slash_command(session_id, "sessions", []):
                yield ev
        elif name == "checkpoint":
            from atelier.core.capabilities.owned_agent_session.checkpoint import (
                save_checkpoint,
            )

            messages = self._sessions.get(session_id, [])
            label = " ".join(args) if args else ""
            cp = save_checkpoint(session_id, messages, label=label)
            yield AssistantMessage(
                type="assistant.message",
                text=(
                    f"✓ Checkpoint saved: `{cp.id}` — {cp.message_count} messages\n\n"
                    f"Restore: `/rewind {cp.id}`"
                ),
            )
        elif name == "rewind":
            cp_id = args[0] if args else ""
            if not cp_id:
                from atelier.core.capabilities.owned_agent_session.checkpoint import (
                    list_checkpoints,
                )

                cps = list_checkpoints(session_id)
                if cps:
                    lines = ["**Checkpoints:**\n"]
                    for cp in cps:
                        lines.append(
                            f"- `{cp.id}` — {cp.label} ({cp.message_count} messages) — {cp.created_at[:16]}"
                        )
                    lines.append("\nRestore: `/rewind <id>`")
                    yield AssistantMessage(
                        type="assistant.message", text="\n".join(lines)
                    )
                else:
                    yield AssistantMessage(
                        type="assistant.message",
                        text="No checkpoints. Create one: `/checkpoint [label]`",
                    )
            else:
                try:
                    from atelier.core.capabilities.owned_agent_session.checkpoint import (
                        load_checkpoint,
                    )

                    messages = load_checkpoint(cp_id, session_id)
                    self._sessions[session_id] = messages
                    yield AssistantMessage(
                        type="assistant.message",
                        text=f"✓ Rewound to checkpoint `{cp_id}` — {len(messages)} messages restored",
                    )
                except FileNotFoundError:
                    yield RuntimeErrorEvent(
                        type="error", message=f"Checkpoint `{cp_id}` not found"
                    )
        elif name == "shell":
            cmd = " ".join(args) if args else ""
            if cmd:
                from atelier.gateway.adapters.mcp_server import tool_shell

                try:
                    result = await asyncio.to_thread(tool_shell, {"command": cmd, "timeout": 30})
                    yield AssistantMessage(
                        type="assistant.message", text=f"```\n{result}\n```"
                    )
                except Exception as exc:  # noqa: BLE001 - shell is best-effort
                    yield RuntimeErrorEvent(type="error", message=f"Shell failed: {exc}")
            else:
                yield RuntimeErrorEvent(type="error", message="Usage: !<command>")
        elif name == "tasks":
            if not self._background_tasks:
                yield AssistantMessage(type="assistant.message", text="No background tasks.")
                return
            lines = ["**Background tasks:**\n"]
            for t in self._background_tasks:
                status_icon = {"running": "⟳", "done": "✓", "failed": "✗"}.get(t["status"], "?")
                lines.append(f"- `{t['id']}` {status_icon} {t['name']}")
            yield AssistantMessage(type="assistant.message", text="\n".join(lines))
        elif name == "background":
            task_id = f"bg-{uuid.uuid4().hex[:6]}"
            self._background_tasks.append({
                "id": task_id,
                "name": f"session-{session_id[:8]}",
                "status": "running",
            })
            yield AssistantMessage(
                type="assistant.message",
                text=f"Session backgrounded as task `{task_id}`. Use `/tasks` to check status.",
            )
        elif name == "plan":
            task = " ".join(args) if args else ""
            if task:
                old_mode = self._current_mode
                old_tools = self._active_tools
                self._current_mode = "explore"
                self._active_tools = ["read", "grep", "explore"]
                yield AssistantMessage(
                    type="assistant.message",
                    text=f"**Plan mode** — exploring (read-only):\n\n> {task}",
                )
                async for event in self.handle_user_message(session_id, task):
                    yield event
                self._current_mode = old_mode
                self._active_tools = old_tools
            else:
                yield AssistantMessage(
                    type="assistant.message",
                    text="Usage: `/plan <task description>`\n\nRuns exploration-only (read-only, no edits).",
                )
        elif name == "btw":
            question = " ".join(args) if args else ""
            if not question:
                yield AssistantMessage(
                    type="assistant.message",
                    text="Usage: `/btw <question>`\n\nAsks an ephemeral question without adding to conversation history.",
                )
                return
            ephemeral_messages = [
                {"role": "system", "content": "Answer the following question concisely. This is a side question."},
                {"role": "user", "content": question},
            ]
            from atelier.core.capabilities.owned_agent_session.phase_runner import (
                _call_llm,
            )

            model = self._override_model or "gpt-4o-mini"
            try:
                content, *_ = _call_llm(ephemeral_messages, model=model, provider="openai")
                yield AssistantMessage(type="assistant.message", text=f"**(btw)** {content}")
            except Exception as exc:  # noqa: BLE001 - ephemeral call is best-effort
                yield RuntimeErrorEvent(type="error", message=f"/btw failed: {exc}")
        elif name == "auth":
            from atelier.core.capabilities.auth.wizard import (
                PROVIDER_CONFIGS,
                list_provider_models,
                load_saved_credentials,
                save_credentials,
                validate_provider,
            )
            from atelier.gateway.cli.events import ChoiceRequested

            if not args:
                saved = load_saved_credentials()
                configured_keys = set(saved.keys())
                lines = ["**Provider Authentication**\n"]
                lines.append("| Provider | Status | Keys |")
                lines.append("|----------|--------|------|")
                for _pid, cfg in PROVIDER_CONFIGS.items():
                    keys = [f["name"] for f in cfg["fields"]]
                    has_all = all(k in configured_keys or k in os.environ for k in keys)
                    status = "✓ configured" if has_all else "○ not set"
                    lines.append(f"| {cfg['name'][:25]} | {status} | {', '.join(keys[:2])} |")
                lines.append("\nTo configure a provider: `/auth <provider-id>`")
                lines.append("Example: `/auth anthropic`, `/auth openai`, `/auth groq`")
                lines.append(f"Supported: {', '.join(PROVIDER_CONFIGS.keys())}")
                yield AssistantMessage(type="assistant.message", text="\n".join(lines))
                return

            provider_id = args[0].lower()
            cfg = PROVIDER_CONFIGS.get(provider_id)
            if not cfg:
                yield RuntimeErrorEvent(
                    type="error",
                    message=f"Unknown provider: {provider_id!r}. Try: {', '.join(PROVIDER_CONFIGS.keys())}",
                )
                return

            fields_text = "\n".join(f"  • {f['label']}" for f in cfg["fields"])
            yield AssistantMessage(
                type="assistant.message",
                text=(
                    f"**Configuring {cfg['name']}**\n\n"
                    f"Required credentials:\n{fields_text}\n\n"
                    f"Get your credentials at: {cfg['link']}\n\n"
                    f"Enter credentials in order (one per message):"
                ),
            )

            collected: dict[str, str] = {}
            for field_cfg in cfg["fields"]:
                field_name = field_cfg["name"]
                default = field_cfg.get("default", "")
                prompt_text = f"{field_cfg['label']}" + (
                    f" [default: {default}]" if default else ""
                )
                choice_id = f"auth-{field_name}"
                self._pending_permissions[choice_id] = {"approved": None, "response": None}
                yield ChoiceRequested(
                    type="choice.requested",
                    id=choice_id,
                    question=prompt_text,
                    choices=[f"Use default ({default})"] if default else [],
                    allow_freeform=True,
                )
                for _ in range(600):
                    await asyncio.sleep(0.1)
                    resp = self._pending_permissions.get(choice_id, {}).get("response")
                    if resp is not None:
                        break
                val = str(
                    self._pending_permissions.get(choice_id, {}).get("response", default)
                    or default
                )
                if val:
                    collected[field_name] = val

            if collected:
                ok, msg = validate_provider(provider_id, collected)
                if ok:
                    save_credentials(collected)
                    for k, v in collected.items():
                        os.environ[k] = v
                    yield AssistantMessage(
                        type="assistant.message",
                        text=f"{msg}\n\nCredentials saved to `~/.atelier/.env`",
                    )
                    models = list_provider_models(provider_id)
                    if models:
                        yield AssistantMessage(
                            type="assistant.message",
                            text="Available models:\n"
                            + "\n".join(f"- `{m}`" for m in models)
                            + f"\n\nUse: `/model {models[0]}`",
                        )
                else:
                    yield AssistantMessage(
                        type="assistant.message",
                        text=f"{msg}\n\nPlease check your credentials and try again.",
                    )
        elif name in ("verify", "diff"):
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

    async def ask_choice(
        self,
        session_id: str,
        question: str,
        choices: list[str],
        *,
        allow_freeform: bool = True,
    ) -> AsyncIterator[AtelierEvent]:
        """Emit a ChoiceRequested event and wait for the frontend response."""
        from atelier.gateway.cli.events import ChoiceRequested

        choice_id = f"choice-{uuid.uuid4().hex[:8]}"
        self._pending_permissions[choice_id] = {"approved": None, "response": None}
        yield ChoiceRequested(
            type="choice.requested",
            id=choice_id,
            question=question,
            choices=choices,
            allow_freeform=allow_freeform,
        )
        for _ in range(600):  # 60s timeout
            await asyncio.sleep(0.1)
            resp = self._pending_permissions.get(choice_id, {}).get("response")
            if resp is not None:
                break


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
