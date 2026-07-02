"""Why are the expensive tasks expensive, and why doesn't atelier save on them?

Compares BOTH arms' cost drivers per task from the captured flows. Cost ~ turns x
context/turn; the drivers of turns are FAIL-churn and exploration. For each
expensive task we print base-vs-atel turns / fail-tests / exploration so we can
see where atelier cuts turns (=> savings) vs churns as much as baseline (=> 0%).

PYTHONPATH=src uv run --project benchmarks python experiments/why_expensive.py <run_dir>
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

from mitmproxy.io import FlowReader

import atelier.gateway.adapters.mcp_server as M


def _msgs(fp):
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
        m = b.get("messages") or []
        if len(m) > len(best):
            best = m
    return best


def _events(messages):
    pending, out = {}, []
    for msg in messages:
        c = msg.get("content")
        if not isinstance(c, list):
            continue
        for b in c:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use":
                inp = b.get("input") or {}
                pending[b.get("id")] = (
                    str(b.get("name") or "").split("__")[-1].lower(),
                    str(inp.get("command") or "") if isinstance(inp, dict) else "",
                )
            elif b.get("type") == "tool_result":
                ref = pending.get(b.get("tool_use_id"))
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


def drivers(fp):
    ed = rd = sr = nb = npass = nfail = 0
    for name, cmd, res in _events(_msgs(fp)):
        if name in {"edit", "codemod", "write", "multiedit"}:
            ed += 1
        elif name == "read":
            rd += 1
        elif name in {"code_search", "grep", "search", "explore", "glob"}:
            sr += 1
        elif name == "bash":
            oc = M._classify_test_outcome(cmd, res)
            if oc == "PASS":
                npass += 1
            elif oc == "FAIL":
                nfail += 1
            else:
                nb += 1
    return dict(edits=ed, reads=rd, searches=sr, nontest_bash=nb, **{"pass": npass, "fail": nfail})


def main(run_dir):
    d = Path(run_dir)
    meta = {}
    for line in (d / "results.jsonl").read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            meta[(r["task"], r["arm"], r["rep"])] = r
    agg = defaultdict(lambda: defaultdict(float))
    cnt = defaultdict(int)
    for (task, arm, _rep), m in meta.items():
        if not m.get("ok"):
            continue
        fp = m.get("flow_path") or ""
        if not fp or not Path(fp).exists():
            continue
        dv = drivers(Path(fp))
        k = (task, arm)
        cnt[k] += 1
        agg[k]["cost"] += m["cost_usd"]
        agg[k]["turns"] += m.get("num_turns") or 0
        agg[k]["out"] += m.get("output_tokens") or 0
        for kk, vv in dv.items():
            agg[k][kk] += vv

    def mean(k, f):
        return agg[k][f] / cnt[k] if cnt[k] else 0

    tasks = sorted({t for (t, a) in agg})
    # expensive = mean cost > $1 on either arm
    exp = [t for t in tasks if mean((t, "baseline"), "cost") > 1 or mean((t, "atelier"), "cost") > 1]
    print(f"{'task / arm':26}{'$':>6}{'turn':>5}{'$/turn':>7}{'fail':>5}{'edit':>5}{'read':>5}{'srch':>5}{'bash':>5}")
    print("-" * 71)
    for t in sorted(exp, key=lambda t: -(mean((t, "baseline"), "cost"))):
        for arm in ("baseline", "atelier"):
            k = (t, arm)
            tn = mean(k, "turns") or 1
            tag = f"{t.split('__')[-1][:18]:18} {arm[:4]}"
            print(
                f"{tag:26}{mean(k, 'cost'):>6.2f}{mean(k, 'turns'):>5.0f}{mean(k, 'cost') / tn:>7.3f}{mean(k, 'fail'):>5.1f}"
                f"{mean(k, 'edits'):>5.1f}{mean(k, 'reads'):>5.1f}{mean(k, 'searches'):>5.1f}{mean(k, 'nontest_bash'):>5.1f}"
            )
        # delta line
        dt = mean((t, "atelier"), "turns") - mean((t, "baseline"), "turns")
        df = mean((t, "atelier"), "fail") - mean((t, "baseline"), "fail")
        sv = (
            (mean((t, "baseline"), "cost") - mean((t, "atelier"), "cost")) / mean((t, "baseline"), "cost") * 100
            if mean((t, "baseline"), "cost")
            else 0
        )
        print(f"  {'Δ (atel-base)':24}{'':>6}{dt:>+5.0f}{df:>+5.1f}{'':>5}{'':>5}{'':>5}{'':>5}   save {sv:+.0f}%")
    # correlation: per expensive task, savings% vs turn-delta
    print("\n--- does atelier save when it cuts turns? ---")
    import statistics

    pairs = []
    for t in exp:
        b, a = mean((t, "baseline"), "cost"), mean((t, "atelier"), "cost")
        if not b:
            continue
        sv = (b - a) / b * 100
        dt = mean((t, "atelier"), "turns") - mean((t, "baseline"), "turns")
        pairs.append((sv, dt))
    if len(pairs) > 2:
        svs = [p[0] for p in pairs]
        dts = [p[1] for p in pairs]
        try:
            r = statistics.correlation(svs, dts)
            print(f"  corr(savings%, turn-delta) = {r:+.2f}  (negative => fewer turns -> more savings)")
        except Exception as e:
            print("  corr n/a", e)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "reports/benchmark/codebench/swe50_final_5rep")
