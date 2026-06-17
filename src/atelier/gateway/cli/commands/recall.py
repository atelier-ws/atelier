"""``atelier recall`` — semantic recall over ALL past sessions."""

from __future__ import annotations

import click

from atelier.gateway.cli.commands._shared import _emit


@click.group("recall")
def recall_group() -> None:
    """Index past sessions and semantically recall across all of them."""


@recall_group.command("index")
@click.option(
    "--window-days", type=int, default=30, show_default=True, help="Only index sessions modified within N days."
)
@click.option("--max-sessions", type=int, default=80, show_default=True)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def recall_index_cmd(ctx: click.Context, window_days: int, max_sessions: int, as_json: bool) -> None:
    """Incrementally index past session transcripts for recall."""
    from atelier.core.capabilities.session_recall import index_sessions

    result = index_sessions(ctx.obj["root"], window_days=window_days, max_sessions=max_sessions)
    if as_json:
        _emit(result, as_json=True)
        return
    click.echo(
        f"Indexed {result['indexed']} snippet(s) from {result['sessions']} session(s) ({result['skipped']} unchanged)."
    )


@recall_group.command("search")
@click.argument("query")
@click.option("--top-k", type=int, default=10, show_default=True)
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def recall_search_cmd(ctx: click.Context, query: str, top_k: int, as_json: bool) -> None:
    """Semantically search across all indexed sessions."""
    from atelier.core.capabilities.session_recall import recall

    results = recall(ctx.obj["root"], query, top_k=top_k)
    if as_json:
        _emit(results, as_json=True)
        return
    if not results:
        click.echo("No matches yet — run `atelier recall index` first, or try a different query.")
        return
    for item in results:
        click.echo(f"· [{item['session']}] {item['text'][:200]}")


@recall_group.command("config")
@click.option("--auto-index/--no-auto-index", default=None, help="Enable the SessionStart background indexer.")
@click.option(
    "--embedder", type=click.Choice(["local", "openai", "ollama"]), default=None, help="Embedder for indexing."
)
@click.option("--embed-model", default=None, help="Embedder model (e.g. an Ollama model name).")
@click.option("--json", "as_json", is_flag=True)
@click.pass_context
def recall_config_cmd(
    ctx: click.Context,
    auto_index: bool | None,
    embedder: str | None,
    embed_model: str | None,
    as_json: bool,
) -> None:
    """Persist Recall settings (auto-index + embedder) to plugin_settings.json."""
    from atelier.core.capabilities.plugin_runtime import set_recall_settings

    updated = set_recall_settings(ctx.obj["root"], auto_index=auto_index, embedder=embedder, embed_model=embed_model)
    summary = {
        "recallAutoIndex": updated.get("recallAutoIndex", True),
        "recallEmbedder": updated.get("recallEmbedder", "local"),
        "recallEmbedModel": updated.get("recallEmbedModel", ""),
    }
    if as_json:
        _emit(summary, as_json=True)
        return
    click.echo(
        f"Recall: auto-index={summary['recallAutoIndex']} "
        f"embedder={summary['recallEmbedder']} model={summary['recallEmbedModel'] or '(default)'}"
    )
