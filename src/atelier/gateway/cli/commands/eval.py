from __future__ import annotations

import os
from pathlib import Path

import click


def _gpu_supports_embedder(min_free_mb: int = 512) -> tuple[bool, str]:
    """Return (ok, reason). True when a CUDA GPU with enough free VRAM is present.

    Uses ``nvidia-smi`` so it works regardless of which Python env is active.
    Falls back to ``torch.cuda`` when nvidia-smi is unavailable.
    """
    import subprocess

    # Primary: nvidia-smi — works in any Python env
    try:
        out = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
        if not out:
            return False, "nvidia-smi returned no GPU info"
        free_mb = max(int(line.strip()) for line in out.splitlines() if line.strip())
        if free_mb < min_free_mb:
            return False, f"only {free_mb} MB free VRAM (need {min_free_mb} MB)"
        return True, f"{free_mb} MB free VRAM"
    except FileNotFoundError:
        pass  # nvidia-smi not installed; fall through to torch
    except Exception as exc:  # noqa: BLE001
        return False, f"nvidia-smi error: {exc}"

    # Fallback: torch (only available when torch is installed in this env)
    try:
        import torch

        if not torch.cuda.is_available():
            return False, "no CUDA GPU detected"
        free_bytes, _ = torch.cuda.mem_get_info()
        free_mb = free_bytes // (1024 * 1024)
        if free_mb < min_free_mb:
            return False, f"only {free_mb} MB free VRAM (need {min_free_mb} MB)"
        return True, f"{free_mb} MB free VRAM"
    except ImportError:
        return False, "nvidia-smi not found and torch not installed"
    except Exception as exc:  # noqa: BLE001
        return False, f"GPU check failed: {exc}"


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


# Atelier channels are env-toggled variants of the SAME shipped stdio surface
# (--provider atelier): no in-process shortcuts, no pure-zoekt diagnostic (it
# bypassed the shipped pipeline and died with fitness_explore_mrr.py).
_ATELIER_CHANNELS = ["lexical", "lexical+zoekt", "lexical+zoekt+semantic"]
_EXTERNAL_CHANNELS = ["cg", "ctags", "ast-grep", "serena", "code-index-mcp", "jcodemunch", "rg", "cmm"]
_RETRIEVAL_CHANNELS = _ATELIER_CHANNELS + _EXTERNAL_CHANNELS
_ALL_CHANNEL = "all"


def _make_golds(pairs: Path | None) -> list[Path]:
    if pairs is not None:
        return [pairs]
    # Default: every gold set that exists, so a bare `eval retrieval` scores the
    # full ~7.5k-query suite (def + content + semantic + swebench + sessions)
    # across all channels, not just a swebench+sessions subset. Narrow with
    # --pairs <file> (single gold) or --sample N when a quick run is wanted.
    base = Path("benchmarks/codebench/data")
    names = [
        "bench_pairs_def_gold.json",
        "bench_pairs_content_gold.json",
        "bench_pairs_qwen_gold.json",
        "bench_pairs_swebench_gold.json",
        "bench_pairs_atelier_sessions_gold.json",
    ]
    return [base / n for n in names if (base / n).exists()]


def _channel_cmd_env(
    channel: str,
    *,
    full: bool,
    sample: int,
    repo: str,
    pairs: Path | None,
) -> tuple[list[str], dict[str, str], list[Path]]:
    """Every channel -- Atelier included -- runs through the same provider
    harness over the shipped stdio surface. Atelier channel variants are env
    toggles the server honours (the provider forwards its environment)."""
    import os
    import sys

    golds = _make_golds(pairs)
    env = dict(os.environ)
    env["FITNESS_PAIRS"] = ",".join(str(g) for g in golds)
    env["EVAL_PAIRS"] = str(golds[0])

    provider = "atelier" if channel in _ATELIER_CHANNELS else channel
    env["EVAL_CHANNEL_LABEL"] = channel
    if channel == "lexical":
        env["ATELIER_ZOEKT_MODE"] = "off"
        env["ATELIER_EXPLORE_SEMANTIC"] = "0"
    elif channel == "lexical+zoekt":
        env["ATELIER_EXPLORE_SEMANTIC"] = "0"
    elif channel == "lexical+zoekt+semantic":
        # Use the embedder pinned by ATELIER_CODE_EMBEDDER in the caller's
        # env, or fall back to the configured best (nomic by default).
        env.setdefault("ATELIER_CODE_EMBEDDER", os.environ.get("ATELIER_CODE_EMBEDDER", "nomic"))

    cmd: list[str] = [
        sys.executable,
        "benchmarks/codebench/eval_external_provider_mrr.py",
        "--provider",
        provider,
    ]
    if full:
        cmd.append("--full")
    elif sample:
        cmd += ["--sample", str(sample)]
    if repo:
        cmd += ["--repo", repo]

    return cmd, env, golds


