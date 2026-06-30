"""Cost autopsy: WHY are the expensive atelier reps expensive?

For each captured flow, reconstruct the tool stream and cross it with the rep's
cost/turns/tokens, then attribute cost to its drivers (turn depth, output/turn,
FAIL-churn, exploration) and audit which EXISTING convergence detectors fire
(driven by the real detector code; fire = detector mutated the result text).

PYTHONPATH=src uv run --project benchmarks python experiments/cost_autopsy.py <run_dir>
"""

import json
import sys
from pathlib import Path

from mitmproxy.io import FlowReader

import atelier.gateway.adapters.mcp_server as M


def _largest_request_messages(flow_path):
    best = []
    with open(flow_path, "rb") as fh:
        try:
            flows = list(FlowReader(fh).stream())
        except Exception:
            return best
    for flow in flows:
        if not flow.request or "v1/messages" not in flow.request.url:
            continue
        try:
            body = json.loads(flow.request.content.decode("utf-8", "ignore"))
        except Exception:
            continue
        msgs = body.get("messages") or []
        if len(msgs) > len(best):
            best = msgs
    return best


def _events(messages):
    pending = {}
    out = []
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for b in content:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use":
                short = str(b.get("name") or "").split("__")[-1].lower()
                inp = b.get("input") or {}
                cmd = str(inp.get("command") or "") if isinstance(inp, dict) else ""
                pending[b.get("id")] = (short, cmd)
            elif b.get("type") == "tool_result":
                ref = pending.get(b.get("tool_use_id"))
                if not ref:
                    continue
                inner = b.get("content")
                if isinstance(inner, list):
                    txt = " ".join(i.get("text", "") for i in inner if isinstance(i, dict))
                else:
                    txt = str(inner or "")
                out.append((ref[0], ref[1], txt))
    return out


def _reset_detectors():
    M._NONEDIT_STREAK[0] = 0
    M._FAILED_TEST_STREAK[0] = 0
    M._EDITS_SINCE_GREEN[0] = 0
    M._HISTORY_STREAK[0] = 0


def analyze(flow_path):
    evs = _events(_largest_request_messages(flow_path))
    edits = reads = searches = nontest_bash = npass = nfail = 0
    seq = []
    _reset_detectors()
    fires = {"gather": False, "churn": False, "history": False}
    dets = [
        ("gather", M._convergence_intervention),
        ("churn", M._test_churn_intervention),
        ("history", M._history_archaeology_intervention),
    ]
    for name, cmd, res in evs:
        if name in {"edit", "codemod", "write"}:
            edits += 1
        elif name == "read":
            reads += 1
        elif name in {"code_search", "grep", "search", "explore"}:
            searches += 1
        elif name == "bash":
            oc = M._classify_test_outcome(cmd, res)
            if oc == "PASS":
                npass += 1
                seq.append("P")
            elif oc == "FAIL":
                nfail += 1
                seq.append("F")
            else:
                nontest_bash += 1
        # fire audit: each detector independently on the original result text
        for key, fn in dets:
            if fn(name, {"command": cmd}, res) != res:
                fires[key] = True
    return {
        "edits": edits,
        "reads": reads,
        "searches": searches,
        "nontest_bash": nontest_bash,
        "pass": npass,
        "fail": nfail,
        "seq": "".join(seq),
        "fires": fires,
    }


def main(run_dir):
    d = Path(run_dir)
    meta = {}
    for line in (d / "results.jsonl").read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            if r["arm"] == "atelier":
                meta[(r["task"], r["rep"])] = r
    rows = []
    for f in sorted(d.glob("*_atelier_rep*.flow")):
        try:
            task, rep = f.stem.rsplit("_atelier_rep", 1)
            rep = int(rep)
        except ValueError:
            continue
        m = meta.get((task, rep))
        if not m or not m.get("cost_usd"):
            continue
        a = analyze(f)
        turns = m.get("num_turns") or 1
        rows.append(
            {
                "task": task.split("__")[-1],
                "rep": rep,
                "cost": m["cost_usd"],
                "turns": turns,
                "out": m.get("output_tokens") or 0,
                "cacheR": m.get("cache_read_tokens") or 0,
                "correct": m.get("correct"),
                **a,
            }
        )
    rows.sort(key=lambda r: -r["cost"])
    cc = {True: "Y", False: "N", None: "?"}
    print(
        f"{'task':22}{'rep':>3}{'$':>6}{'turn':>5}{'out/t':>6}{'cR/t':>6}{'cor':>4} | "
        f"{'ed':>3}{'rd':>3}{'srch':>5}{'bash':>5}{'P':>3}{'F':>3}  fires      seq"
    )
    for r in rows[:28]:
        fr = ",".join(k for k, v in r["fires"].items() if v) or "-"
        print(
            f"{r['task']:22}{r['rep']:>3}{r['cost']:>6.2f}{r['turns']:>5}"
            f"{r['out'] // r['turns']:>6}{r['cacheR'] // r['turns'] // 1000:>5}k{cc[r['correct']]:>4} | "
            f"{r['edits']:>3}{r['reads']:>3}{r['searches']:>5}{r['nontest_bash']:>5}{r['pass']:>3}{r['fail']:>3}  "
            f"{fr:10} {r['seq'][:12]}"
        )
    # aggregate cost-driver correlation: top-decile cost vs rest
    rows2 = [r for r in rows if r["turns"]]
    rows2.sort(key=lambda r: -r["cost"])
    n = max(1, len(rows2) // 5)
    top, rest = rows2[:n], rows2[n:]

    def avg(rs, k):
        return sum(r[k] for r in rs) / len(rs) if rs else 0

    def avg_per_turn(rs, k):
        return sum(r[k] / r["turns"] for r in rs) / len(rs) if rs else 0

    print(f"\n--- TOP-20% costliest ({len(top)} reps) vs REST ({len(rest)}) ---")
    print(f"  mean cost:    top ${avg(top, 'cost'):.2f}  rest ${avg(rest, 'cost'):.2f}")
    print(f"  mean turns:   top {avg(top, 'turns'):.0f}    rest {avg(rest, 'turns'):.0f}")
    print(f"  out/turn:     top {avg_per_turn(top, 'out'):.0f}   rest {avg_per_turn(rest, 'out'):.0f}")
    print(
        f"  cacheR/turn:  top {avg_per_turn(top, 'cacheR') / 1000:.0f}k  rest {avg_per_turn(rest, 'cacheR') / 1000:.0f}k"
    )
    print(f"  edits:        top {avg(top, 'edits'):.1f}   rest {avg(rest, 'edits'):.1f}")
    print(f"  FAIL tests:   top {avg(top, 'fail'):.1f}   rest {avg(rest, 'fail'):.1f}")
    print(f"  PASS tests:   top {avg(top, 'pass'):.1f}   rest {avg(rest, 'pass'):.1f}")
    print(f"  nontest bash: top {avg(top, 'nontest_bash'):.1f}   rest {avg(rest, 'nontest_bash'):.1f}")
    print(f"  reads:        top {avg(top, 'reads'):.1f}   rest {avg(rest, 'reads'):.1f}")
    print(f"  searches:     top {avg(top, 'searches'):.1f}   rest {avg(rest, 'searches'):.1f}")
    for key in ("gather", "churn", "history"):
        print(
            f"  fires[{key}]:  top {sum(1 for r in top if r['fires'][key])}/{len(top)}   "
            f"rest {sum(1 for r in rest if r['fires'][key])}/{len(rest)}"
        )


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "reports/benchmark/codebench/swe50_final_5rep")
