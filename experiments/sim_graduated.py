"""Simulate the graduated code_search policy over captured flows -- no run needed.

Policy: code_search streak<=1 (first / post-edit) -> full top-2 source;
streak>=2 -> outline only (strip the source sections). Top-2 also removes the
later read of the pos-1 file.

For each rep we recompute the retrieval payload (code_search + read chars) under
the policy and compare to actual. Reports two parts separately:
  A) OUTLINE-ON-REPEAT: source stripped from 2nd+ searches (clean save, no assumption)
  B) TOP-2: pos-1 reads eliminated  minus  pos-1 source added on 1st searches

PYTHONPATH=src uv run --project benchmarks python experiments/sim_graduated.py <run_dir>
"""

import json
import sys
from pathlib import Path

from mitmproxy.io import FlowReader

LOSS = {
    "django__django-15957",
    "pylint-dev__pylint-6528",
    "django__django-13449",
    "django__django-13837",
    "matplotlib__matplotlib-24870",
    "psf__requests-2931",
    "sympy__sympy-13091",
    "pytest-dev__pytest-7490",
    "django__django-11333",
    "pallets__flask-5014",
}


def largest(fp):
    best = []
    try:
        flows = list(FlowReader(open(fp, "rb")).stream())
    except (OSError, ValueError):
        return best
    for fl in flows:
        if fl.request and "v1/messages" in fl.request.url:
            try:
                b = json.loads(fl.request.content.decode("utf-8", "ignore"))
            except (json.JSONDecodeError, ValueError):
                continue
            if len(b.get("messages") or []) > len(best):
                best = b["messages"]
    return best


def seq(msgs):
    pend, out = {}, []
    for m in msgs:
        for b in m.get("content") or []:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use":
                pend[b.get("id")] = (str(b.get("name", "")).split("__")[-1].lower(), b.get("input") or {})
            elif b.get("type") == "tool_result":
                ref = pend.get(b.get("tool_use_id"))
                if ref:
                    inner = b.get("content")
                    txt = (
                        " ".join(i.get("text", "") for i in inner if isinstance(i, dict))
                        if isinstance(inner, list)
                        else str(inner or "")
                    )
                    out.append((ref[0], ref[1], txt))
    return out


def _parse(res):
    t = res.strip()
    try:
        return json.loads(t)
    except (json.JSONDecodeError, ValueError):
        if t.startswith(("FIXME", "[atelier]")):
            s = t.find("{")
            if s >= 0:
                try:
                    return json.loads(t[s:])
                except (json.JSONDecodeError, ValueError):
                    return None
        k = t.find("\n\nFIXME")
        if k > 0:
            try:
                return json.loads(t[:k])
            except (json.JSONDecodeError, ValueError):
                return None
    return None


def _base(p):
    return Path(str(p).split("#")[0].split(":")[0]).name


EDIT = {"edit", "codemod", "write"}


def analyze(run_dir, only=None):
    d = Path(run_dir)
    meta = {}
    for line in (d / "results.jsonl").read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            meta[(r["task"], r["arm"], r["rep"])] = r
    reps = 0
    sav_outline = 0.0  # source stripped from 2nd+ searches
    top2_read_saved = 0.0
    top2_src_added = 0.0
    pos1_src_samples = []
    for (task, arm, rep), r in meta.items():
        if arm != "atelier" or not r.get("ok"):
            continue
        if only and task not in only:
            continue
        fp = r.get("flow_path") or ""
        if not fp or not Path(fp).exists():
            continue
        reps += 1
        s = seq(largest(Path(fp)))
        since = 0
        last_pos1 = None  # base name of pos-1 file from the most recent search, + whether 1st-pos
        for i, (tool, inp, res) in enumerate(s):
            if tool in EDIT:
                since = 0
                last_pos1 = None
                continue
            if tool == "code_search":
                since += 1
                j = _parse(res)
                if not j:
                    continue
                files = j.get("files") or []
                sec = sum(len(json.dumps(f.get("sections", []))) for f in files)
                if since >= 2:
                    sav_outline += sec  # would be stripped to outline
                else:
                    # first/post-edit search: top-2 adds pos-1 file source.
                    if len(files) >= 2:
                        last_pos1 = _base(files[1].get("path", ""))
            elif tool == "read":
                rd_files = inp.get("files") or ([inp.get("file_path")] if inp.get("file_path") else [])
                for f in rd_files:
                    b = _base(f if isinstance(f, str) else f.get("path", ""))
                    if last_pos1 and b == last_pos1:
                        top2_read_saved += len(res)
                        pos1_src_samples.append(len(res))
                        last_pos1 = None
    # top-2 cost: pos-1 source added on first searches. Estimate per-first-search
    # source as the avg pos-1 read size; charge it on first searches that did NOT
    # lead to a pos-1 read (the wasted ~70%).
    avg_pos1 = (sum(pos1_src_samples) / len(pos1_src_samples)) if pos1_src_samples else 3000
    return reps, sav_outline, top2_read_saved, avg_pos1, len(pos1_src_samples)


def report(label, run_dir, only):
    reps, outline, rd_saved, avg_pos1, n_pos1 = analyze(run_dir, only)
    if not reps:
        return
    print(f"\n=== {label} ({reps} atelier reps) ===")
    print(f"  A) OUTLINE-ON-REPEAT: strip source from 2nd+ searches")
    print(f"     saves ~{outline / reps:.0f} chars/rep  (clean reduction, agent reads anyway)")
    print(f"  B) TOP-2: eliminate pos-1 reads")
    print(f"     pos-1 reads eliminated: {n_pos1} total, ~{rd_saved / reps:.0f} chars/rep saved")
    print(f"     (cost: pos-1 source ~{avg_pos1:.0f}c added per first-search that has a 2nd file;")
    print(f"      net positive only when that source is actually read)")
    print(f"  COMBINED clean lower-bound: ~{(outline + rd_saved) / reps:.0f} chars/rep retrieval payload removed")


if __name__ == "__main__":
    rd = sys.argv[1] if len(sys.argv) > 1 else "reports/benchmark/codebench/swe50_final_5rep"
    report("ALL atelier tasks", rd, None)
    report("LOSS tasks only", rd, LOSS)
