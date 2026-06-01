from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("terminalbench.aggregate")

from terminalbench.aggregate import summarize_runs, write_summary


def _record(
    *,
    task_id: str,
    mode: str,
    verdict: str,
    rep: int,
    latency_ms: float,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float = 0.0,
) -> dict[str, object]:
    return {
        "task_id": task_id,
        "mode": mode,
        "rep": rep,
        "model": "qwen3.6:27b",
        "grader_verdict": verdict,
        "is_error": False,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "latency_ms": latency_ms,
        "latency_api_ms": latency_ms,
        "cost_usd": cost_usd,
    }


def test_summarize_runs_builds_per_task_cells_and_mode_delta() -> None:
    rows = [
        _record(
            task_id="hello-world",
            mode="off",
            verdict="pass",
            rep=1,
            latency_ms=12_000,
            input_tokens=4000,
            output_tokens=200,
        ),
        _record(
            task_id="hello-world",
            mode="on",
            verdict="pass",
            rep=1,
            latency_ms=8_000,
            input_tokens=3500,
            output_tokens=180,
        ),
        _record(
            task_id="fix-git",
            mode="off",
            verdict="fail",
            rep=1,
            latency_ms=14_000,
            input_tokens=5000,
            output_tokens=250,
        ),
        _record(
            task_id="fix-git",
            mode="on",
            verdict="pass",
            rep=1,
            latency_ms=11_000,
            input_tokens=4200,
            output_tokens=240,
        ),
    ]

    summary = summarize_runs(rows)

    assert summary["cells"]["hello-world"]["off"]["counts"] == {"passed": 1, "total": 1}
    assert summary["cells"]["fix-git"]["off"]["counts"] == {"passed": 0, "total": 1}
    assert summary["by_mode"]["on"]["counts"] == {"passed": 2, "total": 2}
    assert summary["delta_on_minus_off"]["pass_rate"] == pytest.approx(0.5)
    assert summary["delta_on_minus_off"]["latency_ms_mean"] == pytest.approx(-3500.0)


def test_write_summary_accepts_directory_input(tmp_path: Path) -> None:
    runs = tmp_path / "runs.jsonl"
    runs.write_text(
        "\n".join(
            [
                json.dumps(
                    _record(
                        task_id="hello-world",
                        mode="off",
                        verdict="pass",
                        rep=1,
                        latency_ms=12_000,
                        input_tokens=4000,
                        output_tokens=200,
                    )
                ),
                json.dumps(
                    _record(
                        task_id="hello-world",
                        mode="on",
                        verdict="pass",
                        rep=1,
                        latency_ms=8_000,
                        input_tokens=3500,
                        output_tokens=180,
                    )
                ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    out = write_summary(tmp_path)

    payload = json.loads(out.read_text(encoding="utf-8"))
    assert out == tmp_path / "summary.json"
    assert payload["by_mode"]["off"]["counts"] == {"passed": 1, "total": 1}
    assert payload["by_mode"]["on"]["counts"] == {"passed": 1, "total": 1}
