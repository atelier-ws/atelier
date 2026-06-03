from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from atelier.core.capabilities.benchmark_solver import (
    BenchmarkAttempt,
    HarnessFeedback,
    build_retry_context,
    run_benchmark_solver,
    write_solver_artifacts,
)
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
    assert stream_lines[0]["event"] == "start"
    assert any(line["event"] == "complete" for line in stream_lines)


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
