from __future__ import annotations

import os
from pathlib import Path

import click


@click.group(name="eval")
def eval_() -> None:
    """Evaluation case management."""


@eval_.command("mcp")
@click.option("--out", type=click.Path(path_type=Path, file_okay=False), default=None)
@click.option(
    "--tool",
    "tools",
    multiple=True,
    metavar="NAME",
    help="Run only the named tool suite(s), e.g. --tool node --tool read. "
    "Repeatable or comma-separated; use 'code' for all code-intel tools. Default: all tools.",
)
@click.option(
    "--jobs",
    type=int,
    default=0,
    show_default="auto",
    help="Parallel suite shards. Use 0 to auto-size.",
)
def eval_mcp(out: Path | None, tools: tuple[str, ...], jobs: int) -> None:
    """No LLM: Runs the public MCP tool benchmark suite and write results."""
    from atelier.gateway.cli.commands import benchmark as _bm

    repo_root = Path.cwd().resolve()
    suite_filter = _bm._mcp_suite_filter(tools)
    if suite_filter is not None:
        _bm._validate_mcp_suites(suite_filter, repo_root=repo_root)
    run_dir = _bm._run_dir("mcp", out)
    workspace_dir = _bm._workspace_dir("mcp", repo_root=repo_root, run_id=run_dir.name)
    resolved_jobs = _bm._resolve_mcp_jobs(jobs, repo_root=repo_root, suite_names=suite_filter)
    from atelier.gateway.cli.progress import ProgressReporter

    progress = ProgressReporter("mcp", total=1)
    progress.start("starting benchmark", current=f"reports {run_dir} | jobs {resolved_jobs}")
    bench_root = _bm._bench_source_root()
    cmd = [
        *_bm._python_cmd(bench_root),
        "-m",
        "benchmarks.mcp_tools.export_public_mcp_csv",
        "--artifact-root",
        str(workspace_dir),
        "--csv-out",
        str(run_dir / "results.csv"),
        "--jobs",
        str(resolved_jobs),
    ]
    if suite_filter is not None:
        cmd += ["--suites", ",".join(suite_filter)]
    _bm._run(cmd, cwd=bench_root, label="MCP benchmark")
    progress.step("benchmark command complete", current="public MCP tools")
    progress.finish("benchmark complete")
    click.echo(f"Results: {run_dir}")


_RETRIEVAL_CHANNELS = ["lexical", "zoekt", "semantic", "cg", "lexical+zoekt"]


def _make_golds(pairs: Path | None) -> list[Path]:
    return (
        [pairs]
        if pairs is not None
        else [
            Path("benchmarks/codebench/data/bench_pairs_def_gold.json"),
            Path("benchmarks/codebench/data/bench_pairs_content_gold.json"),
        ]
    )


def _channel_cmd_env(
    channel: str,
    *,
    full: bool,
    sample: int,
    repo: str,
    workers: int,
    pairs: Path | None,
    python_bin: str,
    reindex: bool,
) -> tuple[list[str], dict[str, str], list[Path]]:
    import os
    import sys

    golds = _make_golds(pairs)
    env = dict(os.environ)
    env["FITNESS_PAIRS"] = ",".join(str(g) for g in golds)
    env["EVAL_PAIRS"] = str(golds[0])

    if channel == "semantic":
        venv = env.pop("VIRTUAL_ENV", None)
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONHOME", None)
        if venv:
            env["PATH"] = os.pathsep.join(
                p for p in env.get("PATH", "").split(os.pathsep) if p and not p.startswith(venv)
            )
        cmd: list[str] = [
            python_bin,
            "benchmarks/codebench/eval_semantic_mrr.py",
            "--pairs",
            ",".join(str(g) for g in golds),
        ]
        if not full and sample:
            cmd += ["--sample", str(sample)]
        if repo:
            cmd += ["--repo", repo]
    elif channel == "cg":
        cmd = [sys.executable, "benchmarks/codebench/eval_cg_mrr.py"]
        if not full and sample:
            env["FITNESS_SAMPLE"] = str(sample)
        if repo:
            env["FITNESS_REPO"] = repo
    else:
        env["FITNESS_WORKERS"] = str(workers)
        if channel == "zoekt":
            env.setdefault("ATELIER_ZOEKT_MODE", "installed")
            env["ATELIER_ZOEKT_LOC_THRESHOLD"] = "1"
            env["FITNESS_CHANNEL"] = "zoekt"
        elif channel == "lexical+zoekt":
            env["FITNESS_CHANNEL"] = "lexical+zoekt"
        else:
            env["FITNESS_CHANNEL"] = "lexical"
        cmd = [sys.executable, "benchmarks/codebench/fitness_explore_mrr.py"]
        if full:
            cmd.append("--full")
        elif sample:
            cmd += ["--sample", str(sample)]
        if repo:
            cmd += ["--repo", repo]
        if reindex:
            cmd.append("--reindex")

    return cmd, env, golds


