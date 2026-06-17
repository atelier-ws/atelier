"""Interactive REPL loop for the Atelier terminal."""

from __future__ import annotations

import os
from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style
from rich.console import Console

from atelier.gateway.cli.completions import AtelierCompleter
from atelier.gateway.cli.keybindings import make_keybindings
from atelier.gateway.cli.render import EventRenderer
from atelier.gateway.cli.runtime import InteractiveRuntime
from atelier.gateway.cli.slash import parse_input

PROMPT_STYLE = Style.from_dict({"prompt": "ansigreen bold"})


async def run_interactive(
    *,
    project_root: str | None = None,
    yolo: bool = False,
    root: Path | None = None,
) -> int:
    console = Console()
    runtime = InteractiveRuntime(root=root, yolo=yolo)
    renderer = EventRenderer(console)

    cwd = project_root or os.getcwd()
    session_id = await runtime.start_session(project_root=cwd)
    renderer.print_welcome(session_id=session_id, project_root=cwd)

    history_path = Path.home() / ".atelier" / "tui_history"
    history_path.parent.mkdir(parents=True, exist_ok=True)

    prompt_session: PromptSession[str] = PromptSession(
        history=FileHistory(str(history_path)),
        completer=AtelierCompleter(runtime.session_ids),
        complete_while_typing=True,
        key_bindings=make_keybindings(),
        style=PROMPT_STYLE,
    )

    while True:
        try:
            line: str = await prompt_session.prompt_async("atelier> ")
        except EOFError:
            console.print()
            return 0
        except KeyboardInterrupt:
            console.print("[dim]Ctrl-C — use /exit to quit or Ctrl-D.[/dim]")
            continue

        parsed = parse_input(line)

        if parsed.kind == "empty":
            continue
        if parsed.kind == "exit":
            console.print("[dim]Bye.[/dim]")
            return 0
        if parsed.kind == "clear":
            console.clear()
            renderer.print_welcome(session_id=session_id, project_root=cwd)
            continue

        try:
            if parsed.kind == "slash":
                events_iter = runtime.handle_slash_command(
                    session_id=session_id,
                    name=parsed.name,
                    args=parsed.args,
                )
            else:
                events_iter = runtime.handle_user_message(
                    session_id=session_id,
                    text=parsed.text,
                )

            renderer.start_stream()
            async for event in events_iter:
                await renderer.render(event)
            renderer.end_stream()

        except KeyboardInterrupt:
            await runtime.interrupt(session_id)
            console.print("\n[yellow]Interrupted.[/yellow]")
        except Exception as exc:  # noqa: BLE001 - surface any runtime error to user
            renderer.render_exception(exc)
