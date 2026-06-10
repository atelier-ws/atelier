# Atelier Interactive CLI Implementation Handoff

## Purpose

Implement an interactive terminal experience for Atelier without moving product ownership into a third-party agent CLI.

Atelier should remain the owner of:

- agent/runtime behavior
- shared context memory
- model routing
- tool supervision
- loop detection
- lesson promotion
- failure rescue
- verification
- session state
- MCP/background-service integration
- cost/savings logic

The terminal interface should be one more Atelier host, not the source of Atelier's architecture.

## Source-of-truth project facts

The current project positions Atelier as an **Agent Context Runtime**: reusable procedures, failure rescue, context compression, and cross-vendor routing for coding agents.

The README says Atelier is an MCP server and SDK middleware that plugs into Claude Code, Codex CLI, Copilot, opencode, Antigravity, Cursor, Hermes, and any MCP-compatible host. It also says Atelier provides shared context memory, model routing, tool supervision, loop detection, lesson promotion, and a savings-optimized execution layer.

The installed surfaces are already:

- `atelier` CLI
- `atelier-mcp` MCP server
- `atelier background` or `atelierd` service

The repo requires Python `>=3.11` and uses Hatchling.

`AGENTS.md` defines these project areas:

- `capabilities`: context reuse, failure analysis, loop detection, tool supervision, model routing, memory and recall, context compression, lesson promotion, governance
- `infrastructure`: code intelligence, embeddings, storage, runtime plumbing
- `gateway`: CLI, MCP server, host integrations, session parsers
- `integrations`: per-host install scripts, hooks, agent skills, workflow templates

Therefore the interactive CLI belongs under `gateway`, and all intelligence should stay in Atelier's core/runtime layers.

## Decision

Build the interactive CLI from low-level Python terminal primitives:

- `Typer` for normal CLI command registration
- `prompt_toolkit` for interactive REPL input
- `Rich` for rendering markdown, panels, diffs, tables, progress, logs, and tracebacks
- `Textual` later for a full-screen TUI, behind an optional extra

Do **not** use OpenCode, Kilo, Cline, Eval, Aider, Crush, or any other coding-agent CLI as a dependency for Atelier's runtime or CLI implementation.

Those tools may be studied for UX patterns only.

## Product boundary

### Atelier owns

```text
atelier-core
  agent loop
  capabilities
  runtime events
  context compression
  memory
  model routing
  verification
  loop detection
  failure rescue
  governance
  cost/savings logic

atelier-infra
  storage
  embeddings
  code intelligence
  shell/runtime plumbing
  background service clients

atelier-gateway
  CLI
  interactive CLI
  MCP server
  host adapters
  session parsers
```

### The interactive CLI owns only

```text
input
history
slash commands
autocomplete
rendering
approval prompts
keyboard shortcuts
terminal resize/interrupt handling
```

### Third-party terminal libraries own only

```text
terminal input primitives
terminal rendering primitives
layout primitives
syntax highlighting
markdown rendering
prompt history
completion UI
```

## Non-goals

Do not:

- embed OpenCode, Cline, Kilo, Eval, Aider, or Crush as runtime dependencies
- fork another agent CLI as the basis of Atelier
- put model/tool routing logic in the CLI frontend
- create a second session database for the CLI
- create a second memory layer for the CLI
- create a second tool registry for the CLI
- make the dashboard obsolete
- require Textual for the basic interactive experience

## Target user experience

Add:

```bash
atelier chat
```

Optional aliases:

```bash
atelier interactive
atelier repl
```

Later:

```bash
atelier tui
```

### Example flow

```text
$ atelier chat

Atelier interactive runtime
Project: /path/to/repo
Session: new

atelier> explain this codebase

◉ route
  selected: <model/provider>
  reason: context-heavy repo analysis

◉ memory
  found 3 related memories

◉ context
  compressed repo context from 18 files

◉ assistant
  ...

atelier> /tools
atelier> /memory pytest flakes
atelier> /sessions
atelier> /exit
```

## Recommended dependencies

Add default dependencies:

```toml
dependencies = [
  "typer>=0.12",
  "rich>=13",
  "prompt-toolkit>=3.0",
]
```

Add optional TUI dependency:

```toml
[project.optional-dependencies]
tui = [
  "textual>=0.80",
]
```

If the current project later adds stricter dependency management, preserve existing constraints and add these in the project's preferred style.

