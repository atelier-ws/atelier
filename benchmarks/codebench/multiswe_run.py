"""One-command Multi-SWE-bench A/B: vanilla Claude Code vs Atelier, in-container.

Pipeline (single command):
  load+filter instances -> build per-arm overlays -> run each (instance, arm,
  rep) inside its Docker image -> extract the git diff -> grade every diff with
  the official multi_swe_bench harness -> reuse run.py savings/report/CSV.

The arms differ only in overlay contents + claude flags (baseline = vanilla
Claude Code; atelier = + Atelier plugin/MCP), same model, same instance -- the
clean isolation that attributes any cost/quality delta to Atelier alone.

Example:
  uv run --project benchmarks python -m benchmarks.codebench.multiswe_run \
      --languages go rust --per-language-limit 5 --reps 1 --model sonnet --jobs 2
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import time
import urllib.request
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from benchmarks.codebench import grade, incontainer, multiswe, swebench_data, swebench_grade
from benchmarks.codebench.run import (
    BY_ID,
    RESULTS_ROOT,
    ArmResult,
    _apply_savings,
    _load_benchmark_env,
    _write_results_jsonl,
    build_pairwise_quality_rows,
    report,
    write_csv_artifacts,
)
from benchmarks.codebench.tasks import Task

FLASH_URL = (
    "https://huggingface.co/datasets/ByteDance-Seed/Multi-SWE-bench-flash/resolve/main/multi_swe_bench_flash.jsonl"
)
DATA_DIR = Path(__file__).parent / "data"
ARMS = ("baseline", "atelier")


def ensure_flash() -> Path:
    """Download the flash dataset (7 non-Python languages) to the cache if absent."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / "multi_swe_bench_flash.jsonl"
    if not path.exists() or path.stat().st_size < 1_000_000:
        print(f"[dataset] downloading flash -> {path}", flush=True)
        urllib.request.urlretrieve(FLASH_URL, path)
    return path


def _register_stub_task(inst: Any) -> None:
    """Register a lightweight Task so run.py's reporting BY_ID lookups resolve."""
    if inst.instance_id not in BY_ID:
        BY_ID[inst.instance_id] = Task(
            inst.instance_id, inst.language, ("empty",), 1, inst.instance_id, capability="code"
        )


def _patch_path(out_dir: Path, inst: Any, arm: str, rep: int) -> Path:
    return out_dir / f"{inst.instance_id}_{arm}_rep{rep}.patch"


def _prebuild_overlays(instances: list[Any], arms: list[str]) -> None:
    """Build every needed overlay serially up front so parallel runs don't race."""
    seen: set[tuple[str, bool]] = set()
    for inst in instances:
        for arm in arms:
            key = (inst.image, arm == "atelier")
            if key in seen:
                continue
            seen.add(key)
            print(f"[overlay] ensuring {arm} overlay for {inst.image}", flush=True)
            incontainer.ensure_overlay(inst.image, atelier=(arm == "atelier"))


def _grade_arms(
    instances: list[Any],
    results: list[ArmResult],
    *,
    out_dir: Path,
    reps: int,
    arms: list[str],
    grade_workers: int,
    grade_fn: Callable[[list[Any], dict[str, str], Path, int], dict[str, bool]],
    label: str,
) -> None:
    by_id = {inst.instance_id: inst for inst in instances}
    for arm in arms:
        for rep in range(1, reps + 1):
            group = [r for r in results if r.arm == arm and r.rep == rep]
            if not group:
                continue
            insts = [by_id[r.task] for r in group if r.task in by_id]
            patches = {
                inst.instance_id: _patch_path(out_dir, inst, arm, rep).read_text(encoding="utf-8")
                for inst in insts
                if _patch_path(out_dir, inst, arm, rep).exists()
            }
            print(f"[grade] {arm} rep{rep}: {len(patches)} patch(es)", flush=True)
            resolved = grade_fn(insts, patches, out_dir / f"grade_{arm}_rep{rep}", grade_workers)
            for r in group:
                ok = bool(resolved.get(r.task, False))
                r.correct = ok
                r.score = 1.0 if ok else 0.0
                r.judge_model = label
                r.judge_reason = "resolved" if ok else "unresolved"


GradeFn = Callable[[list[Any], dict[str, str], Path, int], dict[str, bool]]


