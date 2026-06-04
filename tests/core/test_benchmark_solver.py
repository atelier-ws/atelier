from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

import atelier.core.capabilities.benchmark_solver as benchmark_solver_module
from atelier.core.capabilities.benchmark_solver import (
    BenchmarkAttempt,
    HarnessFeedback,
    _default_step_executor,
    _parent_step_history,
    _resolve_solver_execution_route,
    build_retry_context,
    run_benchmark_solver,
    write_solver_artifacts,
)
from atelier.core.capabilities.default_definitions import DefaultWorkflowStep
from atelier.core.capabilities.workflow_context import WorkflowContextState
from atelier.gateway.cli.commands.benchmark_solver import benchmark_solver_cmd

ROOT = Path(__file__).resolve().parents[2]


def test_build_retry_context_uses_canonical_solver_rules() -> None:
    feedback = HarnessFeedback(
        summary="pytest -q failed on test_login_flow",
        failing_checks=("pytest -q",),
        raw_log_excerpt="E assert 1 == 2",
        artifact_paths=("/tmp/harness.log",),
    )
    previous = BenchmarkAttempt(
        attempt_number=1,
        workflow_id="owned-benchmark-solver",
        profile_id="terminalbench-owned-solver",
        task_prompt="Fix the failing login task.",
        status="failed",
        review_raw_output='{"verdict":"NEEDS_FIX","checklist":["login"],"missing":["tests"]}',
        review_verdict_json={"verdict": "NEEDS_FIX", "checklist": ["login"], "missing": ["tests"]},
        harness_feedback=feedback,
    )

    retry_context = build_retry_context(previous, feedback, repo_root=ROOT)

    assert "pytest -q failed on test_login_flow" in retry_context
    assert "Do not repeat a failed command verbatim" in retry_context
    assert "Fix the failing login task." in retry_context
    assert "/tmp/harness.log" in retry_context


def test_run_benchmark_solver_retries_with_forked_attempt_context() -> None:
    feedback = HarnessFeedback(
        summary="grader failed after the first implementation",
        failing_checks=("pytest -q tests/test_login.py",),
        raw_log_excerpt="AssertionError: expected login success",
    )
    review_outputs = {1: "NEEDS_FIX", 2: "PASS"}

    def step_executor(step, prompt: str, _context, attempt_number: int) -> dict[str, object]:
        if step.step_id == "review":
            verdict = review_outputs[attempt_number]
            return {
                "status": "done",
                "output": json.dumps(
                    {
                        "verdict": verdict,
                        "checklist": [step.step_id],
                        "missing": [] if verdict == "PASS" else ["login tests"],
                    }
                ),
                "output_json": {
                    "verdict": verdict,
                    "checklist": [step.step_id],
                    "missing": [] if verdict == "PASS" else ["login tests"],
                },
            }
        return {
            "status": "done",
            "output": f"{step.step_id} attempt {attempt_number}",
            "output_json": {"attempt": attempt_number, "step_id": step.step_id},
        }

    def feedback_provider(attempt: BenchmarkAttempt) -> HarnessFeedback | None:
        return feedback if attempt.attempt_number == 1 else None

    run = run_benchmark_solver(
        "Fix the login flow and make the tests pass.",
        repo_root=ROOT,
        step_executor=step_executor,
        feedback_provider=feedback_provider,
    )

    assert run.status == "success"
    assert run.profile_id == "terminalbench-owned-solver"
    assert len(run.attempts) == 2
    assert run.attempts[0].review_verdict_json["verdict"] == "NEEDS_FIX"
    assert run.attempts[1].forked_from_attempt == 1
    assert "grader failed after the first implementation" in run.attempts[1].retry_context
    assert any(event.event == "retry" and event.attempt_number == 2 for event in run.events)


