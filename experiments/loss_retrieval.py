"""On the LOSS tasks: does atelier read more than baseline despite code_search?

For each loss task + arm, sum per-rep: read result chars & count, code_search
chars & count, and combined retrieval chars. If atelier's (read + code_search)
or read-count exceeds baseline's reads, the retrieval is redundant -- the agent
re-reads what code_search pointed to.

PYTHONPATH=src uv run --project benchmarks python experiments/loss_retrieval.py <run_dir>
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

from mitmproxy.io import FlowReader

LOSS = [
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
]


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


def counts(fp):
    names, c = {}, defaultdict(float)
    for m in largest(fp):
        for b in m.get("content") or []:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use":
                names[b.get("id")] = str(b.get("name", "")).split("__")[-1].lower()
            elif b.get("type") == "tool_result":
                nm = names.get(b.get("tool_use_id"), "?")
                inner = b.get("content")
                txt = (
                    " ".join(i.get("text", "") for i in inner if isinstance(i, dict))
                    if isinstance(inner, list)
                    else str(inner or "")
                )
                if nm == "read":
                    c["rd_ch"] += len(txt)
                    c["rd_n"] += 1
                elif nm == "code_search":
                    c["cs_ch"] += len(txt)
                    c["cs_n"] += 1
    return c


def main(run_dir):
    meta = {}
    for line in (Path(run_dir) / "results.jsonl").read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            meta[(r["task"], r["arm"], r["rep"])] = r
    agg = defaultdict(lambda: defaultdict(float))
    n = defaultdict(int)
    for (task, arm, _rep), r in meta.items():
        if task not in LOSS or not r.get("ok"):
            continue
        fp = r.get("flow_path") or ""
        if not fp or not Path(fp).exists():
            continue
        c = counts(Path(fp))
        n[(task, arm)] += 1
        for k, v in c.items():
            agg[(task, arm)][k] += v

    def mn(task, arm, k):
        key = (task, arm)
        return agg[key][k] / n[key] if n[key] else 0

    print(f"{'task':18}{'arm':5}{'read_n':>7}{'read_ch':>9}{'cs_n':>5}{'cs_ch':>8}{'rd+cs ch':>10}")
    print("-" * 62)
    for task in LOSS:
        for arm in ("baseline", "atelier"):
            if not n[(task, arm)]:
                continue
            rd_n, rd_ch, cs_n, cs_ch = (
                mn(task, arm, "rd_n"),
                mn(task, arm, "rd_ch"),
                mn(task, arm, "cs_n"),
                mn(task, arm, "cs_ch"),
            )
            tag = f"{task.split('__')[-1][:16]:16}" if arm == "baseline" else " " * 16
            print(f"{tag:18}{arm[:4]:5}{rd_n:>7.1f}{rd_ch:>9.0f}{cs_n:>5.1f}{cs_ch:>8.0f}{rd_ch + cs_ch:>10.0f}")
        # verdict line
        b_rd = mn(task, "baseline", "rd_ch")
        a_comb = mn(task, "atelier", "rd_ch") + mn(task, "atelier", "cs_ch")
        b_rdn = mn(task, "baseline", "rd_n")
        a_rdn = mn(task, "atelier", "rd_n")
        verdict = "atel retrieval HEAVIER" if a_comb > b_rd else "atel lighter"
        readmore = "reads MORE" if a_rdn > b_rdn else "reads fewer"
        print(
            f"  -> atel(rd+cs)={a_comb:.0f} vs base(rd)={b_rd:.0f}  [{verdict}]; atel {readmore} ({a_rdn:.1f} vs {b_rdn:.1f})"
        )


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "reports/benchmark/codebench/swe50_final_5rep")
