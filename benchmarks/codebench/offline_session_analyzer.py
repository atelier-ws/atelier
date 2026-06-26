"""Offline session analyzer — mine Claude Code session files for search patterns.

Reads session JSONL files from ``~/.claude/projects/`` (or a user-provided path),
extracts all search tool calls (grep, explore, ToolSearch), groups them into
"search episodes" between user messages, and produces:

1. **Savings report** — how many individual grep calls each explore replaced,
   and how many turns were saved per session.
2. **Benchmark pairs** — ``(query, gold_file)`` pairs mined from grep results,
   compatible with the existing ``fitness_explore_mrr.py`` and ``eval_cg_mrr.py``
   MRR eval scripts.

Usage::

    # Analyze and generate pairs JSON for a specific session directory
    python benchmarks/codebench/offline_session_analyzer.py \\
        --session-dir ~/.claude/projects/-my-project \\
        --out /tmp/session_pairs.json

    # Analyze all atelier sessions and run the retrieval benchmark
    python benchmarks/codebench/offline_session_analyzer.py \\
        --repo-filter atelier \\
        --run-eval \\
        --channel lexical

Environment variables:
    SESSION_ROOT      Path to scan for session files (default: ~/.claude/projects/)
    SESSION_REPO_FILTER  Substring filter on project directory name
    SESSION_PAIRS_OUT    Output path for mined pairs JSON
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

SEARCH_TOOLS = {"mcp__atelier__grep", "mcp__atelier__explore", "ToolSearch", "Grep", "mcp__plugin_atelier_atelier__grep"}


def parse_tool_result_files(content) -> list[str]:
    """Extract file paths from a grep tool_result content."""
    files: list[str] = []
    seen: set[str] = set()

    if isinstance(content, str):
        chunks = [content]
    elif isinstance(content, list):
        chunks = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    chunks.append(item.get("text", ""))
                elif item.get("type") == "resource":
                    uri = item.get("resource", {}).get("uri", "")
                    if uri and uri not in seen:
                        seen.add(uri)
                        files.append(uri)
    else:
        return files

    # Regex: matches paths with at least one / and an extension,
        # possibly prefixed with `## `, `### `, or `# grep` headers
    _FILE_RE = re.compile(r"^(?:#+\s+)?([\w./-]+/(?:[\w./-]+\.\w+))")

    for chunk in chunks:
        # JSON format: {"ranked_file_map": [...]} or {"cached":..., "path":"..."}
        first = chunk.strip()
        if first.startswith("{"):
            try:
                obj = json.loads(chunk)
                # Atelier grep ranked results
                ranked = obj.get("ranked_file_map", obj.get("files", obj.get("content", [])))
                if isinstance(ranked, list):
                    for item in ranked:
                        if isinstance(item, dict):
                            fp = item.get("file_path", item.get("path", item.get("file", "")))
                            if fp and fp not in seen:
                                seen.add(fp)
                                files.append(fp)
                        elif isinstance(item, str):
                            if item not in seen:
                                seen.add(item)
                                files.append(item)
                    continue
                # Single resource result: {"cached": false, "path":"...", "summary":"..."}
                single_path = obj.get("path", "")
                if single_path and "/" in single_path:
                    if single_path not in seen:
                        seen.add(single_path)
                        files.append(single_path)
                    continue
            except json.JSONDecodeError:
                pass

        # Plain text format: grep output has file paths on lines, followed
        # by indented match details.
        # Format 1: file_path.py  (possibly with trailing \tcount)
        #   src/atelier/core/capabilities/default_definitions.py
        #   - lines 12-13
        #
        # Format 2: ## file_path.py  (from file_paths_with_content mode)
        #   ## src/atelier/gateway/adapters/mcp_server.py
        #   def _op_usages(
        #
        # Format 3: # grep — output_mode=... header line (skip)
        # Format 4: atelier/src/atelier/...\tcount  (tab-separated match count)

        for line in chunk.split("\n"):
            line_stripped = line.strip()
            if not line_stripped:
                continue
            # Skip match-detail lines and headers
            if line_stripped.startswith("- ") or line_stripped.startswith("# "):
                continue
            # Skip lines that are code content (indented or start with `def `, `class `, etc.)
            if line.startswith(" ") or line.startswith("\t"):
                continue

            # Try to extract file path from diff headers like "## file_path"
            m = _FILE_RE.match(line_stripped)
            if m:
                fp = m.group(1)
                # Remove leading `atelier/` prefix if present (from absolute-path grep results
                # in the atelier__atelier workspace)
                if fp.startswith("atelier/"):
                    fp = fp[len("atelier/"):]
                if fp not in seen:
                    seen.add(fp)
                    files.append(fp)
                continue

            # Fallback: any line with a / and a file extension
            # (catches tab-separated results like "atelier/src/...\t314")
            if "/" in line_stripped:
                # Take the first space/tab-separated token
                first_token = line_stripped.split()[0]
                if "." in first_token and "/" in first_token:
                    fp = first_token.rstrip(":")
                    if fp.startswith("atelier/"):
                        fp = fp[len("atelier/"):]
                    if fp not in seen:
                        seen.add(fp)
                        files.append(fp)

    return files


def _attach_tool_result(block: dict, session_events: list[dict]) -> None:
    """Match a tool_result block to its tool_use call in session_events."""
    tool_id = block.get("tool_use_id", "")
    if not tool_id:
        return
    content_data = block.get("content", "")
    files = parse_tool_result_files(content_data)
    for evt in reversed(session_events):
        if evt.get("id") == tool_id and evt["type"] == "call":
            evt["result_files"] = files
            evt["result_count"] = len(files)
            break


def scan_project_dir(project_dir: str) -> list[dict]:
    """Scan all session JSONL files under a project directory."""
    all_events: list[dict] = []
    dirpath = Path(project_dir)
    if not dirpath.is_dir():
        return all_events

    for fpath in sorted(dirpath.glob("*.jsonl")):
        sz = fpath.stat().st_size
        if sz < 1000 or sz > 50_000_000:  # skip tiny and huge files
            continue
        try:
            with open(fpath) as fh:
                lines = fh.readlines()
        except Exception:
            continue

        session_events = []
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue

            msg_type = obj.get("type", "")

            # User messages — may contain real user text or tool_result blocks.
            # message is always a dict. When content is a string = user text;
            # when content is a list = tool_result wrapper (tool_use_id + content per block).
            if msg_type == "user":
                msg = obj.get("message", None)
                if not isinstance(msg, dict):
                    continue
                content = msg.get("content", "")
                if isinstance(content, str) and content.strip():
                    # Real user text
                    preview = content[:150].replace("\n", " ")
                    session_events.append({"type": "user", "text": preview})
                elif isinstance(content, list):
                    # tool_result blocks
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "tool_result":
                            _attach_tool_result(block, session_events)

            # Assistant messages with tool_use (tool calls)
            elif msg_type == "assistant":
                content = obj.get("message", {}).get("content", [])
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    btype = block.get("type", "")
                    if btype == "tool_use":
                        name = block.get("name", "")
                        if name not in SEARCH_TOOLS:
                            continue
                        inp = block.get("input", {})
                        if not isinstance(inp, dict):
                            continue
                        query = inp.get("query", inp.get("content_regex", ""))
                        tool_id = block.get("id", "")
                        session_events.append({
                            "type": "call",
                            "tool": name,
                            "id": tool_id,
                            "query": str(query)[:500],
                            "file_pattern": inp.get("file_glob_patterns", ""),
                        })

        if any(e["type"] == "call" for e in session_events):
            all_events.extend(session_events)

    return all_events


def build_search_episodes(events: list[dict]) -> list[list[dict]]:
    """Group search calls into episodes between user messages."""
    episodes: list[list[dict]] = []
    current: list[dict] = []

    for evt in events:
        if evt["type"] == "user":
            if current:
                episodes.append(current)
                current = []
        elif evt["type"] == "call":
            current.append(evt)

    if current:
        episodes.append(current)
    return episodes


def generate_pairs(events: list[dict]) -> tuple[list[tuple[str, str, str]], dict[str, list[str]], list[dict]]:
    """Generate (query, tid, prefix) pairs from grep calls that have result files.

    Returns (pairs, true_map, savings_report) where:
    - pairs: [(query, tid, prefix), ...] — each query maps to its result files
    - true_map: {tid: [file_paths...]} — the actual files the grep returned
    - savings: list of per-episode search statistics
    """
    episodes = build_search_episodes(events)

    pairs: list[tuple[str, str, str]] = []
    true_map: dict[str, list[str]] = {}
    savings: list[dict] = []
    pair_id = 0

    for episode in episodes:
        grep_calls = [e for e in episode if "grep" in e["tool"].lower()]
        explore_calls = [e for e in episode if "explore" in e["tool"].lower()]
        toolsearch_calls = [e for e in episode if e["tool"] == "ToolSearch"]

        for gc in grep_calls:
            query = gc.get("query", "")
            files = gc.get("result_files", [])
            if not query or not files:
                continue
            # Use the grep's own result files as the gold files
            tid = f"session_{pair_id}"
            prefix = "atelier__atelier"  # assume atelier repo for these pairs
            pair_id += 1
            true_map[tid] = files[:10]  # top 10 result files
            pairs.append((query, tid, prefix))

        # Generate savings metric for this episode
        if grep_calls:
            unique_queries = set(gc.get("query", "")[:60] for gc in grep_calls)
            savings.append({
                "episode_greps": len(grep_calls),
                "episode_explores": len(explore_calls),
                "episode_toolsearches": len(toolsearch_calls),
                "unique_grep_patterns": len(unique_queries),
                "grep_savings": max(0, len(grep_calls) - len(explore_calls) * 2),
                # ^^ each explore replaces ~3-5 greps, so saving is greps - 2*explores
            })

    return pairs, true_map, savings


def generate_savings_report(savings: list[dict]) -> dict:
    """Generate a comprehensive savings report."""
    if not savings:
        return {"message": "No search tool calls found in session data."}

    total_greps = sum(s["episode_greps"] for s in savings)
    total_explores = sum(s["episode_explores"] for s in savings)
    total_toolsearches = sum(s["episode_toolsearches"] for s in savings)
    total_episodes = len(savings)

    # Each ToolSearch call is ~1 turn (few hundred tokens)
    # Each grep call is ~1 turn (grep results can be many tokens)
    # Each explore call replaces ~3-5 grep calls

    # Estimated savings from replacing greps with explores
    estimated_grep_turns_saved = sum(
        max(0, s["episode_greps"] - s["episode_explores"] * 3)
        for s in savings
        if s["episode_explores"] > 0
    )
    # Each saved grep turn avoids: 1 tool_call + result processing + thinking ≈ 2K tokens
    # Claude Sonnet 4.6: ~$3/M input, ~$15/M output
    avg_saved_tokens_per_grep = 2000
    cost_per_million_input = 3.0
    cost_per_million_output = 15.0
    avg_cost_per_saved_turn = (
        avg_saved_tokens_per_grep / 1_000_000 * cost_per_million_input +
        avg_saved_tokens_per_grep / 1_000_000 * cost_per_million_output
    )
    estimated_cost_saved_usd = estimated_grep_turns_saved * avg_cost_per_saved_turn

    return {
        "total_episodes": total_episodes,
        "total_grep_calls": total_greps,
        "total_explore_calls": total_explores,
        "total_toolsearch_calls": total_toolsearches,
        "total_search_calls": total_greps + total_explores + total_toolsearches,
        "episodes_with_explore": sum(1 for s in savings if s["episode_explores"] > 0),
        "episodes_without_explore": sum(1 for s in savings if s["episode_explores"] == 0),
        "avg_greps_per_episode": round(total_greps / max(total_episodes, 1), 1),
        "estimated_grep_turns_saved": estimated_grep_turns_saved,
        "estimated_cost_saved_usd": round(estimated_cost_saved_usd, 4),
        "per_episode": savings[:20],  # top 20 for detail
    }


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Mine Claude Code session files for search patterns")
    parser.add_argument(
        "--session-dir", "-d",
        default=os.environ.get("SESSION_ROOT", os.path.expanduser("~/.claude/projects/")),
        help="Directory to scan for session files (default: ~/.claude/projects/)",
    )
    parser.add_argument(
        "--repo-filter", "-f",
        default=os.environ.get("SESSION_REPO_FILTER", ""),
        help="Substring filter on project directory name (e.g. 'atelier')",
    )
    parser.add_argument(
        "--out", "-o",
        default=os.environ.get("SESSION_PAIRS_OUT", "/tmp/session_pairs.json"),
        help="Output path for mined pairs JSON",
    )
    parser.add_argument(
        "--run-eval", action="store_true",
        help="Run the retrieval benchmark after generating pairs",
    )
    parser.add_argument(
        "--channel", choices=["lexical", "cg"],
        default="lexical",
        help="Which retrieval eval to run (default: lexical/explore)",
    )
    parser.add_argument(
        "--full", action="store_true",
        help="Run the eval on all mined pairs (no sample cap)",
    )
    args = parser.parse_args()

    session_root = Path(args.session_dir)
    if not session_root.is_dir():
        print(f"[session] ERROR: session dir not found: {session_root}", file=sys.stderr)
        sys.exit(1)

    # Find project directories matching the filter
    project_dirs = sorted(
        d for d in session_root.iterdir()
        if d.is_dir() and (not args.repo_filter or args.repo_filter in d.name)
    )

    if not project_dirs:
        print(f"[session] No project dirs found matching filter '{args.repo_filter}'", file=sys.stderr)
        print(f"[session] Root: {session_root}", file=sys.stderr)
        sys.exit(1)

    print(f"[session] Scanning {len(project_dirs)} project directories under {session_root}", file=sys.stderr)
    print(f"[session] Filter: '{args.repo_filter}'", file=sys.stderr)

    # Scan all sessions
    all_events: list[dict] = []
    scanned_sessions = 0
    for proj_dir in project_dirs:
        events = scan_project_dir(str(proj_dir))
        if events:
            all_events.extend(events)
            scanned_sessions += 1
            print(f"[session] {proj_dir.name}: {sum(1 for e in events if e['type']=='call')} search calls", file=sys.stderr)

    # Generate pairs and savings report
    pairs, true_map, savings = generate_pairs(all_events)
    report = generate_savings_report(savings)

    print(f"\n{'='*60}", file=sys.stderr)
    print("OFFLINE SESSION ANALYSIS", file=sys.stderr)
    print(f"  Projects scanned: {len(project_dirs)}", file=sys.stderr)
    print(f"  Sessions with search calls: {scanned_sessions}", file=sys.stderr)
    print(f"  Total search tool calls: {report['total_search_calls']}", file=sys.stderr)
    print(f"    - mcp__atelier__grep calls:  {report['total_grep_calls']}", file=sys.stderr)
    print(f"    - mcp__atelier__explore calls: {report['total_explore_calls']}", file=sys.stderr)
    print(f"    - ToolSearch calls:           {report['total_toolsearch_calls']}", file=sys.stderr)
    print(f"  Search episodes: {report['total_episodes']}", file=sys.stderr)
    print(f"  Episodes WITH explore: {report['episodes_with_explore']}", file=sys.stderr)
    print(f"  Episodes WITHOUT explore (grep-only): {report['episodes_without_explore']}", file=sys.stderr)
    print(f"  Avg greps per episode: {report['avg_greps_per_episode']}", file=sys.stderr)
    print(f"  Estimated grep turns saved: {report['estimated_grep_turns_saved']}", file=sys.stderr)
    print(f"  Estimated cost saved: ${report['estimated_cost_saved_usd']:.4f}", file=sys.stderr)
    print(f"  Generated {len(pairs)} query pairs from grep result files ({len(true_map)} unique queries)", file=sys.stderr)
    print(f"{'='*60}\n", file=sys.stderr)

    # Deduplicate pairs (same query + tid + prefix)
    deduped_pairs: list[tuple[str, str, str]] = []
    seen_pairs: set[tuple[str, str, str]] = set()
    for q, tid, prefix in pairs:
        key = (q, tid, prefix)
        if key not in seen_pairs:
            seen_pairs.add(key)
            deduped_pairs.append((q, tid, prefix))

    out_data = {
        "pairs": deduped_pairs,
        "true_map": true_map,
        "repos": {
            "atelier__atelier": {
                "ws": str(Path.cwd().resolve()),
            }
        },
    }

    with open(args.out, "w") as f:
        json.dump(out_data, f, indent=2)
    print(f"[session] Pairs written to {args.out} ({len(deduped_pairs)} pairs)", file=sys.stderr)

    # Run eval if requested
    if args.run_eval and len(deduped_pairs) > 0:
        env = dict(os.environ)
        env["FITNESS_PAIRS"] = str(args.out)
        if args.channel == "cg":
            cmd = [sys.executable, "benchmarks/codebench/eval_cg_mrr.py"]
        else:
            cmd = [sys.executable, "benchmarks/codebench/fitness_explore_mrr.py"]
            if args.full:
                cmd.append("--full")
            else:
                cmd.append("--sample")
                cmd.append("100")

        print(f"\n[session] Running eval: {' '.join(cmd)}", file=sys.stderr)
        r = subprocess.run(cmd, cwd=Path.cwd(), env=env, capture_output=True, text=True)
        for line in r.stderr.split("\n"):
            if line.strip():
                print(f"  [eval] {line}", file=sys.stderr)
        if r.stdout.strip():
            try:
                result = json.loads(r.stdout)
                print("\n  EVAL RESULT:", file=sys.stderr)
                print(f"    MRR={result.get('mrr', '?'):.4f}  hit@1={result.get('hit1', '?'):.4f}  hit@3={result.get('hit3', '?'):.4f}  n={result.get('n', '?')}", file=sys.stderr)
                print(f"    latency_mean={result.get('latency_ms', {}).get('mean', '?'):.1f}ms", file=sys.stderr)
            except json.JSONDecodeError:
                print(f"  [eval] stdout: {r.stdout[:500]}", file=sys.stderr)


if __name__ == "__main__":
    main()
