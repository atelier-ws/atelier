from __future__ import annotations

import sqlite3
import shutil
import subprocess
from hashlib import sha256
from pathlib import Path
from typing import Any

import click

from atelier.gateway.cli.commands._shared import _emit
from atelier.gateway.integrations.openmemory_lifecycle import project_root as _project_root


@click.group("zoekt")
def zoekt_group() -> None:
    """Manage Zoekt local binaries and optional Docker sidecar."""


def _zoekt_workspace_prefix(repo_root: Path) -> str:
    return f"atelier-zoekt-{sha256(str(repo_root.resolve()).encode('utf-8')).hexdigest()[:12]}-"


def _zoekt_default_index_dir() -> Path:
    return Path.home() / ".zoekt"


def _zoekt_missing_local_binaries() -> list[str]:
    required = ("zoekt-git-index", "zoekt-index", "zoekt", "zoekt-webserver")
    return [name for name in required if shutil.which(name) is None]


def _zoekt_install_commands() -> tuple[str, ...]:
    return (
        "go install github.com/sourcegraph/zoekt/cmd/zoekt-git-index@latest",
        "go install github.com/sourcegraph/zoekt/cmd/zoekt-index@latest",
        "go install github.com/sourcegraph/zoekt/cmd/zoekt@latest",
        "go install github.com/sourcegraph/zoekt/cmd/zoekt-webserver@latest",
    )


@zoekt_group.command("install")
@click.option("--auto", is_flag=True, help="Run go install commands automatically.")
@click.option("--print-only", is_flag=True, help="Only print the install commands.")
def zoekt_install(auto: bool, print_only: bool) -> None:
    """Install/check local Zoekt binaries (native, no Docker)."""
    missing = _zoekt_missing_local_binaries()
    commands = _zoekt_install_commands()

    if not missing:
        click.echo("Zoekt local binaries are already installed.")
        return

    click.echo("Missing Zoekt binaries: " + ", ".join(missing))
    click.echo("Install with:")
    for command in commands:
        click.echo(f"  {command}")

    if print_only:
        return
    if not auto:
        raise click.ClickException("Install the commands above, or run: atelier zoekt install --auto")
    if shutil.which("go") is None:
        raise click.ClickException("Go is required for --auto install (go command not found on PATH)")

    for command in commands:
        subprocess.run(command.split(), check=True)

    missing_after = _zoekt_missing_local_binaries()
    if missing_after:
        raise click.ClickException("Zoekt install incomplete; still missing: " + ", ".join(missing_after))
    click.echo("Zoekt local binaries installed.")


@zoekt_group.command("index")
@click.argument(
    "target",
    type=click.Path(path_type=Path, exists=True, file_okay=False),
    default=".",
    required=False,
)
@click.option(
    "--index",
    "index_dir",
    type=click.Path(path_type=Path, file_okay=False),
    default=str(_zoekt_default_index_dir()),
    show_default=True,
)
def zoekt_index(target: Path, index_dir: Path) -> None:
    """Index a repository/directory into a local Zoekt index."""
    target = target.resolve()
    index_dir = index_dir.resolve()
    index_dir.mkdir(parents=True, exist_ok=True)

    git_index = shutil.which("zoekt-git-index")
    plain_index = shutil.which("zoekt-index")
    if git_index and (target / ".git").exists():
        cmd = [git_index, "-index", str(index_dir), str(target)]
    elif plain_index:
        cmd = [plain_index, "-index", str(index_dir), str(target)]
    elif git_index:
        cmd = [git_index, "-index", str(index_dir), str(target)]
    else:
        raise click.ClickException("Zoekt index binaries not found. Run: atelier zoekt install")

    subprocess.run(cmd, check=True)
    click.echo(f"Zoekt index updated at {index_dir}")


@zoekt_group.command("search")
@click.argument("query", nargs=-1, required=True)
@click.option(
    "--index",
    "index_dir",
    type=click.Path(path_type=Path, file_okay=False),
    default=str(_zoekt_default_index_dir()),
    show_default=True,
)
def zoekt_search(query: tuple[str, ...], index_dir: Path) -> None:
    """Search the local Zoekt index from CLI."""
    zoekt_bin = shutil.which("zoekt")
    if zoekt_bin is None:
        raise click.ClickException("zoekt binary not found. Run: atelier zoekt install")
    q = " ".join(query).strip()
    if not q:
        raise click.ClickException("query cannot be empty")
    result = subprocess.run([zoekt_bin, "-index", str(index_dir.resolve()), q], check=False)
    if result.returncode not in (0, 1):
        raise click.ClickException(f"zoekt search failed (exit {result.returncode})")


