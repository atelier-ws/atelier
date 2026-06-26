"""Mine Claude Code session files for explore/grep queries + edited files.

Produces (query, tid, prefix) pairs for the Atelier repo using session_id as
task_id and edited src/ files as gold files.
Appends the atelier__atelier repo to benchmarks/codebench/data/bench_pairs_multi.json.

Usage:
  uv run python scripts/_mine_sessions.py
"""

import json
import pathlib
import sys

SESSION_DIR = pathlib.Path("/home/pankaj/.claude/projects/-home-pankaj-Projects-leanchain-atelier")
OUT = pathlib.Path("benchmarks/codebench/data/bench_pairs_multi.json")
ATELIER_WS = pathlib.Path("/home/pankaj/Projects/leanchain/atelier")
ATELIER_DB = pathlib.Path("/home/pankaj/.atelier/workspaces/Projects-leanchain-atelier/code_context.sqlite")
PREFIX = "atelier__atelier"
MIN_Q, MAX_Q = 5, 120

_GOLD_SKIP = (".venv", "node_modules", "__pycache__", ".git", ".mypy_cache")


def mine_session(path: pathlib.Path) -> tuple[list[str], set[str]]:
    """Return (queries, edited_paths) from a session .jsonl file.

    Queries = explore + grep calls.  Gold = any .py/.ts/.js file edited.
    """
    queries: list[str] = []
    gold: set[str] = set()
    seen_q: set[str] = set()
    try:
        for line in path.read_text(errors="replace").splitlines():
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = obj.get("message", {})
            if msg.get("role") != "assistant":
                continue
            for block in msg.get("content", []):
                if not isinstance(block, dict) or block.get("type") != "tool_use":
                    continue
                name = str(block.get("name", "")).lower()
                inp = block.get("input") or {}

                # queries: explore or grep
                if "explore" in name:
                    q = str(inp.get("query") or "").strip()
                    if MIN_Q <= len(q) <= MAX_Q and q not in seen_q:
                        queries.append(q)
                        seen_q.add(q)
                elif "grep" in name:
                    q = str(inp.get("regex") or inp.get("query") or "").strip()
                    if MIN_Q <= len(q) <= MAX_Q and q not in seen_q:
                        queries.append(q)
                        seen_q.add(q)

                # gold: any .py/.ts/.js file edited
                if "edit" in name:
                    for edit in inp.get("edits", []):
                        p = str(edit.get("path") or "")
                        if not p:
                            continue
                        if not any(p.endswith(ext) for ext in (".py", ".ts", ".js")):
                            continue
                        if any(skip in p for skip in _GOLD_SKIP):
                            continue
                        if p.startswith("/"):
                            try:
                                p = str(pathlib.Path(p).relative_to(ATELIER_WS))
                            except ValueError:
                                continue
                        gold.add(p)
    except Exception:  # noqa: BLE001
        pass
    return queries, gold


def main() -> None:
    session_files = sorted(SESSION_DIR.glob("*.jsonl"))
    print(f"[mine] scanning {len(session_files)} session files ...", flush=True)

    by_session: dict[str, dict] = {}
    for sf in session_files:
        tid = sf.stem
        queries, gold = mine_session(sf)
        if queries and gold:
            by_session[tid] = {"queries": queries, "gold": list(gold)}

    print(f"[mine] {len(by_session)} sessions with both queries and edits", flush=True)

    pairs: list[list[str]] = []
    true_map: dict[str, list[str]] = {}
    for tid, d in by_session.items():
        real_gold = [g for g in d["gold"] if (ATELIER_WS / g).exists()]
        if not real_gold:
            continue
        true_map[tid] = real_gold
        for q in d["queries"]:
            pairs.append([q, tid, PREFIX])

    print(f"[mine] {len(pairs)} pairs across {len(true_map)} sessions", flush=True)

    existing = json.loads(OUT.read_text())
    existing_pairs = [p for p in existing["pairs"] if p[2] != PREFIX]
    existing_true = {k: v for k, v in existing["true_map"].items() if k not in true_map}
    existing_true.update(true_map)
    existing_repos = existing["repos"]
    existing_repos[PREFIX] = {
        "ws": str(ATELIER_WS),
        "db": str(ATELIER_DB),
        "anchor": "local",
        "base_commit": "",
    }

    merged_pairs = existing_pairs + pairs
    uniq = len({(q, p) for q, _, p in merged_pairs})
    print(f"[mine] total pairs: {len(merged_pairs)} | unique (query,repo): {uniq}", flush=True)

    OUT.write_text(json.dumps({"pairs": merged_pairs, "true_map": existing_true, "repos": existing_repos}))
    print(f"[mine] wrote {OUT}", flush=True)


if __name__ == "__main__":
    sys.path.insert(0, "src")
    main()
