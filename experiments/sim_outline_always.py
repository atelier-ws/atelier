"""Simulate: code_search ALWAYS returns outline (no source); agent reads on demand.

For each atelier flow:
  SAVE   = all code_search source sections stripped (every call)
  COST   = a read (+1 turn) for each searched files[0] the agent later EDITS but
           didn't already read -- it now must read what code_search used to source
  pure save = sections of files the agent never acted on (exploratory context)

Reports net payload + added read-turns per rep, all tasks and loss tasks.
PYTHONPATH=src uv run --project benchmarks python experiments/sim_outline_always.py <run_dir>
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


def report(label, run_dir, only):
    d = Path(run_dir)
    meta = {}
    for line in (d / "results.jsonl").read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            meta[(r["task"], r["arm"], r["rep"])] = r
    reps = save = added_read = added_turns = pure_save = 0
    for (task, arm, _rep), r in meta.items():
        if arm != "atelier" or not r.get("ok"):
            continue
        if only and task not in only:
            continue
        fp = r.get("flow_path") or ""
        if not fp or not Path(fp).exists():
            continue
        reps += 1
        s = seq(largest(Path(fp)))
        edited = set()
        read_bases = set()
        for tool, inp, res in s:
            if tool in EDIT:
                for key in ("file_path", "path"):
                    if isinstance(inp.get(key), str):
                        edited.add(_base(inp[key]))
                for e in inp.get("edits") or []:
                    if isinstance(e, dict) and (e.get("file_path") or e.get("path")):
                        edited.add(_base(e.get("file_path") or e.get("path")))
            elif tool == "read":
                for f in inp.get("files") or ([inp.get("file_path")] if inp.get("file_path") else []):
                    read_bases.add(_base(f if isinstance(f, str) else f.get("path", "")))
        for tool, inp, res in s:
            if tool != "code_search":
                continue
            j = _parse(res)
            if not j:
                continue
            files = j.get("files") or []
            sec = sum(len(json.dumps(f.get("sections", []))) for f in files)
            save += sec
            f0 = _base(files[0].get("path", "")) if files else ""
            if f0 and f0 in edited and f0 not in read_bases:
                added_read += sec  # must now read what code_search sourced
                added_turns += 1
            elif f0 not in edited:
                pure_save += sec  # exploratory context, never acted on
    if not reps:
        return
    net = save - added_read
    print(f"\n=== {label} ({reps} reps) -- code_search OUTLINE-ALWAYS ===")
    print(f"  source stripped (SAVE):        ~{save / reps:.0f} chars/rep")
    print(
        f"  forced reads of edited files:  ~{added_read / reps:.0f} chars/rep  (+{added_turns / reps:.1f} read-TURNS/rep)"
    )
    print(f"  net payload change:            ~{net / reps:+.0f} chars/rep  (+ {added_turns / reps:.1f} turns)")
    print(f"  (of the save, ~{pure_save / reps:.0f}/rep was exploratory source never acted on = clean win)")


if __name__ == "__main__":
    rd = sys.argv[1] if len(sys.argv) > 1 else "reports/benchmark/codebench/swe50_final_5rep"
    report("ALL atelier tasks", rd, None)
    report("LOSS tasks only", rd, LOSS)
PY = None
