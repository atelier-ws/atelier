"""Aggregator entrypoint for relocated Atelier CLI command modules."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    import click


def register(cli: click.Group) -> None:
    """Register relocated command modules onto the root ``cli`` group."""
    try:
        from . import admin as admin_commands

        cli.add_command(admin_commands.init)
        cli.add_command(admin_commands.uninstall)
        cli.add_command(admin_commands.env_group)
        cli.add_command(admin_commands.login_cmd)
        cli.add_command(admin_commands.logout_cmd)
        cli.add_command(admin_commands.status_cmd)
        cli.add_command(admin_commands.share_cmd)
        cli.add_command(admin_commands.plugin_settings_group)
        doctor_cmd = getattr(admin_commands, "doctor_cmd", None)
        if doctor_cmd is not None:
            cli.add_command(cast("click.Command", doctor_cmd))
        reset_cmd = getattr(admin_commands, "reset_cmd", None)
        if reset_cmd is not None:
            cli.add_command(cast("click.Command", reset_cmd))
        cli.add_command(admin_commands.team_group)
        cli.add_command(admin_commands.governance_group)
        cli.add_command(admin_commands.audit_group)
        cli.add_command(admin_commands.insights_cmd)
    except (ModuleNotFoundError, ImportError):
        pass

    try:
        from .blocks import domain_group, report_cmd

        cli.add_command(domain_group)
        cli.add_command(report_cmd)
    except (ModuleNotFoundError, ImportError):
        pass

    try:
        from .telemetry import telemetry_group

        cli.add_command(telemetry_group)
    except (ModuleNotFoundError, ImportError):
        pass

    try:
        from .stack import stack_group

        cli.add_command(stack_group)
    except (ModuleNotFoundError, ImportError):
        pass

    try:
        from .servicectl import logs_cmd, service_group, servicectl_group, worker_group

        cli.add_command(service_group)
        cli.add_command(worker_group)
        cli.add_command(servicectl_group)
        cli.add_command(logs_cmd)
    except (ModuleNotFoundError, ImportError):
        pass

    try:
        from .background import background_group, systemd_alias_group

        cli.add_command(background_group)
        cli.add_command(systemd_alias_group)
    except (ModuleNotFoundError, ImportError):
        pass

    try:
        from . import admin as admin_commands
        from .tools import tool_mode, tools_group

        tools_group.add_command(tool_mode, name="mode")
        tools_group.add_command(admin_commands.tool_report_cmd, name="report")
        cli.add_command(tools_group)
    except (ModuleNotFoundError, ImportError):
        pass

    try:
        from .savings import (
            optimize_group,
            savings_cmd,
        )

        cli.add_command(savings_cmd)
        cli.add_command(optimize_group)
    except (ModuleNotFoundError, ImportError):
        pass

    try:
        from .benchmark import benchmark_group

        cli.add_command(benchmark_group)
    except (ModuleNotFoundError, ImportError):
        pass

    try:
        from .defaults import defaults_group

        cli.add_command(defaults_group)
    except (ModuleNotFoundError, ImportError):
        pass

    try:
        from .code import code_group

        cli.add_command(code_group)
    except (ModuleNotFoundError, ImportError):
        pass

    try:
        from .route import route_public_group

        cli.add_command(route_public_group)
    except (ModuleNotFoundError, ImportError):
        pass

    try:
        from .hosts import global_import

        cli.add_command(global_import)
    except (ModuleNotFoundError, ImportError):
        pass

    try:
        from .lessons import (
            checkpoint,
            eval_,
            failure,
            ledger,
            lesson,
        )

        cli.add_command(ledger)
        cli.add_command(checkpoint)
        cli.add_command(failure)
        cli.add_command(lesson)
        cli.add_command(eval_)
    except (ModuleNotFoundError, ImportError):
        pass

    try:
        from .sessions import runs_group, session_group

        cli.add_command(runs_group)
        cli.add_command(session_group)
    except (ModuleNotFoundError, ImportError):
        pass

    try:
        from .swarm import swarm_group

        cli.add_command(swarm_group)
    except (ModuleNotFoundError, ImportError):
        pass

    try:
        from .run import run_group

        cli.add_command(run_group)
    except (ModuleNotFoundError, ImportError):
        pass

    try:
        from .memory import memory_group_cli

        cli.add_command(memory_group_cli)
    except (ModuleNotFoundError, ImportError):
        pass

    try:
        import asyncio
        from pathlib import Path

        import click as _click

        from atelier.gateway.cli.interactive import run_interactive

        @_click.command("tui")
        @_click.option("--project-root", default=None, help="Project root directory")
        @_click.option(
            "--yolo", is_flag=True, default=False, help="Skip edit/shell approval prompts"
        )
        @_click.pass_obj
        def tui_cmd(obj: object, project_root: str | None, yolo: bool) -> None:
            """Start the interactive Atelier workspace (Rust frontend)."""
            from pathlib import Path as _Path

            root = obj.get("root") if isinstance(obj, dict) else None
            from atelier.gateway.cli.app import _exec_rust_tui

            _exec_rust_tui(root if isinstance(root, _Path) else _Path.home() / ".atelier")

        @_click.command("chat")
        @_click.option("--project-root", default=None)
        @_click.option("--yolo", is_flag=True, default=False)
        @_click.pass_obj
        def chat_cmd(obj: object, project_root: str | None, yolo: bool) -> None:
            """Alias for ``atelier tui``."""
            root = obj.get("root") if isinstance(obj, dict) else None
            raise SystemExit(
                asyncio.run(
                    run_interactive(
                        project_root=project_root,
                        yolo=yolo,
                        root=root if isinstance(root, Path) else None,
                    )
                )
            )

        @_click.command("workspace")
        @_click.option("--project-root", default=None)
        @_click.option("--yolo", is_flag=True, default=False)
        @_click.pass_obj
        def workspace_cmd(obj: object, project_root: str | None, yolo: bool) -> None:
            """Start the interactive Atelier workspace (explicit alias for tui)."""
            from pathlib import Path as _Path

            root = obj.get("root") if isinstance(obj, dict) else None  # type: ignore[union-attr]
            from atelier.gateway.cli.app import _exec_rust_tui

            _exec_rust_tui(root if isinstance(root, _Path) else _Path.home() / ".atelier")

        cli.add_command(tui_cmd)
        cli.add_command(chat_cmd)
        cli.add_command(workspace_cmd)
    except (ModuleNotFoundError, ImportError):
        pass

    try:
        import click as _click

        @_click.command("dashboard")
        @_click.option("--port", default=8787, show_default=True, help="Atelier service port (default: 8787)")
        @_click.option("--dev", is_flag=True, default=False, help="Open the Vite dev server (port 3125) instead")
        def dashboard_cmd(port: int, dev: bool) -> None:
            """Open the Atelier analytics dashboard in your browser."""
            import urllib.request
            import webbrowser

            target_port = 3125 if dev else port
            url = f"http://localhost:{target_port}/analytics"

            # Check if service is running
            try:
                urllib.request.urlopen(f"http://localhost:{target_port}/health", timeout=2)
                _click.echo(f"  \u25c6 Opening Atelier dashboard: {url}")
                webbrowser.open(url)
            except Exception:
                # Service not running
                dev_hint = "\n  Dev mode: cd frontend && npm run dev" if not dev else ""
                _click.echo(
                    f"  Atelier service not running on port {target_port}.\n\n"
                    f"  Start it with:\n"
                    f"    atelier service start\n"
                    f"  Or in Docker:\n"
                    f"    docker compose up{dev_hint}\n\n"
                    f"  Then run: atelier dashboard"
                )

        cli.add_command(dashboard_cmd)
    except (ModuleNotFoundError, ImportError):
        pass

    try:
        import asyncio as _asyncio

        import click as _click

        @_click.command("tui-backend")
        @_click.option("--project-root", default=None, help="Project root directory")
        @_click.option("--session-id", default=None, help="Resume a saved session")
        @_click.pass_obj
        def tui_backend_cmd(
            obj: object, project_root: str | None, session_id: str | None
        ) -> None:
            """NDJSON backend server for the atelier-tui Rust frontend (internal)."""
            from atelier.gateway.cli.server import run_ndjson_server

            raise SystemExit(
                _asyncio.run(
                    run_ndjson_server(project_root=project_root, session_id=session_id)
                )
            )

        cli.add_command(tui_backend_cmd, name="tui-backend")
    except (ModuleNotFoundError, ImportError):
        pass

    try:
        import click as _click

        @_click.command("serve-openai")
        @_click.option("--port", default=8787, show_default=True, help="Port to listen on")
        @_click.option("--host", default="0.0.0.0", show_default=True, help="Bind address")
        @_click.option("--project-root", default=None, help="Project root directory")
        @_click.option("--no-yolo", is_flag=True, default=False, help="Require manual approval for tool calls (default: auto-approve)")
        def serve_openai_cmd(port: int, host: str, project_root: str | None, no_yolo: bool) -> None:
            """Start the OpenAI-compatible chat completions gateway.

            Any TUI that supports custom OpenAI-compatible endpoints can connect.

            \b
            OpenCode  (opencode.json):
              "provider": {"atelier": {"npm": "@ai-sdk/openai-compatible",
                "options": {"baseURL": "http://localhost:8787/v1", "apiKey": "local"}}}

            Crush  (crush.json):
              "providers": {"atelier": {"type": "openai-compat",
                "base_url": "http://localhost:8787/v1", "api_key": "local"}}

            Codex  (~/.codex/config.toml):
              [model_providers.atelier]
              base_url = "http://localhost:8787/v1"
              wire_api = "chat"
            """
            from atelier.gateway.openai_gateway.serve import serve

            serve(port=port, host=host, project_root=project_root, yolo=not no_yolo)

        cli.add_command(serve_openai_cmd, name="serve-openai")
    except (ModuleNotFoundError, ImportError):
        pass

        @_click.command("completions")
        @_click.argument("shell", type=_click.Choice(["zsh", "bash", "fish"]))
        def completions_cmd(shell: str) -> None:
            """Print shell completion script.

            \b
            # zsh:  echo 'eval "$(atelier completions zsh)"'  >> ~/.zshrc
            # bash: echo 'eval "$(atelier completions bash)"' >> ~/.bashrc
            # fish: atelier completions fish > ~/.config/fish/completions/atelier.fish
            """
            scripts = {
                "zsh": _ZSH_COMPLETION,
                "bash": _BASH_COMPLETION,
                "fish": _FISH_COMPLETION,
            }
            _click.echo(scripts[shell])

        cli.add_command(completions_cmd)
    except (ModuleNotFoundError, ImportError):
        pass


_ZSH_COMPLETION = """
#compdef atelier
_atelier() {
    local -a commands
    commands=(
        'tui:Start interactive workspace'
        'workspace:Start interactive workspace (alias)'
        'chat:Start interactive REPL'
        'run:Run one-shot owned coding session'
        'mcp:Start MCP server'
        'completions:Print shell completion script'
        'savings:Show cost/savings summary'
        'sessions:Session management'
        'context:Context operations'
        'route:Routing operations'
        'service:Service management'
        'worker:Worker management'
    )
    _describe 'atelier commands' commands
}
compdef _atelier atelier
"""

_BASH_COMPLETION = """
_atelier_completions() {
    local cur="${COMP_WORDS[COMP_CWORD]}"
    local commands="tui workspace chat run mcp completions savings sessions context route service worker --help --version"
    COMPREPLY=($(compgen -W "${commands}" -- "${cur}"))
}
complete -F _atelier_completions atelier
"""

_FISH_COMPLETION = """
complete -c atelier -f
complete -c atelier -n '__fish_use_subcommand' -a tui -d 'Start interactive workspace'
complete -c atelier -n '__fish_use_subcommand' -a workspace -d 'Start interactive workspace (alias)'
complete -c atelier -n '__fish_use_subcommand' -a chat -d 'Start interactive REPL'
complete -c atelier -n '__fish_use_subcommand' -a run -d 'Run one-shot owned coding session'
complete -c atelier -n '__fish_use_subcommand' -a mcp -d 'Start MCP server'
complete -c atelier -n '__fish_use_subcommand' -a completions -d 'Print shell completion script'
complete -c atelier -n '__fish_use_subcommand' -a savings -d 'Show cost/savings summary'
"""
