from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

from benchmarks.swe.savings_replay import _load_corpus, run_paired_command_benchmark, run_replay

_BASELINE_FILE = Path(__file__).parent.parent / "fixtures" / "savings_baseline.json"
_NO_REGRESSION_TOLERANCE_PCT = 5.0


def test_replay_corpus_has_at_least_50_prompts() -> None:
    rows = _load_corpus()
    assert len(rows) >= 50
    assert {"id", "task_type", "baseline", "atelier", "lever"}.issubset(rows[0])


def test_savings_replay_persists_benchmark_rows(tmp_path: Path) -> None:
    result = run_replay(root=tmp_path / "atelier")

    assert result.n_prompts >= 50
    assert result.reduction_pct > 0.0
    assert result.median_input_tokens_baseline > result.median_input_tokens_optimized
    with sqlite3.connect(tmp_path / "atelier" / "atelier.db") as conn:
        run_count = conn.execute("SELECT count(*) FROM benchmark_run").fetchone()[0]
        prompt_count = conn.execute("SELECT count(*) FROM benchmark_prompt_result").fetchone()[0]

    assert run_count == 1
    assert prompt_count == result.n_prompts


def test_savings_replay_writes_csv(tmp_path: Path) -> None:
    csv_path = tmp_path / "results.csv"
    result = run_replay(root=tmp_path / "atelier", csv_path=csv_path)
    text = csv_path.read_text(encoding="utf-8")
    assert "baseline_input_tokens" in text
    assert text.count("\n") == result.n_prompts + 1


def test_savings_replay_no_regression_vs_baseline(tmp_path: Path) -> None:
    """Measured reduction_pct must not drop more than 5 pp below the persisted baseline.

    This prevents the V2 pattern of silently eroding measured savings in future
    PRs without anyone noticing. To update the baseline intentionally, edit
    tests/fixtures/savings_baseline.json and leave a note in the commit message.
    """
    baseline_data = json.loads(_BASELINE_FILE.read_text(encoding="utf-8"))
    prior_baseline = float(baseline_data["reduction_pct"])

    result = run_replay(root=tmp_path / "atelier")

    floor = prior_baseline - _NO_REGRESSION_TOLERANCE_PCT
    assert result.reduction_pct >= floor, (
        f"Savings regression: measured {result.reduction_pct:.2f}% vs baseline "
        f"{prior_baseline:.2f}% (floor {floor:.2f}%). "
        f"If this is intentional, update tests/fixtures/savings_baseline.json."
    )


def test_paired_command_benchmark_measures_real_subprocesses(tmp_path: Path) -> None:
    script = tmp_path / "bench_agent.py"
    script.write_text(
        "\n".join(
            [
                "import json",
                "import os",
                "mode = os.environ['ATELIER_BENCH_MODE']",
                "if mode == 'baseline':",
                "    print(json.dumps({'input_tokens': 1000, 'output_tokens': 500, 'cost_usd': 0.02, 'success': True}))",
                "else:",
                "    print(json.dumps({'input_tokens': 600, 'output_tokens': 300, 'cost_usd': 0.01, 'success': True}))",
            ]
        ),
        encoding="utf-8",
    )

    result = run_paired_command_benchmark(
        root=tmp_path / "atelier",
        baseline_command=f"{sys.executable} {script}",
        atelier_command=f"{sys.executable} {script}",
        tasks=[{"id": "case-1", "task_type": "fixture", "task": "Fix a failing test"}],
        model="claude-sonnet-4.6",
        timeout_s=10,
    )

    assert result.n_prompts == 1
    assert result.total_tokens_baseline == 1500
    assert result.total_tokens_atelier == 900
    assert result.reduction_pct == 40.0
    assert result.cost_saved_usd == 0.01
    assert result.baseline_success_rate == 1.0
    assert result.atelier_success_rate == 1.0
    assert (tmp_path / "atelier" / "benchmarks" / "savings" / "latest.json").exists()
    with sqlite3.connect(tmp_path / "atelier" / "atelier.db") as conn:
        suite = conn.execute("SELECT suite FROM benchmark_run").fetchone()[0]
        prompt_count = conn.execute("SELECT count(*) FROM benchmark_prompt_result").fetchone()[0]
    assert suite == "paired_command_savings_v1"
    assert prompt_count == 1
