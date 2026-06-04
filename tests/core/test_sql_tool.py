from __future__ import annotations

import sqlite3
from pathlib import Path

from atelier.core.capabilities.tool_supervision.sql_tool import (
    detect_dialect,
    discover_connection,
    lint_sql,
    mask_connection_string,
    sql_tool,
)


def test_sql_discovery_masking_and_lint(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("DATABASE_URL=sqlite:///data.db\n", encoding="utf-8")

    discovered = discover_connection(tmp_path, env={})
    assert discovered["source"] == "dotenv:DATABASE_URL"
    assert discovered["dialect"] == "sqlite"
    assert detect_dialect("postgres://u:p@example/db") == "postgres"
    assert mask_connection_string("postgres://user:secret@example/db") == "postgres://user:****@example/db"
    assert lint_sql("DELETE FROM users", allow_writes=False)["ok"] is False


def test_sql_sqlite_connect_query_batch_auto_limit(tmp_path: Path) -> None:
    db_path = tmp_path / "data.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE users(id integer primary key, name text)")
    conn.executemany("INSERT INTO users(name) VALUES(?)", [("Ada",), ("Grace",), ("Linus",)])
    conn.commit()
    conn.close()

    connect = sql_tool(action="connect", connection_string=f"sqlite:///{db_path}", repo_root=tmp_path)
    assert connect["overview"]["table_count"] == 1

    result = sql_tool(
        action="query",
        connection_string=f"sqlite:///{db_path}",
        queries=[{"name": "users", "sql": "SELECT * FROM users ORDER BY id"}],
        max_rows=2,
        repo_root=tmp_path,
    )

    assert result["isError"] is False
    assert result["results"][0]["row_count"] == 2
    assert result["results"][0]["truncated"] is False
    assert result["results"][0]["auto_limit_changed"] is True


def test_sql_sqlite_introspection_actions(tmp_path: Path) -> None:
    db_path = tmp_path / "data.db"
    conn = sqlite3.connect(db_path)
    conn.execute("CREATE TABLE users(id integer primary key, name text)")
    conn.execute("CREATE TABLE orders(id integer primary key, user_id integer references users(id), total real)")
    conn.commit()
    conn.close()
    dsn = f"sqlite:///{db_path}"

    tables = sql_tool(action="tables", connection_string=dsn, repo_root=tmp_path)
    assert tables["table_count"] == 2
    assert set(tables["tables"]) == {"users", "orders"}

    table = sql_tool(action="table", name="orders", connection_string=dsn, repo_root=tmp_path)
    assert {c["name"] for c in table["columns"]} == {"id", "user_id", "total"}
    assert table["foreign_keys"][0]["table"] == "users"

    rels = sql_tool(action="relationships", connection_string=dsn, repo_root=tmp_path)
    assert {"from": "orders.user_id", "to": "users.id"} in rels["relationships"]

    found = sql_tool(action="search", name="user", connection_string=dsn, repo_root=tmp_path)
    matched = {m["table"] for m in found["matches"]}
    assert "users" in matched  # matched by table name
    assert "orders" in matched  # matched by user_id column