def _render_comparison(channel_results: dict[str, dict], csv_path: Path | None = None) -> None:
    """Print side-by-side MRR + p100 comparison table and optionally write CSV.

    Rows: OVERALL[def/cnt] then repo[def]/repo[cnt] grouped by repo.
    Columns: one per channel, each showing MRR and p100.
    """
    channels = list(channel_results.keys())
    # Collect every gold_kind present across any channel result.
    _all_gks = ["definition", "content", "qwen_semantic", "swebench", "atelier_sessions"]
    gold_kinds = [gk for gk in _all_gks if any(gk in r.get("golds", {}) for r in channel_results.values())]
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

    for repo in ["OVERALL", *repos]:
        short = repo.split("__")[-1] if "__" in repo else repo
        for gk in gold_kinds:
            label = f"{short}[{gk[:3]}]"
            row = f"{label:<{REPO_W}}"
            for ch in channels:
                m, p = get_cell(ch, gk, repo)
                row += f"  {fmt(m, p)}"
            print(row)
    print()

    if csv_path is None:
        return

    import csv as _csv

    def get_full(channel: str, gold_kind: str, repo: str) -> tuple:
        r = channel_results[channel]
        gdata = r.get("golds", {}).get(gold_kind, {})
        if repo == "OVERALL":
            mrr = gdata.get("mrr")
            hit1 = gdata.get("hit1")
            hit2 = gdata.get("hit2")
            hit3 = gdata.get("hit3")
            n = gdata.get("n")
            lat = r.get("latency_ms", {})
        else:
            byr = gdata.get("by_repo", {}).get(repo) or {}
            mrr, hit1, hit2, hit3, n = byr.get("mrr"), byr.get("hit1"), byr.get("hit2"), byr.get("hit3"), byr.get("n")
            lat = byr.get("latency_ms") or {}
        p95 = lat.get("p95") if isinstance(lat, dict) else None
        p100 = lat.get("max") if isinstance(lat, dict) else None
        return mrr, hit1, hit2, hit3, n, p95, p100

    fieldnames = ["repo", "gold_kind"]
    for ch in channels:
        fieldnames += [f"{ch}_MRR", f"{ch}_hit1", f"{ch}_hit2", f"{ch}_hit3", f"{ch}_n", f"{ch}_p95ms", f"{ch}_p100ms"]

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    with csv_path.open("w", newline="") as fh:
        writer = _csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for repo in ["OVERALL", *repos]:
            short = repo.split("__")[-1] if "__" in repo else repo
            for gk in gold_kinds:
                row_d: dict[str, object] = {"repo": short, "gold_kind": gk}
                for ch in channels:
                    mrr, hit1, hit2, hit3, n, p95, p100 = get_full(ch, gk, repo)
                    row_d[f"{ch}_MRR"] = f"{mrr:.4f}" if mrr is not None else ""
                    row_d[f"{ch}_hit1"] = f"{hit1:.4f}" if hit1 is not None else ""
                    row_d[f"{ch}_hit2"] = f"{hit2:.4f}" if hit2 is not None else ""
                    row_d[f"{ch}_hit3"] = f"{hit3:.4f}" if hit3 is not None else ""
                    row_d[f"{ch}_n"] = n if n is not None else ""
                    row_d[f"{ch}_p95ms"] = f"{int(p95)}" if p95 is not None else ""
                    row_d[f"{ch}_p100ms"] = f"{int(p100)}" if p100 is not None else ""
                writer.writerow(row_d)
    click.echo(f"[eval] CSV written -> {csv_path}", err=True)