@zoekt_group.command("serve")
@click.option(
    "--index",
    "index_dir",
    type=click.Path(path_type=Path, file_okay=False),
    default=str(_zoekt_default_index_dir()),
    show_default=True,
)
@click.option("--host", default="127.0.0.1", show_default=True)
@click.option("--port", default=6070, show_default=True, type=int)
def zoekt_serve(index_dir: Path, host: str, port: int) -> None:
    """Run local Zoekt web/API server against the local index."""
    webserver_bin = shutil.which("zoekt-webserver")
    if webserver_bin is None:
        raise click.ClickException("zoekt-webserver binary not found. Run: atelier zoekt install")
    subprocess.run(
        [webserver_bin, "-index", str(index_dir.resolve()), "-listen", f"{host}:{port}"],
        check=True,
    )


@zoekt_group.command("up")
@click.pass_context
def zoekt_up(ctx: click.Context) -> None:
    """Start the persistent Zoekt search container for the current repo."""
    from atelier.infra.code_intel.zoekt.binary import discover_zoekt_binary
    from atelier.infra.code_intel.zoekt.server import get_zoekt_server

    repo_root = Path(_project_root())
    resolution = discover_zoekt_binary(repo_root)
    if not resolution.available:
        raise click.ClickException(f"Zoekt runtime unavailable: {resolution.reason}")
    server = get_zoekt_server(repo_root, resolution=resolution)
    handle = server.ensure_started()
    click.echo(f"Zoekt started: {handle}")


@zoekt_group.command("down")
@click.pass_context
def zoekt_down(ctx: click.Context) -> None:
    """Stop the persistent Zoekt container for the current repo."""
    from atelier.infra.code_intel.zoekt.server import get_zoekt_server

    repo_root = Path(_project_root())
    server = get_zoekt_server(repo_root)
    server.stop()
    click.echo("Zoekt stopped.")


@zoekt_group.command("status")
@click.option(
    "--index",
    "index_dir",
    type=click.Path(path_type=Path, file_okay=False),
    default=str(_zoekt_default_index_dir()),
    show_default=True,
)
@click.pass_context
def zoekt_status(ctx: click.Context, index_dir: Path) -> None:
    """Show local Zoekt status (and Docker sidecar status if present)."""
    missing = _zoekt_missing_local_binaries()
    if missing:
        click.echo("Local Zoekt binaries: missing -> " + ", ".join(missing))
        click.echo("Install with: atelier zoekt install")
    else:
        click.echo("Local Zoekt binaries: installed")
    resolved_index = index_dir.resolve()
    click.echo(f"Local index dir: {resolved_index} ({'exists' if resolved_index.exists() else 'missing'})")

    repo_root = Path(_project_root())
    prefix = _zoekt_workspace_prefix(repo_root)
    if shutil.which("docker") is None:
        return
    click.echo("")
    click.echo("Docker sidecar containers (optional):")
    subprocess.run(["docker", "ps", "-a", "--filter", f"name={prefix}"], check=False)


@zoekt_group.command("reindex")
@click.option(
    "--index",
    "index_dir",
    type=click.Path(path_type=Path, file_okay=False),
    default=str(_zoekt_default_index_dir()),
    show_default=True,
)
@click.pass_context
def zoekt_reindex(ctx: click.Context, index_dir: Path) -> None:
    """Reindex current repository into local Zoekt index."""
    target = Path(_project_root())
    ctx.invoke(zoekt_index, target=target, index_dir=index_dir)


