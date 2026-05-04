from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from atelier.gateway.adapters.mcp_server import _handle


def _call(name: str, args: dict[str, Any]) -> Any:
    req: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": name, "arguments": args},
    }
    resp = _handle(req)
    assert isinstance(resp, dict)
    return resp


def _result(resp: dict[str, Any]) -> Any:
    assert "result" in resp, resp
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert isinstance(payload, dict)
    return payload


def _seed_sqlite(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
        conn.executemany(
            "INSERT INTO items(name) VALUES(?)",
            [("a",), ("b",), ("c",), ("d",)],
        )
        conn.commit()
    finally:
        conn.close()


@pytest.fixture()
def sql_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    root = tmp_path / ".atelier"
    root.mkdir(parents=True, exist_ok=True)

    db_path = tmp_path / "inspect.sqlite"
    _seed_sqlite(db_path)

    monkeypatch.setenv("ATELIER_LOCAL_SQLITE", str(db_path))
    monkeypatch.setenv("ATELIER_ROOT", str(root))

    (root / "sql_aliases.toml").write_text(
        """
[aliases.atelier_local]
backend = "sqlite"
env = "ATELIER_LOCAL_SQLITE"
allow_writes = false
""".strip() + "\n",
        encoding="utf-8",
    )

    import atelier.gateway.adapters.mcp_server as m

    m._current_ledger = None
    return root


def test_sql_inspect_tool_registered() -> None:
    from atelier.gateway.adapters.mcp_server import TOOLS

    assert "atelier_sql_inspect" in TOOLS


def test_sql_inspect_read_only_query(sql_env: Path) -> None:
    resp = _call(
        "atelier_sql_inspect",
        {
            "connection_alias": "atelier_local",
            "sql": "SELECT id, name FROM items ORDER BY id",
            "row_limit": 2,
        },
    )
    payload = _result(resp)
    assert payload["row_count"] == 2
    assert payload["truncated"] is True
    assert len(payload["columns"]) == 2
    assert payload["rows"][0]["id"] == 1


def test_sql_inspect_rejects_write_on_read_only_alias(sql_env: Path) -> None:
    resp = _call(
        "atelier_sql_inspect",
        {
            "connection_alias": "atelier_local",
            "sql": "INSERT INTO items(name) VALUES('x')",
        },
    )
    assert "error" in resp
    assert "read-only" in resp["error"]["message"].lower()