## Proposed file layout

Create or extend:

```text
src/atelier/gateway/cli/
  __init__.py
  app.py
  interactive.py
  events.py
  render.py
  slash.py
  completions.py
  keybindings.py

tests/gateway/cli/
  test_interactive_events.py
  test_slash_commands.py
  test_render.py
```

If the current CLI entrypoint lives elsewhere, adapt the import paths but preserve this separation:

- command registration in the existing CLI entrypoint
- interactive REPL in `interactive.py`
- rendering in `render.py`
- event types in `events.py`
- slash-command parsing in `slash.py`
- prompt completion in `completions.py`

## Event protocol

Create a small internal event protocol between the Atelier runtime and the CLI renderer.

Use `dataclasses`, `TypedDict`, or Pydantic depending on what the repo already uses. Prefer lightweight Python stdlib unless the project already uses Pydantic.

### Minimal event types

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


@dataclass(frozen=True)
class SessionStarted:
    type: Literal["session.started"]
    session_id: str
    project_root: str | None = None


@dataclass(frozen=True)
class AssistantDelta:
    type: Literal["assistant.delta"]
    text: str


@dataclass(frozen=True)
class AssistantMessage:
    type: Literal["assistant.message"]
    text: str


@dataclass(frozen=True)
class RouteSelected:
    type: Literal["route.selected"]
    provider: str | None
    model: str | None
    reason: str | None = None


@dataclass(frozen=True)
class MemoryHit:
    type: Literal["memory.hit"]
    key: str
    summary: str | None = None
    score: float | None = None


@dataclass(frozen=True)
class ToolRequested:
    type: Literal["tool.requested"]
    id: str
    name: str
    args: dict[str, Any]


@dataclass(frozen=True)
class ToolStarted:
    type: Literal["tool.started"]
    id: str
    name: str


@dataclass(frozen=True)
class ToolOutput:
    type: Literal["tool.output"]
    id: str
    chunk: str
    stream: Literal["stdout", "stderr", "log"] = "log"


@dataclass(frozen=True)
class ToolFinished:
    type: Literal["tool.finished"]
    id: str
    name: str
    ok: bool
    result: Any | None = None


@dataclass(frozen=True)
class PatchProposed:
    type: Literal["patch.proposed"]
    id: str
    files: list[str]
    diff: str


@dataclass(frozen=True)
class PermissionRequested:
    type: Literal["permission.requested"]
    id: str
    action: str
    reason: str | None = None
    risk: Literal["low", "medium", "high"] = "medium"


@dataclass(frozen=True)
class VerificationResult:
    type: Literal["verification.result"]
    ok: bool
    rubric: str | None = None
    details: str | None = None


@dataclass(frozen=True)
class RuntimeErrorEvent:
    type: Literal["error"]
    message: str
    details: str | None = None


AtelierEvent = (
    SessionStarted
    | AssistantDelta
    | AssistantMessage
    | RouteSelected
    | MemoryHit
    | ToolRequested
    | ToolStarted
    | ToolOutput
    | ToolFinished
    | PatchProposed
    | PermissionRequested
    | VerificationResult
    | RuntimeErrorEvent
)
```

### Input commands from CLI to runtime

```python
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class UserMessage:
    type: Literal["user.message"]
    text: str


@dataclass(frozen=True)
class UserSlashCommand:
    type: Literal["user.command"]
    name: str
    args: list[str]


@dataclass(frozen=True)
class PermissionResponse:
    type: Literal["permission.response"]
    id: str
    approved: bool
    scope: Literal["once", "session", "always"] = "once"


@dataclass(frozen=True)
class Interrupt:
    type: Literal["interrupt"]


AtelierInput = UserMessage | UserSlashCommand | PermissionResponse | Interrupt
```

## Runtime adapter

The CLI should consume an async event stream.

Create a small adapter that wraps whatever internal service currently handles `atelier tools call context`, `atelier tools call verify`, `atelier memory`, `atelier sessions`, and routing.

### Desired shape

```python
from collections.abc import AsyncIterator


class InteractiveRuntime:
    async def start_session(self, project_root: str | None = None) -> str:
        ...

    async def handle_user_message(
        self,
        session_id: str,
        text: str,
    ) -> AsyncIterator[AtelierEvent]:
        ...

    async def handle_slash_command(
        self,
        session_id: str,
        name: str,
        args: list[str],
    ) -> AsyncIterator[AtelierEvent]:
        ...

    async def respond_to_permission(
        self,
        session_id: str,
        permission_id: str,
        approved: bool,
        scope: str = "once",
    ) -> AsyncIterator[AtelierEvent]:
        ...

    async def interrupt(self, session_id: str) -> None:
        ...