@eval_.command("retrieval")
@click.option(
    "--channel",
    "channels",
    multiple=True,
    type=click.Choice([_ALL_CHANNEL, *_RETRIEVAL_CHANNELS]),
    default=("lexical",),
    show_default=True,
    help="Channel(s) to benchmark. Repeatable for side-by-side comparison: "
    "--channel lexical --channel lexical+zoekt. "
    "Use 'all' to run every channel. "
    "Atelier (env-toggled variants of the shipped MCP surface): lexical, "
    "lexical+zoekt, lexical+zoekt+semantic. "
    "External: cg, ctags, ast-grep, serena, code-index-mcp, jcodemunch, rg, cmm.",
)
@click.option("--full", is_flag=True, default=False, help="Run all available query pairs (no cap).")
@click.option("--sample", type=int, default=0, help="Total queries to sample across repos (0 = default 500).")
@click.option("--repo", default="", metavar="PREFIX", help="Substring filter on repo prefix.")
@click.option(
    "--pairs",
    type=click.Path(path_type=Path),
    default=None,
    help="Explicit (query, gold-file) pairs JSON. Default scores BOTH golds "
    "(definition = FTS-symbol's task, content = Zoekt's task) in one run.",
)
@click.option(
    "--csv",
    "csv_path",
    type=click.Path(path_type=Path),
    default=None,
    metavar="FILE",
    help="Write comparison results to a CSV file (wide: one row per repoxgold, one column-group per channel).",
)
@click.option(
    "--serial/--parallel",
    "serial",
    default=True,
    help="--parallel runs channels concurrently (faster but shared CPU skews latency). Default: serial.",
)
@click.option(
    "--resume",
    is_flag=True,
    default=False,
    help="Reuse per-channel results already cached beside --csv (in <csv-stem>_channels/): "
    "skip channels that finished, run only the missing ones, then re-render the CSV. "
    "Lets a long multi-channel/all-gold sweep continue after an interruption without redoing finished channels.",
)
def eval_retrieval(
    channels: tuple[str, ...],
    full: bool,
    sample: int,
    repo: str,
    pairs: Path | None,
    csv_path: Path | None,
    serial: bool,
    resume: bool,
) -> None:
    """Retrieval MRR + latency over definition + content golds.

    Scores BOTH golds (definition = which file defines the symbol, content =
    which files contain the pattern) in one run.

    Pass --channel multiple times for a side-by-side comparison table::

        atelier eval retrieval --channel lexical --channel lexical+zoekt --full
    """
    import json
    import subprocess
    from concurrent.futures import ThreadPoolExecutor, as_completed

    repo_root = Path.cwd().resolve()

    # Expand 'all' to every real channel, preserving any explicit order and deduplicating.
    if _ALL_CHANNEL in channels:
        seen_ch: set[str] = set()
        expanded: list[str] = []
        for ch in channels:
            targets = _RETRIEVAL_CHANNELS if ch == _ALL_CHANNEL else [ch]
            for t in targets:
                if t not in seen_ch:
                    seen_ch.add(t)
                    expanded.append(t)
        channels = tuple(expanded)

    # Per-channel result cache: each channel's JSON is persisted the moment it
    # finishes, so a --resume run can skip completed channels and re-run only the
    # missing ones — essential for long all-gold sweeps across many channels that
    # may be interrupted. Location derives from --csv so the cache sits beside the
    # output; without --csv, --resume falls back to a repo-local cache dir.
    results_dir: Path | None = None
    if csv_path is not None:
        results_dir = csv_path.parent / f"{csv_path.stem}_channels"
    elif resume:
        results_dir = repo_root / ".eval_retrieval_channels"
    if results_dir is not None:
        results_dir.mkdir(parents=True, exist_ok=True)

    def _cache_path(ch: str) -> Path | None:
        if results_dir is None:
            return None
        safe = ch.replace("+", "_").replace("/", "_")
        return results_dir / f"{safe}.json"

    def _run_channel(ch: str) -> tuple[str, dict | None]:
        cache = _cache_path(ch)
        if resume and cache is not None and cache.exists():
            try:
                cached = json.loads(cache.read_text())
                click.echo(f"[eval] resume channel={ch} (cached {cache})", err=True)
                return ch, cached
            except Exception:  # noqa: BLE001 — corrupt cache: fall through and re-run
                click.echo(f"[eval] cache for channel={ch} unreadable — re-running", err=True)
        cmd, env, _ = _channel_cmd_env(
            ch,
            full=full,
            sample=sample,
            repo=repo,
            pairs=pairs,
        )
        click.echo(f"[eval] start channel={ch} :: {' '.join(cmd)}", err=True)
        proc = subprocess.run(cmd, cwd=repo_root, env=env, check=False, stdout=subprocess.PIPE)
        if proc.returncode != 0:
            click.echo(f"[eval] channel={ch} exited {proc.returncode}", err=True)
            return ch, None
        stdout = (proc.stdout or b"").decode(errors="replace")
        for line in reversed(stdout.splitlines()):
            line = line.strip()
            if line.startswith("{"):
                try:
                    result = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if cache is not None:
                    try:
                        cache.write_text(json.dumps(result))
                    except Exception:  # noqa: BLE001 — caching is best-effort
                        pass
                click.echo(f"[eval] done  channel={ch}", err=True)
                return ch, result
        click.echo(f"[eval] channel={ch}: no JSON in stdout — check stderr above", err=True)
        return ch, None

    if len(channels) == 1 and csv_path is None and not resume:
        # Fast path: single channel with no CSV — stream directly.
        cmd, env, golds = _channel_cmd_env(
            channels[0],
            full=full,
            sample=sample,
            repo=repo,
            pairs=pairs,
        )
        click.echo(f"[eval] channel={channels[0]} golds={len(golds)} :: {' '.join(cmd)}", err=True)
        raise SystemExit(subprocess.run(cmd, cwd=repo_root, env=env, check=False).returncode)

    channel_results: dict[str, dict] = {}
    any_failed = False

    if not serial and len(channels) > 1:
        click.echo(f"[eval] running {len(channels)} channels in parallel", err=True)
        with ThreadPoolExecutor(max_workers=len(channels)) as pool:
            futures = {pool.submit(_run_channel, ch): ch for ch in channels}
            for fut in as_completed(futures):
                ch, result = fut.result()
                if result is None:
                    any_failed = True
                else:
                    channel_results[ch] = result
        # Restore original channel order.
        channel_results = {ch: channel_results[ch] for ch in channels if ch in channel_results}
    else:
        for ch in channels:
            ch, result = _run_channel(ch)
            if result is None:
                any_failed = True
            else:
                channel_results[ch] = result

    if channel_results:
        _render_comparison(channel_results, csv_path=csv_path)

    raise SystemExit(1 if any_failed else 0)