def _select_backend(args: argparse.Namespace) -> tuple[list[Any], GradeFn, str]:
    """Resolve (instances, grade_fn, judge-label) for the selected ``--suite``.

    swe-bench-verified -> SWE-bench (Python), graded by the ``swebench`` harness;
    multi-swe-bench -> the 7 non-Python languages, graded by ``multi_swe_bench``.
    """
    if args.suite == "swe-bench-verified":
        instances = swebench_data.load_instances(
            dataset=args.dataset,
            instances=args.instances,
            min_changed_files=args.min_changed_files,
            limit=args.limit,
        )

        def grade_swe(insts: list[Any], patches: dict[str, str], work_dir: Path, workers: int) -> dict[str, bool]:
            return swebench_grade.grade(
                insts, patches, dataset_name=args.dataset, work_dir=work_dir, max_workers=workers, timeout=args.timeout
            )

        return list(instances), grade_swe, "swebench"

    dataset_path = Path(args.dataset) if args.dataset else ensure_flash()
    # Explicit --instances must never be silently dropped by the corpus filters
    # (min-changed-files / per-language / limit). Those filters shape the *random*
    # sample; an explicitly named instance is a deliberate request, so bypass them
    # and surface any id missing from the dataset instead of dropping it quietly.
    explicit = set(args.instances) if args.instances else None
    multi = multiswe.load_instances(
        dataset_path,
        languages=args.languages,
        min_changed_files=0 if explicit else args.min_changed_files,
        per_language_limit=None if explicit else args.per_language_limit,
        limit=None if explicit else args.limit,
    )
    if explicit:
        multi = [i for i in multi if i.instance_id in explicit]
        missing = explicit - {i.instance_id for i in multi}
        if missing:
            print(f"[warn] requested --instances not found in dataset: {sorted(missing)}", flush=True)

    def grade_multi(insts: list[Any], patches: dict[str, str], work_dir: Path, workers: int) -> dict[str, bool]:
        return grade.grade(insts, patches, dataset_path=dataset_path, work_dir=work_dir, max_workers=workers)

    return list(multi), grade_multi, "multiswe"


def _load_prior_results(out_dir: Path) -> dict[tuple[str, str, int], ArmResult]:
    """Index an existing results.jsonl by (task, arm, rep) for --resume reuse.

    Each row is ``asdict(ArmResult)`` so it round-trips back via ``ArmResult(**row)``
    (extra/unknown keys are dropped defensively against schema drift).
    """
    path = out_dir / "results.jsonl"
    if not path.exists():
        return {}
    names = {f.name for f in dataclasses.fields(ArmResult)}
    prior: dict[tuple[str, str, int], ArmResult] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        res = ArmResult(**{k: v for k, v in row.items() if k in names})
        prior[(res.task, res.arm, res.rep)] = res
    return prior


