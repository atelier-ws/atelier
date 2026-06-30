"""Decompose atelier's +26%/turn context premium into its parts.

Per-turn cost is ~all cache_read = the re-sent prefix (system + tool schemas +
conversation so far). This measures, per arm, from the captured request bodies:
  - FIXED overhead re-sent EVERY turn: system prompt size + tool-schema size + #tools
  - VARIABLE payload: average tool_result size by tool (what retrieval returns)
so we know which part to trim first. Sizes in chars (~4 chars/token).

PYTHONPATH=src uv run --project benchmarks python experiments/context_breakdown.py <run_dir>
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

from mitmproxy.io import FlowReader


def _requests(fp):
    """All parsed /v1/messages request bodies in a flow, smallest-first."""
    out = []
    with open(fp, "rb") as fh:
        try:
            flows = list(FlowReader(fh).stream())
        except Exception:
            return out
    for fl in flows:
        if not fl.request or "v1/messages" not in fl.request.url:
            continue
        try:
            out.append(json.loads(fl.request.content.decode("utf-8", "ignore")))
        except Exception:
            continue
    out.sort(key=lambda b: len(b.get("messages") or []))
    return out


def _sz(o):
    return len(json.dumps(o, ensure_ascii=False)) if o is not None else 0


def analyze_arm(run_dir, arm, sample=10):
    d = Path(run_dir)
    flows = sorted(d.glob(f"*_{arm}_rep*.flow"))[:sample]
    sys_sz = []
    tools_sz = []
    n_tools = []
    result_sz = defaultdict(list)  # tool name -> [result char sizes]
    for fp in flows:
        reqs = _requests(fp)
        if not reqs:
            continue
        # the real agent request = the one carrying the full tool set (not a tiny
        # haiku title-gen auxiliary call, which has no tools).
        first = max(reqs, key=lambda r: _sz(r.get("tools")))
        sys_sz.append(_sz(first.get("system")))
        tools_sz.append(_sz(first.get("tools")))
        n_tools.append(len(first.get("tools") or []))
        # tool_result sizes: scan the largest request's messages
        big = reqs[-1]
        pend = {}
        for msg in big.get("messages", []):
            c = msg.get("content")
            if not isinstance(c, list):
                continue
            for b in c:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_use":
                    pend[b.get("id")] = str(b.get("name") or "").split("__")[-1].lower()
                elif b.get("type") == "tool_result":
                    nm = pend.get(b.get("tool_use_id"), "?")
                    inner = b.get("content")
                    txt = json.dumps(inner, ensure_ascii=False) if inner is not None else ""
                    result_sz[nm].append(len(txt))

    def avg(xs):
        return sum(xs) / len(xs) if xs else 0

    return {
        "flows": len(flows),
        "system": avg(sys_sz),
        "tools": avg(tools_sz),
        "n_tools": avg(n_tools),
        "results": {k: (avg(v), len(v)) for k, v in result_sz.items()},
    }


def main(run_dir):
    a = analyze_arm(run_dir, "atelier")
    b = analyze_arm(run_dir, "baseline")
    print("=== FIXED per-turn overhead (re-sent + cached EVERY turn) ===")
    print(f"{'component':16}{'baseline':>12}{'atelier':>12}{'delta':>12}")
    for f, lbl in [("system", "system prompt"), ("tools", "tool schemas"), ("n_tools", "# tools")]:
        bv, av = b[f], a[f]
        unit = "" if f == "n_tools" else " ch"
        dl = f"+{av - bv:.0f}{unit}" if av >= bv else f"{av - bv:.0f}{unit}"
        print(f"{lbl:16}{bv:>10.0f}{unit}{av:>10.0f}{unit}{dl:>12}")
    fixed_b = b["system"] + b["tools"]
    fixed_a = a["system"] + a["tools"]
    print(
        f"{'FIXED total':16}{fixed_b:>10.0f} ch{fixed_a:>10.0f} ch   +{(fixed_a - fixed_b) / max(fixed_b, 1) * 100:.0f}% (~{(fixed_a - fixed_b) / 4:.0f} tok/turn)"
    )
    print("\n=== VARIABLE payload: avg tool_result size by tool (chars) ===")
    print(f"{'tool':16}{'baseline (n)':>20}{'atelier (n)':>20}")
    keys = sorted(set(a["results"]) | set(b["results"]))
    for k in keys:
        av, an = a["results"].get(k, (0, 0))
        bv, bn = b["results"].get(k, (0, 0))
        print(f"{k:16}{f'{bv:.0f} (n={bn})':>20}{f'{av:.0f} (n={an})':>20}")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "reports/benchmark/codebench/swe50_final_5rep")
