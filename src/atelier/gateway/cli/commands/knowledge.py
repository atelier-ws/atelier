"""``atelier knowledge`` — local review knowledge base (extract + view)."""

from __future__ import annotations

import os

import click

from atelier.gateway.cli.commands._shared import _emit


@click.group("knowledge")
def knowledge_group() -> None:
    """Local review knowledge base: distil rules from .lessons; view the overlay."""


@knowledge_group.command("extract")
@click.option(
    "--host",
    default="auto",
    show_default=True,
    type=click.Choice(["auto", "claude", "codex", "ollama"]),
    help="Model backend: auto (Atelier owned routing) or a host CLI.",
)
@click.option("--model", default="", help="Model id (required for ollama; optional elsewhere).")
@click.option("--max-items", type=int, default=20, show_default=True, help="Max .lessons blocks to read.")
@click.option(
    "--max-spend",
    "max_spend",
    type=float,
    default=0.50,
    show_default=True,
    help="Hard USD cap; aborts if the estimate exceeds it.",
)
@click.option("--dry-run", is_flag=True, help="Show rules without writing the overlay.")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def knowledge_extract_cmd(
    ctx: click.Context,
    host: str,
    model: str,
    max_items: int,
    max_spend: float,
    dry_run: bool,
    as_json: bool,
) -> None:
    """Distil durable review rules from .lessons into the review overlay."""
    from atelier.core.capabilities.knowledge_extract import extract_rules

    repo_root = os.environ.get("CLAUDE_WORKSPACE_ROOT", os.getcwd())
    result = extract_rules(
        ctx.obj["root"],
        repo_root,
        host=host,
        model=model,
        max_items=max_items,
        max_spend_usd=max_spend,
        dry_run=dry_run,
    )
    if as_json:
        _emit(result, as_json=True)
        return
    if result.get("error"):
        raise click.ClickException(str(result["error"]))
    if result.get("reason"):
        click.echo(result["reason"])
        return
    rules = result["rules"]
    click.echo(
        f"Extracted {len(rules)} rule(s) from {result['sources']} lessons "
        f"(host={result['host']}, est ${result['estimated_cost_usd']})."
    )
    for rule in rules:
        click.echo(f"  - {rule}")
    if dry_run:
        click.echo("(dry run — overlay not modified)")
    else:
        click.echo(f"Applied {result['applied']} new rule(s) to review_overlay.json.")


@knowledge_group.command("show")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def knowledge_show_cmd(ctx: click.Context, as_json: bool) -> None:
    """Show the current review overlay (notes / boost / suppress)."""
    from atelier.core.capabilities.live_reviewer.knowledge import load_overlay

    overlay = load_overlay(ctx.obj["root"])
    if as_json:
        _emit(overlay, as_json=True)
        return
    for key in ("notes", "boost", "suppress"):
        values = overlay.get(key) or []
        click.echo(f"{key} ({len(values)}):")
        for value in values:
            click.echo(f"  - {value}")