def run(args: argparse.Namespace) -> int:
    instances, grade_fn, grade_label = _select_backend(args)
    if not instances:
        print("no instances matched the filters", flush=True)
        return 1
    for inst in instances:
        _register_stub_task(inst)

    # Resolve to absolute: out_dir feeds docker -v bind mounts (prompt.txt, flow)
    # and the grader's predictions path; a relative path makes docker reject the
    # mount ("invalid characters for a local volume name") and grading FileNotFound.
    out_dir = (Path(args.out) if args.out else RESULTS_ROOT / f"multiswe-{time.strftime('%Y%m%d-%H%M%S')}").resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    print(f"[run] {len(instances)} instance(s) x {len(args.arms)} arm(s) x {args.reps} rep(s)", flush=True)
    print(f"[run] results -> {out_dir}", flush=True)

    _prebuild_overlays(instances, args.arms)

    agent_env = _load_benchmark_env()
    jobs = [(inst, arm, rep) for inst in instances for arm in args.arms for rep in range(1, args.reps + 1)]
    # --resume: reuse a prior (task, arm, rep) result when its patch artifact is
    # still present, so a re-run re-executes only the missing/stripped jobs (e.g.
    # keep valid baseline runs, re-run atelier after a fix) without re-paying.
    prior = _load_prior_results(out_dir) if getattr(args, "resume", False) else {}
    results: list[ArmResult] = []
    pending: list[tuple[Any, str, int]] = []
    for job in jobs:
        inst, arm, rep = job
        cached = prior.get((inst.instance_id, arm, rep))
        if cached is not None and _patch_path(out_dir, inst, arm, rep).exists():
            results.append(cached)
            print(f"  -> {inst.instance_id}/{arm} rep{rep}: reused (resume)", flush=True)
        else:
            pending.append(job)
    if prior:
        # Carry forward prior rows outside this run's scope so a narrower resume
        # (e.g. -a atelier only) never drops the rows it isn't re-running.
        covered = {(i.instance_id, a, r) for (i, a, r) in jobs}
        preserved = [res for key, res in prior.items() if key not in covered]
        results.extend(preserved)
        print(
            f"[resume] reused {len(results) - len(preserved)} in-scope + carried {len(preserved)} "
            f"out-of-scope prior result(s); running {len(pending)} job(s)",
            flush=True,
        )

    def _one(job: tuple[Any, str, int]) -> ArmResult:
        inst, arm, rep = job
        return incontainer.run_in_container(
            inst,
            arm,
            rep,
            model=args.model,
            out_dir=out_dir,
            timeout=args.timeout,
            agent_env=agent_env,
            max_turns=args.max_turns,
        )

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        futures = {pool.submit(_one, job): job for job in pending}
        for fut in as_completed(futures):
            inst, arm, rep = futures[fut]
            try:
                res = fut.result()
            except Exception as exc:  # keep going; record a failed row
                res = ArmResult(
                    inst.instance_id,
                    arm,
                    rep,
                    False,
                    0.0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    0,
                    [],
                    True,
                    f"runner error: {exc}"[:200],
                    "",
                )
            results.append(res)
            # Persist incrementally so partial progress is durable and visible
            # mid-run (resume-safe: `results` already holds reused/preserved rows,
            # so a full rewrite never duplicates). Runs in the main thread, so the
            # as_completed loop serializes these writes.
            _write_results_jsonl(out_dir, results)
            print(
                f"  -> {inst.instance_id}/{arm} rep{rep}: ok={res.ok} cost=${res.cost_usd:.4f} turns={res.num_turns}",
                flush=True,
            )

    if not args.no_grade:
        _grade_arms(
            instances,
            results,
            out_dir=out_dir,
            reps=args.reps,
            arms=args.arms,
            grade_workers=args.grade_workers,
            grade_fn=grade_fn,
            label=grade_label,
        )

    _apply_savings(results)
    pairwise = build_pairwise_quality_rows(results)
    _write_results_jsonl(out_dir, results)
    write_csv_artifacts(out_dir, results, pairwise)
    rendered = report(results)
    (out_dir / "report.txt").write_text(rendered, encoding="utf-8")
    print(rendered, flush=True)
    return 0


def main() -> int:
    p = argparse.ArgumentParser(
        description="SWE A/B: vanilla Claude Code vs Atelier, in-container (multi-swe-bench or swe-bench)"
    )
    p.add_argument(
        "--suite",
        choices=["multi-swe-bench", "swe-bench-verified"],
        default="multi-swe-bench",
        help="Backend: multi-swe-bench (7 non-Python langs) or swe-bench-verified (Python).",
    )
    p.add_argument("--dataset", default=None, help="Dataset path/name (default: per-suite default)")
    p.add_argument("--languages", nargs="*", default=None, help="Filter to these languages (multi-swe-bench only)")
    p.add_argument("--per-language-limit", type=int, default=None, help="Max instances per language")
    p.add_argument("--min-changed-files", type=int, default=2, help="Min files in the gold patch (multi-file filter)")
    p.add_argument("--limit", type=int, default=None, help="Max total instances")
    p.add_argument("--instances", nargs="*", default=None, help="Explicit instance ids to run")
    p.add_argument("-a", "--arms", nargs="*", default=list(ARMS), choices=ARMS)
    p.add_argument("--reps", type=int, default=1)
    p.add_argument("--model", default="sonnet")
    p.add_argument(
        "--max-turns",
        type=int,
        default=50,
        help=(
            "Runaway-loop safety cap on agentic turns. Kept at 50: raising it to 100 let "
            "non-converging tasks spiral into the 1800s --timeout wall (more cost, same "
            "failure) instead of stopping early. Converging tasks finish well below it."
        ),
    )
    p.add_argument("--timeout", type=int, default=1800, help="Per-run agent timeout (s)")
    p.add_argument("--jobs", type=int, default=1, help="Parallel container runs")
    p.add_argument("--grade-workers", type=int, default=4, help="multi_swe_bench eval workers")
    p.add_argument("--no-grade", action="store_true", help="Skip Docker grading (cost/turns only)")
    p.add_argument(
        "--resume",
        action="store_true",
        help="Reuse existing results.jsonl rows whose patch artifact is present; run only the rest",
    )
    p.add_argument("--out", default=None, help="Results dir")
    return run(p.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