def test_run_benchmark_solver_applies_stem_prompt_and_step_fork_history() -> None:
    prompts: dict[tuple[int, str], str] = {}

    def step_executor(step, prompt: str, _context, attempt_number: int) -> dict[str, object]:
        prompts[(attempt_number, step.step_id)] = prompt
        if step.step_id == "review":
            return {
                "status": "done",
                "output": json.dumps({"verdict": "PASS", "checklist": [step.step_id], "missing": []}),
                "output_json": {"verdict": "PASS", "checklist": [step.step_id], "missing": []},
            }
        return {
            "status": "done",
            "output": f"{step.step_id} attempt {attempt_number}",
            "output_json": {"step_id": step.step_id, "attempt": attempt_number},
        }

    run_benchmark_solver(
        "Fix the login flow and make the tests pass.",
        repo_root=ROOT,
        step_executor=step_executor,
    )

    assert "prompt caches stay warm" in prompts[(1, "explore")]
    assert "Current phase prompt:" in prompts[(1, "explore")]
    assert "Forked conversation transcript:" in prompts[(1, "plan")]
    assert "explore attempt 1" in prompts[(1, "plan")]
    assert "owned-explore-phase" in prompts[(1, "plan")]


def test_run_benchmark_solver_retries_from_prior_attempt_transcript() -> None:
    prompts: dict[tuple[int, str], str] = {}
    review_outputs = {1: "NEEDS_FIX", 2: "PASS"}

    def step_executor(step, prompt: str, _context, attempt_number: int) -> dict[str, object]:
        prompts[(attempt_number, step.step_id)] = prompt
        if step.step_id == "review":
            verdict = review_outputs[attempt_number]
            return {
                "status": "done",
                "output": json.dumps(
                    {
                        "verdict": verdict,
                        "checklist": [step.step_id],
                        "missing": [] if verdict == "PASS" else ["login tests"],
                    }
                ),
                "output_json": {
                    "verdict": verdict,
                    "checklist": [step.step_id],
                    "missing": [] if verdict == "PASS" else ["login tests"],
                },
            }
        return {
            "status": "done",
            "output": f"{step.step_id} attempt {attempt_number}",
            "output_json": {"step_id": step.step_id, "attempt": attempt_number},
        }

    run_benchmark_solver(
        "Fix the login flow and make the tests pass.",
        repo_root=ROOT,
        step_executor=step_executor,
        feedback_provider=lambda attempt: (
            HarnessFeedback(summary="grader failed") if attempt.attempt_number == 1 else None
        ),
    )

    assert "explore attempt 1" in prompts[(2, "explore")]
    assert '"verdict": "NEEDS_FIX"' in prompts[(2, "explore")]
    assert "Forked conversation transcript:" in prompts[(2, "explore")]


def test_fresh_workflow_step_does_not_inherit_parent_or_prior_attempt_history() -> None:
    fresh_step = DefaultWorkflowStep(
        step_id="independent_research",
        role_id="research",
        phase_prompt_id="owned-explore-phase",
        effort="medium",
        read_mode_hint="compact",
        fork_from="explore",
        context_mode="fresh",
    )

    inherited = _parent_step_history(
        default_step=fresh_step,
        step_histories={
            "explore": (
                {
                    "step_id": "explore",
                    "phase_prompt_id": "owned-explore-phase",
                    "input_prompt": "prior prompt",
                    "output": "prior output",
                },
            )
        },
        prior_attempt_history=(
            {
                "step_id": "review",
                "phase_prompt_id": "owned-review-phase",
                "input_prompt": "old prompt",
                "output": "old output",
            },
        ),
    )

    assert inherited == ()