def _render_comparison(channel_results: dict[str, dict]) -> None:
    """Print side-by-side MRR + p100 comparison table.

    Rows: OVERALL[def/cnt] then repo[def]/repo[cnt] grouped by repo.
    Columns: one per channel, each showing MRR and p100.
    """
    channels = list(channel_results.keys())
    gold_kinds = [gk for gk in ("definition", "content") if any(
        gk in r.get("golds", {}) for r in channel_results.values()
    )]
    if not gold_kinds:
        gold_kinds = ["definition"]

    all_repos: set[str] = set()
    for r in channel_results.values():
        for gk in gold_kinds:
            all_repos.update(r.get("golds", {}).get(gk, {}).get("by_repo", {}).keys())
    repos = sorted(all_repos)

    def get_cell(channel: str, gold_kind: str, repo: str) -> tuple[float | None, float | None]:
        r = channel_results[channel]
        gdata = r.get("golds", {}).get(gold_kind, {})
        if repo == "OVERALL":
            mrr: float | None = gdata.get("mrr")
            lat = r.get("latency_ms", {})
            p100: float | None = lat.get("max") if isinstance(lat, dict) else None
        else:
            byr = gdata.get("by_repo", {}).get(repo) or {}
            mrr = byr.get("mrr")
            lat = byr.get("latency_ms") or {}
            p100 = lat.get("max") if isinstance(lat, dict) else None
        return mrr, p100

    def fmt(mrr: float | None, p100: float | None) -> str:
        if mrr is None:
            return "  --    --  "
        m = f"{mrr:.3f}"
        p = f"{int(p100)}ms" if p100 is not None else "--"
        return f"{m:>6} {p:>5}"

    REPO_W = 28
    CELL_W = 13  # "0.742  215ms"

    h1 = " " * REPO_W
    h2 = " " * REPO_W
    for ch in channels:
        h1 += f"  {ch:^{CELL_W}}"
        h2 += f"  {'MRR':>6} {'p100':>5}"
    sep = "-" * len(h1)

    print()
    print(h1)
    print(h2)
    print(sep)

    for repo in ["OVERALL"] + repos:
        short = repo.split("__")[-1] if "__" in repo else repo
        for gk in gold_kinds:
            label = f"{short}[{gk[:3]}]"
            row = f"{label:<{REPO_W}}"
            for ch in channels:
                m, p = get_cell(ch, gk, repo)
                row += f"  {fmt(m, p)}"
            print(row)
    print()


