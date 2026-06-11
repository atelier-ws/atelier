"""Aggregator entrypoint for relocated Atelier CLI command modules."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    import click


def _h(cmd: object) -> object:
    """Mark a click command/group hidden (used for internal commands)."""
    if cmd is not None and hasattr(cmd, "hidden"):
        cmd.hidden = True  # type: ignore[union-attr]
    return cmd


def register(cli: click.Group) -> None:
    """Register relocated command modules onto the root ``cli`` group."""
    try:
        from . import admin as admin_commands

        cli.add_command(admin_commands.init)
        cli.add_command(admin_commands.uninstall)
        _h(admin_commands.env_group)  # internal validation
        cli.add_command(admin_commands.env_group)
        cli.add_command(admin_commands.login_cmd)
        cli.add_command(admin_commands.logout_cmd)
        # status_cmd is registered as 'dashboard' later (with 'status' as hidden alias)
        _h(admin_commands.share_cmd)
        cli.add_command(admin_commands.share_cmd)
        cli.add_command(admin_commands.plugin_settings_group)
        doctor_cmd = getattr(admin_commands, "doctor_cmd", None)
        if doctor_cmd is not None:
            cli.add_command(cast("click.Command", doctor_cmd))
        reset_cmd = getattr(admin_commands, "reset_cmd", None)
        if reset_cmd is not None:
            cli.add_command(cast("click.Command", reset_cmd))
        cli.add_command(admin_commands.team_group)
        _h(admin_commands.governance_group)
        cli.add_command(admin_commands.governance_group)
        cli.add_command(admin_commands.audit_group)
        _h(admin_commands.insights_cmd)
        cli.add_command(admin_commands.insights_cmd)
    except (ModuleNotFoundError, ImportError):
        pass

    try:
        from .blocks import domain_group, report_cmd

        _h(domain_group)
        cli.add_command(domain_group)
        _h(report_cmd)
        cli.add_command(report_cmd)
    except (ModuleNotFoundError, ImportError):
        pass

    try:
        from .telemetry import telemetry_group

        cli.add_command(telemetry_group)
    except (ModuleNotFoundError, ImportError):
        pass

    try:
        from .servicectl import servicectl_group, worker_group

        _h(worker_group)
        cli.add_command(worker_group)
        _h(servicectl_group)
        cli.add_command(servicectl_group)
    except (ModuleNotFoundError, ImportError):
        pass

    # ── hidden internal commands (used by dev.sh, not user-facing) ───────────
    try:
        from .background import background_group

        cli.add_command(background_group, name="background")
    except (ModuleNotFoundError, ImportError):
        pass

    try:
        from . import admin as admin_commands
        from .tools import tool_mode, tools_group

        tools_group.add_command(tool_mode, name="mode")
        tools_group.add_command(admin_commands.tool_report_cmd, name="report")
        # Hide the 'tools' name; expose only the canonical 'mcp' alias
        _h(tools_group)
        cli.add_command(tools_group)
        # Add 'mcp' as the canonical alias (Claude Code uses 'claude mcp')
        try:
            import click as _c

            mcp_alias = _c.CommandCollection(name="mcp", sources=[tools_group])
            mcp_alias.help = "Configure and inspect Atelier MCP tools."
            cli.add_command(mcp_alias)
        except Exception:  # noqa: BLE001
            pass
    except (ModuleNotFoundError, ImportError):
        pass

    try:
        from .savings import (
            optimize_group,
            savings_cmd,
        )

        _h(savings_cmd)
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

        _h(defaults_group)
        cli.add_command(defaults_group)
    except (ModuleNotFoundError, ImportError):
        pass

    try:
        from .code import code_group

        cli.add_command(code_group)
    except (ModuleNotFoundError, ImportError):
        pass

    try:
        from .route import proof_group, route_public_group

        cli.add_command(route_public_group)
        cli.add_command(proof_group)
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

        _h(ledger)
        cli.add_command(ledger)
        cli.add_command(checkpoint)
        _h(failure)
        cli.add_command(failure)
        _h(lesson)
        cli.add_command(lesson)
        cli.add_command(eval_)
    except (ModuleNotFoundError, ImportError):
        pass

    try:
        from .sessions import runs_group, session_group

        cli.add_command(runs_group)
        _h(session_group)
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
        import click as _click

        from . import admin as admin_commands

        @_click.group("dashboard", invoke_without_command=True)
        @_click.pass_context
        def dashboard_group(ctx: _click.Context) -> None:
            """Show Atelier runs dashboard, costs, and service status.

            Run with no arguments for the terminal overview.
            Use ``atelier dashboard open`` to open the browser analytics UI.
            """
            if ctx.invoked_subcommand is None:
                # Forward to the underlying status_cmd
                ctx.invoke(admin_commands.status_cmd)

        @dashboard_group.command("open")
        @_click.option("--port", default=8787, show_default=True, help="Atelier service port")
        @_click.option("--dev", is_flag=True, default=False, help="Open Vite dev server (port 3125)")
        def dashboard_open_cmd(port: int, dev: bool) -> None:
            """Open the Atelier analytics dashboard in your browser."""
            import urllib.request
            import webbrowser

            target_port = 3125 if dev else port
            url = f"http://localhost:{target_port}/analytics"
            try:
                urllib.request.urlopen(f"http://localhost:{target_port}/health", timeout=2)
                _click.echo(f"  ◆ Opening Atelier dashboard: {url}")
                webbrowser.open(url)
            except Exception:  # noqa: BLE001
                _click.echo(
                    f"  Atelier service not running on port {target_port}.\n\n"
                    f"  Start it with:\n"
                    f"    atelierd start\n"
                    f"  Or as background service:\n"
                    f"    atelierd install && atelierd restart\n\n"
                    f"  Then run: atelier dashboard open"
                )

        cli.add_command(dashboard_group)
        # Keep 'status' as a hidden alias for backward compatibility
        _h(admin_commands.status_cmd)
        cli.add_command(admin_commands.status_cmd)
    except (ModuleNotFoundError, ImportError):
        pass

    try:
        import click as _click

        @_click.command("serve-openai")
        @_click.option(
            "--port", default=8790, show_default=True, help="Port to listen on (8787 is the Atelier service port)"
        )
        @_click.option("--host", default="0.0.0.0", show_default=True, help="Bind address")
        @_click.option("--project-root", default=None, help="Project root directory")
        @_click.option(
            "--no-yolo",
            is_flag=True,
            default=False,
            help="Require manual approval for tool calls (default: auto-approve)",
        )
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

        serve_openai_cmd.hidden = True  # internal: integrated into atelier service
        cli.add_command(serve_openai_cmd, name="serve-openai")
    except (ModuleNotFoundError, ImportError):
        pass

    try:
        import click as _click

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
    except ImportError:
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