def test_write_solver_artifacts_writes_json_and_stream_records(tmp_path: Path) -> None:
    run = run_benchmark_solver(
        "Produce the requested artifact.",
        repo_root=ROOT,
        step_executor=lambda step, prompt, _context, attempt_number: {
            "status": "done",
            "output": (
                json.dumps(
                    {
                        "verdict": "PASS" if step.step_id == "review" else f"{step.step_id} ok",
                        "checklist": [step.step_id],
                        "missing": [],
                    }
                )
                if step.step_id == "review"
                else f"{step.step_id} ok"
            ),
            "output_json": {
                "verdict": "PASS" if step.step_id == "review" else "STEP_OK",
                "attempt": attempt_number,
            },
        },
    )

    written = write_solver_artifacts(run, tmp_path)

    run_payload = json.loads(written.run_json_path.read_text(encoding="utf-8"))
    stream_lines = [
        json.loads(line) for line in written.stream_jsonl_path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]

    assert run_payload["run_id"] == run.run_id
    assert run_payload["status"] == "success"
    assert run_payload["attempts"][0]["step_artifacts"][0]["step_id"] == "explore"
    assert "input_prompt" in run_payload["attempts"][0]["step_artifacts"][0]
    assert stream_lines[0]["event"] == "start"
    assert any(line["event"] == "complete" for line in stream_lines)


def test_default_step_executor_uses_owned_provider_execution(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        benchmark_solver_module,
        "execute_owned_prompt",
        lambda prompt, **kwargs: SimpleNamespace(
            output="owned result",
            receipt=SimpleNamespace(
                to_dict=lambda: {
                    "status": "done",
                    "mode": "auto",
                    "selected_provider": "openai",
                    "selected_model": "gpt-4o",
                    "selected_runner": "openai",
                    "selected_transport": "openai",
                    "executed_provider": "openai",
                    "executed_model": "gpt-4o",
                    "executed_runner": "openai",
                    "executed_transport": "openai",
                    "request_id": "req-1",
                    "input_tokens": 21,
                    "output_tokens": 7,
                    "cache_read_input_tokens": 5,
                    "cache_write_input_tokens": 0,
                    "modeled_cache_read_input_tokens": 0,
                    "stable_prefix_hash": "",
                    "prefix_invalidated_reason": "",
                    "cache_evidence": "none",
                    "duration_seconds": 1.3,
                    "cost_usd": 0.0,
                    "rerouted": False,
                    "attempts": [],
                    "error": "",
                },
                duration_seconds=1.3,
                cost_usd=0.0,
                modeled_cache_read_input_tokens=0,
                stable_prefix_hash="",
                prefix_invalidated_reason="",
                cache_evidence="none",
            ),
        ),
    )

    executor = _default_step_executor(
        repo_root=tmp_path,
        route_decision=SimpleNamespace(
            mode="auto",
            provider="openai",
            model="gpt-4o",
            runner="openai",
            transport="openai",
        ),
        runner="claude",
        model="claude-opus-4.8",
    )
    result = executor(SimpleNamespace(step_id="explore"), "Implement the fix.", WorkflowContextState(), 1)

    assert result["status"] == "done"
    assert result["output"] == "owned result"
    assert result["execution_receipt"]["executed_transport"] == "openai"


def test_run_benchmark_solver_records_execution_receipts_and_transport(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        benchmark_solver_module,
        "_resolve_solver_execution_route",
        lambda **_kwargs: (
            SimpleNamespace(
                mode="auto",
                provider="openai",
                model="gpt-4o",
                runner="openai",
                transport="openai",
            ),
            "openai",
            "openai",
            "gpt-4o",
            "openai",
        ),
    )

    run = run_benchmark_solver(
        "Produce the requested artifact.",
        repo_root=ROOT,
        step_executor=lambda step, prompt, _context, attempt_number: {
            "status": "done",
            "output": (
                json.dumps(
                    {
                        "verdict": "PASS" if step.step_id == "review" else f"{step.step_id} ok",
                        "checklist": [step.step_id],
                        "missing": [],
                    }
                )
                if step.step_id == "review"
                else f"{step.step_id} ok"
            ),
            "output_json": {
                "verdict": "PASS" if step.step_id == "review" else "STEP_OK",
                "attempt": attempt_number,
            },
            "execution_receipt": {
                "executed_provider": "openai",
                "executed_model": "gpt-4o",
                "executed_transport": "openai",
                "input_tokens": 30,
                "output_tokens": 10,
                "cache_read_input_tokens": 4,
                "cache_write_input_tokens": 2,
            },
        },
    )

    assert run.transport == "openai"
    assert run.input_tokens == 210
    assert run.cache_creation_input_tokens == 14
    assert run.cache_read_input_tokens == 28
    assert run.attempts[0].step_artifacts[0].execution_receipt["executed_transport"] == "openai"