@eval_.command("retrieval")
@click.option(
    "--channel",
    "channels",
    multiple=True,
    type=click.Choice(_RETRIEVAL_CHANNELS),
    default=("lexical",),
    show_default=True,
    help="Channel(s) to benchmark. Repeatable for side-by-side comparison: "
    "--channel lexical --channel lexical+zoekt. "
    "lexical = pure FTS5 symbol search; zoekt = pure Zoekt trigram; "
    "semantic = BGE embeddings; cg = CodeGraph; lexical+zoekt = FTS5+Zoekt parallel.",
)
@click.option("--full", is_flag=True, default=False, help="Run all available query pairs (no cap).")
@click.option("--sample", type=int, default=0, help="Total queries to sample across repos (0 = default 500).")
@click.option("--repo", default="", metavar="PREFIX", help="Substring filter on repo prefix.")
@click.option(
    "-j",
    "--workers",
    type=int,
    default=1,
    show_default=True,
    help="Parallel workers. Keep 1 for trustworthy latency numbers.",
)
@click.option(
    "--pairs",
    type=click.Path(path_type=Path),
    default=None,
    help="Explicit (query, gold-file) pairs JSON. Default scores BOTH golds "
    "(definition = FTS-symbol's task, content = Zoekt's task) in one run.",
)
@click.option(
    "--python",
    "python_bin",
    default="python3",
    show_default=True,
    help="Interpreter for the semantic channel (must have sentence-transformers + torch).",
)
@click.option(
    "--reindex",
    is_flag=True,
    default=False,
    help="Re-index all repos via 'atelier code index --reindex --db-path' before benchmarking.",
)
def eval_retrieval(
    channels: tuple[str, ...],
    full: bool,
    sample: int,
    repo: str,
    workers: int,
    pairs: Path | None,
    python_bin: str,
    reindex: bool,
) -> None:
    """Retrieval MRR + latency over definition + content golds.

    Scores BOTH golds (definition = which file defines the symbol, content =
    which files contain the pattern) in one run. See RETRIEVAL_EVAL.md.

    Pass --channel multiple times for a side-by-side comparison table::

        atelier eval retrieval --channel lexical --channel lexical+zoekt --full
    """
    import subprocess

    repo_root = Path.cwd().resolve()

    if len(channels) == 1:
        # Single channel: stream output directly (existing behaviour).
        cmd, env, golds = _channel_cmd_env(
            channels[0],
            full=full,
            sample=sample,
            repo=repo,
            workers=workers,
            pairs=pairs,
            python_bin=python_bin,
            reindex=reindex,
        )
        click.echo(f"[eval] channel={channels[0]} golds={len(golds)} :: {' '.join(cmd)}", err=True)
        raise SystemExit(subprocess.run(cmd, cwd=repo_root, env=env, check=False).returncode)

    # Multiple channels: run each sequentially (serial = trustworthy latency),
    # capture JSON output, render side-by-side comparison table.
    import json

    channel_results: dict[str, dict] = {}
    any_failed = False
    for ch in channels:
        cmd, env, golds = _channel_cmd_env(
            ch,
            full=full,
            sample=sample,
            repo=repo,
            workers=workers,
            pairs=pairs,
            python_bin=python_bin,
            reindex=reindex,
        )
        click.echo(f"\n[eval] channel={ch} golds={len(golds)} :: {' '.join(cmd)}", err=True)
        # stderr inherits (progress streams to terminal); stdout captured for JSON.
        proc = subprocess.run(cmd, cwd=repo_root, env=env, check=False, stdout=subprocess.PIPE)
        if proc.returncode != 0:
            click.echo(f"[eval] channel={ch} exited {proc.returncode}", err=True)
            any_failed = True
            continue
        stdout = (proc.stdout or b"").decode(errors="replace")
        result: dict = {}
        for line in reversed(stdout.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    result = json.loads(line)
                    break
                except json.JSONDecodeError:
                    pass
        if not result:
            click.echo(f"[eval] channel={ch}: no JSON in stdout — check stderr above", err=True)
            any_failed = True
            continue
        channel_results[ch] = result

    if channel_results:
        _render_comparison(channel_results)

    raise SystemExit(1 if any_failed else 0)


@eval_.command("sessions")
@click.option(
    "--session-dir",
    "-d",
    default=os.environ.get("SESSION_ROOT", os.path.expanduser("~/.claude/projects/")),
    show_default=True,
    help="Directory to scan for Claude Code session files.",
)
@click.option(
    "--repo-filter",
    "-f",
    default=os.environ.get("SESSION_REPO_FILTER", ""),
    help="Substring filter on project directory name (e.g. 'atelier').",
)
@click.option(
    "--out",
    "-o",
    default=os.environ.get("SESSION_PAIRS_OUT", "/tmp/session_pairs.json"),
    show_default=True,
    help="Output path for mined pairs JSON.",
)
@click.option("--run-eval", is_flag=True, default=False, help="Run the retrieval benchmark after mining.")
@click.option(
    "--channel",
    type=click.Choice(["lexical", "zoekt", "cg", "lexical+zoekt"]),
    default="lexical",
    show_default=True,
    help="Which retrieval eval to run after mining pairs.",
)
@click.option("--full", is_flag=True, default=False, help="Run eval on all mined pairs (no cap).")
def eval_sessions(
    session_dir: str,
    repo_filter: str,
    out: Path,
    run_eval: bool,
    channel: str,
    full: bool,
) -> None:
    """Offline: mine search patterns from Claude Code & Codex session files,
    show savings analysis, and optionally run the retrieval benchmark.

    This reads your real session history to quantify how many individual
    grep calls Atelier's ``explore`` collapses, and generates query pairs
    for the MRR retrieval eval.

    The repo filter is auto-detected from your current working directory
    (basename). Both ``~/.claude/projects/`` and ``~/.codex/sessions/`` are
    scanned automatically.
    """
    import subprocess

    from atelier.gateway.cli.commands import benchmark as _bm

    bench_root = _bm._bench_source_root()
    env = dict(os.environ)
    env["FITNESS_PAIRS"] = str(out)
    env["SESSION_ROOT"] = session_dir
    env["SESSION_REPO_FILTER"] = repo_filter

    cmd = [
        *_bm._python_cmd(bench_root),
        "benchmarks/codebench/offline_session_analyzer.py",
        "--session-dir",
        session_dir,
        "--out",
        str(out),
    ]
    if repo_filter:
        cmd += ["--repo-filter", repo_filter]
    if run_eval:
        cmd += ["--run-eval", "--channel", channel]
        if full:
            cmd.append("--full")

    click.echo(f"[eval sessions] {' '.join(cmd)}", err=True)
    raise SystemExit(subprocess.run(cmd, cwd=bench_root, env=env, check=False).returncode)


@eval_.command("providers")
@click.option("--repo-root", type=click.Path(path_type=Path, file_okay=False), default=Path("."))
@click.option(
    "--workspace-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=None,
    help="Benchmark workspace/cache root. Defaults outside the repo under ../benchmarks/<repo>/.",
)
@click.option("--out", type=click.Path(path_type=Path, file_okay=False), default=None)
@click.option("--iterations", type=int, default=1, show_default=True)
@click.option(
    "--max-cases",
    type=int,
    default=100,
    show_default=True,
    help="Maximum cases per family (default 100). Use 0 for no cap.",
)
@click.option(
    "--jobs",
    type=int,
    default=0,
    show_default="auto",
    help="Parallel provider processes. Use 0 to auto-size.",
)
@click.option(
    "--providers",
    default=("atelier,atelier-zoekt,zoekt,serena,codegraph,code-index-mcp,jcodemunch-mcp,ast-grep,universal-ctags"),
    show_default=True,
)
@click.option(
    "--families",
    default=(
        "exact_symbol,exact_search,substring_search,file_outline,references,"
        "callers,callees,fuzzy_symbol,structural_search,nohit_search"
    ),
    show_default=True,
)
@click.option(
    "--install/--no-install",
    default=True,
    show_default=True,
    help="Install external provider tools (npm/uv) before running. On by default; use --no-install to skip.",
)
def eval_providers(
    repo_root: Path,
    workspace_root: Path | None,
    out: Path | None,
    iterations: int,
    max_cases: int,
    jobs: int,
    providers: str,
    families: str,
    install: bool,
) -> None:
    """Run the external code-search provider matrix and write CSV/JSON artifacts."""
    import shutil

    from atelier.gateway.cli.commands import benchmark as _bm
    from atelier.gateway.cli.progress import ProgressReporter

    repo_root = repo_root.resolve()
    run_dir = _bm._run_dir("providers", out, repo_root=repo_root)
    workspace_root = (
        workspace_root.resolve()
        if workspace_root is not None
        else _bm._workspace_dir("providers", repo_root=repo_root, run_id=run_dir.name)
    )
    cache_root = _bm._cache_dir("providers", repo_root=repo_root)
    # Always start from a clean provider cache so it does not accumulate across runs.
    shutil.rmtree(cache_root, ignore_errors=True)
    cache_root.mkdir(parents=True, exist_ok=True)
    click.echo(f"Cleared provider cache: {cache_root}")
    provider_list = _bm._csv_values(providers)
    resolved_jobs = _bm._resolve_provider_jobs(jobs, provider_list)
    csv_out = run_dir / "results.csv"
    json_out = run_dir / "results.json"
    progress = ProgressReporter("providers", total=1)
    progress.start("starting benchmark", current=f"reports {run_dir} | jobs {resolved_jobs}")
    bench_root = _bm._bench_source_root()
    cmd = [
        *_bm._python_cmd(bench_root),
        "-m",
        "benchmarks.mcp_tools.bench_external_matrix",
        "--repo-root",
        str(repo_root),
        "--workspace-root",
        str(workspace_root),
        "--cache-root",
        str(cache_root),
        "--manifest-path",
        str(workspace_root / "external_matrix_cases.json"),
        "--audit-path",
        str(workspace_root / "external_tool_surfaces.json"),
        "--json-out",
        str(json_out),
        "--csv-out",
        str(csv_out),
        "--iterations",
        str(iterations),
        "--jobs",
        str(resolved_jobs),
        "--tools",
        providers,
        "--families",
        families,
    ]
    if max_cases > 0:
        cmd.extend(["--max-cases", str(max_cases)])
    if install:
        cmd.append("--install")
    _bm._run(cmd, cwd=bench_root, label="provider benchmark")
    progress.step("benchmark command complete", current="external provider matrix")
    progress.finish("benchmark complete")
    click.echo(f"Results: {run_dir}")


__all__ = [
    "eval_",
]
