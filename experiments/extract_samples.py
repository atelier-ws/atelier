"""Dump REAL atelier narration + tool outputs so we can see what to trim.

Prints: (1) a sample of narration text blocks (the prose before tool calls),
(2) a couple full code_search results, (3) a couple full read results -- so we
can eyeball structure/sections and judge what the LLM actually uses.

PYTHONPATH=src uv run --project benchmarks python experiments/extract_samples.py <flow>
"""

import json
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


def main(flow):
    msgs = _largest_msgs(Path(flow))
    narration, results = [], []
    pend = {}
    for m in msgs:
        c = m.get("content")
        if not isinstance(c, list):
            continue
        for b in c:
            if not isinstance(b, dict):
                continue
            if b.get("type") == "text" and m.get("role") == "assistant":
                t = b.get("text", "").strip()
                if t:
                    narration.append(t)
            elif b.get("type") == "tool_use":
                pend[b.get("id")] = str(b.get("name", "")).split("__")[-1].lower()
            elif b.get("type") == "tool_result":
                nm = pend.get(b.get("tool_use_id"), "?")
                inner = b.get("content")
                txt = (
                    " ".join(i.get("text", "") for i in inner if isinstance(i, dict))
                    if isinstance(inner, list)
                    else str(inner or "")
                )
                results.append((nm, txt))
    print("#" * 70)
    print(f"NARRATION blocks ({len(narration)}); showing first 8:")
    print("#" * 70)
    for t in narration[:8]:
        print(f"  [{len(t)}c] {t[:240]}")
    for want in ("code_search", "read"):
        samples = [(nm, tx) for nm, tx in results if nm == want]
        print("\n" + "#" * 70)
        print(f"{want.upper()} results ({len(samples)}); showing first 2 FULL:")
        print("#" * 70)
        for nm, tx in samples[:2]:
            print(f"\n----- {nm} result ({len(tx)}c) -----")
            print(tx[:2200])


if __name__ == "__main__":
    main(sys.argv[1])
