"""Is 'full content for top 1-2 matches, pointers for the rest' viable?

Measures, from atelier flows:
  READ: files-per-call (batching) + range/expand usage -> is 2x from batching or wide reads?
  CODE_SEARCH: per returned file (in order) its source size + whether it's later
    EDITED -> if edits concentrate on the FIRST 1-2 files, pointer-izing files[2:]
    is safe. Estimates the payload saved by keeping top-2 full + rest as pointers.

PYTHONPATH=src uv run --project benchmarks python experiments/graduated_detail.py <run_dir>
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

from mitmproxy.io import FlowReader


def _largest_msgs(fp):
    best = []
    with open(fp, "rb") as fh:
        try:
            flows = list(FlowReader(fh).stream())
        except Exception:
            return best
    for fl in flows:
        if not fl.request or "v1/messages" not in fl.request.url:
            continue
        try:
            b = json.loads(fl.request.content.decode("utf-8", "ignore"))
        except Exception:
            continue
        if len(b.get("messages") or []) > len(best):
            best = b["messages"]
    return best


def _seq(msgs):
    pend, out = {}, []
    for m in msgs:
        c = m.get("content")
        if not isinstance(c, list):
            continue
        for b in c:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use":
                pend[b.get("id")] = (str(b.get("name", "")).split("__")[-1].lower(), b.get("input") or {})
            elif b.get("type") == "tool_result":
                ref = pend.get(b.get("tool_use_id"))
                if ref:
                    out.append(ref)
    return out


def _base(p):
    return Path(str(p).split("#")[0].split(":")[0]).name


def _extract_cs_json(txt):
    """Recover code_search JSON, stripping any convergence wrapper.

    The detectors wrap a tool result as 'FIXME (convergence): <reason>\n\n{JSON}'
    (prefix) or '{JSON}\n\nFIXME (convergence): <reason>' (suffix nudge). They fire
    on gather-spirals -> exactly the big exploration code_search calls, so without
    stripping these the sample skews tiny. Returns (obj, status) where status is
    'clean' | 'unwrapped' | 'truncated' | 'bad'.
    """
    t = txt.strip()
    try:
        return json.loads(t), "clean"
    except (json.JSONDecodeError, ValueError):
        pass
    for marker in ("\n\nFIXME (convergence):", "\n\n[atelier]"):  # suffix-appended nudge
        k = t.find(marker)
        if k > 0 and t.lstrip().startswith("{"):
            try:
                return json.loads(t[:k].strip()), "unwrapped"
            except (json.JSONDecodeError, ValueError):
                pass
    if t.startswith("FIXME (convergence):") or t.startswith("[atelier]"):  # prefix-prepended
        s = t.find("{")  # reasons carry no braces -> first { is the JSON start
        if s >= 0:
            try:
                return json.loads(t[s:]), "unwrapped"
            except (json.JSONDecodeError, ValueError):
                return None, "truncated"  # degrade tier truncates response_text[:400]
    return None, "bad"


def main(run_dir):
    d = Path(run_dir)
    flows = sorted(d.glob("*_atelier_rep*.flow"))[:25]
    # read batching
    rd_calls = 0
    rd_files = 0
    rd_ranged = 0
    rd_expand = 0
    rd_multi = 0
    # code_search position analysis
    pos_edited = defaultdict(int)   # position -> times that file later edited
    pos_count = defaultdict(int)    # position -> times a file appeared there
    pos_srcsize = defaultdict(int)  # position -> total source chars
    parse_status = defaultdict(int)
    for fp in flows:
        # gather all edited basenames in the flow (for later-edit test)
        msgs = _largest_msgs(fp)
        seq = _seq(msgs)
        edited = set()
        for tool, inp in seq:
            if tool in {"edit", "codemod", "write"}:
                for key in ("file_path", "path"):
                    if isinstance(inp.get(key), str):
                        edited.add(_base(inp[key]))
                for e in inp.get("edits") or []:
                    if isinstance(e, dict) and (e.get("file_path") or e.get("path")):
                        edited.add(_base(e.get("file_path") or e.get("path")))
        for tool, inp in seq:
            if tool == "read":
                rd_calls += 1
                files = inp.get("files") or ([inp.get("file_path")] if inp.get("file_path") else [])
                rd_files += len(files)
                if len(files) > 1:
                    rd_multi += 1
                for f in files:
                    fs = f if isinstance(f, str) else json.dumps(f)
                    if ":L" in fs or inp.get("offset") or inp.get("limit"):
                        rd_ranged += 1
                    if "expand" in fs or inp.get("expand"):
                        rd_expand += 1
    # second pass for code_search (need result text -> reparse with results)
    for fp in flows:
        pend, msgs = {}, _largest_msgs(fp)
        edited = set()
        # collect edited
        for m in msgs:
            for b in m.get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    nm = str(b.get("name", "")).split("__")[-1].lower()
                    inp = b.get("input") or {}
                    if nm in {"edit", "codemod", "write"}:
                        for key in ("file_path", "path"):
                            if isinstance(inp.get(key), str):
                                edited.add(_base(inp[key]))
                        for e in inp.get("edits") or []:
                            if isinstance(e, dict) and (e.get("file_path") or e.get("path")):
                                edited.add(_base(e.get("file_path") or e.get("path")))
        # code_search results
        for m in msgs:
            for b in m.get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    pend[b.get("id")] = str(b.get("name", "")).split("__")[-1].lower()
                elif isinstance(b, dict) and b.get("type") == "tool_result":
                    if pend.get(b.get("tool_use_id")) != "code_search":
                        continue
                    inner = b.get("content")
                    txt = (
                        " ".join(i.get("text", "") for i in inner if isinstance(i, dict))
                        if isinstance(inner, list)
                        else str(inner or "")
                    )
                    j, status = _extract_cs_json(txt)
                    parse_status[status] += 1
                    if j is None:
                        continue
                    for pos, f in enumerate(j.get("files") or []):
                        pos_count[pos] += 1
                        pos_srcsize[pos] += len(json.dumps(f.get("sections", "")))
                        if _base(f.get("path", "")) in edited:
                            pos_edited[pos] += 1
    print(f"atelier flows: {len(flows)}")
    print(f"\n=== READ batching ({rd_calls} calls) ===")
    if rd_calls:
        print(
            f"  avg files per read call: {rd_files / rd_calls:.2f}   (multi-file calls: {rd_multi} = {rd_multi / rd_calls * 100:.0f}%)"
        )
        print(f"  calls using a range (:Lx / offset): {rd_ranged}   expand: {rd_expand}")
        print(
            f"  => 2x size is from {'BATCHING multiple files' if rd_files / rd_calls > 1.3 else 'wider single reads'}"
        )
    print(f"\n=== CODE_SEARCH parse recovery: {dict(parse_status)} ===")
    print("\n=== CODE_SEARCH: edit-rate & source size by file POSITION ===")
    print(f"  {'pos':>4}{'appeared':>10}{'edited':>8}{'edit%':>7}{'avg src chars':>15}")
    tot_src = tot_savable = 0
    for pos in sorted(pos_count):
        n = pos_count[pos]
        e = pos_edited[pos]
        avg = pos_srcsize[pos] / n
        tot_src += pos_srcsize[pos]
        if pos >= 2:
            tot_savable += pos_srcsize[pos]
        print(f"  {pos:>4}{n:>10}{e:>8}{e / n * 100:>6.0f}%{avg:>15.0f}")
    if tot_src:
        print(
            f"\n  if files[2:] became pointers (path:line only): save ~{tot_savable / tot_src * 100:.0f}% of code_search source payload"
        )


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "reports/benchmark/codebench/swe50_final_5rep")
