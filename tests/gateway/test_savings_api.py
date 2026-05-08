from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="FastAPI API tests require the api extra")

from fastapi.testclient import TestClient

from atelier.core.service.api import create_app


def _write_cost_history(path: Path) -> None:
    now = datetime.now(UTC)
    history = {
        "operations": {
            "op-search": {
                "domain": "atelier.platform",
                "task_sample": "search",
                "first_seen": now.isoformat(),
                "calls": [
                    {
                        "operation": "search_read",
                        "model": "test-model",
                        "input_tokens": 120,
                        "output_tokens": 30,
                        "cache_read_tokens": 60,
                        "cost_usd": 0.01,
                        "lessons_used": [],
                        "op_key": "op-search",
                        "at": now.isoformat(),
                    },
                    {
                        "operation": "search_read",
                        "model": "test-model",
                        "input_tokens": 80,
                        "output_tokens": 20,
                        "cache_read_tokens": 40,
                        "cost_usd": 0.008,
                        "lessons_used": [],
                        "op_key": "op-search",
                        "at": (now - timedelta(days=1)).isoformat(),
                    },
                ],
            },
            "op-batch": {
                "domain": "atelier.platform",
                "task_sample": "edit",
                "first_seen": now.isoformat(),
                "calls": [
                    {
                        "operation": "batch_edit",
                        "model": "test-model",
                        "input_tokens": 100,
                        "output_tokens": 25,
                        "cache_read_tokens": 50,
                        "cost_usd": 0.009,
                        "lessons_used": [],
                        "op_key": "op-batch",
                        "at": now.isoformat(),
                    }
                ],
            },
        }
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(history), encoding="utf-8")


def _write_live_savings_events(path: Path) -> None:
    now = datetime.now(UTC)
    rows = [
        {
            "at": now.isoformat(),
            "run_id": "run-live-1",
            "agent": "codex",
            "tool_name": "search",
            "lever": "search_read",
            "equivalent_baseline_calls": 3.0,
            "calls_saved": 2,
            "time_saved_ms": 50_000,
            "input_tokens_saved": 52_000,
            "output_tokens_saved": 100_000,
            "cache_read_tokens_saved": 2_600,
            "cache_write_tokens_saved": 0,
            "tool_tokens_saved": 400,
            "tokens_saved": 155_000,
            "cost_saved_usd": 1.66278,
            "model": "claude-sonnet-4",
        },
        {
            "at": (now - timedelta(days=40)).isoformat(),
            "run_id": "old-run",
            "agent": "codex",
            "tool_name": "sql",
            "lever": "sql_batch",
            "calls_saved": 4,
            "tokens_saved": 300_000,
            "cost_saved_usd": 3.0,
            "time_saved_ms": 100_000,
        },
    ]
    path.write_text("\n".join(json.dumps(row) for row in rows), encoding="utf-8")


def _write_latest_benchmark(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "run_id": "bench-live",
                "model": "test-model",
                "n_prompts": 2,
                "total_tokens_baseline": 1000,
                "total_tokens_atelier": 600,
                "tokens_saved": 400,
                "reduction_pct": 40.0,
                "total_cost_baseline_usd": 0.02,
                "total_cost_atelier_usd": 0.012,
                "cost_saved_usd": 0.008,
                "total_time_baseline_ms": 2000,
                "total_time_atelier_ms": 1500,
                "time_saved_ms": 500,
                "baseline_success_rate": 1.0,
                "atelier_success_rate": 1.0,
                "prompts": [],
            }
        ),
        encoding="utf-8",
    )


def test_savings_summary_returns_per_lever_and_by_day(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / ".atelier"
    _write_cost_history(root / "cost_history.json")

    monkeypatch.setenv("ATELIER_REQUIRE_AUTH", "false")
    monkeypatch.setenv("ATELIER_ROOT", str(root))

    client = TestClient(create_app())
    resp = client.get("/v1/savings/summary?window_days=14")

    assert resp.status_code == 200
    data = resp.json()
    assert data["window_days"] == 14
    assert data["total_naive_tokens"] == 525
    assert data["total_actual_tokens"] == 375
    assert data["reduction_pct"] == 28.6
    assert data["per_lever"]["search_read"] == 100
    assert data["per_lever"]["batch_edit"] == 50
    assert len(data["by_day"]) == 14
    assert all("day" in row and "naive" in row and "actual" in row for row in data["by_day"])


def test_savings_summary_includes_live_plugin_sources(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / ".atelier"
    _write_cost_history(root / "cost_history.json")
    _write_live_savings_events(root / "live_savings_events.jsonl")
    _write_latest_benchmark(root / "benchmarks" / "savings" / "latest.json")

    monkeypatch.setenv("ATELIER_REQUIRE_AUTH", "false")
    monkeypatch.setenv("ATELIER_ROOT", str(root))

    client = TestClient(create_app())
    resp = client.get("/v1/savings/summary?window_days=14")

    assert resp.status_code == 200
    data = resp.json()
    assert data["total_naive_tokens"] == 155_525
    assert data["total_actual_tokens"] == 375
    assert data["per_lever"]["search_read"] == 155_100
    assert data["live_calls_saved"] == 2
    assert data["live_time_saved_ms"] == 50_000
    assert data["live_saved_usd"] == 1.66278
    assert data["top_sources"] == [
        {
            "lever": "search_read",
            "tool_name": "search",
            "calls_saved": 2,
            "tokens_saved": 155_000,
            "cost_saved_usd": 1.66278,
            "time_saved_ms": 50_000,
        }
    ]
    assert data["latest_benchmark"]["run_id"] == "bench-live"
    assert data["latest_benchmark"]["reduction_pct"] == 40.0
    assert "prompts" not in data["latest_benchmark"]


def test_savings_summary_empty_state(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    root = tmp_path / ".atelier"
    root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setenv("ATELIER_REQUIRE_AUTH", "false")
    monkeypatch.setenv("ATELIER_ROOT", str(root))

    client = TestClient(create_app())
    resp = client.get("/v1/savings/summary?window_days=14")

    assert resp.status_code == 200
    data = resp.json()
    assert data["window_days"] == 14
    assert data["total_naive_tokens"] == 0
    assert data["total_actual_tokens"] == 0
    assert data["reduction_pct"] == 0.0
    assert data["per_lever"] == {}
    assert len(data["by_day"]) == 14
