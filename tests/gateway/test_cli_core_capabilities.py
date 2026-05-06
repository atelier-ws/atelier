from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from click.testing import CliRunner

from atelier.gateway.adapters.cli import cli
from atelier.infra.runtime.run_ledger import RunLedger


def _invoke(root: Path, *args: str) -> tuple[int, str]:
    runner = CliRunner()
    res = runner.invoke(cli, ["--root", str(root), *args])
    return res.exit_code, res.output


def test_capability_commands_and_benchmark_runtime(tmp_path: Path) -> None:
    root = tmp_path / ".atelier"
    code, out = _invoke(root, "init")
    assert code == 0, out

    code, out = _invoke(root, "capability", "list", "--json")
    assert code == 0, out
    payload = json.loads(out)
    ids = {item["id"] for item in payload}
    assert "reasoning_reuse" in ids
    assert "tool_supervision" in ids

    code, out = _invoke(root, "capability", "status", "--json")
    assert code == 0, out
    status = json.loads(out)
    assert "tool_supervision" in status

    code, out = _invoke(root, "benchmark-runtime", "--json")
    assert code == 0, out
    metrics = json.loads(out)
    assert "total_tool_calls" in metrics


def test_memory_summarize_search_smart_and_sql_inspect(tmp_path: Path) -> None:
    root = tmp_path / ".atelier"
    code, out = _invoke(root, "init")
    assert code == 0, out

    ledger = RunLedger(root=root, agent="test", task="t", domain="d")
    ledger.record_command("pytest", ok=False, error_signature="same")
    ledger.record_alert("repeated_command_failure", "high", "repeat")
    ledger.persist(root)

    code, out = _invoke(root, "memory", "summarize", "--run-id", ledger.run_id)
    assert code == 0, out
    summary = json.loads(out)
    assert summary["run_id"] == ledger.run_id

    code, out = _invoke(root, "search", "smart", "shopify", "--limit", "3")
    assert code == 0, out
    search_payload = json.loads(out)
    assert "matches" in search_payload

    db_path = tmp_path / "cli_sqlite.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE items(id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO items(name) VALUES('cli')")
        conn.commit()
    finally:
        conn.close()

    alias_file = root / "sql_aliases.toml"
    alias_file.write_text(
        ("[aliases.cli_local]\n" 'backend = "sqlite"\n' f'dsn = "{db_path}"\n' "allow_writes = false\n"),
        encoding="utf-8",
    )

    code, out = _invoke(
        root,
        "sql",
        "inspect",
        "--alias",
        "cli_local",
        "--sql",
        "select id, name from items order by id",
    )
    assert code == 0, out
    sql_payload = json.loads(out)
    assert "columns" in sql_payload


def test_read_smart_and_edit_smart(tmp_path: Path) -> None:
    root = tmp_path / ".atelier"
    code, out = _invoke(root, "init")
    assert code == 0, out

    target = tmp_path / "module.py"
    target.write_text("def f():\n    return 1\n", encoding="utf-8")

    code, out = _invoke(root, "read", "smart", str(target), "--max-lines", "20")
    assert code == 0, out
    payload = json.loads(out)
    assert payload["language"] == "python"

    edit_file = tmp_path / "edits.json"
    edit_file.write_text(
        json.dumps([{"path": str(target), "find": "return 1", "replace": "return 2"}]),
        encoding="utf-8",
    )

    code, out = _invoke(root, "edit", "smart", "--input", str(edit_file))
    assert code == 0, out
    edit_payload = json.loads(out)
    assert edit_payload["applied"] == 1
    assert "return 2" in target.read_text(encoding="utf-8")