@zoekt_group.command("reset")
@click.option("--yes", is_flag=True, help="Confirm removal of Zoekt runtime data.")
@click.pass_context
def zoekt_reset(ctx: click.Context, yes: bool) -> None:
    """Stop Zoekt and remove runtime state for this repository."""
    if not yes:
        raise click.ClickException("Pass --yes to confirm index cleanup.")
    repo_root = Path(_project_root())
    prefix = _zoekt_workspace_prefix(repo_root)
    result = subprocess.run(
        ["docker", "ps", "-aq", "--filter", f"name={prefix}"],
        capture_output=True,
        text=True,
        check=False,
    )
    container_ids = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if container_ids:
        subprocess.run(["docker", "rm", "-f", *container_ids], check=False)
    from atelier.core.foundation.paths import default_store_root

    workspace_hash = sha256(str(repo_root.resolve()).encode("utf-8")).hexdigest()[:12]
    runtime_root = default_store_root() / "workspaces" / workspace_hash / "zoekt"
    shutil.rmtree(runtime_root, ignore_errors=True)
    click.echo("Zoekt state removed.")


def _code_context_engine(repo_root: str) -> Any:
    from atelier.core.capabilities.code_context import CodeContextEngine

    # One-shot CLI commands don't need background autosync threads
    return CodeContextEngine(repo_root, autosync_enabled=False)


def _index_repo_with_progress(
    engine: Any,
    *,
    force: bool = False,
    include_globs: list[str] | None = None,
    exclude_globs: list[str] | None = None,
    description: str = "Indexing code",
    success_description: str | None = None,
    frame_prefix: str = "",
) -> dict[str, Any]:
    try:
        from rich.console import Console
        from rich.progress import (
            BarColumn,
            Progress,
            TextColumn,
            TimeRemainingColumn,
        )

        prefix_markup = f"[dim]{frame_prefix}[/dim]" if frame_prefix else ""
        console = Console(stderr=True)
        progress = Progress(
            TextColumn(f"{prefix_markup}{{task.description}}"),
            BarColumn(
                bar_width=32,
                style="bright_black",
                complete_style="cyan",
                finished_style="green",
                pulse_style="magenta",
            ),
            TextColumn("[bold cyan]{task.percentage:3.0f}%[/bold cyan]"),
            TimeRemainingColumn(),
            console=console,
            transient=False,
        )
        with progress:
            task_id = progress.add_task("[yellow]⏳[/yellow]  Acquiring index lock...", total=None)
            _phase: list[str] = ["lock"]  # list hack for nonlocal assignment
            _last_total: list[int] = [0]

            def _on_progress(current: int, total: int) -> None:
                # Transition: lock -> discovery -> indexing
                # When discovery sends (0, total), we transition to discovery phase
                if current == 0 and total > 0 and _phase[0] == "lock":
                    _phase[0] = "discovery"
                # Transition from discovery -> indexing when total drops
                # (raw git entries -> filtered file count).
                if total and total < _last_total[0] and _phase[0] == "discovery":
                    _phase[0] = "indexing"
                
                if _phase[0] == "lock":
                    progress.update(
                        task_id,
                        description=f"[yellow]⏳[/yellow]  Acquiring index lock...",
                    )
                elif _phase[0] == "discovery":
                    if total:
                        progress.update(
                            task_id,
                            description=f"[green]\u27f3[/green]  Discovering files...  ({current}/{total})",
                        )
                    else:
                        progress.update(
                            task_id,
                            description=f"[green]\u27f3[/green]  Discovering files...  ({current})",
                        )
                else:
                    progress.update(
                        task_id,
                        completed=current,
                        total=total,
                        description=f"[green]\u27f3[/green]  {description}  ({current}/{total})",
                    )
                _last_total[0] = total

            payload = engine.index_repo(
                force=force,
                include_globs=include_globs,
                exclude_globs=exclude_globs,
                progress_callback=_on_progress,
            ).model_dump(mode="json")
            progress.update(
                task_id,
                total=100,
                completed=100,
                description=f"[green]✓[/green]  {success_description or description}",
            )
            return payload
    except ImportError:
        return engine.index_repo(
            force=force,
            include_globs=include_globs,
            exclude_globs=exclude_globs,
        ).model_dump(mode="json")


