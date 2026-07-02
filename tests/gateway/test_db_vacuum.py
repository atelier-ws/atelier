from __future__ import annotations

import sqlite3
from pathlib import Path

from click.testing import CliRunner

from atelier.core.foundation.store import ContextStore
from atelier.gateway.cli import cli


def _seed_trace(root: Path) -> None:
    # Sessions are file-based now, so the schema no longer creates a traces table.
    # Simulate a legacy pre-redesign DB so `db vacuum --reset-traces` can reclaim it.
    ContextStore(root).init()
    with sqlite3.connect(str(root / "atelier.db")) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS traces (id TEXT PRIMARY KEY, payload TEXT)")
        conn.execute("INSERT INTO traces (id, payload) VALUES ('legacy-1', '{}')")
        conn.commit()


def _trace_count(root: Path) -> int:
    conn = sqlite3.connect(str(root / "atelier.db"))
    try:
        return int(conn.execute("SELECT COUNT(*) FROM traces").fetchone()[0])
    except sqlite3.OperationalError:
        return 0  # legacy table dropped by reset-traces
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
