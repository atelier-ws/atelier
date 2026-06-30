"""What part of atelier's tool outputs does the LLM actually USE?

For code_search results (JSON: candidate_files + files[].sections source) and
read results, reconstruct the action sequence per flow and measure:
  - code_search payload split: candidate_files vs source vs line-number overhead
  - usage: are candidate_files later read/edited? are returned files later edited?
  - read: is the read file later edited (on-target) and result size
Goal: generalizable conclusion on what to eliminate/trim.

PYTHONPATH=src uv run --project benchmarks python experiments/deep_tool_usage.py <run_dir>
"""

import json
import re
import sys
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
    """Ordered list of (tool, input_dict, result_text)."""
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
                if not ref:
                    continue
                inner = b.get("content")
                txt = (
                    " ".join(i.get("text", "") for i in inner if isinstance(i, dict))
                    if isinstance(inner, list)
                    else str(inner or "")
                )
                out.append((ref[0], ref[1], txt))
    return out


def _base(p):
    return Path(str(p).split("#")[0].split(":")[0]).name


def main(run_dir):
    d = Path(run_dir)
    flows = sorted(d.glob("*_atelier_rep*.flow"))[:25]
    cs_total = cs_cand = cs_src = cs_linenums = 0
    cs_calls = 0
    cand_total = cand_used = 0  # individual candidate_files later read/edited
    cs_with_used_cand = 0  # calls where >=1 candidate used
    srcfile_total = srcfile_edited = 0  # returned source files later edited
    rd_calls = rd_size = rd_edited = 0
    for fp in flows:
        seq = _seq(_largest_msgs(fp))
        # paths acted on AFTER index i
        acted = []  # (idx, base) for read/edit targets
        for i, (tool, inp, res) in enumerate(seq):
            if tool in {"read", "edit", "codemod", "write"}:
                for key in ("file_path", "path", "filename"):
                    v = inp.get(key)
                    if isinstance(v, str):
                        acted.append((i, _base(v)))
                for e in inp.get("edits") or []:
                    if isinstance(e, dict):
                        v = e.get("file_path") or e.get("path")
                        if v:
                            acted.append((i, _base(v)))
                for f in inp.get("files") or []:
                    acted.append((i, _base(f if isinstance(f, str) else f.get("path", ""))))
        edited_after = lambda i, base: any(j > i and bb == base for j, bb in acted)
        any_after = lambda i, base: any(j >= i and bb == base for j, bb in acted)
        for i, (tool, inp, res) in enumerate(seq):
            if tool == "code_search":
                cs_calls += 1
                cs_total += len(res)
                try:
                    j = json.loads(res)
                except Exception:
                    continue
                cand = j.get("candidate_files") or []
                cs_cand += len(json.dumps(cand))
                files = j.get("files") or []
                src = json.dumps(files)
                cs_src += len(src)
                cs_linenums += len(re.findall(r"\\n\d+\\t", src))  # numbered-line prefixes
                used_here = False
                for cf in cand:
                    cand_total += 1
                    if edited_after(i, _base(cf)) or any_after(i, _base(cf)):
                        cand_used += 1
                        used_here = True
                if used_here:
                    cs_with_used_cand += 1
                for f in files:
                    srcfile_total += 1
                    if edited_after(i, _base(f.get("path", ""))):
                        srcfile_edited += 1
            elif tool == "read":
                rd_calls += 1
                rd_size += len(res)
                v = inp.get("file_path") or inp.get("path") or ""
                files = inp.get("files") or ([v] if v else [])
                if any(edited_after(i, _base(f if isinstance(f, str) else f.get("path", ""))) for f in files):
                    rd_edited += 1
    print(f"atelier flows: {len(flows)}")
    print(f"\n=== code_search ({cs_calls} calls) payload split ===")
    if cs_calls:
        print(f"  avg total result:     {cs_total / cs_calls:.0f}c")
        print(f"  avg candidate_files:  {cs_cand / cs_calls:.0f}c  ({cs_cand / cs_total * 100:.0f}% of payload)")
        print(f"  avg source(files):    {cs_src / cs_calls:.0f}c  ({cs_src / cs_total * 100:.0f}% of payload)")
        print(f"  line-number prefixes: ~{cs_linenums} occurrences (~{cs_linenums * 4} chars of \\nNNN\\t overhead)")
    print(f"\n=== usage (what the agent acts on) ===")
    if cand_total:
        print(
            f"  candidate_files offered: {cand_total};  later read/edited: {cand_used} ({cand_used / cand_total * 100:.0f}%)"
        )
        print(
            f"  code_search calls whose candidate_files were used at all: {cs_with_used_cand}/{cs_calls} ({cs_with_used_cand / cs_calls * 100:.0f}%)"
        )
    if srcfile_total:
        print(
            f"  source files returned: {srcfile_total};  later EDITED: {srcfile_edited} ({srcfile_edited / srcfile_total * 100:.0f}%)"
        )
    if rd_calls:
        print(f"\n=== read ({rd_calls} calls) ===")
        print(
            f"  avg read result: {rd_size / rd_calls:.0f}c;  read file later EDITED: {rd_edited}/{rd_calls} ({rd_edited / rd_calls * 100:.0f}%)"
        )


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "reports/benchmark/codebench/swe50_final_5rep")
