#!/usr/bin/env python3
"""One-time bulk push of all historical Claude session savings to D1.

Run from the repo root:
    uv run python scripts/bulk_push_savings.py [--dry-run] [--limit N]

Iterates every ~/.claude/projects/**/<session-id>.jsonl, computes savings,
and POSTs to the public rollup endpoint.  D1 upserts via max() so re-running
is safe -- no double-counting.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Args
# ---------------------------------------------------------------------------
parser = argparse.ArgumentParser(description="Bulk-push historical savings to D1")
parser.add_argument("--dry-run", action="store_true", help="Print payload, don't POST")
parser.add_argument("--limit", type=int, default=0, help="Max sessions (0=all)")
parser.add_argument("--endpoint", default="https://atelier.ws/api/telemetry/rollup")
args = parser.parse_args()

# ---------------------------------------------------------------------------
# Imports that need the atelier venv (uv run)
# ---------------------------------------------------------------------------
try:
    import atelier as _atelier_pkg
    from atelier.core.capabilities.savings_summary import compute_savings_summary

    VERSION = getattr(_atelier_pkg, "__version__", "unknown")
except ImportError as e:
    print(f"ERROR: {e}\nRun with: uv run python scripts/bulk_push_savings.py", file=sys.stderr)
    sys.exit(1)

try:
    import httpx

    def _post(url: str, data: dict) -> int:
        r = httpx.post(url, json=data, timeout=10)
        return r.status_code

except ImportError:
    import urllib.request

    def _post(url: str, data: dict) -> int:  # type: ignore[misc]
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": "application/json",
                "User-Agent": f"atelier/{VERSION} (bulk-push)",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# install_id
# ---------------------------------------------------------------------------
_auth_path = Path.home() / ".atelier" / "auth.json"
try:
    _auth = json.loads(_auth_path.read_text())
    INSTALL_ID: str = _auth.get("install_id") or _auth.get("userId") or "unknown"
except Exception:  # noqa: BLE001
    INSTALL_ID = "unknown"

print(f"install_id: {INSTALL_ID[:12]}...")

# ---------------------------------------------------------------------------
# Discover all Claude sessions
# ---------------------------------------------------------------------------
projects_root = (
    Path(os.environ["CLAUDE_CONFIG_DIR"])
    if "CLAUDE_CONFIG_DIR" in os.environ
    else Path(os.environ["CLAUDE_HOME"]) if "CLAUDE_HOME" in os.environ else Path.home() / ".claude"
) / "projects"

sessions: list[tuple[str, Path]] = []
for proj_dir in sorted(projects_root.iterdir()):
    if not proj_dir.is_dir():
        continue
    for jl in sorted(proj_dir.glob("*.jsonl")):
        sessions.append((jl.stem, jl))
    sub = proj_dir / "subagents"
    if sub.is_dir():
        for jl in sorted(sub.glob("*.jsonl")):
            sessions.append((jl.stem, jl))

print(f"Found {len(sessions)} sessions")

if args.limit:
    sessions = sessions[: args.limit]
    print(f"Limiting to first {args.limit}")

# ---------------------------------------------------------------------------
# Process
# ---------------------------------------------------------------------------
pushed = skipped = errors = 0

for i, (session_id, path) in enumerate(sessions, 1):
    try:
        result = compute_savings_summary(session_id)
    except Exception:  # noqa: BLE001
        errors += 1
        continue

    if not result:
        skipped += 1
        continue

    # SavingsSummary dataclass — same fields stop.py uses
    saved_usd: float = float(result.saved_usd or 0)
    tokens_saved: int = int(result.ctx_saved or 0)
    calls_avoided: int = int(result.smart_calls or 0)
    carry_usd: float = float(result.carry_usd or 0)
    carry_tokens: int = int(result.carry_tokens or 0)

    if saved_usd == 0 and tokens_saved == 0 and carry_usd == 0 and carry_tokens == 0:
        skipped += 1
        continue

    # Count human turns from transcript
    turns = 0
    try:
        with open(path) as f:
            for line in f:
                d = json.loads(line)
                if d.get("type") == "user":
                    turns += 1
    except Exception:  # noqa: BLE001
        pass

    occurred_at = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC).isoformat()

    payload = {
        "session_id": session_id,
        "install_id": INSTALL_ID,
        "occurred_at": occurred_at,
        "atelier_version": VERSION,
        "source": "atelier",
        "saved_usd": round(saved_usd, 6),
        "tokens_saved": tokens_saved,
        "calls_avoided": calls_avoided,
        "carry_usd": round(carry_usd, 6),
        "carry_tokens": carry_tokens,
        "turn_count": turns,
    }

    if args.dry_run:
        print(
            f"[{i}] DRY {session_id[:8]} saved=${saved_usd:.4f} tokens={tokens_saved} calls={calls_avoided} turns={turns}"
        )
        pushed += 1
        continue

    try:
        status = _post(args.endpoint, payload)
        if status in (200, 201):
            pushed += 1
            if pushed % 20 == 0:
                print(f"  pushed {pushed}/{i} ...")
        else:
            errors += 1
            if errors <= 5:
                print(f"  HTTP {status} for {session_id[:8]}", file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        errors += 1
        if errors <= 5:
            print(f"  error {session_id[:8]}: {e}", file=sys.stderr)

    time.sleep(0.05)  # 20 req/s

print(f"\nDone: pushed={pushed} skipped={skipped} errors={errors}")