def _index_git_history_with_progress(engine: Any, frame_prefix: str = "") -> dict[str, int] | None:
    try:
        from rich.console import Console
        from rich.progress import Progress, TextColumn, BarColumn

        adapter = engine._deleted_history_adapter()
        current_head = adapter._current_head()
        if current_head is None:
            return None

        import sqlite3
        from contextlib import closing
        with closing(adapter._connection_factory()) as conn:
            row = conn.execute("SELECT value FROM engine_state WHERE key = ?", (adapter._head_state_key,)).fetchone()
            previous_head = str(row["value"]) if row is not None else None
            count_row = conn.execute("SELECT COUNT(*) AS n FROM symbol_graveyard").fetchone()
            graveyard_count = int(count_row["n"]) if count_row is not None else 0

        if previous_head == current_head and graveyard_count > 0:
            return None

        prefix_markup = f"[dim]{frame_prefix}[/dim]" if frame_prefix else ""
        console = Console(stderr=True)
        progress = Progress(
            TextColumn(f"{prefix_markup}{{task.description}}"),
            BarColumn(
                bar_width=32,
                style="bright_black",
                complete_style="cyan",
                finished_style="green",
                pulse_style="magenta",
            ),
            console=console,
            transient=False,
        )
        with progress:
            task_id = progress.add_task("[green]⟳[/green]  Indexing Git history...", total=None)
            
            def on_commit(current: int, total: int) -> None:
                progress.update(
                    task_id,
                    total=total,
                    completed=current,
                    description=f"[cyan]⟳[/cyan]  Indexing Git history... {current}/{total}",
                )
            
            summary = adapter._ensure_history_ready(on_commit=on_commit)
            progress.update(
                task_id,
                total=100,
                completed=100,
                description="[green]✓[/green]  Indexed Git history",
            )
            return summary
    except Exception:
        try:
            engine._deleted_history_adapter()._ensure_history_ready()
        except Exception:
            pass
        return None


def _prewarm_embeddings_with_progress(engine: Any, frame_prefix: str = "") -> None:
    try:
        from rich.console import Console
        from rich.progress import Progress, TextColumn, BarColumn

        if not engine._semantic_ranker.available:
            return

        embedder = engine._semantic_ranker.embedder
        embedding_dim = embedder.dim
        if embedding_dim <= 0:
            return

        index_version = engine._current_index_version()
        candidates = engine._semantic_symbol_candidates(limit=2000)
        if not candidates:
            return

        import sqlite3
        from contextlib import closing
        with closing(engine._connect()) as conn:
            engine._init_schema(conn)
            fresh_ids = engine._ann_symbol_index.existing_stamped_ids(
                conn,
                embedder_name=embedder.name,
                embedding_dim=embedding_dim,
                index_version=index_version,
            )

        to_embed = [c for c in candidates if c.symbol_id not in fresh_ids]
        if not to_embed:
            return

        prefix_markup = f"[dim]{frame_prefix}[/dim]" if frame_prefix else ""
        console = Console(stderr=True)
        progress = Progress(
            TextColumn(f"{prefix_markup}{{task.description}}"),
            BarColumn(
                bar_width=32,
                style="bright_black",
                complete_style="cyan",
                finished_style="green",
            ),
            console=console,
            transient=False,
        )
        with progress:
            task_id = progress.add_task(
                f"[green]⟳[/green]  Pre-warming symbol embeddings... (0/{len(to_embed)})",
                total=len(to_embed),
            )
            with closing(engine._connect()) as conn:
                engine._init_schema(conn)
                new_vectors = {}
                for i, symbol in enumerate(to_embed, start=1):
                    source_text = engine._read_file_slice(symbol.file_path, symbol.start_byte, symbol.end_byte)
                    vector = engine._semantic_ranker.embed_symbol(symbol, source_text=source_text)
                    if vector and len(vector) == embedding_dim:
                        new_vectors[symbol.symbol_id] = (symbol.content_hash, vector)
                    progress.update(
                        task_id,
                        completed=i,
                        description=f"[green]⟳[/green]  Pre-warming symbol embeddings... ({i}/{len(to_embed)})",
                    )
                if new_vectors:
                    engine._ann_symbol_index.upsert_vectors(
                        conn,
                        embedder_name=embedder.name,
                        embedding_dim=embedding_dim,
                        index_version=index_version,
                        vectors=new_vectors,
                    )
            progress.update(
                task_id,
                description="[green]✓[/green]  Pre-warmed symbol embeddings",
            )
    except Exception:
        try:
            engine._prewarm_symbol_embeddings()
        except Exception:
            pass


@click.group("code")
def code_group() -> None:
    """Code context indexing, retrieval, repo maps, and impact analysis."""