def test_resolve_solver_execution_route_native_mode_skips_owned_route(monkeypatch) -> None:
    monkeypatch.setattr(
        benchmark_solver_module,
        "select_owned_route",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("owned route should not be selected")),
    )

    decision, provider, runner, model, transport = _resolve_solver_execution_route(
        task_prompt="Fix the login flow.",
        defaults=benchmark_solver_module.build_default_registry(ROOT),
        profile_id="terminalbench-owned-solver",
        route_mode="native",
        provider=None,
        model=None,
        runner=None,
    )

    assert decision is None
    assert provider == "anthropic"
    assert runner == "claude"
    assert model == "claude-opus-4.8"
    assert transport == ""


def test_resolve_solver_execution_route_auto_mode_raises_when_owned_route_missing(
    monkeypatch,
) -> None:
    from atelier.core.capabilities.cross_vendor_routing.router import NoFeasibleRouteError

    monkeypatch.setattr(
        benchmark_solver_module,
        "select_owned_route",
        lambda *args, **kwargs: (_ for _ in ()).throw(NoFeasibleRouteError("no owned route")),
    )

    with pytest.raises(NoFeasibleRouteError, match="no owned route"):
        _resolve_solver_execution_route(
            task_prompt="Fix the login flow.",
            defaults=benchmark_solver_module.build_default_registry(ROOT),
            profile_id="terminalbench-owned-solver",
            route_mode="auto",
            provider=None,
            model=None,
            runner=None,
        )


def test_benchmark_solver_cli_supports_json_and_stream_json(monkeypatch, tmp_path: Path) -> None:
    run = run_benchmark_solver(
        "Solve the benchmark task.",
        repo_root=ROOT,
        step_executor=lambda step, prompt, _context, attempt_number: {
            "status": "done",
            "output": (
                json.dumps(
                    {
                        "verdict": "PASS" if step.step_id == "review" else f"{step.step_id} ok",
                        "checklist": [step.step_id],
                        "missing": [],
                    }
                )
                if step.step_id == "review"
                else f"{step.step_id} ok"
            ),
            "output_json": {
                "verdict": "PASS" if step.step_id == "review" else "STEP_OK",
                "attempt": attempt_number,
            },
        },
    )

    monkeypatch.setattr(
        "atelier.gateway.cli.commands.benchmark_solver.run_benchmark_solver",
        lambda *args, **kwargs: run,
    )
    monkeypatch.setattr(
        "atelier.gateway.cli.commands.benchmark_solver.write_solver_artifacts",
        lambda _run, out_dir: write_solver_artifacts(run, out_dir),
    )

    runner = CliRunner()
    json_result = runner.invoke(
        benchmark_solver_cmd,
        [
            "--task-prompt",
            "Solve the benchmark task.",
            "--format",
            "json",
            "--out",
            str(tmp_path / "json"),
        ],
    )
    assert json_result.exit_code == 0
    assert json.loads(json_result.output)["status"] == "success"

    stream_result = runner.invoke(
        benchmark_solver_cmd,
        [
            "--task-prompt",
            "Solve the benchmark task.",
            "--format",
            "stream-json",
            "--out",
            str(tmp_path / "stream"),
        ],
    )
    assert stream_result.exit_code == 0
    stream_lines = [json.loads(line) for line in stream_result.output.splitlines() if line.strip()]
    assert stream_lines[0]["event"] == "start"
    assert stream_lines[-1]["event"] == "complete"
