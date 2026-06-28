"""CLI tests for V2 commands: ledger, compress, env, failure, eval, read, savings."""

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


def test_failure_list_accept_reject(tmp_path: Path) -> None:
    root = tmp_path / "a"
    init_store_at(str(root))
    _seed_ledger(root)
    _seed_ledger(root, session_id="run2")

    res = _invoke(root, "failure", "list", "--json")
    assert res.exit_code == 0
    clusters = json.loads(res.output)
    assert clusters
    cid = clusters[0]["id"]

    res2 = _invoke(root, "failure", "accept", cid)
    assert res2.exit_code == 0
    res3 = _invoke(root, "failure", "list", "--json")
    payload = json.loads(res3.output)
    assert any(c["status"] == "accepted" for c in payload)

    res4 = _invoke(root, "failure", "reject", cid)
    assert res4.exit_code == 0


def test_analyze_failures_cli(tmp_path: Path) -> None:
    root = tmp_path / "a"
    init_store_at(str(root))
    _seed_ledger(root)
    res = _invoke(root, "analyze-failures", "--json")
    assert res.exit_code == 0
    assert json.loads(res.output)


def test_eval_lifecycle(tmp_path: Path) -> None:
    root = tmp_path / "a"
    init_store_at(str(root))
    eval_dir = root / "evals"
    eval_dir.mkdir(parents=True, exist_ok=True)
    case = {
        "id": "case1",
        "domain": "state.change",
        "description": "blocks slug-only identity plan",
        "task": "Fix external state",
        "plan": ["Resolve target from URL slug alone"],
        "expected_status": "blocked",
        "status": "draft",
    }
    (eval_dir / "case1.json").write_text(json.dumps(case), encoding="utf-8")

    res = _invoke(root, "eval", "list", "--json")
    assert res.exit_code == 0
    assert json.loads(res.output)

    res2 = _invoke(root, "eval", "run", "--case", "case1", "--json")
    assert res2.exit_code == 0
    results = json.loads(res2.output)
    assert results[0]["passed"] is True

    res3 = _invoke(root, "eval", "promote", "case1")
    assert res3.exit_code == 0
    promoted = json.loads((eval_dir / "case1.json").read_text(encoding="utf-8"))
    assert promoted["status"] == "active"


def test_tool_mode_show_set(tmp_path: Path) -> None:
    root = tmp_path / "a"
    init_store_at(str(root))
    res = _invoke(root, "tool-mode", "show")
    assert res.exit_code == 0
    assert res.output.strip() == "shadow"
    res2 = _invoke(root, "tool-mode", "set", "suggest")
    assert res2.exit_code == 0
    res3 = _invoke(root, "tool-mode", "show")
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

    res = _invoke(root, "optimize", "--host", "qwen", "--json")

    assert res.exit_code == 0, res.output
    payload = json.loads(res.output)
    assert payload["host"] == "qwen"
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


def test_optimize_apply_preset_writes_policy(tmp_path: Path) -> None:
    root = tmp_path / "a"
    init_store_at(str(root))

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