```

If the real runtime APIs do not exist yet, implement a thin first version that calls existing capability/tool functions directly and emits events around them.

Do not shell out to `atelier ...` from inside `atelier chat` unless there is no internal Python API available. Prefer direct in-process calls.

## Slash commands

Implement this minimum set:

```text
/help
/exit
/quit
/clear
/tools
/sessions
/session <id>
/memory <query>
/route <task>
/context <task>
/verify <rubric-or-task>
/background status
/diff
/approve
/deny
```

### Command behavior

| Command                      | Behavior                                                  |
| ---------------------------- | --------------------------------------------------------- |
| `/help`                    | Render available commands and examples.                   |
| `/exit`, `/quit`         | Exit gracefully.                                          |
| `/clear`                   | Clear terminal screen.                                    |
| `/tools`                   | Show available Atelier tools.                             |
| `/sessions`                | Show known sessions.                                      |
| `/session <id>`            | Switch session or load session context.                   |
| `/memory <query>`          | Search Atelier memory.                                    |
| `/route <task>`            | Ask routing layer what model/provider should handle task. |
| `/context <task>`          | Run context capability for task.                          |
| `/verify <rubric-or-task>` | Run verification capability.                              |
| `/background status`       | Show background service status.                           |
| `/diff`                    | Show pending patch/diff if any.                           |
| `/approve`                 | Approve latest pending permission request.                |
| `/deny`                    | Deny latest pending permission request.                   |

Plain text that does not start with `/` should be treated as `user.message`.

## Completion behavior

Use `prompt_toolkit` completers.

Complete:

- slash command names
- known session IDs after `/session`
- tool names after `/tools` or `/call` if `/call` is added
- recent memory keys after `/memory`
- background subcommands after `/background`
- file paths only if needed later

Keep completions fast and non-blocking. Avoid doing expensive memory or session lookups on every keystroke. Cache the data for a few seconds or refresh after commands.

## Keybindings

Implement:

| Key                                 | Behavior                                              |
| ----------------------------------- | ----------------------------------------------------- |
| `Ctrl-C` once                     | Interrupt current runtime operation if one is active. |
| `Ctrl-C` twice or at empty prompt | Exit prompt after confirmation or print hint.         |
| `Ctrl-D`                          | Exit.                                                 |
| `Ctrl-L`                          | Clear screen.                                         |
| `Alt-Enter` or `Esc Enter`      | Insert newline for multiline messages if supported.   |

Use simple behavior first. Do not overfit.

## Rendering rules

Use Rich for all output.

Suggested renderer mapping:

| Event                    | Rich rendering                           |
| ------------------------ | ---------------------------------------- |
| `session.started`      | small panel or status line               |
| `route.selected`       | compact panel with model/provider/reason |
| `memory.hit`           | bullet list or table                     |
| `assistant.delta`      | stream text incrementally                |
| `assistant.message`    | render markdown                          |
| `tool.requested`       | dim tool-call header                     |
| `tool.started`         | spinner/status                           |
| `tool.output`          | syntax-aware or plain log block          |
| `tool.finished`        | success/failure line                     |
| `patch.proposed`       | syntax-highlighted diff                  |
| `permission.requested` | approval panel with `[y] [n] [always]` |
| `verification.result`  | success/failure panel                    |
| `error`                | red error panel with optional details    |

Do not make output too noisy. The default should be compact. Add a later `--verbose` mode for full traces.

## Minimal interactive implementation sketch

```python
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.completion import WordCompleter
from rich.console import Console

from atelier.gateway.cli.render import EventRenderer
from atelier.gateway.cli.slash import parse_input
from atelier.gateway.cli.runtime import InteractiveRuntime


COMMANDS = [
    "/help",
    "/exit",
    "/quit",
    "/clear",
    "/tools",
    "/sessions",
    "/session",
    "/memory",
    "/route",
    "/context",
    "/verify",
    "/background",
    "/diff",
    "/approve",
    "/deny",
]