@eval_.command("fitness")
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
@click.option("--no-eval", is_flag=True, default=False, help="Skip the retrieval benchmark; only mine and save pairs.")
@click.option(
    "--channel",
    "channels",
    multiple=True,
    type=click.Choice([_ALL_CHANNEL, *_RETRIEVAL_CHANNELS]),
    default=("lexical", "lexical+zoekt", "lexical+zoekt+semantic", "rg"),
    show_default=True,
    help="Retrieval channel(s) to benchmark. Pass multiple times for side-by-side.",
)
@click.option("--full", is_flag=True, default=False, help="Run eval on all mined pairs (no cap).")
def eval_fitness(
    session_dir: str,
    repo_filter: str,
    out: Path,
    no_eval: bool,
    channels: tuple[str, ...],
    full: bool,
) -> None:
    """Mine search patterns from your real Claude Code & Codex sessions and
    benchmark Atelier's retrieval quality against them.

    Scans ``~/.claude/projects/`` and ``~/.codex/sessions/`` for real explore
    queries you made during past coding sessions, writes them to a pairs file,
    then immediately runs ``eval retrieval`` on those pairs so you can see how
    well Atelier finds files for queries like the ones you actually ask.

    Use ``--no-eval`` to only mine and save the pairs without running the benchmark.
    """
    import subprocess

    from atelier.gateway.cli.commands import benchmark as _bm

    bench_root = _bm._bench_source_root()
    env = dict(os.environ)
    env["FITNESS_PAIRS"] = str(out)
    env["SESSION_ROOT"] = session_dir
    env["SESSION_REPO_FILTER"] = repo_filter

    # Step 1: mine queries from sessions.
    mine_cmd = [
        *_bm._python_cmd(bench_root),
        "benchmarks/codebench/offline_session_analyzer.py",
        "--session-dir",
        session_dir,
        "--out",
        str(out),
    ]
    if repo_filter:
        mine_cmd += ["--repo-filter", repo_filter]

    click.echo("[eval fitness] mining queries ...", err=True)
    r = subprocess.run(mine_cmd, cwd=bench_root, env=env, check=False)
    if r.returncode != 0:
        raise SystemExit(r.returncode)

    # Step 2: augment with synthetic queries from the current project.
    # Cap synthetic pairs at the session pair count so neither source dominates
    # (50/50 split). When there are no session pairs, the cap is lifted so
    # synthetic pairs fill the whole benchmark.
    click.echo("[eval fitness] generating synthetic pairs ...", err=True)
    import json as _json

    _session_count = 0
    _session_prefix = ""
    try:
        _pd = _json.loads(out.read_text())
        _session_count = len(_pd.get("pairs", []))
        _session_prefix = next(iter(_pd.get("repos", {})), "")
    except (_json.JSONDecodeError, KeyError, TypeError):
        pass
    syn_cmd = [
        *_bm._python_cmd(bench_root),
        "benchmarks/codebench/synthetic_pair_miner.py",
        "--repo-dir",
        str(Path(".").resolve()),
        "--merge",
        str(out),  # merge into the session pairs file in-place
        "--out",
        str(out),
    ]
    if _session_prefix:
        syn_cmd += ["--repo-prefix", _session_prefix]
    # 50/50 cap with gap-fill:
    # - No sessions       → unlimited synthetic (pure synthetic benchmark)
    # - Sessions sparse   → synthetic fills up to MIN_TOTAL so the benchmark
    #                       stays meaningful even when real sessions are few
    # - Sessions plentiful → synthetic capped at session_count (≤50% of total)
    _MIN_TOTAL = 500
    if _session_count == 0:
        pass  # no cap — synthetic fills everything
    elif _session_count < _MIN_TOTAL // 2:
        syn_cmd += ["--max-pairs", str(_MIN_TOTAL - _session_count)]
    else:
        syn_cmd += ["--max-pairs", str(_session_count)]
    r2 = subprocess.run(syn_cmd, cwd=bench_root, env=env, check=False)
    if r2.returncode != 0:
        click.echo("[eval fitness] synthetic mining failed (continuing without it)", err=True)

    # Step 2.5: augment with semantic queries (docstring + intent-based) from the project.
    click.echo("[eval fitness] generating semantic pairs ...", err=True)
    # Re-read session count (may have changed after synthetic merge)
    try:
        _pd = _json.loads(out.read_text())
        _session_count = len(_pd.get("pairs", []))
        _session_prefix = next(iter(_pd.get("repos", {})), "")
    except (_json.JSONDecodeError, KeyError, TypeError):
        pass
    sem_cmd = [
        *_bm._python_cmd(bench_root),
        "benchmarks/codebench/semantic_pair_miner.py",
        "--repo-dir",
        str(Path(".").resolve()),
        "--merge",
        str(out),
        "--out",
        str(out),
    ]
    if _session_prefix:
        sem_cmd += ["--repo-prefix", _session_prefix]
    # Similar 50/50 cap: semantic fills up to session_count (≤50% of total)
    if _session_count == 0:
        sem_cmd += ["--max-pairs", "200"]  # pure semantic fallback
    elif _session_count < _MIN_TOTAL // 2:
        sem_cmd += ["--max-pairs", str(_MIN_TOTAL - _session_count)]
    else:
        sem_cmd += ["--max-pairs", str(_session_count)]
    r3 = subprocess.run(sem_cmd, cwd=bench_root, env=env, check=False)
    if r3.returncode != 0:
        click.echo("[eval fitness] semantic mining failed (continuing without it)", err=True)

    if no_eval:
        click.echo(f"[eval fitness] pairs written -> {out}", err=True)
        return

    # Step 3: run retrieval benchmark on the combined pairs.
    # Drop semantic channel if the GPU can't support the embedding model.
    active_channels = list(channels)
    if "lexical+zoekt+semantic" in active_channels:
        gpu_ok, gpu_reason = _gpu_supports_embedder()
        if not gpu_ok:
            click.echo(
                f"[eval fitness] skipping lexical+zoekt+semantic ({gpu_reason})",
                err=True,
            )
            active_channels.remove("lexical+zoekt+semantic")

    eval_cmd = ["atelier", "eval", "retrieval", "--pairs", str(out)]
    for ch in active_channels:
        eval_cmd += ["--channel", ch]
    if full:
        eval_cmd.append("--full")

    click.echo(f"[eval fitness] {' '.join(eval_cmd)}", err=True)
    raise SystemExit(subprocess.run(eval_cmd, cwd=str(Path(".").resolve()), env=env, check=False).returncode)


__all__ = [
    "eval_",
]
