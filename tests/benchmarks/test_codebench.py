from __future__ import annotations

import asyncio
import csv
import importlib
import json
import sys
import time
import types
from itertools import pairwise
from pathlib import Path
from types import ModuleType
from typing import Any

from pytest import MonkeyPatch

ROOT = Path(__file__).resolve().parents[2]


def _ensure_benchmarks_package() -> None:
    import benchmarks

    benchmark_paths = list(getattr(benchmarks, "__path__", []))
    root_path = str(ROOT / "benchmarks")
    src_path = str(ROOT / "src" / "benchmarks")
    for path in (root_path, src_path):
        if path not in benchmark_paths:
            benchmark_paths.append(path)
    benchmarks.__path__ = benchmark_paths

    codebench_pkg = sys.modules.get("benchmarks.codebench")
    if codebench_pkg is None:
        codebench_pkg = types.ModuleType("benchmarks.codebench")
        sys.modules["benchmarks.codebench"] = codebench_pkg
    codebench_paths = list(getattr(codebench_pkg, "__path__", []))
    root_codebench_path = str(ROOT / "benchmarks" / "codebench")
    if root_codebench_path not in codebench_paths:
        codebench_paths.append(root_codebench_path)
    codebench_pkg.__path__ = codebench_paths


def _load(module_name: str) -> ModuleType:
    _ensure_benchmarks_package()
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


CODEBENCH = _load("benchmarks.codebench.run")
RATE_LIMIT = _load("benchmarks.codebench.rate_limit")
TASKS = _load("benchmarks.codebench.tasks")


def test_arm_specs_resolve_persona_by_capability() -> None:
    specs = CODEBENCH.ARM_SPECS
    # baseline runs the built-in twin per capability (vanilla default for code).
    assert specs["baseline"].persona_by_capability == {
        "code": None,
        "explore": "Explore",
        "plan": "Plan",
    }
    # atelier runs the generated plugin's personas; code keeps the prior behavior.
    assert specs["atelier"].plugin is True
    assert specs["atelier"].strip_mcp is False
    assert specs["atelier"].persona_by_capability["code"] == "atelier:code"
    assert specs["atelier"].persona_by_capability["explore"] == "atelier:explore"
    # execute / solve are code-only coding personas (no built-in twin).
    assert set(specs["execute"].persona_by_capability) == {"code"}
    assert set(specs["solve"].persona_by_capability) == {"code"}
    assert CODEBENCH.VALID_ARMS == ("baseline", "atelier", "execute", "solve")
    assert CODEBENCH.HEAVY_ARMS == ("atelier", "execute", "solve")


def test_arm_applicability_skips_coding_arms_on_explore_tasks() -> None:
    # The (arm, capability) predicate _run_task_rep consults to skip arms.
    def applies(arm: str, capability: str) -> bool:
        return capability in CODEBENCH.ARM_SPECS[arm].persona_by_capability

    assert applies("baseline", "explore") and applies("atelier", "explore")
    assert not applies("execute", "explore") and not applies("solve", "explore")
    assert applies("execute", "code") and applies("solve", "code")


def _armresult(task: str, excerpt: str, ok: bool = True) -> Any:
    return CODEBENCH.ArmResult(task, "atelier", 0, ok, 0.0, 0, 0, 0, 0, 0, 0, 0, [], False, excerpt, "")


def test_grade_explore_marks_correct_when_answer_key_matches(monkeypatch: MonkeyPatch) -> None:
    task = TASKS.Task("explore_probe", "python", ("empty",), 1, "explore_probe", capability="explore")
    monkeypatch.setitem(CODEBENCH.BY_ID, "explore_probe", task)
    monkeypatch.setattr(CODEBENCH, "_task_answer_key", lambda _t: (["run_arm", "VALID_ARMS", "ArmSpec"], [], 0.6))
    res = _armresult("explore_probe", "The runner's run_arm dispatches each ArmSpec; see VALID_ARMS.")
    CODEBENCH._grade_explore(res)
    assert res.judge_model == "answer"
    assert res.correct is True
    assert res.score == 1.0


