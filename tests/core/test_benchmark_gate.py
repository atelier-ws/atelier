from __future__ import annotations

import json
from pathlib import Path

from atelier.core.capabilities.benchmark_gate import (
    evaluate_terminalbench_gate,
    evaluate_vix_gate,
)


def test_evaluate_terminalbench_gate_passes_with_noninferior_cheaper_candidate(tmp_path: Path) -> None:
    run_dir = tmp_path / "terminalbench"
    run_dir.mkdir()
    rows = [{"mode": "off", "grader_verdict": "pass", "cost_usd": 3.0} for _ in range(40)] + [
        {"mode": "on", "grader_verdict": "pass", "cost_usd": 1.0} for _ in range(40)
    ]
    (run_dir / "runs.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )

    verdict = evaluate_terminalbench_gate(run_dir, margin=0.10, confidence=0.95)

    assert verdict["suite"] == "terminalbench"
    assert verdict["passed"] is True
    assert verdict["details"]["estimated_cost_savings_usd"] == 80.0


def test_evaluate_vix_gate_requires_judged_results_and_cost_reduction(tmp_path: Path) -> None:
    run_dir = tmp_path / "vix"
    run_dir.mkdir()
    rows = [
        {"arm": "baseline", "correct": True, "cost_usd": 2.0, "valid": True},
        {"arm": "atelier", "correct": None, "cost_usd": 1.0, "valid": True},
    ]
    (run_dir / "results.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n",
        encoding="utf-8",
    )

    verdict = evaluate_vix_gate(run_dir, baseline_arm="baseline", candidate_arm="atelier")

    assert verdict["suite"] == "vix"
    assert verdict["passed"] is False
    assert "quality gate requires judged results" in verdict["reasons"][0]
