"""``atelier benchmark`` command group.

Quick-reference invocation patterns
------------------------------------

All examples use ``atelier benchmark atelierbench``
(default task = all, default model = sonnet).


Atelier vs Baseline on Claude CLI (default transport)
......................................................

  # Atelier arm (latent + swarm), local Claude CLI:
  atelier benchmark atelierbench --arm atelier

  # Baseline arm (no Atelier, vanilla Claude CLI):
  atelier benchmark atelierbench --arm baseline

  # Compare both in one run:
  atelier benchmark atelierbench --arm baseline --arm atelier

  # With a specific model:
  atelier benchmark atelierbench --arm atelier --model claude-sonnet-4-20250514

  # Limit to a single task for fast iteration:
  atelier benchmark atelierbench --task codegen_hello_world --arm atelier



OpenCode as the CLI driver (--cli-driver opencode)
...................................................

  # Atelier arm, but the sub-task prompt is handed to `opencode run`:
  atelier benchmark atelierbench --arm atelier --cli-driver opencode

  # Compare atelier vs baseline on OpenCode driver:
  atelier benchmark atelierbench --arm baseline --arm atelier --cli-driver opencode


Atelier on Bedrock (AWS) with rate limiting
............................................

  Shorthand via --provider:

    atelier benchmark atelierbench --arm atelier --provider bedrock --rate-limit-rpm 5
    atelier benchmark atelierbench --arm baseline --arm atelier --provider bedrock --rate-limit-rpm 5

  Explicit preset (same effect):

    atelier benchmark atelierbench --arm atelier --claude-provider-preset aws-claude --rate-limit-rpm 5

  With token-level rate limit:

    atelier benchmark atelierbench --arm atelier --provider bedrock --rate-limit-rpm 5 --rate-limit-tpm 50000


Baseline on Bedrock with rate limiting
.......................................

  atelier benchmark atelierbench --arm baseline --provider bedrock --rate-limit-rpm 5


Atelier on GCP Vertex with rate limiting
........................................

  atelier benchmark atelierbench --arm atelier --provider gcp --rate-limit-rpm 5
  atelier benchmark atelierbench --arm baseline --arm atelier --provider gcp --rate-limit-rpm 5


Atelier on Azure with rate limiting
....................................

  atelier benchmark atelierbench --arm atelier --provider azure --rate-limit-rpm 5
  atelier benchmark atelierbench --arm baseline --arm atelier --provider azure --rate-limit-rpm 5


Atelier on OpenRouter
.....................

  atelier benchmark atelierbench --arm atelier --provider openrouter --rate-limit-rpm 10
  atelier benchmark atelierbench --arm baseline --arm atelier --provider openrouter --rate-limit-rpm 10


All five arms together (compare everything)
...........................................

  atelier benchmark atelierbench --arm baseline --arm atelier --arm atelier.raw \
      --cli-driver claude --reps 3


Atelier-run arm (runs ``atelier run start`` as the driver -- Atelier's own
owned-agent loop, using YOUR API credentials directly)
........................................................

  atelier benchmark atelierbench --arm atelier --cli-driver atelier-run

  # Atelier-run on Bedrock with rate limiting (the driver is `atelier run start`,
  # not the `claude` CLI -- `atelier run` uses your own ANTHROPIC_API_KEY or
  # other provider credentials):
  atelier benchmark atelierbench --arm atelier --cli-driver atelier-run \
      --model us.anthropic.claude-sonnet-4-6 --rate-limit-rpm 10

  # Compare atelier (plugin) vs atelier-run (owned-agent loop) on Bedrock:
  atelier benchmark atelierbench \
      --arm atelier \
      --cli-driver atelier-run \
      --model us.anthropic.claude-sonnet-4-6 \
      --rate-limit-rpm 10 \
      --reps 1


Atelier on Bedrock with explicit model + rate limit (copy-paste ready)
......................................................................

  # Atelier plugin arm via Claude CLI routed through Bedrock:
  atelier benchmark atelierbench \
      --arms atelier \
      --provider bedrock \
      --model us.anthropic.claude-sonnet-4-6 \
      --rate-limit-rpm 10 \
      --transport cli --cli-driver claude \
      --reps 1 --tasks all

  # Compare atelier vs baseline on Bedrock:
  atelier benchmark atelierbench \
      --arms baseline --arms atelier \
      --provider bedrock \
      --model us.anthropic.claude-sonnet-4-6 \
      --rate-limit-rpm 10 \
      --reps 1 --tasks all


Common pitfalls
...............

  # WRONG: --cli-driver atelier-run gets rejected by the CLI gateway if the
  # click.Choice is out of sync. This is now fixed.
  #
  # WRONG: --cli-extra-arg=--provider --cli-extra-arg=bedrock
  # Those get forwarded to the CLI driver binary (claude / atelier run start),
  # not to the benchmark harness. Use --provider / --agent-env instead.
  #
  # CORRECT: use --provider to set cloud-provider env vars for the claude CLI:
  atelier benchmark atelierbench --arm atelier --provider bedrock --rate-limit-rpm 5


Use --help on the sub-command for all available flags:

  atelier benchmark atelierbench --help
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from datetime import UTC, datetime
from os import cpu_count, environ
from pathlib import Path
from shutil import rmtree, which

import click

from atelier.core.capabilities.benchmark_evidence import (
    build_atelierbench_evidence,
    git_state,
    write_benchmark_evidence,
)
from atelier.core.capabilities.benchmark_gate import (
    evaluate_atelierbench_gate,
    load_benchmark_gate,
    require_benchmark_gate_pass,
    write_benchmark_gate,
)
from atelier.core.capabilities.benchmark_manifest import (
    build_atelierbench_manifest,
    write_benchmark_manifest,
)
from atelier.core.capabilities.host_runners import (
    CLAUDE_PROVIDER_PRESETS,
    resolve_claude_provider_preset,
)
from atelier.gateway.cli.commands.benchmark_solver import benchmark_solver_cmd
from atelier.gateway.cli.progress import ProgressReporter

_PROVIDER_ALIASES: dict[str, str] = {
    "aws": "aws-claude",
    "bedrock": "aws-claude",
    "gcp": "gcp-claude",
    "vertex": "gcp-claude",
    "azure": "azure-claude",
    "openrouter": "openrouter-claude",
}


@click.group("benchmark")
def benchmark_group() -> None:
    """Run Atelier benchmark suites and reports."""


benchmark_group.add_command(benchmark_solver_cmd, name="solver")


@benchmark_group.command("mcp")
@click.option("--out", type=click.Path(path_type=Path, file_okay=False), default=None)
@click.option(
    "--jobs",
    type=int,
    default=0,
    show_default="auto",
    help="Parallel suite shards. Use 0 to auto-size.",
)
def benchmark_mcp_cmd(out: Path | None, jobs: int) -> None:
    """Run the public MCP tool benchmark suite and write results."""
    repo_root = Path.cwd().resolve()
    run_dir = _run_dir("mcp", out)
    workspace_dir = _workspace_dir("mcp", repo_root=repo_root, run_id=run_dir.name)
    resolved_jobs = _resolve_mcp_jobs(jobs, repo_root=repo_root)
    progress = ProgressReporter("mcp", total=1)
    progress.start("starting benchmark", current=f"reports {run_dir} | jobs {resolved_jobs}")
    bench_root = _bench_source_root()
    _run(
        [
            *_python_cmd(bench_root),
            "-m",
            "benchmarks.mcp_tools.export_public_mcp_csv",
            "--artifact-root",
            str(workspace_dir),
            "--csv-out",
            str(run_dir / "results.csv"),
            "--jobs",
            str(resolved_jobs),
        ],
        cwd=bench_root,
        label="MCP benchmark",
    )
    progress.step("benchmark command complete", current="public MCP tools")
    progress.finish("benchmark complete")
    click.echo(f"Results: {run_dir}")


@benchmark_group.command("providers")
@click.option("--repo-root", type=click.Path(path_type=Path, file_okay=False), default=Path("."))
@click.option(
    "--workspace-root",
    type=click.Path(path_type=Path, file_okay=False),
    default=None,
    help="Benchmark workspace/cache root. Defaults outside the repo under ../benchmarks/<repo>/.",
)
@click.option("--out", type=click.Path(path_type=Path, file_okay=False), default=None)
@click.option("--iterations", type=int, default=1, show_default=True)
@click.option("--max-cases", type=int, default=100, show_default=True)
@click.option(
    "--jobs",
    type=int,
    default=0,
    show_default="auto",
    help="Parallel provider processes. Use 0 to auto-size.",
)
@click.option(
    "--providers",
    default=(
        "atelier,atelier-zoekt,zoekt,atelier-serena,serena,atelier-codegraph,codegraph,code-index-mcp,jcodemunch-mcp"
    ),
    show_default=True,
)
@click.option("--families", default="exact_search,substring_search,nohit_search", show_default=True)
@click.option(
    "--install/--no-install",
    default=True,
    show_default=True,
    help="Install external provider tools (npm/uv) before running. On by default; use --no-install to skip.",
)
def benchmark_providers_cmd(
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
    repo_root = repo_root.resolve()
    run_dir = _run_dir("providers", out, repo_root=repo_root)
    workspace_root = (
        workspace_root.resolve()
        if workspace_root is not None
        else _workspace_dir("providers", repo_root=repo_root, run_id=run_dir.name)
    )
    cache_root = _cache_dir("providers", repo_root=repo_root)
    # Always start from a clean provider cache so it does not accumulate across runs.
    rmtree(cache_root, ignore_errors=True)
    cache_root.mkdir(parents=True, exist_ok=True)
    click.echo(f"Cleared provider cache: {cache_root}")
    provider_list = _csv_values(providers)
    resolved_jobs = _resolve_provider_jobs(jobs, provider_list)
    csv_out = run_dir / "results.csv"
    json_out = run_dir / "results.json"
    progress = ProgressReporter("providers", total=1)
    progress.start("starting benchmark", current=f"reports {run_dir} | jobs {resolved_jobs}")
    bench_root = _bench_source_root()
    cmd = [
        *_python_cmd(bench_root),
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
    _run(cmd, cwd=bench_root, label="provider benchmark")
    progress.step("benchmark command complete", current="external provider matrix")
    progress.finish("benchmark complete")
    click.echo(f"Results: {run_dir}")


@benchmark_group.command("gate", hidden=True)
@click.option(
    "--run-dir",
    type=click.Path(path_type=Path, file_okay=False),
    required=True,
    help="Benchmark run directory containing benchmark-gate.json.",
)
@click.option("--json", "as_json", is_flag=True, help="Emit the loaded benchmark gate as JSON.")
@click.option(
    "--require-pass/--allow-failed-gate",
    default=False,
    show_default=True,
    help="Exit non-zero when the loaded benchmark gate did not pass.",
)
def benchmark_gate_cmd(run_dir: Path, as_json: bool, require_pass: bool) -> None:
    """Load an existing benchmark gate artifact and optionally fail on a failed gate."""
    gate = load_benchmark_gate(run_dir.resolve())
    if as_json:
        click.echo(json.dumps(gate))
    else:
        click.echo(f"suite: {gate.get('suite', '')}")
        click.echo(f"passed: {bool(gate.get('passed'))}")
        for reason in gate.get("reasons", []) or []:
            click.echo(f"- {reason}")
    if require_pass:
        try:
            require_benchmark_gate_pass(run_dir.resolve())
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc


@benchmark_group.command("atelierbench")
@click.option(
    "--task",
    "tasks",
    multiple=True,
    default=("all",),
    show_default=True,
    help="AtelierBench task id; repeat for multiple or use 'all'.",
)
@click.option(
    "--arm",
    "arms",
    multiple=True,
    default=("baseline", "atelier"),
    show_default=True,
    type=click.Choice(["baseline", "atelier"]),
)
@click.option("--reps", type=int, default=1, show_default=True)
@click.option("--model", default="sonnet", show_default=True)
@click.option("--timeout", type=int, default=1800, show_default=True)
@click.option(
    "--rate-limit-rpm",
    type=click.FloatRange(min=0),
    default=0,
    show_default=True,
    help="Maximum model inference requests per minute; 0 disables throttling.",
)
@click.option(
    "--rate-limit-tpm",
    type=click.IntRange(min=0),
    default=0,
    show_default=True,
    help="Maximum reserved output tokens per rolling minute; 0 disables throttling.",
)
@click.option(
    "--cli-driver",
    type=click.Choice(["claude", "copilot", "codex", "opencode", "atelier-run"]),
    default="claude",
    show_default=True,
    help="CLI host to benchmark.",
)
@click.option(
    "--jobs",
    type=int,
    default=1,
    show_default=True,
    help="Parallel task/rep workers; arms stay serial within each worker.",
)
@click.option(
    "--parallel-scope",
    type=click.Choice(["task", "arm"]),
    default="task",
    show_default=True,
    help="Use 'arm' only for throughput experiments; 'task' preserves fair per-task comparisons.",
)
@click.option("--judge", is_flag=True, help="Score correctness with an LLM judge.")
@click.option("--judge-model", default=None)
@click.option("--judge-agent-command", default=None)
@click.option(
    "--agent-command",
    default="claude",
    show_default=True,
    help="Claude-compatible command to run each arm.",
)
@click.option(
    "--agent-env",
    "agent_env",
    multiple=True,
    help="CLI transport env override in KEY=VALUE form; repeatable.",
)
@click.option(
    "--agent-env-from-host",
    "agent_env_from_host",
    multiple=True,
    help="Copy a host env var into the Claude CLI env as DEST_KEY=SOURCE_ENV; repeatable.",
)
@click.option(
    "--cli-extra-arg",
    "cli_extra_args",
    multiple=True,
    help="Extra CLI argument passed to the selected driver; repeatable.",
)
@click.option(
    "--openrouter-claude/--no-openrouter-claude",
    "--openrouter-anthropic/--no-openrouter-anthropic",
    "openrouter_claude",
    default=False,
    show_default=True,
    help="Preset Claude CLI env for OpenRouter's Anthropic-compatible endpoint.",
)
@click.option(
    "--claude-provider-preset",
    type=click.Choice(sorted(CLAUDE_PROVIDER_PRESETS)),
    default=None,
    help="Named Claude CLI provider preset (for example openrouter-claude, aws-claude, azure-claude, gcp-claude).",
)
@click.option(
    "--openrouter-key-env",
    default="OPENROUTER_API_KEY",
    show_default=True,
    help="Host env var that holds the OpenRouter API key for --openrouter-claude.",
)
@click.option(
    "--claude-base-url",
    default=None,
    help="Set ANTHROPIC_BASE_URL for Claude CLI transport.",
)
@click.option(
    "--claude-auth-token-env",
    default=None,
    help="Copy a host env var into ANTHROPIC_AUTH_TOKEN for Claude CLI transport.",
)
@click.option(
    "--claude-api-key-env",
    default=None,
    help="Copy a host env var into ANTHROPIC_API_KEY for Claude CLI transport.",
)
@click.option(
    "--clear-claude-api-key",
    is_flag=True,
    help="Set ANTHROPIC_API_KEY to an empty string for Claude CLI transport.",
)
@click.option("--bridge-command", default=None, help="Optional background bridge command to launch first.")
@click.option("--bridge-wait", type=float, default=3.0, show_default=True)
@click.option(
    "--task-source-dir",
    "atelierbench_tasks_dir",
    type=click.Path(path_type=Path, file_okay=False),
    default=None,
)
@click.option(
    "--require-pass/--allow-failed-gate",
    default=False,
    show_default=True,
    help="Exit non-zero after writing artifacts when the benchmark gate does not pass.",
)
@click.option(
    "--provider",
    default=None,
    metavar="PROVIDER",
    help=(
        "Cloud provider shorthand: aws/bedrock, gcp/vertex, azure, openrouter. "
        "Reads credentials from .env or the current environment. "
        "Shorthand for --claude-provider-preset; explicit --agent-env takes precedence."
    ),
)
def benchmark_atelierbench_cmd(
    tasks: tuple[str, ...],
    arms: tuple[str, ...],
    reps: int,
    model: str,
    timeout: int,
    rate_limit_rpm: float,
    rate_limit_tpm: int,
    cli_driver: str,
    jobs: int,
    parallel_scope: str,
    judge: bool,
    judge_model: str | None,
    judge_agent_command: str | None,
    agent_command: str,
    agent_env: tuple[str, ...],
    agent_env_from_host: tuple[str, ...],
    cli_extra_args: tuple[str, ...],
    openrouter_claude: bool,
    claude_provider_preset: str | None,
    openrouter_key_env: str,
    claude_base_url: str | None,
    claude_auth_token_env: str | None,
    claude_api_key_env: str | None,
    clear_claude_api_key: bool,
    bridge_command: str | None,
    bridge_wait: float,
    atelierbench_tasks_dir: Path | None,
    require_pass: bool,
    provider: str | None,
) -> None:
    """Run cost/quality comparison (Atelier vs baseline) and write a report."""
    repo_root = Path.cwd().resolve()
    run_dir = _atelierbench_run_dir(repo_root)
    resolved_atelierbench_tasks_dir = _ensure_atelierbench_tasks_dir(repo_root, atelierbench_tasks_dir)
    env = {"ATELIERBENCH_TASKS_DIR": str(resolved_atelierbench_tasks_dir)}
    bridge_args = []
    if bridge_command:
        bridge_args = ["--bridge-command", bridge_command, "--bridge-wait", str(bridge_wait)]
    judge_args = []
    if judge:
        judge_args.append("--judge")
    if judge_model:
        judge_args.extend(["--judge-model", judge_model])
    if judge_agent_command:
        judge_args.extend(["--judge-agent-command", judge_agent_command])
    agent_env_args: list[str] = []
    if provider:
        preset_key = _PROVIDER_ALIASES.get(provider.lower())
        if preset_key is None:
            raise click.ClickException(
                f"unknown --provider {provider!r}; choices: {', '.join(sorted(_PROVIDER_ALIASES))}"
            )
        claude_provider_preset = claude_provider_preset or preset_key
    if openrouter_claude:
        claude_provider_preset = claude_provider_preset or "openrouter-claude"
    if claude_provider_preset:
        preset = resolve_claude_provider_preset(
            claude_provider_preset,
            openrouter_key_env=openrouter_key_env,
        )
        if cli_driver not in preset.supported_drivers:
            raise click.ClickException(
                f"{claude_provider_preset} only supports CLI drivers: {', '.join(preset.supported_drivers)}"
            )
        for key, value in preset.env.items():
            agent_env_args.extend(["--agent-env", f"{key}={value}"])
        for dest, source in preset.env_from_host.items():
            agent_env_args.extend(["--agent-env-from-host", f"{dest}={source}"])
    if claude_base_url:
        agent_env_args.extend(["--agent-env", f"ANTHROPIC_BASE_URL={claude_base_url}"])
    if claude_auth_token_env:
        agent_env_args.extend(["--agent-env-from-host", f"ANTHROPIC_AUTH_TOKEN={claude_auth_token_env}"])
    if claude_api_key_env:
        agent_env_args.extend(["--agent-env-from-host", f"ANTHROPIC_API_KEY={claude_api_key_env}"])
    if clear_claude_api_key:
        agent_env_args.extend(["--agent-env", "ANTHROPIC_API_KEY="])
    for item in agent_env:
        agent_env_args.extend(["--agent-env", item])
    for item in agent_env_from_host:
        agent_env_args.extend(["--agent-env-from-host", item])
    baseline_arm = "baseline" if "baseline" in arms else arms[0]
    candidate_arm = next((arm for arm in arms if arm != baseline_arm), baseline_arm)
    task_catalog = _load_atelierbench_catalog(repo_root)
    task_ids = [task["id"] for task in task_catalog] if tasks == ("all",) else list(tasks)
    task_payload = [task for task in task_catalog if task["id"] in task_ids]
    manifest_path = write_benchmark_manifest(
        run_dir,
        build_atelierbench_manifest(
            tasks=task_payload,
            arms=list(arms),
            reps=reps,
            model=model,
            cli_driver=cli_driver,
            timeout=timeout,
            jobs=jobs,
            parallel_scope=parallel_scope,
            atelierbench_tasks_dir=resolved_atelierbench_tasks_dir,
            bridge_command=bridge_command,
        ),
    )
    repo_state = git_state(repo_root)
    forwarded_cli_extra_args = [f"--cli-extra-arg={arg}" for arg in cli_extra_args]
    progress = ProgressReporter("atelierbench", total=1)
    progress.start("starting benchmark", current=f"{len(tasks)} task selector(s) x {len(arms)} arm(s)")
    _run(
        [
            *_python_cmd(repo_root),
            "-m",
            "benchmarks.atelierbench.run",
            *tasks,
            "--arms",
            *arms,
            "--reps",
            str(reps),
            "--model",
            model,
            "--timeout",
            str(timeout),
            "--rate-limit-rpm",
            str(rate_limit_rpm),
            "--rate-limit-tpm",
            str(rate_limit_tpm),
            "--cli-driver",
            cli_driver,
            "--jobs",
            str(jobs),
            "--parallel-scope",
            parallel_scope,
            "--agent-command",
            agent_command,
            *forwarded_cli_extra_args,
            *agent_env_args,
            *judge_args,
            *bridge_args,
            "--out",
            str(run_dir),
        ],
        cwd=repo_root,
        label="AtelierBench",
        env=env,
    )
    progress.step("benchmark command complete", current=run_dir.name)
    write_benchmark_evidence(
        run_dir,
        build_atelierbench_evidence(
            run_dir=run_dir,
            manifest_path=manifest_path,
            repo_state=repo_state,
        ),
    )
    write_benchmark_gate(
        run_dir,
        evaluate_atelierbench_gate(
            run_dir,
            baseline_arm=baseline_arm,
            candidate_arm=candidate_arm,
        ),
    )
    if require_pass:
        try:
            require_benchmark_gate_pass(run_dir)
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
    progress.finish("benchmark complete")
    click.echo(f"Results: {run_dir}")


def _atelierbench_run_dir(repo_root: Path) -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = repo_root.resolve() / "benchmarks" / "atelierbench" / "results" / timestamp
    path.mkdir(parents=True, exist_ok=True)
    return path


def _run_dir(suite: str, out: Path | None, *, repo_root: Path | None = None) -> Path:
    if out is not None:
        path = out.resolve()
    else:
        root = (repo_root or Path.cwd()).resolve()
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        path = root / "reports" / "benchmark" / suite / timestamp
    path.mkdir(parents=True, exist_ok=True)
    return path


def _workspace_dir(suite: str, *, repo_root: Path, run_id: str) -> Path:
    path = repo_root.resolve().parent / "benchmarks" / repo_root.name / suite / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def _cache_dir(suite: str, *, repo_root: Path) -> Path:
    path = repo_root.resolve().parent / "benchmarks" / repo_root.name / f"{suite}-cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _csv_values(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def _auto_jobs(item_count: int, *, hard_cap: int) -> int:
    detected = max(cpu_count() or 1, 1)
    return max(1, min(item_count, hard_cap, detected))


def _resolve_mcp_jobs(requested_jobs: int, *, repo_root: Path) -> int:
    if requested_jobs > 0:
        return requested_jobs
    repo_root = repo_root.resolve()
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))
    from benchmarks.mcp_tools.export_public_mcp_csv import _select_suite_specs

    return _auto_jobs(len(_select_suite_specs(None)), hard_cap=32)


def _resolve_provider_jobs(requested_jobs: int, providers: list[str]) -> int:
    if requested_jobs > 0:
        return requested_jobs
    return _auto_jobs(len(providers), hard_cap=32)


def _ensure_atelierbench_tasks_dir(repo_root: Path, configured_dir: Path | None) -> Path:
    resolved = (
        configured_dir.resolve()
        if configured_dir is not None
        else repo_root.parent / "benchmarks" / repo_root.name / "atelierbench-tasks"
    )
    tasks_dir = resolved / "tasks"
    if tasks_dir.is_dir():
        return resolved
    raise click.ClickException(
        f"AtelierBench tasks directory not found: {tasks_dir}\n"
        "Pass --task-source-dir pointing to a directory that contains a 'tasks/' subdirectory."
    )


def _python_cmd(repo_root: Path) -> list[str]:
    repo_root = repo_root.resolve()
    if which("uv") and (repo_root / "pyproject.toml").is_file():
        return ["uv", "run", "--project", str(repo_root), "python"]
    return [sys.executable]


def _bench_source_root() -> Path:
    """Atelier source root that contains the ``benchmarks/`` harness package.

    The ``benchmarks.*`` packages live in the Atelier source tree, not in the
    target repo under test, so subprocesses that import them must run from here
    (the target repo is passed explicitly via ``--repo-root``).
    """
    return Path(__file__).resolve().parents[5]


def _load_atelierbench_catalog(repo_root: Path) -> list[dict[str, object]]:
    tasks_path = repo_root / "benchmarks" / "atelierbench" / "tasks.py"
    module_name = "_atelierbench_tasks"
    spec = importlib.util.spec_from_file_location(module_name, tasks_path)
    if spec is None or spec.loader is None:
        raise click.ClickException(f"Unable to load AtelierBench task catalog: {tasks_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    tasks = getattr(module, "TASKS", None)
    if not isinstance(tasks, list):
        raise click.ClickException(f"Invalid AtelierBench task catalog: {tasks_path}")
    catalog: list[dict[str, object]] = []
    for task in tasks:
        task_id = getattr(task, "id", None)
        language = getattr(task, "language", None)
        weight = getattr(task, "weight", None)
        task_dir = getattr(task, "task_dir", None)
        source = getattr(task, "source", None)
        if (
            not isinstance(task_id, str)
            or not isinstance(language, str)
            or not isinstance(weight, int)
            or not isinstance(task_dir, str)
        ):
            raise click.ClickException(f"Invalid AtelierBench task metadata: {tasks_path}")
        catalog.append(
            {
                "id": task_id,
                "language": language,
                "weight": weight,
                "task_dir": task_dir,
                "source": list(source) if isinstance(source, tuple) else [],
            }
        )
    return catalog


def _run(cmd: list[str], *, cwd: Path, label: str, env: dict[str, str] | None = None) -> None:
    click.echo("Running: " + _display_cmd(cmd))
    run_env = None
    if env is not None:
        run_env = dict(environ)
        run_env.update(env)
    completed = subprocess.run(cmd, check=False, cwd=cwd, env=run_env)
    if completed.returncode != 0:
        raise click.ClickException(f"{label} failed with exit {completed.returncode}")


def _display_cmd(cmd: list[str]) -> str:
    if "-c" not in cmd:
        return " ".join(cmd)
    index = cmd.index("-c")
    compact = [*cmd[: index + 1], "<inline python>", *cmd[index + 2 :]]
    return " ".join(compact)