def test_grade_explore_fails_below_threshold(monkeypatch: MonkeyPatch) -> None:
    task = TASKS.Task("explore_probe", "python", ("empty",), 1, "explore_probe", capability="explore")
    monkeypatch.setitem(CODEBENCH.BY_ID, "explore_probe", task)
    monkeypatch.setattr(
        CODEBENCH,
        "_task_answer_key",
        lambda _t: (["run_arm", "VALID_ARMS", "ArmSpec", "judge_results"], [], 0.6),
    )
    res = _armresult("explore_probe", "I think it uses run_arm somewhere.")
    CODEBENCH._grade_explore(res)
    assert res.correct is False
    assert res.score == 0.25


def test_grade_explore_zeroes_score_when_forbidden_token_present(monkeypatch: MonkeyPatch) -> None:
    task = TASKS.Task("explore_probe", "python", ("empty",), 1, "explore_probe", capability="explore")
    monkeypatch.setitem(CODEBENCH.BY_ID, "explore_probe", task)
    monkeypatch.setattr(CODEBENCH, "_task_answer_key", lambda _t: (["run_arm"], ["i cannot"], 0.5))
    res = _armresult("explore_probe", "I cannot find run_arm in this workspace.")
    CODEBENCH._grade_explore(res)
    assert res.correct is False
    assert res.score == 0.0


def test_plan_mentions_path_matches_full_and_basename() -> None:
    assert CODEBENCH._plan_mentions_path("I'd edit benchmarks/codebench/run.py", "benchmarks/codebench/run.py")
    assert CODEBENCH._plan_mentions_path("change store.py and orders.py", "inventory/store.py")
    assert not CODEBENCH._plan_mentions_path("touch limits.py only", "inventory/store.py")


def test_grade_plan_scores_target_file_overlap(monkeypatch: MonkeyPatch) -> None:
    task = TASKS.Task("plan_probe", "python", ("empty",), 1, "plan_probe", capability="plan")
    monkeypatch.setitem(CODEBENCH.BY_ID, "plan_probe", task)
    monkeypatch.setattr(
        CODEBENCH,
        "_task_plan_key",
        lambda _t: (["inventory/store.py", "inventory/orders.py", "inventory/__init__.py"], "", 0.6),
    )
    good = _armresult(
        "plan_probe",
        "Add release_stock to store.py, a cancel_order in orders.py, and export it from __init__.py.",
    )
    CODEBENCH._grade_plan(good)
    assert good.judge_model == "plan"
    assert good.correct is True
    assert good.score == 1.0
    thin = _armresult("plan_probe", "I'll change store.py only.")
    CODEBENCH._grade_plan(thin)
    assert thin.correct is False
    assert thin.score == round(1 / 3, 3)


def test_grade_plan_combines_overlap_and_rubric_judge(monkeypatch: MonkeyPatch) -> None:
    task = TASKS.Task("plan_probe", "python", ("empty",), 1, "plan_probe", capability="plan")
    monkeypatch.setitem(CODEBENCH.BY_ID, "plan_probe", task)
    monkeypatch.setattr(
        CODEBENCH,
        "_task_plan_key",
        lambda _t: (["inventory/store.py", "inventory/orders.py"], "rubric text", 0.6),
    )
    # Stub the LLM half so no subprocess runs: a weak-quality verdict.
    monkeypatch.setattr(CODEBENCH, "_run_plan_judge", lambda *a, **k: {"score": 0.4, "reason": "shaky approach"})
    res = _armresult("plan_probe", "Edit store.py and orders.py to add release_stock.")
    CODEBENCH._grade_plan(res, run_judge=True, judge_model="sonnet")
    # overlap 2/2 = 1.0 combined with rubric 0.4 -> mean 0.7
    assert res.judge_model == "plan"
    assert res.score == 0.7
    assert res.correct is True


def test_grade_plan_overlap_only_when_judge_disabled(monkeypatch: MonkeyPatch) -> None:
    task = TASKS.Task("plan_probe", "python", ("empty",), 1, "plan_probe", capability="plan")
    monkeypatch.setitem(CODEBENCH.BY_ID, "plan_probe", task)
    monkeypatch.setattr(
        CODEBENCH, "_task_plan_key", lambda _t: (["inventory/store.py", "inventory/orders.py"], "rubric text", 0.6)
    )

    def _boom(*_a: object, **_k: object) -> object:
        raise AssertionError("rubric judge must not run when run_judge is False")

    monkeypatch.setattr(CODEBENCH, "_run_plan_judge", _boom)
    res = _armresult("plan_probe", "Edit store.py and orders.py.")
    CODEBENCH._grade_plan(res)  # run_judge defaults False
    assert res.score == 1.0
    assert res.judge_model == "plan"


