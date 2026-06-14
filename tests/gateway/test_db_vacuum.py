from __future__ import annotations

import sqlite3
from pathlib import Path

from click.testing import CliRunner

from atelier.core.foundation.store import ContextStore
from atelier.gateway.cli import cli


def _seed_trace(root: Path) -> None:
    # record_trace now writes the file-based session store, so seed the DB traces
    # table directly to simulate legacy pre-migration rows that `db vacuum` reclaims.
    ContextStore(root).init()
    with sqlite3.connect(str(root / "atelier.db")) as conn:
        conn.execute(
            "INSERT INTO traces (id, agent, host, domain, status, task, workspace_path, created_at, payload)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            ("legacy-1", "gsd-executor", "claude", "coding", "success", "x", "/w", "2026-06-10T00:00:00+00:00", "{}"),
        )
        conn.commit()


def _trace_count(root: Path) -> int:
    conn = sqlite3.connect(str(root / "atelier.db"))
    try:
        return int(conn.execute("SELECT COUNT(*) FROM traces").fetchone()[0])
    finally:
        conn.close()


def test_db_vacuum_reset_traces_clears_history(tmp_path: Path) -> None:
    root = tmp_path / ".atelier"
    _seed_trace(root)
    assert _trace_count(root) == 1

    result = CliRunner().invoke(cli, ["--root", str(root), "db", "vacuum", "--reset-traces", "-f", "--json"])
    assert result.exit_code == 0, result.output
    assert _trace_count(root) == 0


def test_db_vacuum_without_reset_keeps_traces(tmp_path: Path) -> None:
    root = tmp_path / ".atelier"
    _seed_trace(root)
    result = CliRunner().invoke(cli, ["--root", str(root), "db", "vacuum", "--json"])
    assert result.exit_code == 0, result.output
    assert _trace_count(root) == 1  # vacuum alone must not delete data


def test_db_vacuum_no_db(tmp_path: Path) -> None:
    result = CliRunner().invoke(cli, ["--root", str(tmp_path / ".atelier"), "db", "vacuum"])
    assert result.exit_code == 0
    assert "no atelier.db" in result.output