@code_group.command("index")
@click.option("--repo-root", default=".", show_default=True)
@click.option("--include", "include_globs", multiple=True)
@click.option("--exclude", "exclude_globs", multiple=True)
@click.option("--reindex", is_flag=True, help="Full rebuild from scratch (default: incremental).")
@click.option("--json", "as_json", is_flag=True)
@click.option("--frame-prefix", default="", hidden=True, help="Prefix for progress output (used by dev.sh)")
def code_index_cmd(
    repo_root: str,
    include_globs: tuple[str, ...],
    exclude_globs: tuple[str, ...],
    reindex: bool,
    as_json: bool,
    frame_prefix: str,
) -> None:
    """Index a repository into the SQLite FTS5 symbol store.

    Incremental by default (only re-indexes changed files). Use --reindex
    for a full rebuild from scratch.
    """
    engine = _code_context_engine(repo_root)
    force = reindex
    if as_json:
        payload = engine.index_repo(
            force=force,
            include_globs=list(include_globs) or None,
            exclude_globs=list(exclude_globs) or None,
        ).model_dump(mode="json")
        try:
            engine._deleted_history_adapter()._ensure_history_ready()
            engine._prewarm_symbol_embeddings()
        except Exception:
            pass
        _emit(payload, as_json=True)
        return

    payload = _index_repo_with_progress(
        engine,
        force=force,
        include_globs=list(include_globs) or None,
        exclude_globs=list(exclude_globs) or None,
        description="Indexing code",
        success_description="Indexed code",
     frame_prefix=frame_prefix,
    )

    git_summary = _index_git_history_with_progress(engine, frame_prefix=frame_prefix)
    _prewarm_embeddings_with_progress(engine, frame_prefix=frame_prefix)

    stats_line = (
        f"{click.style('✓', fg='green')}  Indexed {payload['files_indexed']} files, {payload['symbols_indexed']} "
        f"symbols ({payload['imports_indexed']} imports)"
    )
    prefix_markup = click.style(frame_prefix, dim=True) if frame_prefix else ""
    click.echo(f"{prefix_markup}{stats_line}" if frame_prefix else stats_line)
    
    # Print git history summary if any commits were processed
    if git_summary and git_summary.get("commits_walked", 0) > 0:
        git_line = (
            f"{click.style('✓', fg='green')}  Indexed Git history: "
            f"{git_summary['commits_walked']} commits, {git_summary['symbols_found']} deleted/renamed symbols "
            f"({git_summary['deletions_found']} deletions, {git_summary['renames_found']} renames)"
        )
        click.echo(f"{prefix_markup}{git_line}" if frame_prefix else git_line)
    
    _print_index_stats(engine.db_path, frame_prefix=frame_prefix)


