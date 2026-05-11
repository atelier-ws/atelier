from __future__ import annotations

from pathlib import Path

import pytest

from atelier.gateway.integrations import external_analytics as ext


def test_external_status_reports_installed_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ext, "_find_executable", lambda spec: "/usr/bin/fake")

    payload = ext.external_status(cwd=Path("/tmp/work"))

    by_tool = {item["tool"]: item for item in payload}
    assert by_tool["tokscale"]["available"] is True
    assert by_tool["codeburn"]["available"] is True
    assert set(by_tool) == {"tokscale", "codeburn"}


def test_run_external_reports_collects_reportable_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(tool: str, *, period: str = "week", cwd: Path | None = None) -> dict[str, object]:
        return {"tool": tool, "period": period, "cwd": str(cwd), "ok": True, "payload": {"tool": tool}}

    monkeypatch.setattr(ext, "run_external_report", fake_run)

    payload = ext.run_external_reports(tool="all", period="week", cwd=Path("/tmp/work"))

    assert payload["tool"] == "all"
    assert [item["tool"] for item in payload["reports"]] == ["tokscale", "codeburn"]
