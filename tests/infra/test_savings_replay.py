from __future__ import annotations

import sqlite3
from pathlib import Path

from benchmarks.swe.savings_replay import _load_corpus, run_replay


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
