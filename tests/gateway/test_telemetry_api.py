from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("fastapi", reason="FastAPI API tests require the api extra")

from fastapi.testclient import TestClient

from atelier.core.service.api import create_app
from atelier.infra.storage.sqlite_store import SQLiteStore


@pytest.fixture()
def app_no_auth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("ATELIER_REQUIRE_AUTH", "false")
    monkeypatch.setenv("ATELIER_TELEMETRY", "0")
    monkeypatch.setenv("ATELIER_TELEMETRY_DB", str(tmp_path / "telemetry.db"))
    monkeypatch.setenv("ATELIER_TELEMETRY_CONFIG", str(tmp_path / "telemetry.toml"))
    monkeypatch.setenv("ATELIER_TELEMETRY_ID_PATH", str(tmp_path / "telemetry_id"))
    monkeypatch.setenv("ATELIER_TELEMETRY_ACK", str(tmp_path / "telemetry_ack"))
    store = SQLiteStore(tmp_path / ".atelier")
    store.init()
    return TestClient(create_app(store=store))


def test_telemetry_api_local_schema_summary_and_config(app_no_auth: TestClient) -> None:
    cfg = app_no_auth.get("/telemetry/config")
    assert cfg.status_code == 200
    assert cfg.json()["remote_enabled"] is False

    write = app_no_auth.post(
        "/telemetry/local",
        json={
            "event": "session_start",
            "props": {
                "agent_host": "frontend",
                "atelier_version": "0.1.0",
                "os": "browser",
                "py_version": "n/a",
                "anon_id": "a",
                "session_id": "s",
            },
        },
    )
    assert write.status_code == 200

    events = app_no_auth.get("/telemetry/local?limit=10")
    assert events.status_code == 200
    names = [event["event"] for event in events.json()["events"]]
    assert "session_start" in names

    summary = app_no_auth.get("/telemetry/summary")
    assert summary.status_code == 200
    assert summary.json()["events_total"] >= 1

    schema = app_no_auth.get("/telemetry/schema")
    assert schema.status_code == 200
    assert "cli_command_invoked" in schema.json()["events"]

    updated = app_no_auth.post("/telemetry/config", json={"lexical_frustration_enabled": False})
    assert updated.status_code == 200
    assert updated.json()["lexical_frustration_enabled"] is False

    ack = app_no_auth.post("/telemetry/ack")
    assert ack.status_code == 200
    assert ack.json()["acknowledged"] is True
