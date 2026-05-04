from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
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


def test_savings_summary_returns_per_lever_and_by_day(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
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
