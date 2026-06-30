"""Size the top-2 opportunity: how many read turns fetch a file code_search
already ranked but returned as a pointer (no source)?

For each flow, track code_search emissions: files[0]=source(rank0), files[1:]=
pointer(rank1+), candidate_files=candidate. Then every later read is classified:
  - hits pos-1 (files[1])  -> a read TOP-2 would eliminate
  - hits files[2:]/candidate -> a read fuller graduation would eliminate
  - hits files[0] (re-read) -> already had source
  - novel (not offered)    -> code_search can't help

PYTHONPATH=src uv run --project benchmarks python experiments/measure_read_savings.py <run_dir>
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
        except (OSError, ValueError):
            return best
    for fl in flows:
        if not fl.request or "v1/messages" not in fl.request.url:
            continue
        try:
            b = json.loads(fl.request.content.decode("utf-8", "ignore"))
        except (json.JSONDecodeError, ValueError):
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


def _cs(txt):
    t = txt.strip()
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


def main(run_dir):
    d = Path(run_dir)
    flows = sorted(d.glob("*_atelier_rep*.flow"))[:30]
    cls = defaultdict(int)
    total_reads = 0
    for fp in flows:
        seq = _seq(_largest_msgs(fp))
        offered = {}  # base -> best rank-class seen so far ('pos1','tail','candidate','source')
        for tool, inp, res in seq:
            if tool == "code_search":
                j = _cs(res)
                if not j:
                    continue
                files = j.get("files") or []
                for pos, f in enumerate(files):
                    b = _base(f.get("path", ""))
                    has_src = len(json.dumps(f.get("sections", []))) > 20
                    if pos == 0 and has_src:
                        offered.setdefault(b, "source")
                    elif pos == 1:
                        offered[b] = "pos1"
                    else:
                        offered.setdefault(b, "tail")
                for cf in j.get("candidate_files") or []:
                    offered.setdefault(_base(cf), "candidate")
            elif tool == "read":
                files = inp.get("files") or ([inp.get("file_path")] if inp.get("file_path") else [])
                for f in files:
                    total_reads += 1
                    b = _base(f if isinstance(f, str) else f.get("path", ""))
                    cls[offered.get(b, "novel")] += 1
    print(f"atelier flows: {len(flows)}   total read targets: {total_reads}\n")
    print(f"{'read hit a code_search...':32}{'count':>8}{'% of reads':>12}")
    order = [
        ("pos1", "pos-1 file (TOP-2 saves)"),
        ("tail", "files[2:] pointer"),
        ("candidate", "candidate_file"),
        ("source", "files[0] re-read (had source)"),
        ("novel", "novel (not offered)"),
    ]
    for k, lbl in order:
        print(f"{lbl:32}{cls[k]:>8}{cls[k] / max(total_reads, 1) * 100:>11.0f}%")
    saved = cls["pos1"]
    print(
        f"\nTOP-2 would eliminate ~{saved} read turns ({saved / max(total_reads, 1) * 100:.0f}% of reads) across {len(flows)} flows"
    )
    print(f"= ~{saved / len(flows):.1f} read turns saved per rep")
    deeper = cls["pos1"] + cls["tail"] + cls["candidate"]
    print(
        f"(full graduation incl. candidates would reach ~{deeper} reads = ~{deeper / len(flows):.1f}/rep, but those are lower-hit-rate)"
    )


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "reports/benchmark/codebench/swe50_final_5rep")
