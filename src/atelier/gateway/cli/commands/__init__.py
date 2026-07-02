"""Aggregator entrypoint for relocated Atelier CLI command modules."""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    import click


# Set ATELIER_SHOW_ALL=1 to reveal internal/hidden commands in ``atelier --help``.
_SHOW_ALL = os.environ.get("ATELIER_SHOW_ALL") == "1"


def _h(cmd: Any) -> Any:
    """Mark a click command/group hidden (used for internal commands).

    Hidden commands stay fully runnable and ``atelier <cmd> --help`` still
    prints their help; they are only dropped from the top-level ``--help``
    listing. Set ``ATELIER_SHOW_ALL=1`` to reveal them all.
    """
    if not _SHOW_ALL and cmd is not None:
        cmd.hidden = True
    return cmd


def register(cli: click.Group) -> None:
    """Register relocated command modules onto the root ``cli`` group."""
    from atelier.gateway.cli.commands._shared import _IMPORT_FAILED

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
            _h(cast("click.Command", reset_cmd))
            cli.add_command(cast("click.Command", reset_cmd))
        _h(admin_commands.team_group)
        cli.add_command(admin_commands.team_group)
        _h(admin_commands.governance_group)
        cli.add_command(admin_commands.governance_group)
        _h(admin_commands.audit_group)
        cli.add_command(admin_commands.audit_group)
        _h(admin_commands.insights_cmd)
        cli.add_command(admin_commands.insights_cmd)
    except (ModuleNotFoundError, ImportError):
        _IMPORT_FAILED = True

    try:
        from .playbooks import (
            add_playbook,
            domain_group,
            import_style_guide_cmd,
            list_blocks_cmd,
            playbook_group,
            reembed,
            report_cmd,
        )

        _h(domain_group)
        cli.add_command(domain_group)
        _h(report_cmd)
        cli.add_command(report_cmd)
        _h(playbook_group)
        cli.add_command(playbook_group)
        _h(list_blocks_cmd)
        cli.add_command(list_blocks_cmd)
        _h(add_playbook)
        cli.add_command(cast("click.Command", add_playbook))
        _h(import_style_guide_cmd)
        cli.add_command(import_style_guide_cmd)
        _h(reembed)
        cli.add_command(cast("click.Command", reembed))
    except (ModuleNotFoundError, ImportError):
        _IMPORT_FAILED = True

    try:
        from .telemetry import telemetry_group

        cli.add_command(telemetry_group)
    except (ModuleNotFoundError, ImportError):
        _IMPORT_FAILED = True

    try:
        from .servicectl import service_group, servicectl_group, worker_group

        cli.add_command(service_group)
        _h(worker_group)
        cli.add_command(worker_group)
        _h(servicectl_group)
        cli.add_command(servicectl_group)
    except (ModuleNotFoundError, ImportError):
        _IMPORT_FAILED = True

    try:
        from .stack import stack_group

        cli.add_command(stack_group)
    except (ModuleNotFoundError, ImportError):
        _IMPORT_FAILED = True

    # ── hidden internal commands (used by dev.sh, not user-facing) ───────────
    try:
        from .background import background_group

        cli.add_command(background_group, name="background")
    except (ModuleNotFoundError, ImportError):
        _IMPORT_FAILED = True

    try:
        from .background import systemd_alias_group

        cli.add_command(systemd_alias_group)
    except (ModuleNotFoundError, ImportError):
        _IMPORT_FAILED = True

    try:
        from . import admin as admin_commands
        from .tools import tool_mode, tools_group

        tools_group.add_command(tool_mode, name="mode")
        tools_group.add_command(admin_commands.tool_report_cmd, name="report")
        _h(tools_group)
        cli.add_command(tools_group)

        # 'atelier mcp' starts the stdio MCP server (replaces the legacy standalone binary)
        try:
            from .mcp import mcp_group

            cli.add_command(mcp_group)
        except (ModuleNotFoundError, ImportError):
            _IMPORT_FAILED = True
    except (ModuleNotFoundError, ImportError):
        _IMPORT_FAILED = True

    try:
        from .savings import (
            optimize_group,
            savings_cmd,
        )

        # savings is the headline metric — kept visible in --help.
        cli.add_command(savings_cmd)
        _h(optimize_group)  # advanced tuning advisor — internal
        cli.add_command(optimize_group)
    except (ModuleNotFoundError, ImportError):
        _IMPORT_FAILED = True

    try:
        from .update import update_cmd

        cli.add_command(update_cmd)
    except (ModuleNotFoundError, ImportError):
        _IMPORT_FAILED = True

    try:
        from .benchmark import benchmark_group

        cli.add_command(benchmark_group)
    except (ModuleNotFoundError, ImportError):
        _IMPORT_FAILED = True

    try:
        from .knowledge import knowledge_group

        _h(knowledge_group)
        cli.add_command(knowledge_group)
    except (ModuleNotFoundError, ImportError):
        _IMPORT_FAILED = True

    try:
        from .router import router_daemon_group

        _h(router_daemon_group)
        cli.add_command(router_daemon_group)
    except (ModuleNotFoundError, ImportError):
        _IMPORT_FAILED = True

    try:
        from .recall import recall_group

        cli.add_command(recall_group)
    except (ModuleNotFoundError, ImportError):
        _IMPORT_FAILED = True

    try:
        from .db import db_group

        _h(db_group)
        cli.add_command(db_group)
    except (ModuleNotFoundError, ImportError):
        _IMPORT_FAILED = True

    try:
        from .defaults import defaults_group

        _h(defaults_group)
        cli.add_command(defaults_group)
    except (ModuleNotFoundError, ImportError):
        _IMPORT_FAILED = True

    try:
        from .code import code_group, zoekt_group

        _h(code_group.commands.get("train"))  # [EXPERIMENTAL] embedder finetune — internal
        cli.add_command(code_group)
        _h(zoekt_group)  # search-backend infra used transparently by code_search
        cli.add_command(zoekt_group)
    except (ModuleNotFoundError, ImportError):
        _IMPORT_FAILED = True

    try:
        from .perf import perf_group

        _h(perf_group)
        cli.add_command(perf_group)
    except (ModuleNotFoundError, ImportError):
        _IMPORT_FAILED = True

    try:
        from .route import proof_group, route_public_group

        _h(route_public_group)
        cli.add_command(route_public_group)
        _h(proof_group)
        cli.add_command(proof_group)
    except (ModuleNotFoundError, ImportError):
        _IMPORT_FAILED = True

    try:
        from .hosts import global_import

        _h(global_import)
        cli.add_command(global_import)
    except (ModuleNotFoundError, ImportError):
        _IMPORT_FAILED = True

    try:
        from .eval import eval_
        from .lessons import (
            checkpoint,
            ledger,
            lesson,
        )

        _h(ledger)
        cli.add_command(ledger)
        _h(checkpoint)
        cli.add_command(checkpoint)
        _h(lesson)
        cli.add_command(lesson)
        _h(eval_)
        cli.add_command(eval_)
    except (ModuleNotFoundError, ImportError):
        _IMPORT_FAILED = True

    try:
        from .sessions import runs_group, session_group

        _h(runs_group)
        cli.add_command(runs_group)
        cli.add_command(session_group)
    except (ModuleNotFoundError, ImportError):
        _IMPORT_FAILED = True

    try:
        from .swarm import swarm_group

        cli.add_command(swarm_group)
    except (ModuleNotFoundError, ImportError):
        _IMPORT_FAILED = True

    try:
        from .run import run_group

        _h(run_group)  # owned coding sessions — undocumented; hidden until launched
        cli.add_command(run_group)
    except (ModuleNotFoundError, ImportError):
        _IMPORT_FAILED = True

    try:
        from .memory import memory_group_cli

        _h(memory_group_cli)
        cli.add_command(memory_group_cli)
    except (ModuleNotFoundError, ImportError):
        _IMPORT_FAILED = True

    try:
        from .letta import letta_group

        _h(letta_group)
        cli.add_command(letta_group)
    except (ModuleNotFoundError, ImportError):
        _IMPORT_FAILED = True

    try:
        import click as _click

        from . import admin as admin_commands

        @_click.group("dashboard", invoke_without_command=True)
        @_click.pass_context
        def dashboard_group(ctx: _click.Context) -> None:
            """Show the Atelier spend & savings dashboard.

            Run with no arguments for the terminal rollup (last 7 days + recent
            runs). Use ``atelier dashboard open`` for the browser analytics UI.
            """
            if ctx.invoked_subcommand is None:
                from atelier.core.capabilities.reporting.dashboard import render_overview

                _click.echo(render_overview(ctx.obj["root"]))

        @dashboard_group.command("open")
        @_click.option("--port", default=3125, show_default=True, help="Atelier web UI (frontend) port")
        def dashboard_open_cmd(port: int) -> None:
            """Open the Atelier analytics web UI in your browser.

            Targets the frontend (Vite) on port 3125 — the backend service on
            8787 only serves the JSON API, not the dashboard.
            """
            import urllib.request
            import webbrowser

            # Frontend root ('/') redirects to the dashboard home ('/overview').
            url = f"http://localhost:{port}/"
            try:
                urllib.request.urlopen(url, timeout=2)
            except Exception:  # noqa: BLE001
                _click.echo(
                    f"  Atelier web UI not running on port {port}.\n\n"
                    f"  Start the full stack (backend + web UI):\n"
                    f"    atelier stack start\n"
                    f"  Or just the frontend:\n"
                    f"    atelierd frontend-start\n\n"
                    f"  Then run: atelier dashboard open"
                )
                return
            _click.echo(f"  ◆ Opening Atelier dashboard: {url}")
            webbrowser.open(url)

        cli.add_command(dashboard_group)
        # Keep 'status' as a hidden alias for backward compatibility
        _h(admin_commands.status_cmd)
        cli.add_command(admin_commands.status_cmd)
    except (ModuleNotFoundError, ImportError):
        _IMPORT_FAILED = True

    try:
        import click as _click

        @_click.command("serve-openai")
        @_click.option(
            "--port", default=8790, show_default=True, help="Port to listen on (8787 is the Atelier service port)"
        )
        @_click.option(
            "--host",
            default="127.0.0.1",
            show_default=True,
            help="Bind address (default loopback-only; the gateway runs an auto-approving agent)",
        )
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
        _IMPORT_FAILED = True

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
        _IMPORT_FAILED = True

    try:
        from .project import project_cmd

        _h(project_cmd)
        cli.add_command(project_cmd, name="project")
    except ImportError:
        pass