async def run_interactive(project_root: str | None = None) -> int:
    console = Console()
    runtime = InteractiveRuntime()
    renderer = EventRenderer(console)

    session_id = await runtime.start_session(project_root=project_root)
    renderer.print_welcome(session_id=session_id, project_root=project_root)

    prompt = PromptSession(
        history=FileHistory(".atelier-chat-history"),
        completer=WordCompleter(COMMANDS, ignore_case=True),
        complete_while_typing=True,
    )

    while True:
        try:
            line = await prompt.prompt_async("atelier> ")
        except EOFError:
            console.print()
            return 0
        except KeyboardInterrupt:
            console.print("[dim]Use /exit to quit, or continue typing.[/dim]")
            continue

        parsed = parse_input(line)

        if parsed.kind == "empty":
            continue

        if parsed.kind == "exit":
            return 0

        if parsed.kind == "clear":
            console.clear()
            continue

        try:
            if parsed.kind == "slash":
                events = runtime.handle_slash_command(
                    session_id=session_id,
                    name=parsed.name,
                    args=parsed.args,
                )
            else:
                events = runtime.handle_user_message(
                    session_id=session_id,
                    text=parsed.text,
                )

            async for event in events:
                await renderer.render(event)

        except KeyboardInterrupt:
            await runtime.interrupt(session_id)
            console.print("[yellow]Interrupted.[/yellow]")
        except Exception as exc:
            renderer.render_exception(exc)
```

## CLI registration sketch

Wire into the current CLI app.

If the project uses Typer:

```python
import typer

from atelier.gateway.cli.interactive import run_interactive

app = typer.Typer()


@app.command("chat")
def chat(project_root: str | None = typer.Option(None, "--project-root")) -> None:
    """Start the interactive Atelier CLI."""
    import asyncio

    raise typer.Exit(asyncio.run(run_interactive(project_root=project_root)))


@app.command("interactive")
def interactive(project_root: str | None = typer.Option(None, "--project-root")) -> None:
    """Alias for `atelier chat`."""
    import asyncio

    raise typer.Exit(asyncio.run(run_interactive(project_root=project_root)))
```

If the project does not currently use Typer, do not rewrite the whole CLI immediately. Add the smallest compatible entrypoint that registers `chat`.

## Implementation phases

### Phase 0: repo-safe foundation

Tasks:

1. Add dependencies:
   - `rich`
   - `prompt-toolkit`
   - `typer` only if not already present or if the CLI already uses it.
2. Add `src/atelier/gateway/cli/events.py`.
3. Add `src/atelier/gateway/cli/slash.py`.
4. Add `src/atelier/gateway/cli/render.py`.
5. Add `src/atelier/gateway/cli/interactive.py`.
6. Register `atelier chat`.
7. Add tests for slash parsing and rendering smoke tests.
8. Update README quick start with `atelier chat`.

Acceptance criteria:

- `atelier chat` starts without requiring MCP host setup.
- `/help`, `/exit`, `/clear` work.
- Plain text input reaches the runtime adapter.
- Runtime events render through Rich.
- Tests pass.

### Phase 1: connect to real Atelier capabilities

Tasks:

1. Wire `/tools` to the existing tools registry.
2. Wire `/sessions` and `/session <id>` to existing session storage.
3. Wire `/memory <query>` to existing memory search.
4. Wire `/route <task>` to the model routing capability.
5. Wire `/context <task>` to the context capability.
6. Wire `/verify <rubric-or-task>` to verification.
7. Emit route/memory/context/verification events instead of printing directly.
8. Ensure errors become `RuntimeErrorEvent`.

Acceptance criteria:

- Every existing documented CLI surface has an interactive equivalent where appropriate.
- No CLI-specific memory/session storage is introduced.
- No runtime logic lives in renderer/completer/slash modules.

### Phase 2: approvals and tool visibility

Tasks:

1. Add permission request event support.
2. Render approval prompt for shell/edit/high-risk tool calls.
3. Implement `/approve` and `/deny`.
4. Allow direct key approval later, but slash commands are enough for first version.
5. Show compact tool call lifecycle:
   - requested
   - started
   - output
   - finished
6. Preserve a pending approval queue in runtime/session state, not renderer state.

Acceptance criteria:

- Dangerous tool calls can pause for user approval.
- User can approve or deny from the interactive CLI.
- Approval decisions are passed back to Atelier runtime, not handled ad hoc in frontend.

### Phase 3: patch/diff UX

Tasks:

1. Add `PatchProposed` events for file edits.
2. Render unified diffs with Rich syntax highlighting.
3. Add `/diff`.
4. Add accept/deny flow if patches are staged before writing.
5. If the current runtime writes files directly, initially show post-change diff from Git and warn accordingly.

Acceptance criteria:

- User can inspect proposed or recent changes from within `atelier chat`.
- Diff rendering works for multiple files.
- No separate patch engine is introduced in the CLI.

### Phase 4: polish

Tasks:

1. Add completions for slash commands.
2. Add cached completions for sessions/tools.
3. Add persistent history in an Atelier config/cache directory.
4. Add `--verbose` and `--json-events`.
5. Add compact mode for small terminals.
6. Add `Ctrl-C` interruption behavior.
7. Add terminal-width-aware rendering.

Acceptance criteria:

- Interactive CLI feels usable for real coding-agent sessions.
- JSON event mode can be used for debugging or future frontend reuse.
- Rendering does not break in narrow terminals.

### Phase 5: optional fullscreen TUI

Add only after the event protocol is stable.

Tasks:

1. Add optional `tui` extra with Textual.
2. Add `atelier tui`.
3. Build panes:
   - sessions
   - conversation
   - tool calls
   - approvals
   - memory hits
   - diffs
4. Reuse the same `AtelierEvent` protocol.
5. Do not fork runtime behavior for Textual.

Acceptance criteria:

- `atelier chat` remains the default lightweight interface.
- `atelier tui` is only an alternate frontend.
- Both consume the same runtime event stream.

## Testing plan

### Unit tests

Test `slash.py`:

- empty input
- plain message
- `/help`
- `/exit`
- `/memory query here`
- `/background status`
- unknown command

Test `render.py`:

- each event type renders without exception
- markdown assistant message renders
- diff event renders
- error event renders

Test `events.py`:

- event dataclasses are constructible
- event unions are accepted by renderer

### Integration tests

Add a fake runtime that emits deterministic events:

```python
class FakeRuntime:
    async def start_session(self, project_root=None):
        return "test-session"

    async def handle_user_message(self, session_id, text):
        yield RouteSelected(type="route.selected", provider="test", model="test-model")
        yield AssistantMessage(type="assistant.message", text=f"Echo: {text}")