def test_rate_limiter_does_not_block_proxy_event_loop(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("CODEBENCH_RATE_LIMIT_RPM", "1200")
    limiter = RATE_LIMIT.ModelRequestRateLimiter()
    flow = types.SimpleNamespace(
        request=types.SimpleNamespace(
            path="/model/test/invoke-with-response-stream",
            headers={},
            get_text=lambda strict=False: '{"max_tokens": 32000}',
        )
    )
    ticks: list[float] = []

    async def heartbeat() -> None:
        for _ in range(6):
            ticks.append(time.monotonic())
            await asyncio.sleep(0.01)

    async def exercise() -> None:
        await asyncio.gather(limiter.request(flow), limiter.request(flow), heartbeat())

    asyncio.run(exercise())

    assert len(ticks) == 6
    assert max(later - earlier for earlier, later in pairwise(ticks)) < 0.04
    assert flow.request.headers["Connection"] == "close"


def test_rate_limiter_accounts_for_reserved_output_tokens(
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.setenv("CODEBENCH_RATE_LIMIT_RPM", "10")
    monkeypatch.setenv("CODEBENCH_RATE_LIMIT_TPM", "100000")
    limiter = RATE_LIMIT.ModelRequestRateLimiter()
    limiter._token_reservations.extend([(100.0, 32000), (106.0, 32000), (112.0, 32000)])

    assert limiter._token_delay(118.0, 32000) == 42.0
    assert limiter._token_delay(160.0, 32000) == 0.0


def test_write_csv_artifacts_emits_detail_and_summary(tmp_path: Path) -> None:
    results = [
        CODEBENCH.ArmResult(
            task="task-1",
            arm="baseline",
            rep=0,
            ok=True,
            cost_usd=1.25,
            duration_ms=1000,
            duration_api_ms=800,
            num_turns=3,
            input_tokens=100,
            cache_read_tokens=10,
            cache_creation_tokens=0,
            output_tokens=25,
            models=["sonnet"],
            is_error=False,
            result_excerpt="ok",
            flow_path="baseline.flow",
        ),
        CODEBENCH.ArmResult(
            task="task-1",
            arm="atelier",
            rep=0,
            ok=True,
            cost_usd=0.75,
            duration_ms=700,
            duration_api_ms=500,
            num_turns=2,
            input_tokens=70,
            cache_read_tokens=20,
            cache_creation_tokens=5,
            output_tokens=20,
            models=["sonnet"],
            is_error=False,
            result_excerpt="ok",
            flow_path="atelier.flow",
        ),
        CODEBENCH.ArmResult(
            task="task-1",
            arm="eval",
            rep=0,
            ok=True,
            cost_usd=1.0,
            duration_ms=900,
            duration_api_ms=650,
            num_turns=2,
            input_tokens=80,
            cache_read_tokens=15,
            cache_creation_tokens=0,
            output_tokens=22,
            models=["sonnet"],
            is_error=False,
            result_excerpt="ok",
            flow_path="eval.flow",
        ),
    ]

    CODEBENCH.write_csv_artifacts(tmp_path, results)

    with (tmp_path / "results.csv").open("r", encoding="utf-8", newline="") as handle:
        detail_rows = list(csv.DictReader(handle))
    with (tmp_path / "summary.csv").open("r", encoding="utf-8", newline="") as handle:
        summary_rows = list(csv.DictReader(handle))
    with (tmp_path / "task_metrics.csv").open("r", encoding="utf-8", newline="") as handle:
        task_metric_rows = list(csv.DictReader(handle))
    with (tmp_path / "task_correctness.csv").open("r", encoding="utf-8", newline="") as handle:
        task_correctness_rows = list(csv.DictReader(handle))
    with (tmp_path / "pairwise_quality.csv").open("r", encoding="utf-8", newline="") as handle:
        pairwise_rows = list(csv.DictReader(handle))
    with (tmp_path / "quality_adjusted_summary.csv").open("r", encoding="utf-8", newline="") as handle:
        adjusted_rows = list(csv.DictReader(handle))
    with (tmp_path / "model_audit.csv").open("r", encoding="utf-8", newline="") as handle:
        model_rows = list(csv.DictReader(handle))

    assert len(detail_rows) == 3
    assert {row["arm"] for row in summary_rows} == {"baseline", "atelier", "eval"}
    atelier_row = next(row for row in summary_rows if row["arm"] == "atelier")
    vix_row = next(row for row in summary_rows if row["arm"] == "eval")
    assert atelier_row["cost_usd"] == "0.75"
    assert atelier_row["cost_savings_vs_baseline_pct"] == "40.0"
    assert atelier_row["duration_savings_vs_baseline_pct"] == "30.0"
    assert atelier_row["input_token_savings_vs_baseline_pct"] == "30.0"
    assert atelier_row["output_token_savings_vs_baseline_pct"] == "20.0"
    assert atelier_row["valid_runs"] == "1"
    assert vix_row["cost_savings_vs_baseline_pct"] == "20.0"
    assert {row["candidate_arm"] for row in task_metric_rows} == {"atelier", "eval"}
    atelier_task_row = next(row for row in task_metric_rows if row["candidate_arm"] == "atelier")
    assert atelier_task_row["baseline_cost_usd_median"] == "1.25"
    assert atelier_task_row["candidate_cost_usd_median"] == "0.75"
    assert atelier_task_row["cost_savings_vs_baseline_pct"] == "40.0"
    assert atelier_task_row["baseline_tokens_median"] == "135"
    assert atelier_task_row["candidate_tokens_median"] == "115"
    assert atelier_task_row["tokens_savings_vs_baseline_pct"] == "14.8"
    assert atelier_task_row["tool_calls_savings_vs_baseline_pct"] == "33.3"
    assert {row["candidate_arm"] for row in task_correctness_rows} == {"atelier", "eval"}
    assert next(row for row in task_correctness_rows if row["candidate_arm"] == "atelier")["winner"] == "unjudged"
    assert {row["candidate_arm"] for row in pairwise_rows} == {"atelier", "eval"}
    assert next(row for row in pairwise_rows if row["candidate_arm"] == "atelier")["status"] == "unjudged"
    assert {row["candidate_arm"] for row in adjusted_rows} == {"atelier", "eval"}
    assert next(row for row in adjusted_rows if row["candidate_arm"] == "atelier")["raw_saved_usd"] == "0.5"
    assert {row["source"] for row in model_rows} == {"result_totals"}

    report = CODEBENCH.report(results)
    assert "=== Per-task medians (clean runs) ===" in report
    assert "| task-1 | atelier | 40% cheaper | 14.8% fewer | 30% faster | 33.3% fewer | 1 |" in report
    assert "| task-1 | baseline | 1.2500 | 135 | 1.0 | 3 | 1 |" in report
    assert "=== Per-task correctness and cost ===" in report
    assert "| task-1 | atelier | 0/0 | unjudged | unjudged | $0.7500 | 40% cheaper | unjudged |" in report
    assert "Quality     : unjudged" in report
    assert "task_correctness.csv" in report
    assert "model_audit.csv" in report


def test_task_correctness_rows_pick_winner_from_score_then_cost() -> None:
    baseline = CODEBENCH.ArmResult(
        task="task-1",
        arm="baseline",
        rep=0,
        ok=True,
        cost_usd=1.25,
        duration_ms=1000,
        duration_api_ms=800,
        num_turns=3,
        input_tokens=100,
        cache_read_tokens=10,
        cache_creation_tokens=0,
        output_tokens=25,
        models=["sonnet"],
        is_error=False,
        result_excerpt="ok",
        flow_path="baseline.flow",
        correct=True,
        score=0.8,
        judge_model="verify",
    )
    candidate = CODEBENCH.ArmResult(
        task="task-1",
        arm="atelier",
        rep=0,
        ok=True,
        cost_usd=0.75,
        duration_ms=700,
        duration_api_ms=500,
        num_turns=2,
        input_tokens=70,
        cache_read_tokens=20,
        cache_creation_tokens=5,
        output_tokens=20,
        models=["sonnet"],
        is_error=False,
        result_excerpt="ok",
        flow_path="atelier.flow",
        correct=True,
        score=0.8,
        judge_model="verify",
    )

    rows = CODEBENCH._task_correctness_rows([baseline, candidate])

    assert rows == [
        {
            "task": "task-1",
            "baseline_arm": "baseline",
            "candidate_arm": "atelier",
            "baseline_runs": 1,
            "candidate_runs": 1,
            "baseline_judged_runs": 1,
            "candidate_judged_runs": 1,
            "baseline_correct_runs": 1,
            "candidate_correct_runs": 1,
            "baseline_avg_score": 0.8,
            "candidate_avg_score": 0.8,
            "correctness_delta": 0.0,
            "baseline_cost_usd": 1.25,
            "candidate_cost_usd": 0.75,
            "cost_savings_vs_baseline_pct": 40.0,
            "winner": "atelier",
            "baseline_judge_models": "verify",
            "candidate_judge_models": "verify",
        }
    ]


def test_pairwise_quality_judge_counts_only_non_regressed_savings(monkeypatch: MonkeyPatch) -> None:
    task = TASKS.Task("pair_probe", "python", ("empty",), 1, "pair_probe")
    monkeypatch.setitem(CODEBENCH.BY_ID, "pair_probe", task)
    monkeypatch.setattr(CODEBENCH, "_task_description", lambda _task: "rubric")
    monkeypatch.setattr(
        CODEBENCH, "_run_judge", lambda *a, **k: {"winner": "A", "a_score": 0.9, "b_score": 0.7, "reason": "A richer"}
    )
    monkeypatch.setattr(CODEBENCH, "_candidate_first", lambda *_args: True)
    baseline = CODEBENCH.ArmResult(
        "pair_probe", "baseline", 0, True, 1.0, 10, 9, 1, 100, 0, 0, 10, ["sonnet"], False, "base", ""
    )
    candidate = CODEBENCH.ArmResult(
        "pair_probe", "atelier", 0, True, 0.4, 8, 7, 1, 50, 0, 0, 8, ["sonnet"], False, "better", ""
    )

    rows = CODEBENCH.judge_pairwise_quality(
        [baseline, candidate], judge_model="sonnet", judge_agent_command="claude", timeout=30
    )
    adjusted = CODEBENCH._quality_adjusted_summary_rows(rows)

    assert rows[0].judged is True
    assert rows[0].winner == "atelier"
    assert rows[0].candidate_at_least_baseline is True
    assert rows[0].quality_adjusted_saved_usd == 0.6
    assert adjusted[0]["quality_passed_pairs"] == 1
    assert adjusted[0]["quality_adjusted_saved_usd"] == 0.6


def test_task_prompt_prefers_variant_prompt_when_prompt_md_missing(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    task_source_dir = tmp_path / "codebench-tasks"
    task_dir = task_source_dir / "tasks" / "task2_variant"
    task_dir.mkdir(parents=True)
    (task_dir / "prompt_medium.md").write_text("medium prompt", encoding="utf-8")
    (task_dir / "prompt_hard.md").write_text("hard prompt", encoding="utf-8")
    monkeypatch.setenv("CODEBENCH_TASKS_DIR", str(task_source_dir))

    task = TASKS.Task("task2", "swift", ("empty",), 1, "task2_variant")

    assert task.prompt() == "hard prompt"


def test_main_resume_skips_existing_runs(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    existing = CODEBENCH.ArmResult(
        task="task-1",
        arm="baseline",
        rep=0,
        ok=True,
        cost_usd=1.0,
        duration_ms=10,
        duration_api_ms=9,
        num_turns=1,
        input_tokens=11,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        output_tokens=7,
        models=["sonnet"],
        is_error=False,
        result_excerpt="ok",
        flow_path="baseline.flow",
    )
    (run_dir / "results.jsonl").write_text(json.dumps(existing.__dict__) + "\n", encoding="utf-8")

    task = TASKS.Task("task-1", "swift", ("empty",), 1, "task1")
    monkeypatch.setattr(CODEBENCH, "TASKS", [task])
    monkeypatch.setattr(CODEBENCH, "BY_ID", {task.id: task})

    calls: list[tuple[str, str, int]] = []

    def fake_run_arm(
        task_obj: Any,
        arm: str,
        rep: int,
        model: str,
        out_dir: Path,
        timeout: int,
        agent_command: str = "claude",
        cli_driver: str = "claude",
        agent_env: dict[str, str] | None = None,
        cli_extra_args: list[str] | tuple[str, ...] = (),
        resume_state: bool = False,
        capture: bool = True,
    ) -> Any:
        del (
            model,
            out_dir,
            timeout,
            agent_command,
            cli_driver,
            agent_env,
            cli_extra_args,
            resume_state,
            capture,
        )
        calls.append((task_obj.id, arm, rep))
        return CODEBENCH.ArmResult(
            task=task_obj.id,
            arm=arm,
            rep=rep,
            ok=True,
            cost_usd=0.5,
            duration_ms=5,
            duration_api_ms=4,
            num_turns=1,
            input_tokens=6,
            cache_read_tokens=0,
            cache_creation_tokens=0,
            output_tokens=3,
            models=["sonnet"],
            is_error=False,
            result_excerpt="ok",
            flow_path=f"{arm}.flow",
        )

    monkeypatch.setattr(CODEBENCH, "run_arm", fake_run_arm)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "run.py",
            "task-1",
            "--arms",
            "baseline",
            "atelier",
            "--reps",
            "1",
            "--out",
            str(run_dir),
            "--resume",
        ],
    )

    assert CODEBENCH.main() == 0
    assert calls == [("task-1", "atelier", 0)]


def test_validate_result_excerpt_rejects_placeholder_response() -> None:
    task = TASKS.Task("task-1", "swift", ("empty",), 1, "task1")

    valid, reason, _hard = CODEBENCH._validate_result_excerpt(
        task,
        "I'm ready to help! What would you like to work on?",
    )

    assert valid is False
    assert reason == "generic placeholder response"


def test_validate_result_excerpt_rejects_off_topic_research_response() -> None:
    task = TASKS.Task("task-1", "swift", ("empty",), 1, "task1")

    valid, reason, _hard = CODEBENCH._validate_result_excerpt(
        task,
        "I need to research how CLI coding agents detect the host IDE/terminal environment. "
        "I'll start by searching the web for Claude Code, Gemini CLI, Cody, and Aider.",
    )

    assert valid is False
    assert "off-topic" in reason


def test_validate_result_excerpt_rejects_harness_error() -> None:
    task = TASKS.Task("task-1", "swift", ("empty",), 1, "task1")

    valid, reason, _hard = CODEBENCH._validate_result_excerpt(
        task,
        "harness error: Command '['opencode', 'run', '...']' timed out after 60 seconds",
    )

    assert valid is False
    assert reason == "harness/runtime error"


def test_validate_result_excerpt_rejects_zero_overlap_response(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    task_source_dir = tmp_path / "codebench-tasks"
    task_dir = task_source_dir / "tasks" / "task1"
    task_dir.mkdir(parents=True)
    (task_dir / "prompt.md").write_text("Build a Swift LRU cache", encoding="utf-8")
    monkeypatch.setenv("CODEBENCH_TASKS_DIR", str(task_source_dir))
    task = TASKS.Task("task-1", "swift", ("empty",), 1, "task1")

    valid, reason, _hard = CODEBENCH._validate_result_excerpt(
        task,
        "Remember stable user preferences and summarize them into ~/.claude/skills/ for reuse.",
    )

    assert valid is False
    assert reason == "no task keyword overlap"


def test_validate_result_excerpt_accepts_task_relevant_summary() -> None:
    task = TASKS.Task("task-1", "swift", ("empty",), 1, "task1")

    valid, reason, _hard = CODEBENCH._validate_result_excerpt(
        task,
        "Implemented the Swift LRU cache with disk-backed index persistence, atomic writes, "
        "and debounced access-date updates for get and promote.",
    )

    assert valid is True
    assert reason == ""


def test_validate_result_excerpt_accepts_error_handling_summary() -> None:
    task = TASKS.Task("task-1", "swift", ("empty",), 1, "task1")

    valid, reason, _hard = CODEBENCH._validate_result_excerpt(
        task,
        "Implemented the Swift LRU cache with persistence and explicit error handling for corrupted index recovery.",
    )

    assert valid is True
    assert reason == ""


def test_validate_result_excerpt_rejects_unnecessary_clarification() -> None:
    task = TASKS.Task("task-1", "swift", ("empty",), 1, "task1")

    valid, reason, _hard = CODEBENCH._validate_result_excerpt(
        task,
        "The workspace contains only the `CLAUDE.md` file. Could you tell me more about what task1 "
        "should do, or should I scaffold something new?",
    )

    assert valid is False
    assert "clarification" in reason or "workspace confusion" in reason


def test_validate_result_excerpt_rejects_generic_capability_intro() -> None:
    task = TASKS.Task("task-1", "swift", ("empty",), 1, "task1")

    valid, reason, _hard = CODEBENCH._validate_result_excerpt(
        task,
        "Hello! I can help with many tasks:\n\n"
        "- Code development: write and debug code\n"
        "- Code review: inspect PRs and bugs\n"
        "- Research: investigate topics and summarize findings\n"
        "- Project management: plan and track work\n",
    )

    assert valid is False
    assert "off-task capability/list response" in reason


def test_parse_agent_env_supports_empty_values() -> None:
    parsed = CODEBENCH._parse_agent_env(
        [
            "ANTHROPIC_BASE_URL=https://openrouter.ai/api",
            "ANTHROPIC_AUTH_TOKEN=secret",
            "ANTHROPIC_API_KEY=",
        ]
    )

    assert parsed == {
        "ANTHROPIC_BASE_URL": "https://openrouter.ai/api",
        "ANTHROPIC_AUTH_TOKEN": "secret",
        "ANTHROPIC_API_KEY": "",
    }


def test_parse_agent_env_from_host_reads_existing_env(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "secret")

    parsed = CODEBENCH._parse_agent_env_from_host(["ANTHROPIC_AUTH_TOKEN=OPENROUTER_API_KEY"])

    assert parsed == {"ANTHROPIC_AUTH_TOKEN": "secret"}


def test_parse_agent_env_from_host_reads_repo_env_file(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text("export OPENROUTER_API_KEY=secret-from-file\n", encoding="utf-8")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(CODEBENCH, "REPO_ROOT", tmp_path)

    parsed = CODEBENCH._parse_agent_env_from_host(["ANTHROPIC_AUTH_TOKEN=OPENROUTER_API_KEY"])

    assert parsed == {"ANTHROPIC_AUTH_TOKEN": "secret-from-file"}


def test_load_benchmark_env_prefers_most_specific(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    (tmp_path / "benchmarks" / "codebench").mkdir(parents=True)
    (tmp_path / ".env").write_text("ANTHROPIC_API_KEY=root\nROOT_ONLY=r\n", encoding="utf-8")
    (tmp_path / "benchmarks" / ".env").write_text("ANTHROPIC_API_KEY=mid\n", encoding="utf-8")
    (tmp_path / "benchmarks" / "codebench" / ".env").write_text("ANTHROPIC_API_KEY=specific\n", encoding="utf-8")
    monkeypatch.setattr(CODEBENCH, "REPO_ROOT", tmp_path)

    merged = CODEBENCH._load_benchmark_env()

    # codebench/.env wins for the shared key; root-only keys still cascade in.
    assert merged["ANTHROPIC_API_KEY"] == "specific"
    assert merged["ROOT_ONLY"] == "r"


def test_load_benchmark_env_empty_value_falls_through(tmp_path: Path, monkeypatch: MonkeyPatch) -> None:
    (tmp_path / "benchmarks" / "codebench").mkdir(parents=True)
    # An empty placeholder in the most-specific file must not clobber a real
    # value set in a less-specific file.
    (tmp_path / "benchmarks" / "codebench" / ".env").write_text("CLAUDE_CODE_OAUTH_TOKEN=\n", encoding="utf-8")
    (tmp_path / ".env").write_text("CLAUDE_CODE_OAUTH_TOKEN=real-token\n", encoding="utf-8")
    monkeypatch.setattr(CODEBENCH, "REPO_ROOT", tmp_path)

    merged = CODEBENCH._load_benchmark_env()

    assert merged["CLAUDE_CODE_OAUTH_TOKEN"] == "real-token"


def test_benchmark_auth_present_distinguishes_identity_from_ambient() -> None:
    # Explicit benchmark identity (from .env / --provider / --agent-env) -> skip copy.
    assert CODEBENCH._benchmark_auth_present({"ANTHROPIC_API_KEY": "k"}, {})
    # Legacy host-exported long-lived token -> skip copy.
    assert CODEBENCH._benchmark_auth_present({}, {"CLAUDE_CODE_OAUTH_TOKEN": "t"})
    # No identity at all -> fall back to copying the default session creds.
    assert not CODEBENCH._benchmark_auth_present({}, {})
    # Empty placeholder is not auth.
    assert not CODEBENCH._benchmark_auth_present({"ANTHROPIC_API_KEY": ""}, {})
    # Ambient ANTHROPIC_API_KEY in the host shell alone does NOT skip the copy.
    assert not CODEBENCH._benchmark_auth_present({}, {"ANTHROPIC_API_KEY": "ambient"})


def test_normalize_model_usage_reads_camelcase_keys() -> None:
    # Claude emits modelUsage with camelCase token-component keys; the breakdown
    # must read them instead of silently zeroing on a snake_case lookup miss.
    rows = [
        CODEBENCH.ArmResult(
            task="task-1",
            arm="atelier",
            rep=rep,
            ok=True,
            cost_usd=1.0,
            duration_ms=1000,
            duration_api_ms=800,
            num_turns=2,
            input_tokens=100,
            cache_read_tokens=1000,
            cache_creation_tokens=10,
            output_tokens=40,
            models=["m"],
            is_error=False,
            result_excerpt="ok",
            flow_path=f"atelier-{rep}.flow",
            model_usage={
                "m": {
                    "inputTokens": 100,
                    "outputTokens": 40,
                    "cacheReadInputTokens": 1000,
                    "cacheCreationInputTokens": 10,
                }
            },
        )
        for rep in range(2)
    ]

    assert CODEBENCH._normalize_model_usage(rows[0].model_usage["m"]) == {
        "input": 100,
        "output": 40,
        "cache_read": 1000,
        "cache_write": 10,
        "thinking": 0,
    }
    # Aggregating both rows sums the per-component tokens rather than zeroing them.
    agg = CODEBENCH._agg(rows, "atelier")
    assert agg["model_usage"]["m"] == {
        "input": 200,
        "output": 80,
        "cache_read": 2000,
        "cache_write": 20,
        "thinking": 0,
    }


def test_is_content_invalid_excludes_timeouts_but_flags_off_topic() -> None:
    timed_out = CODEBENCH.ArmResult(
        task="task-1",
        arm="atelier",
        rep=0,
        ok=False,
        cost_usd=0.0,
        duration_ms=1800000,
        duration_api_ms=1800000,
        num_turns=0,
        input_tokens=0,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        output_tokens=0,
        models=[],
        is_error=True,
        result_excerpt="timed out after 1800s",
        flow_path="atelier.flow",
        valid=False,
        validity_reason=CODEBENCH.EXECUTION_FAILED_REASON,
        timed_out=True,
    )
    off_topic = CODEBENCH.ArmResult(
        task="task-1",
        arm="atelier",
        rep=0,
        ok=True,
        cost_usd=0.5,
        duration_ms=1000,
        duration_api_ms=800,
        num_turns=2,
        input_tokens=10,
        cache_read_tokens=0,
        cache_creation_tokens=0,
        output_tokens=5,
        models=["sonnet"],
        is_error=False,
        result_excerpt="here is a list of things I can do",
        flow_path="atelier.flow",
        valid=False,
        validity_reason="off-task capability/list response",
        timed_out=False,
    )

    assert CODEBENCH._is_content_invalid(timed_out) is False
    assert CODEBENCH._is_content_invalid(off_topic) is True
