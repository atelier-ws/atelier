from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import click

from atelier.gateway.cli.commands._shared import _emit

if TYPE_CHECKING:
    from atelier.core.capabilities.owned_agent_session import OwnedAgentSession


def _root_from_obj(obj: dict[str, Any]) -> Path:
    if isinstance(obj, dict):
        root = obj.get("root")
        if isinstance(root, Path):
            return root
    return Path.home() / ".atelier"


def _run_owned_session(
    task: str,
    *,
    provider: str,
    model: str,
    budget: str,
    cache_policy: str,
    phase_linear: bool,
    max_cost: float | None,
    yolo: bool,
    dry_run: bool,
    root: Path,
) -> None:
    from atelier.core.capabilities.cross_vendor_routing.configuration import (
        detect_api_key_vendors,
    )
    from atelier.core.capabilities.cross_vendor_routing.router import NoFeasibleRouteError
    from atelier.core.capabilities.owned_agent_session import (
        KeepaliveThread,
        OwnedAgentSession,
        run_phase_linear,
        run_single_shot,
    )
    from atelier.core.capabilities.owned_execution_routing import (
        OwnedCachePolicy,
        OwnedRouteBudget,
        OwnedRouteRequest,
        select_owned_route,
    )

    # Credential check — fail fast with actionable message
    vendors = detect_api_key_vendors()
    if not vendors:
        click.echo(
            "Error: No API key found.\n\n"
            "Set one of the following environment variables (or add to .env):\n"
            "  ANTHROPIC_API_KEY   — for Anthropic / Claude models\n"
            "  OPENAI_API_KEY      — for OpenAI models\n"
            "  GOOGLE_API_KEY      — for Google / Gemini models\n",
            err=True,
        )
        sys.exit(1)

    budget_cast: OwnedRouteBudget = (
        budget if budget in ("cheap", "balanced", "best") else "balanced"  # type: ignore[assignment]
    )
    cache_policy_cast: OwnedCachePolicy = "fresh" if cache_policy == "fresh" else "inherit"

    try:
        decision = select_owned_route(
            root,
            OwnedRouteRequest(
                tool_name="run",
                task_text=task,
                mode="explicit" if (provider or model) else "auto",
                budget=budget_cast,
                provider=provider,
                model=model,
                cache_policy=cache_policy_cast,
            ),
        )
    except NoFeasibleRouteError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    session = OwnedAgentSession.new(
        provider=decision.provider,
        model=decision.model,
        transport=decision.transport,
        cache_policy=cache_policy_cast,
        phase_linear=phase_linear,
    )

    click.echo(f"[atelier run] session={session.session_id}  " f"provider={decision.provider}  model={decision.model}")
    if dry_run:
        click.echo("[atelier run] --dry-run: planning only, no edits will be applied")

    keepalive: KeepaliveThread | None = None
    if not dry_run:
        keepalive = KeepaliveThread(model=decision.model)
        keepalive.start()

    try:
        if phase_linear:
            receipt = run_phase_linear(session, task, dry_run=dry_run)
        else:
            receipt = run_single_shot(session, task, dry_run=dry_run)
    finally:
        if keepalive is not None:
            keepalive.stop()

    # Cost guardrail check (post-hoc for now; pre-hoc requires token estimation)
    if max_cost is not None and receipt.cost_usd() > max_cost:
        click.echo(
            f"\nWarning: session cost ${receipt.cost_usd():.4f} " f"exceeded --max-cost ${max_cost:.4f}",
            err=True,
        )

    session_path = session.save()
    click.echo(f"\nSession saved: {session_path}")
    click.echo("")
    click.echo(receipt.format_receipt())


@click.group("run")
def run_group() -> None:
    """Run an owned coding session on your own API credentials."""


@run_group.command("start", context_settings={"ignore_unknown_options": False})
@click.argument("task")
@click.option("--provider", default="", help="Provider: anthropic, openai, google")
@click.option("--model", default="", help="Explicit model name")
@click.option(
    "--budget",
    type=click.Choice(["cheap", "balanced", "best"]),
    default="balanced",
    show_default=True,
)
@click.option(
    "--cache-policy",
    type=click.Choice(["inherit", "fresh"]),
    default="inherit",
    show_default=True,
)
@click.option(
    "--phase-linear/--no-phase-linear",
    default=True,
    show_default=True,
    help="Survey→Plan→Implement in one conversation",
)
@click.option("--max-cost", type=float, default=None, help="Abort if cost exceeds this USD amount")
@click.option("--yolo", is_flag=True, default=False, help="Skip edit-approval prompts")
@click.option("--dry-run", is_flag=True, default=False, help="Preview plan without applying edits")
@click.pass_obj
def run_start(
    obj: dict[str, Any],
    task: str,
    provider: str,
    model: str,
    budget: str,
    cache_policy: str,
    phase_linear: bool,
    max_cost: float | None,
    yolo: bool,
    dry_run: bool,
) -> None:
    """Run an owned coding session. TASK is the coding task description."""
    root = _root_from_obj(obj)
    _run_owned_session(
        task,
        provider=provider,
        model=model,
        budget=budget,
        cache_policy=cache_policy,
        phase_linear=phase_linear,
        max_cost=max_cost,
        yolo=yolo,
        dry_run=dry_run,
        root=root,
    )


@run_group.command("resume")
@click.argument("session_id")
@click.option("--task", default="", help="Additional task to continue with")
@click.pass_obj
def run_resume(obj: dict[str, Any], session_id: str, task: str) -> None:
    """Resume a session with its warm prefix intact."""
    from atelier.core.capabilities.owned_agent_session import (
        OwnedAgentSession,
        run_phase_linear,
    )

    root = _root_from_obj(obj)

    try:
        session = OwnedAgentSession.load(session_id, root=root)
    except FileNotFoundError:
        click.echo(f"Error: session {session_id!r} not found in {root / 'runs'}", err=True)
        sys.exit(1)

    click.echo(
        f"[atelier run resume] session={session.session_id}  " f"provider={session.provider}  model={session.model}"
    )
    click.echo(f"  Restoring {len(session.messages)} turns from previous session")

    if not task:
        click.echo("No --task provided; displaying saved receipt.")
        _print_receipt_from_session(session)
        return

    receipt = run_phase_linear(session, task)
    session.save(root=root)
    click.echo(receipt.format_receipt())


@run_group.command("report")
@click.argument("session_id")
@click.option("--json", "as_json", is_flag=True)
@click.pass_obj
def run_report(obj: dict[str, Any], session_id: str, as_json: bool) -> None:
    """Display the cache-economics receipt for a past session."""
    from atelier.core.capabilities.owned_agent_session import OwnedAgentSession
    from atelier.core.capabilities.owned_agent_session.receipt import SessionReceipt

    root = _root_from_obj(obj)

    try:
        session = OwnedAgentSession.load(session_id, root=root)
    except FileNotFoundError:
        click.echo(f"Error: session {session_id!r} not found in {root / 'runs'}", err=True)
        sys.exit(1)

    # Reconstruct a receipt from saved session metadata
    receipt = SessionReceipt(
        session_id=session.session_id,
        provider=session.provider,
        model=session.model,
    )

    if as_json:
        _emit(receipt.to_dict(), as_json=True)
    else:
        click.echo(receipt.format_receipt())


def _print_receipt_from_session(session: OwnedAgentSession) -> None:
    from atelier.core.capabilities.owned_agent_session.receipt import SessionReceipt

    receipt = SessionReceipt(
        session_id=session.session_id,
        provider=session.provider,
        model=session.model,
    )
    click.echo(receipt.format_receipt())


__all__ = ["run_group"]
