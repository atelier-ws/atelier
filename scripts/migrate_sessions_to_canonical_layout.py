"""Migrate every per-session directory into the canonical
sessions/YYYY/MM/DD/<host>/<session_id>/ layout (host-segregated, date-resolved).

Consolidates three legacy shapes, all rooted at one atelier store root, into one:
  - <root>/sessions/<id>/                     (old flat -- no date, no host)
  - <root>/sessions/YYYY/MM/DD/<id>/           (old dated -- no host)
  - <root>/workspaces/<ws>/sessions/<id>/      (old workspace-nested flat)
into:
  - <root>/sessions/YYYY/MM/DD/<host>/<id>/

Host is read from the session's own run.json "agent" field when present, else
defaults to "claude" (the pre-migration default agent -- see
atelier.core.foundation.paths.detect_host). Date is read from run.json's
"created_at", else stats.json's started_at_ms, else the directory's own
YYYY/MM/DD path segments (for the old-dated shape), else the directory's own
mtime as a last resort.

Dry-run by default -- prints the plan without moving anything. Pass --apply to
actually perform the moves (a plain Path.rename per directory, so this is a
cheap same-filesystem operation, not a copy). Already-canonical (5-level,
host-segregated) directories are left untouched. Any destination collision is
skipped with a warning, never overwritten or merged.

Usage:
    uv run python scripts/migrate_sessions_to_canonical_layout.py [ROOT] [--apply]
"""

from __future__ import annotations

import json
import sys
from datetime import date, datetime
from pathlib import Path

_SESSION_FILES = (
    "run.json",
    "stats.json",
    "events.jsonl",
    "mcp_debug.jsonl",
    "runtime_state.json",
    "statusline_segment",
    "savings.jsonl",
    "outcomes.json",
    "compact_manifest.json",
    "HANDOVER.md",
    "spend_cache.json",
)


def _looks_like_session_dir(p: Path) -> bool:
    return p.is_dir() and any((p / f).exists() for f in _SESSION_FILES)


def _detect_host(session_dir: Path) -> str:
    run_json = session_dir / "run.json"
    if run_json.exists():
        try:
            data = json.loads(run_json.read_text("utf-8"))
            agent = str(data.get("agent") or "").strip()
            if agent:
                return agent
        except (OSError, ValueError):
            pass
    return "claude"


def _detect_date(session_dir: Path, path_date: date | None) -> date:
    if path_date is not None:
        return path_date
    run_json = session_dir / "run.json"
    if run_json.exists():
        try:
            data = json.loads(run_json.read_text("utf-8"))
            created = str(data.get("created_at") or "").strip()
            if created:
                return datetime.fromisoformat(created.replace("Z", "+00:00")).date()
        except (OSError, ValueError):
            pass
    stats_json = session_dir / "stats.json"
    if stats_json.exists():
        try:
            data = json.loads(stats_json.read_text("utf-8"))
            started_ms = data.get("started_at_ms")
            if isinstance(started_ms, (int, float)) and started_ms > 0:
                return datetime.fromtimestamp(started_ms / 1000).date()
        except (OSError, ValueError):
            pass
    try:
        return datetime.fromtimestamp(session_dir.stat().st_mtime).date()
    except OSError:
        return date.today()


def _scan_sessions_tree(root: Path, sessions_root: Path, moves: list[tuple[Path, Path]]) -> None:
    if not sessions_root.is_dir():
        return
    for child in sorted(sessions_root.iterdir()):
        if not child.is_dir():
            continue
        if _looks_like_session_dir(child):
            # sessions/<id>/ -- old flat, no date, no host.
            session_id = child.name
            d = _detect_date(child, None)
            host = _detect_host(child)
            new_dir = root / "sessions" / f"{d.year:04d}" / f"{d.month:02d}" / f"{d.day:02d}" / host / session_id
            moves.append((child, new_dir))
            continue
        if not (child.name.isdigit() and len(child.name) == 4):
            continue  # not a year dir and not a session dir -- ignore
        year = child
        for month in sorted(p for p in year.iterdir() if p.is_dir()):
            for day in sorted(p for p in month.iterdir() if p.is_dir()):
                for leaf in sorted(p for p in day.iterdir() if p.is_dir()):
                    if not _looks_like_session_dir(leaf):
                        continue  # already host-segregated (canonical) -- nothing to do
                    # day/<id>/ -- old dated, no host. Date is already known
                    # from the path itself.
                    session_id = leaf.name
                    host = _detect_host(leaf)
                    new_dir = root / "sessions" / year.name / month.name / day.name / host / session_id
                    moves.append((leaf, new_dir))


def _plan_moves(root: Path) -> list[tuple[Path, Path]]:
    moves: list[tuple[Path, Path]] = []
    _scan_sessions_tree(root, root / "sessions", moves)
    workspaces_root = root / "workspaces"
    if workspaces_root.is_dir():
        for ws_dir in sorted(p for p in workspaces_root.iterdir() if p.is_dir()):
            _scan_sessions_tree(root, ws_dir / "sessions", moves)
    return moves


def main(argv: list[str]) -> int:
    apply = "--apply" in argv
    args = [a for a in argv if a != "--apply"]
    root = Path(args[0]).expanduser().resolve() if args else Path.home() / ".atelier"

    moves = _plan_moves(root)
    if not moves:
        print(f"[done] no legacy session directories found under {root}")
        return 0

    by_host: dict[str, int] = {}
    for _old_dir, new_dir in moves:
        by_host[new_dir.parent.name] = by_host.get(new_dir.parent.name, 0) + 1

    print(f"{'[apply]' if apply else '[dry-run]'} {len(moves)} legacy session directories under {root}")
    for host, count in sorted(by_host.items()):
        print(f"    {host}: {count}")

    moved = 0
    skipped = 0
    for old_dir, new_dir in moves:
        if new_dir.exists():
            print(f"[skip] target already exists: {new_dir} (from {old_dir})")
            skipped += 1
            continue
        if not apply:
            continue
        new_dir.parent.mkdir(parents=True, exist_ok=True)
        old_dir.rename(new_dir)
        moved += 1

    if apply:
        print(f"[done] moved {moved}, skipped {skipped}")
    else:
        print("dry run only -- pass --apply to actually move directories")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
