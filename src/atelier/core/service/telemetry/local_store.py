"""Local SQLite product telemetry store."""

from __future__ import annotations

import json
import os
import sqlite3
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

RETENTION_DAYS = 30


def default_db_path() -> Path:
    return Path(os.environ.get("ATELIER_TELEMETRY_DB", Path.home() / ".atelier" / "telemetry.db"))


class LocalTelemetryStore:
    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or default_db_path()

    def write_event(
        self,
        *,
        event: str,
        props: dict[str, Any],
        exported: bool,
        ts: float | None = None,
    ) -> int:
        timestamp = time.time() if ts is None else ts
        session_id = props.get("session_id") if isinstance(props.get("session_id"), str) else None
        with self._connect() as conn:
            self._init(conn)
            self._prune(conn, timestamp)
            cur = conn.execute(
                """
                INSERT INTO events (ts, event, session_id, props_json, exported)
                VALUES (?, ?, ?, ?, ?)
                """,
                (timestamp, event, session_id, json.dumps(props, sort_keys=True), int(exported)),
            )
            return int(cur.lastrowid or 0)

    def list_events(
        self,
        *,
        since: float | None = None,
        event: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 1000))
        clauses: list[str] = []
        params: list[Any] = []
        if since is not None:
            clauses.append("ts >= ?")
            params.append(since)
        if event:
            clauses.append("event = ?")
            params.append(event)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as conn:
            self._init(conn)
            rows = conn.execute(
                f"""
                SELECT id, ts, event, session_id, props_json, exported
                FROM events{where}
                ORDER BY ts DESC
                LIMIT ?
                """,
                (*params, limit),
            ).fetchall()
        return [_row_to_event(row) for row in rows]

    def summary(self, *, since: float | None = None) -> dict[str, Any]:
        events = self.list_events(since=since, limit=1000)
        commands_by_day: Counter[str] = Counter()
        top_commands: Counter[str] = Counter()
        agent_hosts: Counter[str] = Counter()
        top_reasonblocks: Counter[str] = Counter()
        reasonblock_domains: dict[str, str] = {}
        retrieval_scores: Counter[str] = Counter()
        plan_checks: Counter[str] = Counter()
        frustration_behavioral: Counter[str] = Counter()
        frustration_lexical: Counter[str] = Counter()
        value = {"tokens_saved_estimate": 0, "cache_hits": 0, "blocks_applied": 0}
        event_counts: Counter[str] = Counter()

        for item in events:
            props = item["props"]
            event_counts[item["event"]] += 1
            day = time.strftime("%Y-%m-%d", time.localtime(float(item["ts"])))
            if item["event"] in {"cli_command_invoked", "cli_command_completed"}:
                commands_by_day[day] += 1
                command = props.get("command_name")
                if isinstance(command, str):
                    top_commands[command] += 1
            if item["event"] == "session_start":
                host = props.get("agent_host")
                if isinstance(host, str):
                    agent_hosts[host] += 1
            if item["event"] == "reasonblock_applied":
                block_hash = props.get("block_id_hash")
                if isinstance(block_hash, str):
                    top_reasonblocks[block_hash] += 1
                    domain = props.get("domain")
                    if isinstance(domain, str):
                        reasonblock_domains[block_hash] = domain
            if item["event"] in {"reasonblock_applied", "reasonblock_retrieved"}:
                score = props.get("retrieval_score")
                if isinstance(score, (int, float)):
                    retrieval_scores[_score_bucket(float(score))] += 1
            if item["event"].startswith("plan_check_"):
                plan_checks[item["event"]] += 1
            if item["event"] == "frustration_signal_behavioral":
                signal = props.get("signal_type")
                if isinstance(signal, str):
                    frustration_behavioral[signal] += 1
            if item["event"] == "frustration_signal_lexical":
                category = props.get("category")
                if isinstance(category, str):
                    frustration_lexical[category] += 1
            if item["event"] == "value_estimate":
                for key in value:
                    raw = props.get(key)
                    if isinstance(raw, int) and not isinstance(raw, bool):
                        value[key] += raw

        return {
            "events_total": sum(event_counts.values()),
            "event_counts": dict(event_counts),
            "commands_by_day": _counter_series(commands_by_day),
            "top_commands": _counter_items(top_commands),
            "agent_hosts": _counter_items(agent_hosts),
            "top_reasonblocks": [
                {"block_id_hash": key, "count": count, "domain": reasonblock_domains.get(key, "")}
                for key, count in top_reasonblocks.most_common(10)
            ],
            "retrieval_score_distribution": _counter_items(retrieval_scores),
            "plan_checks": dict(plan_checks),
            "frustration_behavioral": _counter_items(frustration_behavioral),
            "frustration_lexical": _counter_items(frustration_lexical),
            "value_estimate": value,
        }

    def _connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self, conn: sqlite3.Connection) -> None:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              ts REAL NOT NULL,
              event TEXT NOT NULL,
              session_id TEXT,
              props_json TEXT NOT NULL,
              exported INTEGER NOT NULL DEFAULT 0
            )
            """)
        conn.execute("CREATE INDEX IF NOT EXISTS events_ts ON events(ts DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS events_event_ts ON events(event, ts DESC)")
        conn.execute("CREATE INDEX IF NOT EXISTS events_session ON events(session_id)")

    def _prune(self, conn: sqlite3.Connection, now: float) -> None:
        cutoff = now - RETENTION_DAYS * 24 * 60 * 60
        conn.execute("DELETE FROM events WHERE ts < ?", (cutoff,))


def _row_to_event(row: sqlite3.Row) -> dict[str, Any]:
    try:
        props = json.loads(row["props_json"])
    except json.JSONDecodeError:
        props = {}
    return {
        "id": row["id"],
        "ts": row["ts"],
        "event": row["event"],
        "session_id": row["session_id"],
        "props": props,
        "exported": bool(row["exported"]),
    }


def _counter_items(counter: Counter[str]) -> list[dict[str, Any]]:
    return [{"name": key, "count": count} for key, count in counter.most_common(20)]


def _counter_series(counter: Counter[str]) -> list[dict[str, Any]]:
    by_day: defaultdict[str, int] = defaultdict(int)
    by_day.update(counter)
    return [{"day": key, "count": by_day[key]} for key in sorted(by_day)]


def _score_bucket(value: float) -> str:
    if value < 0.25:
        return "0-0.25"
    if value < 0.5:
        return "0.25-0.5"
    if value < 0.75:
        return "0.5-0.75"
    return "0.75-1.0"