_ZSH_COMPLETION = """
#compdef atelier
_atelier() {
    local -a commands
    commands=(
        'init:Initialize the runtime store'
        'update:Check for and apply updates'
        'mcp:Start the MCP server'
        'benchmark:Run Atelier benchmark suites'
        'savings:Show cost/savings summary'
        'recall:Recall across past sessions'
        'swarm:Coordinate isolated child attempts'
        'dashboard:Show runs dashboard and costs'
        'doctor:Run installation diagnostics'
        'code:Code index and retrieval'
        'service:Service management'
        'completions:Print shell completion script'
        'uninstall:Remove Atelier'
    )
    _describe 'atelier commands' commands
}
compdef _atelier atelier
"""

_BASH_COMPLETION = """
_atelier_completions() {
    local cur="${COMP_WORDS[COMP_CWORD]}"
    local commands="init update mcp benchmark savings recall swarm dashboard doctor code service completions uninstall --help --version"
    COMPREPLY=($(compgen -W "${commands}" -- "${cur}"))
}
complete -F _atelier_completions atelier
"""

_FISH_COMPLETION = """
complete -c atelier -f
complete -c atelier -n '__fish_use_subcommand' -a init -d 'Initialize the runtime store'
complete -c atelier -n '__fish_use_subcommand' -a update -d 'Check for and apply updates'
complete -c atelier -n '__fish_use_subcommand' -a mcp -d 'Start the MCP server'
complete -c atelier -n '__fish_use_subcommand' -a benchmark -d 'Run Atelier benchmark suites'
complete -c atelier -n '__fish_use_subcommand' -a savings -d 'Show cost/savings summary'
complete -c atelier -n '__fish_use_subcommand' -a recall -d 'Recall across past sessions'
complete -c atelier -n '__fish_use_subcommand' -a swarm -d 'Coordinate isolated child attempts'
complete -c atelier -n '__fish_use_subcommand' -a dashboard -d 'Show runs dashboard and costs'
complete -c atelier -n '__fish_use_subcommand' -a doctor -d 'Run installation diagnostics'
complete -c atelier -n '__fish_use_subcommand' -a code -d 'Code index and retrieval'
complete -c atelier -n '__fish_use_subcommand' -a service -d 'Service management'
complete -c atelier -n '__fish_use_subcommand' -a completions -d 'Print shell completion script'
complete -c atelier -n '__fish_use_subcommand' -a uninstall -d 'Remove Atelier'
"""
