"""CLI tests for V2 commands: ledger, compress, env, eval, read, savings."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from atelier.core.foundation.models import Trace, UsageEntry
from atelier.core.foundation.store import ContextStore
from atelier.gateway.cli import cli
from atelier.infra.runtime.run_ledger import RunLedger
from tests.helpers import init_store_at


def _invoke(root: Path, *args: str, input: str | None = None) -> Result:
    runner = CliRunner()
    if args and args[0] == "init" and "--index" not in args and "--no-index" not in args:
        args = (*args, "--no-index")
    return runner.invoke(cli, ["--root", str(root), *args], input=input)


def _seed_ledger(root: Path, session_id: str = "run1") -> Path:
    led = RunLedger(session_id=session_id, agent="codex", task="t", domain="d", root=root)
    led.record_command("pytest", ok=False, error_signature="sig1")
    led.record_command("pytest", ok=False, error_signature="sig1")
    led.record_alert("repeated_command_failure", "high", "pytest x2")
    path: Path = led.persist()
    return path


def _seed_optimizer_traces(root: Path) -> None:
    store = ContextStore(root)
    store.init()
    created_at = datetime.now(UTC)
    for trace in (
        Trace(
            id="peer-low",
            agent="codex",
            host="codex",
            domain="optimizer-test",
            task="small run",
            status="success",
            input_tokens=80_000,
            output_tokens=4_000,
            model="gpt-5.5-pro",
            files_touched=["a.py"],
            created_at=created_at,
        ),
        Trace(
            id="outlier",
            agent="codex",
            host="codex",
            domain="optimizer-test",
            task="large run",
            status="success",
            input_tokens=1_000_000,
            output_tokens=10_000,
            model="gpt-5.5-pro",
            created_at=created_at,
        ),
    ):
        store.record_trace(trace)


def _seed_advisor_traces(root: Path, count: int = 20) -> None:
    store = ContextStore(root)
    store.init()
    created_at = datetime.now(UTC)
    for index in range(count):
        store.record_trace(
            Trace(
                id=f"advisor-{index}",
                agent="codex",
                host="codex",
                domain="advisor-test",
                task=f"Fix regression {index}",
                status="success",
                files_touched=[f"src/module_{index % 4}/file.py"],
                input_tokens=20_000,
                output_tokens=2_000,
                model="gpt-4o",
                usage_entries=[
                    UsageEntry(
                        model="gpt-4o",
                        input_tokens=20_000,
                        output_tokens=2_000,
                        cost_usd=1.0,
                    )
                ],
                created_at=created_at,
            )
        )


def test_ledger_show_and_summarize(tmp_path: Path) -> None:
    root = tmp_path / "a"
    init_store_at(str(root))
    _seed_ledger(root)
    res = _invoke(root, "ledger", "show", "--json")
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert payload["session_id"] == "run1"

    res2 = _invoke(root, "ledger", "summarize")
    assert res2.exit_code == 0
    assert "Atelier compact state" in res2.output


def test_tool_mode_show_set(tmp_path: Path) -> None:
    root = tmp_path / "a"
    init_store_at(str(root))
    res = _invoke(root, "tools", "mode", "show")
    assert res.exit_code == 0
    assert res.output.strip() == "shadow"
    res2 = _invoke(root, "tools", "mode", "set", "suggest")
    assert res2.exit_code == 0
    res3 = _invoke(root, "tools", "mode", "show")
    assert res3.output.strip() == "suggest"


def test_read_returns_summary_and_related(tmp_path: Path) -> None:
    root = tmp_path / "a"
    init_store_at(str(root))
    f = tmp_path / "x.py"
    f.write_text("\n".join(f"line {i}" for i in range(200)), encoding="utf-8")
    res = _invoke(
        root,
        "tools",
        "call",
        "read",
        "--dev",
        "--args",
        json.dumps({"path": str(f), "max_lines": 50}),
        "--json",
    )
    assert res.exit_code == 0
    payload = json.loads(res.output)
    assert payload["lines_total"] == 200
    assert "summary" in payload


def test_savings_reports_counters(tmp_path: Path) -> None:
    root = tmp_path / "a"
    init_store_at(str(root))
    _seed_ledger(root)
    res = _invoke(root, "savings", "--json")
    assert res.exit_code == 0
    payload = json.loads(res.output)
    assert "rescue_events" in payload
    assert payload["rescue_events"] >= 1
    assert "optimization" in payload


def test_optimize_reports_trace_recommendations(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "a"
    _seed_optimizer_traces(root)
    monkeypatch.setattr("atelier.gateway.cli.commands.savings._run_external_optimize", lambda *_args, **_kwargs: None)

    res = _invoke(root, "optimize", "--host", "codex", "--json")

    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    recommendation_ids = {item["id"] for item in payload["recommendations"]}
    assert payload["host"] == "codex"
    assert "high-cost-session-outliers" in recommendation_ids
    assert "low-worth-expensive-sessions" in recommendation_ids


def test_optimize_accepts_new_registry_host_choice(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "a"
    _seed_optimizer_traces(root)
    monkeypatch.setattr("atelier.gateway.cli.commands.savings._run_external_optimize", lambda *_args, **_kwargs: None)

    # `cursor` is a supported registry host with no seeded traces here; optimize
    # must accept it and report an empty trace count.
    res = _invoke(root, "optimize", "--host", "cursor", "--json")

    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert payload["host"] == "cursor"
    assert payload["trace_count"] == 0


def test_optimize_details_reports_advisor_breakdowns(tmp_path: Path) -> None:
    root = tmp_path / "a"
    _seed_advisor_traces(root)

    res = _invoke(root, "optimize", "details", "--host", "codex", "--json")

    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert payload["has_recommendation"] is True
    recommended = min(
        [candidate for candidate in payload["candidates"] if candidate["id"] != "current"],
        key=lambda candidate: candidate["weekly_cost_usd"],
    )
    assert set(recommended["compaction_breakdown"]) == {
        "prompt_cache_reorder",
        "dedup",
        "retrieval_filter",
        "lossy_summary",
    }


def test_optimize_apply_preset_writes_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "a"
    init_store_at(str(root))

    # Applying a policy is an Atelier Pro feature gated on two walls: a valid
    # license AND the proprietary `atelier_pro` overlay. Grant the license and
    # supply a stub overlay so this exercises the write path, not the gates.
    from types import SimpleNamespace

    from atelier.core.capabilities.optimization.policy import save_policy as _save_policy

    monkeypatch.setattr("atelier.core.capabilities.licensing.require", lambda *a, **k: None)
    monkeypatch.setattr(
        "atelier.core.capabilities.licensing.pro_impl",
        lambda feature: SimpleNamespace(apply_policy=lambda root, policy: _save_policy(Path(root), policy)),
    )

    res = _invoke(root, "optimize", "apply", "--preset", "economy", "--json")

    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert payload["applied"]["preset"] == "economy"
    assert (root / "optimization.yaml").exists()


def test_optimize_shadow_requires_consent_then_records_state(tmp_path: Path) -> None:
    root = tmp_path / "a"
    _seed_advisor_traces(root)

    refused = _invoke(root, "optimize", "shadow", "--json")
    assert refused.exit_code != 0
    assert "requires --i-understand-this-costs-money" in refused.output

    started = _invoke(
        root,
        "optimize",
        "shadow",
        "--i-understand-this-costs-money",
        "--yes",
        "--json",
    )
    assert started.exit_code == 0, started.output
    payload = json.loads(started.output)
    assert payload["status"] == "running"
    assert payload["estimated_weekly_spend_usd"] <= payload["baseline_weekly_cost_usd"]

    status = _invoke(root, "optimize", "shadow", "status", "--json")
    assert status.exit_code == 0, status.output
    assert json.loads(status.output)["status"] == "running"

    forgot = _invoke(root, "optimize", "shadow", "forget-consent", "--json")
    assert forgot.exit_code == 0, forgot.output
    assert json.loads(forgot.output)["revoked"] is True


def test_external_status_cli_reports_tools(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "a"
    init_store_at(str(root))

    monkeypatch.setattr(
        "atelier.gateway.integrations.external_analytics.external_status",
        lambda cwd=None: [
            {
                "tool": "tokscale",
                "display_name": "Tokscale",
                "available": True,
                "license": "MIT",
                "execution_mode": "installed_cli",
                "path": "/usr/bin/tokscale",
                "update_strategy": "pin",
                "install_hint": "install",
                "notes": ["reporting"],
                "recommended_integration": "pinned_sidecar_cli",
            }
        ],
    )

    res = _invoke(root, "savings", "external", "status", "--json")

    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert payload["tools"][0]["tool"] == "tokscale"


def test_external_report_cli_returns_reports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "a"
    init_store_at(str(root))

    monkeypatch.setattr(
        "atelier.gateway.integrations.external_analytics.run_external_reports",
        lambda tool="all", period="week", cwd=None, include_optimize=False: {
            "tool": tool,
            "period": period,
            "reports": [
                {
                    "tool": "codeburn",
                    "ok": True,
                    "command_display": "codeburn report --format json -p week",
                    "payload": {"overview": {"cost": 12.5, "calls": 8, "sessions": 3}},
                }
            ],
        },
    )

    res = _invoke(root, "savings", "external", "report", "--tool", "codeburn", "--json")

    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert payload["reports"][0]["tool"] == "codeburn"


def test_external_report_cli_persists_reports(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "a"
    init_store_at(str(root))

    monkeypatch.setattr(
        "atelier.gateway.integrations.external_analytics.run_external_reports",
        lambda tool="all", period="today", cwd=None, include_optimize=False: {
            "generated_at": "2026-05-14T09:00:00+00:00",
            "tool": tool,
            "period": period,
            "reports": [
                {
                    "tool": "codeburn",
                    "period": period,
                    "ok": True,
                    "returncode": 0,
                    "command_display": "codeburn report --format json -p today",
                    "payload": {"overview": {"cost": 12.5, "calls": 48, "sessions": 3}},
                }
            ],
        },
    )

    res = _invoke(root, "savings", "external", "report", "--tool", "all", "--period", "today", "--persist", "--json")

    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert payload["persisted"][0]["tool"] == "codeburn"

    runs = ContextStore(root).list_external_analytics_runs(tool="codeburn", period="today", limit=10)
    assert len(runs) == 1
    assert runs[0]["payload"]["overview"]["calls"] == 48


def test_external_report_cli_streams_tool_progress(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = tmp_path / "a"
    init_store_at(str(root))
    calls: list[str] = []

    def fake_run_external_report(tool: str, *, period: str = "week", cwd: Path | None = None) -> dict[str, object]:
        _ = cwd
        calls.append(tool)
        return {
            "tool": tool,
            "period": period,
            "ok": True,
            "returncode": 0,
            "command_display": f"{tool} report -p {period}",
            "payload": {"overview": {"cost": 1.0, "calls": len(calls), "sessions": 1}},
        }

    monkeypatch.setattr(
        "atelier.gateway.integrations.external_analytics.run_external_report",
        fake_run_external_report,
    )

    res = _invoke(root, "savings", "external", "report", "--tool", "all", "--period", "today")

    assert res.exit_code == 0, res.output
    assert calls == ["tokscale", "codeburn", "codeburn:optimize"]
    assert "[external-report] running tokscale period=today..." in res.output
    assert "[external-report] done tokscale status=ok" in res.output
    assert "[external-report] running codeburn period=today..." in res.output
    assert "[external-report] done codeburn:optimize status=ok" in res.output


def test_session_hosts_lists_host_rows_without_sync(tmp_path: Path) -> None:
    root = tmp_path / "a"
    init_store_at(str(root))
    store = ContextStore(root)
    store.init()
    now = datetime.now(UTC)
    store.record_trace(
        Trace(
            id="codex-1",
            session_id="sid-codex-1",
            agent="atelier:code",
            host="codex",
            domain="coding",
            task="Fix parser",
            status="success",
            input_tokens=1200,
            cached_input_tokens=3400,
            output_tokens=220,
            model="gpt-5.5",
            usage_entries=[UsageEntry(model="gpt-5.5", input_tokens=1200, output_tokens=220, cost_usd=0.1234)],
            created_at=now,
        )
    )
    store.record_trace(
        Trace(
            id="copilot-1",
            session_id="sid-copilot-1",
            agent="atelier:code",
            host="copilot",
            domain="coding",
            task="Refactor helper",
            status="success",
            input_tokens=800,
            cached_input_tokens=500,
            output_tokens=100,
            model="gpt-5.3-codex",
            usage_entries=[UsageEntry(model="gpt-5.3-codex", input_tokens=800, output_tokens=100, cost_usd=0.05)],
            created_at=now,
        )
    )

    res = _invoke(root, "session", "list", "--host", "codex", "--limit", "5", "--source", "store", "--json")
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert payload["hosts"]["codex"][0]["session_id"] == "sid-codex-1"
    assert payload["hosts"]["codex"][0]["source"] == "host_sessions"
    assert payload["hosts"]["codex"][0]["cost_usd"] > 0


def test_session_hosts_filters_by_session_id(tmp_path: Path) -> None:
    root = tmp_path / "a"
    init_store_at(str(root))
    store = ContextStore(root)
    store.init()
    now = datetime.now(UTC)
    store.record_trace(
        Trace(
            id="codex-1",
            session_id="codex-target-xyz",
            agent="atelier:code",
            host="codex",
            domain="coding",
            task="A",
            status="success",
            model="gpt-5.5",
            usage_entries=[UsageEntry(model="gpt-5.5", cost_usd=0.01)],
            created_at=now,
        )
    )
    store.record_trace(
        Trace(
            id="codex-2",
            session_id="codex-other-abc",
            agent="atelier:code",
            host="codex",
            domain="coding",
            task="B",
            status="success",
            model="gpt-5.5",
            usage_entries=[UsageEntry(model="gpt-5.5", cost_usd=0.02)],
            created_at=now,
        )
    )

    res = _invoke(
        root,
        "session",
        "list",
        "--host",
        "codex",
        "--id",
        "target",
        "--source",
        "store",
        "--json",
    )
    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    rows = payload["hosts"]["codex"]
    assert len(rows) == 1
    assert rows[0]["session_id"] == "codex-target-xyz"