```

Use this to test:

- `atelier chat` starts
- a message is accepted
- output is rendered
- `/exit` exits cleanly

Avoid tests that require real model calls.

## Documentation updates

Update README:

```bash
# Start the interactive CLI
atelier chat
```

Add a short section:

```md
## Interactive CLI

`atelier chat` starts a local interactive shell over the Atelier runtime.

It reuses Atelier's existing memory, routing, tools, sessions, verification, and background service. It does not embed a third-party agent CLI.
```

Add docs page if desired:

```text
docs/interactive-cli.md
```

## Risks and mitigations

### Risk: duplicating runtime logic in CLI

Mitigation:

- keep runtime adapter thin
- renderer only receives events
- slash commands dispatch to runtime services

### Risk: overbuilding fullscreen UI too early

Mitigation:

- start with REPL using prompt_toolkit + Rich
- make Textual optional and later

### Risk: blocking prompt during long tool calls

Mitigation:

- use async event stream
- render tool events incrementally
- add interruption support

### Risk: noisy output

Mitigation:

- compact defaults
- `--verbose` for full traces
- group tool output in panels or collapsible sections later

### Risk: expensive completions

Mitigation:

- cache sessions/tools/memory suggestions
- do not query storage on every keystroke

## UX references, not dependencies

Study these tools for interaction patterns only:

- OpenCode: terminal-native agent UX, modes, approval flow
- Kilo: product packaging around OpenCode-style workflows
- Cline: task lifecycle and IDE-oriented agent UX
- Eval: daemon/session feeling and token-efficiency ideas
- Aider: repo-editing flow and Git-aware code changes
- Crush: polished terminal visual design

Do not depend on their internals.

## Final instruction to coding agent

Implement `atelier chat` as an Atelier-owned interactive frontend.

Use `prompt_toolkit` and `Rich` for P0. Keep all agent intelligence in existing Atelier runtime/capability layers. Add a small event protocol so future frontends, including a Textual fullscreen TUI, can reuse the same stream.

Do not introduce a third-party coding-agent runtime. Do not introduce a second memory/session/tool system. Do not make CLI rendering modules responsible for planning, routing, verification, or tool execution.
