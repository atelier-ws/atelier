"""Extract ALL retrieval data from ALL available sources into training/test splits.

Sources mined:
  1. `.flow_dump.txt` files — text summaries of tool calls (441 files)
  2. `.flow` files via mitmproxy — full API conversations for directories
     that have NO `.flow_dump.txt` (2,169 files across many benchmark runs)
  3. `.prompt.txt` files — SWE-bench problem statements as queries
  4. `benchmarks/codebench/data/bench_pairs_multi.json`
     → Pre-extracted pairs (Claude Code / Codex UUID sessions)
  5. SWE-bench dataset (via swebench_data) → problem statements for every task

Outputs:
  experiments/extract_all/train_pairs.jsonl
  experiments/extract_all/test_pairs.jsonl
  experiments/extract_all/split_meta.json
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[2]

_BENCH_PAIRS_PATH = PROJECT_ROOT / "benchmarks" / "codebench" / "data" / "bench_pairs_multi.json"

# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

_TASK_ID_RE = re.compile(r"^(?P<task>.+?)_(?:atelier|baseline)_rep\d+\.flow(?:_dump)?\.txt$")

# Tool call in dump files
_TOOL_CALL_RE = re.compile(
    r"\[tool_use:\s*(\S+?)\]\s*(\{.*?\})",
    re.DOTALL,
)

_REGEX_FIELD_RE = re.compile(r'"regex"\s*:\s*"((?:[^"\\]|\\.)*)"', re.DOTALL)

_BASH_GREP_CMD_RE = re.compile(
    r'\b(grep|rg|ripgrep|ag|ack|git\s+grep)\b',
    re.IGNORECASE,
)

_PATCH_FILE_RE = re.compile(r"^\+\+\+ b/(.+)$", re.MULTILINE)
_TOOL_RESULT_FILE_RE = re.compile(r"^(?:#+\s+)?([\w./-]+/(?:[\w./-]+\.\w+))")
_TURN_MARKER_RE = re.compile(r"^=== Turn \d+ ===\n?", re.MULTILINE)
_TEST_PATH_RE = re.compile(r"(^|/)(test_|tests?/|testing/|conftest(?:\.py)?$)", re.IGNORECASE)

_NOISY_QUERY_RE = re.compile(
    r"^"
    r"(?:\^)?(?:OK|FAILED|FAIL|ERROR|Ran)\|?"
    r"|^(?:Ran|OK|FAILED|ERROR|Warning)\b"
    r"|^(?:verbose|recursive|unittest|cds|href)\b"
    r"|^(?:from|import|class|def|return|self|pass|true|false|none)$"
    r"|^[\s\^$|]+$"
    r"|^\d+\s*$"
)

# .flow file task ID from filename
_FLOW_TASK_RE = re.compile(r"^(?P<task>.+?)_(?:atelier|baseline)_rep\d+\.flow$")

# (repo_prefix extraction uses simple task_id manipulation, not a regex)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def decode_json_string(value: str) -> str:
    try:
        return json.loads(f'"{value}"')
    except json.JSONDecodeError:
        return value.encode().decode("unicode_escape", "replace")


def stable_hash(value: str) -> float:
    d = hashlib.sha256(value.encode("utf-8")).digest()
    return int.from_bytes(d[:8], "big") / float(1 << 64)


def is_noisy_query(q: str) -> bool:
    if len(q) < 4:
        return True
    if _NOISY_QUERY_RE.search(q):
        return True
    tokens = re.split(r"[\s|]+", q)
    noisy_tokens = {
        "from", "import", "class", "def", "return", "self", "pass",
        "true", "false", "none", "ok", "failed", "ran", "error",
        "warning", "verbose",
    }
    if tokens and all(t.lower().strip() in noisy_tokens for t in tokens if t.strip()):
        return True
    return False


def extract_repo_prefix(task_id: str) -> str:
    """Extract repo prefix from a task ID (e.g. astropy__astropy-13398 → astropy__astropy)."""
    # SWE-bench format: owner__repo-issue_number  →  owner__repo
    m = re.match(r"^(.+)-\d+$", task_id)
    if m:
        return m.group(1)
    # UUID session: return as-is (will map to atelier__atelier in bench_pairs)
    return task_id


def parse_tool_result_content(content: list | str) -> list[str]:
    """Extract file paths from tool_result content (reuse logic from offline_session_analyzer)."""
    files: list[str] = []
    seen: set[str] = set()

    chunks: list[str] = []
    if isinstance(content, str):
        chunks = [content]
    elif isinstance(content, list):
        for item in content:
            if isinstance(item, dict):
                t = item.get("type", "")
                if t == "text":
                    chunks.append(item.get("text", ""))
                elif t == "resource":
                    uri = item.get("resource", {}).get("uri", "")
                    if uri and uri not in seen:
                        seen.add(uri)
                        files.append(uri)
            elif isinstance(item, str):
                chunks.append(item)

    for chunk in chunks:
        for line in chunk.split("\n"):
            line_stripped = line.strip()
            if not line_stripped:
                continue
            if line_stripped.startswith("- ") or line_stripped.startswith("# "):
                continue
            if line.startswith(" ") or line.startswith("\t"):
                continue
            m = _TOOL_RESULT_FILE_RE.match(line_stripped)
            if m:
                fp = m.group(1)
                if fp not in seen:
                    seen.add(fp)
                    files.append(fp)
                continue
            if "/" in line_stripped:
                first = line_stripped.split()[0].rstrip(",:")
                if "." in first and "/" in first and first not in seen:
                    seen.add(first)
                    files.append(first)

    return files


# ---------------------------------------------------------------------------
# 1. Flow-dump-txt parser (existing, handles atelier + baseline dumps)
# ---------------------------------------------------------------------------


def parse_dump_file(dump_path: Path) -> dict[str, Any]:
    """Parse one flow_dump.txt → queries (grep + bash), edit paths, results."""
    text = dump_path.read_text(encoding="utf-8", errors="replace")

    m_name = _TASK_ID_RE.match(dump_path.name)
    if not m_name:
        return {}
    task_id = m_name.group("task")
    stem = dump_path.stem
    run_type = "baseline" if "_baseline_" in stem else "atelier"
    rp = re.search(r"_rep(\d+)", stem)
    rep = int(rp.group(1)) if rp else 0

    turns = _TURN_MARKER_RE.split(text)
    if turns and not turns[0].strip():
        turns = turns[1:]

    all_grep_queries: list[dict] = []
    all_context_files: list[str] = []
    seen_ctx: set[str] = set()
    edit_files: set[str] = set()
    write_files: set[str] = set()
    pending_grep: list[dict] = []
    seen_q_key: set[tuple[str, str]] = set()

    for turn_text in turns:
        for tm in _TOOL_CALL_RE.finditer(turn_text):
            tool_name = tm.group(1)
            raw_json = tm.group(2)

            if tool_name in ("mcp__plugin_atelier_atelier__grep", "Grep"):
                query = _extract_grep_query(raw_json)
                if query and not is_noisy_query(query) and len(query) <= 200:
                    key = (task_id, query)
                    if key not in seen_q_key:
                        seen_q_key.add(key)
                        gc = {"query": query, "result_files": []}
                        pending_grep.append(gc)
                        all_grep_queries.append(gc)

            elif tool_name == "mcp__plugin_atelier_atelier__edit":
                _collect_edit_paths(raw_json, edit_files)
            elif tool_name == "Edit":
                _collect_baseline_edit_path(raw_json, edit_files)
            elif tool_name == "Write":
                _collect_baseline_write_path(raw_json, write_files)
            elif tool_name in ("mcp__plugin_atelier_atelier__bash", "Bash",):
                try:
                    cmd = json.loads(raw_json).get("command", "")
                except json.JSONDecodeError:
                    cmd = ""
                if _BASH_GREP_CMD_RE.search(cmd):
                    pattern = _extract_bash_grep_pattern(cmd)
                    if pattern and not is_noisy_query(pattern) and len(pattern) <= 200:
                        key = (task_id, pattern)
                        if key not in seen_q_key:
                            seen_q_key.add(key)
                            gc = {"query": pattern, "result_files": []}
                            pending_grep.append(gc)
                            all_grep_queries.append(gc)

        result_files = _parse_tool_result_blocks(turn_text)
        for fp in result_files:
            if fp not in seen_ctx:
                seen_ctx.add(fp)
                all_context_files.append(fp)

        if result_files and pending_grep:
            pg = pending_grep.pop(0)
            pg["result_files"] = result_files.copy()

    return {
        "task_id": task_id,
        "run_type": run_type,
        "rep": rep,
        "grep_calls": all_grep_queries,
        "context_files": all_context_files,
        "edit_files": sorted(edit_files | write_files),
    }


def _extract_grep_query(raw_json: str) -> str | None:
    try:
        obj = json.loads(raw_json)
        q = str(obj.get("regex", "")).strip()
        if q:
            return q
    except json.JSONDecodeError:
        pass
    m = _REGEX_FIELD_RE.search(raw_json)
    if m:
        return decode_json_string(m.group(1)).strip()
    return None


def _extract_bash_grep_pattern(cmd: str) -> str | None:
    clean = re.sub(r'^git\s+grep\b', 'grep', cmd, flags=re.IGNORECASE)
    m = re.search(
        r"""(?:grep|rg|ripgrep|ag|ack)\b"""
        r"""(?:\s+-\w+(?:=\S+)?|\s+--[\w-]+(?:=\S+)?|\s+-\w+\s+\S+)*\s+"""
        r"""["'"']([^"'"']+?)["'"']""",
        clean,
        re.IGNORECASE,
    )
    if m:
        return m.group(1).strip()
    parts = clean.split()
    found_tool = False
    for i, part in enumerate(parts):
        p = part.strip("\"'")
        if p in ("grep", "rg", "ripgrep", "ag", "ack"):
            found_tool = True
            continue
        if not found_tool:
            continue
        if p.startswith("-"):
            if i + 1 < len(parts) and not parts[i + 1].startswith("-"):
                if re.match(r"^-[A-Za-z]$", p) or re.match(r"^--[\w-]+$", p):
                    continue
            continue
        if p.strip():
            return p.strip("\"'")
    return None


def _collect_edit_paths(raw_json: str, dest: set[str]) -> None:
    try:
        obj = json.loads(raw_json)
        for item in (obj.get("edits") or []):
            path = (item.get("path") or "").lstrip("/")
            if path and not _TEST_PATH_RE.search(path):
                dest.add(path)
    except (json.JSONDecodeError, AttributeError):
        pass


def _collect_baseline_edit_path(raw_json: str, dest: set[str]) -> None:
    try:
        obj = json.loads(raw_json)
        path = (obj.get("file_path") or "").lstrip("/")
        if path and not _TEST_PATH_RE.search(path):
            dest.add(path)
    except (json.JSONDecodeError, AttributeError):
        pass


def _collect_baseline_write_path(raw_json: str, dest: set[str]) -> None:
    try:
        obj = json.loads(raw_json)
        path = (obj.get("file_path") or "").lstrip("/")
        if path and not _TEST_PATH_RE.search(path):
            dest.add(path)
    except (json.JSONDecodeError, AttributeError):
        pass


def _parse_tool_result_blocks(turn_text: str) -> list[str]:
    files: list[str] = []
    seen: set[str] = set()
    for block in re.split(r"(?=\[user\] \[tool_result\])", turn_text):
        if "[tool_result]" not in block:
            continue
        content = block.split("[tool_result]", 1)[1].strip()
        if not content:
            continue
        for line in content.split("\n"):
            ls = line.strip()
            if not ls:
                continue
            if line[0] in (" ", "\t"):
                continue
            if ls.startswith(("- ", "# ", "@@", "--- ", "diff ")):
                continue
            m = _TOOL_RESULT_FILE_RE.match(ls)
            if m:
                fp = m.group(1)
                if fp not in seen:
                    seen.add(fp)
                    files.append(fp)
                continue
            if "/" in ls and "." in ls.split()[0]:
                first = ls.split()[0].rstrip(",:")
                if first not in seen:
                    seen.add(first)
                    files.append(first)
    return files


# ---------------------------------------------------------------------------
# 2. Flow-file parser (mitmproxy) — for files WITH & WITHOUT .flow_dump.txt
# ---------------------------------------------------------------------------


def parse_flow_file(flow_path: Path) -> dict[str, Any]:
    """Parse one .flow file via mitmproxy → tool_use + tool_result data.

    Returns the same structure as parse_dump_file() but with RICHER data:
    - All tool_use blocks from the full conversation
    - All read paths (supplementary gold)
    - All tool_result content (file paths from grep output)
    """
    from mitmproxy.io import FlowReader

    m_name = _FLOW_TASK_RE.match(flow_path.name)
    if not m_name:
        return {}

    task_id = m_name.group("task")
    stem = flow_path.stem
    run_type = "baseline" if "_baseline_" in stem else "atelier"
    rp = re.search(r"_rep(\d+)", stem)
    rep = int(rp.group(1)) if rp else 0

    # Read all flows from the .flow file
    flows = []
    try:
        with open(flow_path, "rb") as f:
            for flow in FlowReader(f).stream():
                flows.append(flow)
    except Exception:
        return {}

    # Find the LAST POST request body (contains the complete conversation)
    last_body = None
    for flow in flows:
        req = flow.request
        if req.method == "POST" and "v1/messages" in req.pretty_url:
            try:
                last_body = json.loads(req.content or b"{}")
            except json.JSONDecodeError:
                continue

    if last_body is None:
        return {}

    all_grep_queries: list[dict] = []
    edit_files: set[str] = set()
    read_files: set[str] = set()
    seen_q_key: set[tuple[str, str]] = set()
    pending_grep: dict[str, dict] = {}  # tool_use_id → grep call

    for msg in last_body.get("messages", []):
        content = msg.get("content", "")
        if not isinstance(content, list):
            continue

        for block in content:
            if not isinstance(block, dict):
                continue

            bt = block.get("type")

            # --- tool_use blocks (in assistant messages) ---
            if bt == "tool_use":
                name = block.get("name", "")
                inp = block.get("input", {})
                tid = block.get("id", "")

                if "grep" in name.lower():
                    query = str(inp.get("regex", inp.get("query", ""))).strip()
                    if query and not is_noisy_query(query) and len(query) <= 200:
                        key = (task_id, query)
                        if key not in seen_q_key:
                            seen_q_key.add(key)
                            gc = {"query": query, "result_files": [], "tool_use_id": tid}
                            pending_grep[tid] = gc
                            all_grep_queries.append(gc)

                elif "bash" in name.lower():
                    cmd = str(inp.get("command", "") or "").strip()
                    if _BASH_GREP_CMD_RE.search(cmd):
                        pattern = _extract_bash_grep_pattern(cmd)
                        if pattern and not is_noisy_query(pattern) and len(pattern) <= 200:
                            key = (task_id, pattern)
                            if key not in seen_q_key:
                                seen_q_key.add(key)
                                gc = {"query": pattern, "result_files": [], "tool_use_id": tid}
                                pending_grep[tid] = gc
                                all_grep_queries.append(gc)

                elif "read" in name.lower():
                    # Read tool → file path = supplementary gold
                    path = str(inp.get("path", inp.get("file_path", ""))).lstrip("/")
                    if path and not _TEST_PATH_RE.search(path):
                        read_files.add(path)

                elif "edit" in name.lower():
                    # Edit tool → file path = gold
                    if "file_path" in inp:
                        path = str(inp.get("file_path", "")).lstrip("/")
                        if path and not _TEST_PATH_RE.search(path):
                            edit_files.add(path)
                    for edit in (inp.get("edits") or []):
                        if isinstance(edit, dict):
                            path = str(edit.get("path", "")).lstrip("/")
                            if path and not _TEST_PATH_RE.search(path):
                                edit_files.add(path)

            # --- tool_result blocks (in user messages) ---
            elif bt == "tool_result":
                tool_use_id = block.get("tool_use_id", "")
                result_content = block.get("content", [])
                file_paths = parse_tool_result_content(result_content)

                # Associate with pending grep if tool_use_id matches
                if tool_use_id and tool_use_id in pending_grep:
                    pending_grep[tool_use_id]["result_files"] = file_paths

    return {
        "task_id": task_id,
        "run_type": run_type,
        "rep": rep,
        "grep_calls": all_grep_queries,
        "edit_files": sorted(edit_files),
        "read_files": sorted(read_files),
    }


# ---------------------------------------------------------------------------
# 3. Prompt-file parser (problem statements as queries)
# ---------------------------------------------------------------------------


def parse_prompt_file(prompt_path: Path) -> dict[str, Any]:
    """Extract problem statement from a .prompt.txt file."""
    m_name = _TASK_ID_RE.match(prompt_path.name)
    if not m_name:
        m_name = re.match(
            r"^(?P<task>.+?)_(?:atelier|baseline)_rep\d+\.prompt\.txt$",
            prompt_path.name,
        )
    if not m_name:
        return {}
    task_id = m_name.group("task")
    text = prompt_path.read_text(encoding="utf-8", errors="replace")

    # Problem statement = first meaningful paragraph(s), before boilerplate
    # Strip HTML comments first
    clean = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
    lines = [l.strip() for l in clean.split("\n") if l.strip()]

    # Take content before "### Additional context" or similar headings
    problem_parts = []
    for line in lines:
        if line.startswith("### ") or line.startswith("**"):
            continue
        if line.startswith("<!--") or line.startswith("-->") or line.startswith("# "):
            continue
        # Skip boilerplate lines
        if any(b in line.lower() for b in (
            "please be sure", "please have a search", "this comments are hidden",
            "if a similar issue", "if not please go ahead",
        )):
            continue
        # Skip code blocks
        if line.startswith("```") or line.startswith("~~~"):
            continue
        problem_parts.append(line)

    problem = " ".join(problem_parts).strip()
    if not problem:
        return {}
    return {"task_id": task_id, "problem_statement": problem}


# ---------------------------------------------------------------------------
# Patch gold loader
# ---------------------------------------------------------------------------


def load_gold_from_patch(patch_path: Path) -> list[str]:
    if not patch_path.exists():
        return []
    text = patch_path.read_text(encoding="utf-8", errors="replace")
    return _parse_patch_for_gold_files(text)


def load_gold_from_patch_str(patch_text: str) -> list[str]:
    """Parse diff text to extract gold file paths."""
    return _parse_patch_for_gold_files(patch_text)


def _parse_patch_for_gold_files(text: str) -> list[str]:
    files: list[str] = []
    seen: set[str] = set()
    for fp in _PATCH_FILE_RE.findall(text):
        fp = fp.strip().replace("\\", "/")
        if not fp or fp == "/dev/null" or _TEST_PATH_RE.search(fp):
            continue
        if fp not in seen:
            seen.add(fp)
            files.append(fp)
    return files


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main() -> int:
    t0 = time.time()
    dump_roots = sorted(
        d for d in (PROJECT_ROOT / "reports" / "benchmark").rglob("*")
        if d.is_dir() and not d.name.startswith("_") and not d.name.startswith(".")
    )

    # =================================================================
    # Phase A: Mine tool calls from ALL .flow files (with & without dumps)
    # =================================================================
    by_task: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "grep_calls": [],
        "edit_files": set(),
        "read_files": set(),
        "context_files": [],
        "sources": set(),
        "run_types": set(),
    })

    # Track which .flow files we process (avoid double-counting symlinks)
    seen_flow_files: set[Path] = set()

    flow_count = 0
    dump_only_count = 0
    for root in dump_roots:
        for f in sorted(root.glob("*.flow_dump.txt")):
            r = f.resolve()
            if r not in seen_flow_files:
                seen_flow_files.add(r)
                parsed = parse_dump_file(r)
                if parsed:
                    tid = parsed["task_id"]
                    by_task[tid]["grep_calls"].extend(parsed["grep_calls"])
                    by_task[tid]["edit_files"].update(parsed["edit_files"])
                    by_task[tid]["context_files"].extend(parsed["context_files"])
                    by_task[tid]["sources"].add("flow_dump")
                    by_task[tid]["run_types"].add(parsed["run_type"])
                    dump_only_count += 1

        for f in sorted(root.glob("*.flow")):
            r = f.resolve()
            if r in seen_flow_files:
                continue
            seen_flow_files.add(r)

            # Check if there's a corresponding .flow_dump.txt
            has_dump = (r.with_suffix(".flow_dump.txt")).exists()

            parsed = parse_flow_file(r)
            if not parsed:
                continue

            tid = parsed["task_id"]
            by_task[tid]["grep_calls"].extend(parsed["grep_calls"])
            by_task[tid]["edit_files"].update(parsed["edit_files"])
            by_task[tid]["read_files"].update(parsed.get("read_files", []))
            by_task[tid]["sources"].add("flow" if not has_dump else "flow_with_dump")
            by_task[tid]["run_types"].add(parsed["run_type"])
            flow_count += 1

    print(f"[extract] Processed {dump_only_count} .flow_dump.txt + {flow_count} .flow files", file=sys.stderr)
    print(f"[extract] Parsed {len(by_task)} task IDs from flow data", file=sys.stderr)

    # =================================================================
    # Phase B: Compute gold files per task
    # =================================================================
    for tid in list(by_task.keys()):
        task = by_task[tid]
        repo_prefix = extract_repo_prefix(tid)

        # Find any matching patch file across all dump dirs
        patch_gold: list[str] = []
        for root in dump_roots:
            for pp in sorted(root.glob(f"{tid}_*.patch")):
                gold = load_gold_from_patch(pp)
                if gold:
                    patch_gold = gold
                    break
            if patch_gold:
                break

        task["repo_prefix"] = repo_prefix
        task["repo"] = repo_prefix.replace("__", "/")
        task["patch_gold"] = patch_gold
        all_gold = list(dict.fromkeys(
            patch_gold
            + list(task["edit_files"])
            + list(task["read_files"])     # read files as supplementary gold
        ))
        task["gold_files"] = all_gold

    total_dump_grep = sum(len(t["grep_calls"]) for t in by_task.values())
    print(f"[extract] Total grep calls from flow data: {total_dump_grep}", file=sys.stderr)

    # =================================================================
    # Phase C: SWE-bench problem statements (from .prompt.txt)
    # =================================================================
    problem_statements: dict[str, str] = {}
    for root in dump_roots:
        for f in sorted(root.glob("*.prompt.txt")):
            parsed = parse_prompt_file(f)
            if parsed and parsed["task_id"] not in problem_statements:
                problem_statements[parsed["task_id"]] = parsed["problem_statement"]

    print(f"[extract] Extracted {len(problem_statements)} problem statements from .prompt.txt", file=sys.stderr)

    # =================================================================
    # Phase C2: SWE-bench canonical problem statements (via datasets)
    # Overlays SWE-bench's canonical issue descriptions for any SWE-bench
    # task ID, preferring them over the .prompt.txt ones.
    # =================================================================
    swebench_patches: dict[str, str] = {}
    try:
        from datasets import load_dataset
        swebench_ds = load_dataset("princeton-nlp/SWE-bench", split="test")
        for inst in swebench_ds:
            tid = inst["instance_id"]
            prob = inst.get("problem_statement", "").strip()
            patch = inst.get("patch", "").strip()
            if prob:
                problem_statements[tid] = prob  # overwrite .prompt.txt with canonical
            if patch:
                swebench_patches[tid] = patch
        print(f"[extract] SWE-bench dataset: {len(swebench_patches)} patches, {len(problem_statements)} total problem statements ({len([k for k in problem_statements if k in {x['instance_id'] for x in swebench_ds}])} from swebench)", file=sys.stderr)
    except Exception:
        # datasets not available or download failed — that's ok, .prompt.txt is fallback
        print("[extract] WARNING: SWE-bench dataset not available (pip install datasets)", file=sys.stderr)

    # =================================================================
    # Phase D: Augment with bench_pairs_multi.json (UUID session data)
    # =================================================================
    bench_pairs: list[tuple] = []
    bench_true_map: dict[str, list[str]] = {}
    if _BENCH_PAIRS_PATH.exists():
        bd = json.loads(_BENCH_PAIRS_PATH.read_text())
        bench_pairs = bd.get("pairs", [])
        bench_true_map = bd.get("true_map", {})
        print(f"[extract] bench_pairs_multi.json: {len(bench_pairs)} pairs, {len(bench_true_map)} true_map entries", file=sys.stderr)

    # =================================================================
    # Phase E: Build unified record list
    # =================================================================
    records: list[dict] = []
    seen: set[tuple[str, str]] = set()  # (task_id, query) dedup

    # E1. Records from flow grep calls
    for tid in sorted(by_task):
        task = by_task[tid]
        for gc in task["grep_calls"]:
            q = gc["query"]
            key = (tid, q)
            if key in seen:
                continue
            seen.add(key)
            gold = task.get("gold_files") or bench_true_map.get(tid, bench_true_map.get(task["repo_prefix"], []))
            records.append({
                "task_id": tid,
                "repo": task["repo"],
                "repo_prefix": task["repo_prefix"],
                "query": q,
                "gold_files": gold,
                "result_files": gc.get("result_files", []),
                "query_source": "agent_grep",
                "source_dumps": sorted(task["sources"]),
                "run_types": sorted(task["run_types"]),
            })

    # E2. Problem statements as queries (from .prompt.txt)
    for tid, prob in sorted(problem_statements.items()):
        if tid not in by_task:
            continue
        task = by_task[tid]
        key = (tid, prob)
        if key in seen:
            continue
        seen.add(key)
        gold = task.get("gold_files") or bench_true_map.get(tid, bench_true_map.get(task["repo_prefix"], []))
        if not gold:
            continue
        records.append({
            "task_id": tid,
            "repo": task["repo"],
            "repo_prefix": task["repo_prefix"],
            "query": prob,
            "gold_files": gold,
            "result_files": [],
            "query_source": "problem_statement",
            "source_dumps": sorted(task["sources"]),
            "run_types": sorted(task["run_types"]),
        })

    # E2b. Problem statement records for SWE-bench tasks NOT in any .flow/dump
    #       (builds gold from the SWE-bench patch alone)
    for tid, prob in sorted(problem_statements.items()):
        if tid in by_task:
            continue  # already handled in E2
        key = (tid, prob)
        if key in seen:
            continue
        # Extract gold files from swebench patch
        gold: list[str] = swebench_patches.get(tid, [])
        if isinstance(gold, str):
            gold = list(dict.fromkeys(load_gold_from_patch_str(gold)))
        repo_prefix = extract_repo_prefix(tid)
        if not gold:
            continue
        seen.add(key)
        records.append({
            "task_id": tid,
            "repo": repo_prefix.replace("__", "/"),
            "repo_prefix": repo_prefix,
            "query": prob,
            "gold_files": gold,
            "result_files": [],
            "query_source": "problem_statement",
            "source_dumps": ["swebench_data"],
            "run_types": ["swebench_data"],
        })

    # E3. Records from bench_pairs_multi.json (UUID sessions, etc.)
    for q, tid, prefix in bench_pairs:
        key = (tid, q)
        if key in seen:
            continue
        seen.add(key)
        gold = bench_true_map.get(tid, bench_true_map.get(prefix, []))
        repo = prefix.replace("__", "/")
        records.append({
            "task_id": tid,
            "repo": repo,
            "repo_prefix": prefix,
            "query": q,
            "gold_files": gold,
            "result_files": [],
            "query_source": "agent_grep",
            "source_dumps": [],
            "run_types": ["bench_pairs"],
        })

    # Drop records with no gold files
    before_filter = len(records)
    records = [r for r in records if r.get("gold_files")]
    dropped = before_filter - len(records)
    if dropped:
        print(f"[extract] Dropped {dropped} records with empty gold_files", file=sys.stderr)

    print(f"[extract] Total unique records: {len(records)}", file=sys.stderr)

    # =================================================================
    # Phase F: Split 80/20 stratified by repo
    # =================================================================
    by_repo: dict[str, list[dict]] = defaultdict(list)
    for rec in records:
        by_repo[rec["repo_prefix"]].append(rec)

    train: list[dict] = []
    test: list[dict] = []
    for repo_prefix, repo_recs in sorted(by_repo.items()):
        by_tid: dict[str, list[dict]] = defaultdict(list)
        for rec in repo_recs:
            by_tid[rec["task_id"]].append(rec)
        for tid in sorted(by_tid):
            if stable_hash(tid) < 0.8:
                train.extend(by_tid[tid])
            else:
                test.extend(by_tid[tid])

    # =================================================================
    # Phase G: Write outputs
    # =================================================================
    out_dir = PROJECT_ROOT / "experiments" / "extract_all"
    out_dir.mkdir(parents=True, exist_ok=True)

    def write_jsonl(path: Path, data: list[dict]) -> None:
        with open(path, "w", encoding="utf-8") as f:
            for rec in data:
                f.write(json.dumps(rec, sort_keys=True) + "\n")

    train_path = out_dir / "train_pairs.jsonl"
    test_path = out_dir / "test_pairs.jsonl"
    meta_path = out_dir / "split_meta.json"

    write_jsonl(train_path, train)
    write_jsonl(test_path, test)

    train_tasks = len({r["task_id"] for r in train})
    test_tasks = len({r["task_id"] for r in test})
    train_repos = len({r["repo_prefix"] for r in train})
    test_repos = len({r["repo_prefix"] for r in test})

    elapsed = time.time() - t0

    meta = {
        "elapsed_seconds": round(elapsed, 1),
        "flow_files_processed": flow_count,
        "dump_files_processed": dump_only_count,
        "task_ids_from_flow": len(by_task),
        "problem_statements": len(problem_statements),
        "source_bench_pairs": len(bench_pairs),
        "total_records": len(records),
        "train_records": len(train),
        "test_records": len(test),
        "train_task_ids": train_tasks,
        "test_task_ids": test_tasks,
        "train_repos": train_repos,
        "test_repos": test_repos,
        "split_method": "80/20 stratified by repo via stable_hash(task_id)",
        "output_dir": str(out_dir),
    }
    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)
        f.write("\n")

    print(f"[extract] Train: {len(train)} records ({train_tasks} tasks, {train_repos} repos)", file=sys.stderr)
    print(f"[extract] Test:  {len(test)} records ({test_tasks} tasks, {test_repos} repos)", file=sys.stderr)
    print(f"[extract] Meta → {meta_path}  ({elapsed:.0f}s)", file=sys.stderr)
    print(json.dumps(meta, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