def _print_index_stats(db_path: str, frame_prefix: str = "") -> None:
    """Print language and symbol-kind breakdown after indexing."""
    import sqlite3
    from pathlib import Path

    if not Path(db_path).exists():
        return
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # Language breakdown
    rows = c.execute(
        "SELECT f.language, COUNT(DISTINCT f.file_path), COUNT(s.symbol_id) "
        "FROM files f LEFT JOIN symbols s ON s.repo_id = f.repo_id AND s.file_path = f.file_path "
        "GROUP BY f.language ORDER BY COUNT(DISTINCT f.file_path) DESC"
    ).fetchall()

    total_f = 0
    total_s = 0
    for _, fls, syms in rows:
        total_f += fls
        total_s += syms

    # Symbol kinds (top ones)
    kinds = c.execute(
        "SELECT kind, COUNT(*) FROM symbols GROUP BY kind ORDER BY COUNT(*) DESC"
    ).fetchall()

    prefix_markup = click.style(frame_prefix, dim=True) if frame_prefix else ""

    try:
        from rich.console import Console
        from rich.table import Table
        from rich import box

        console = Console()

        def print_prefixed(renderable) -> None:
            # Capture what rich would print, then write it with the prefix
            with console.capture() as cap:
                console.print(renderable)
            text = cap.get()
            lines = text.split("\n")
            if lines and lines[-1] == "":
                lines.pop()
            for line in lines:
                if line.strip():
                    click.echo(f"{prefix_markup}  {line}")
                else:
                    click.echo(f"{prefix_markup}")

        # Language breakdown
        print_prefixed("")
        print_prefixed("[bold bright_white]Language breakdown[/]  [dim]by files and symbols[/]")

        lang_table = Table(
            box=box.SIMPLE,
            show_header=True,
            header_style="dim",
            padding=(0, 1),
            show_footer=True,
        )
        lang_table.add_column("Language", style="bold", min_width=15, footer="TOTAL")
        lang_table.add_column("Files", justify="right", footer=f"{total_f:,}")
        lang_table.add_column("Symbols", justify="right", footer=f"{total_s:,}")

        lang_styles = {
            "python": ("Python", "bright_yellow"),
            "typescript": ("TypeScript", "bright_cyan"),
            "javascript": ("JavaScript", "yellow"),
            "rust": ("Rust", "red"),
            "go": ("Go", "cyan"),
            "swift": ("Swift", "orange3"),
            "kotlin": ("Kotlin", "bright_magenta"),
            "java": ("Java", "bright_blue"),
            "c/c++": ("C/C++", "blue"),
            "cpp": ("C++", "blue"),
            "c": ("C", "blue"),
            "csharp": ("C#", "bright_green"),
            "ruby": ("Ruby", "red"),
            "php": ("PHP", "magenta"),
            "scala": ("Scala", "bright_red"),
            "bash": ("Shell", "green"),
            "shell": ("Shell", "green"),
            "html": ("HTML", "orange1"),
            "css": ("CSS", "bright_blue"),
            "toml": ("TOML", "dim white"),
            "yaml": ("YAML", "dim white"),
            "json": ("JSON", "dim white"),
            "markdown": ("Markdown", "dim white"),
            "sql": ("SQL", "dim white"),
            "astro": ("Astro", "bright_cyan"),
        }

        for lang, fls, syms in rows:
            if lang in lang_styles:
                display_name, color = lang_styles[lang]
            else:
                display_name = lang.title() if lang else "Unknown"
                color = "white"
            lang_table.add_row(f"[{color}]{display_name}[/]", f"{fls:,}", f"{syms:,}")

        print_prefixed(lang_table)

        # Symbol kinds
        if kinds:
            print_prefixed("")
            print_prefixed("[bold bright_white]Symbol kinds[/]  [dim]top kinds by count[/]")

            kind_table = Table(
                box=box.SIMPLE,
                show_header=True,
                header_style="dim",
                padding=(0, 1),
                show_footer=True,
            )
            kind_table.add_column("Symbol Kind", style="bold", min_width=20, footer="TOTAL")
            kind_table.add_column("Count", justify="right", footer=f"{sum(cnt for _, cnt in kinds):,}")

            kind_styles = {
                "class": "bright_blue",
                "interface": "bright_blue",
                "struct": "bright_blue",
                "method": "bright_cyan",
                "function": "cyan",
                "async_function": "cyan",
                "variable": "white",
                "heading": "dim white",
                "type": "bright_green",
                "module": "bright_magenta",
                "import": "dim white",
            }

            for kind, cnt in kinds:
                display_kind = kind.replace("_", " ").title() if kind else "Unknown"
                color = kind_styles.get(kind, "white")
                kind_table.add_row(f"[{color}]{display_kind}[/]", f"{cnt:,}")

            print_prefixed(kind_table)

    except ImportError:
        # Fallback to simple prints if rich is not available, but with prefix support
        click.echo(f"{prefix_markup}")
        click.echo(f"{prefix_markup}  ── Language breakdown ──")
        click.echo(f"{prefix_markup}  {'Language':<15s}  {'Files':>5s}  {'Symbols':>7s}")
        click.echo(f"{prefix_markup}  " + "-" * 35)
        for lang, fls, syms in rows:
            click.echo(f"{prefix_markup}  {lang:<15s}  {fls:>5d}  {syms:>7d}")
        click.echo(f"{prefix_markup}  " + "-" * 35)
        click.echo(f"{prefix_markup}  {'TOTAL':<15s}  {total_f:>5d}  {total_s:>7d}")

        if kinds:
            click.echo(f"{prefix_markup}")
            click.echo(f"{prefix_markup}  ── Symbol kinds ──")
            click.echo(f"{prefix_markup}  {'Kind':<20s}  {'Count':>7s}")
            click.echo(f"{prefix_markup}  " + "-" * 29)
            for kind, cnt in kinds:
                click.echo(f"{prefix_markup}  {kind:<20s}  {cnt:>7d}")

    conn.close()


__all__ = ["_code_context_engine", "_index_repo_with_progress", "code_group", "zoekt_group"]
