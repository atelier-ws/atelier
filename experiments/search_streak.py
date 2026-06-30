"""Back the graduated-code_search policy with data.

Policy to justify: 1st code_search (or 1st after an edit) -> full content (top-2);
2nd+ search with no edit since -> outline only. So we measure, per code_search,
its STREAK POSITION (searches since last edit) and:
  - what the NEXT action is (edit / read / another search)  -> exploration vs action
  - whether an edit follows within 3 actions (did this search lead to a fix?)
  - the source payload it returned (savings if pos>=2 -> outline)
  - how often the next thing is ANOTHER search (current source never acted on)

PYTHONPATH=src uv run --project benchmarks python experiments/search_streak.py <run_dir>
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

from mitmproxy.io import FlowReader


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


def _src(res):
    """Source chars in a code_search result, stripping any convergence wrapper."""
    t = res.strip()
    j = None
    try:
        j = json.loads(t)
    except (json.JSONDecodeError, ValueError):
        # suffix nudge: '{json}\n\nFIXME...'
        k = t.find("\n\nFIXME")
        if k > 0 and t.startswith("{"):
            try:
                j = json.loads(t[:k])
            except (json.JSONDecodeError, ValueError):
                j = None
        # prefix: 'FIXME...\n\n{json}' / '[atelier]...{json}'
        if j is None and t.startswith(("FIXME", "[atelier]")):
            s = t.find("{")
            if s >= 0:
                try:
                    j = json.loads(t[s:])
                except (json.JSONDecodeError, ValueError):
                    j = None
    if j is None:
        return 0
    return sum(len(json.dumps(f.get("sections", []))) for f in (j.get("files") or []))


EDIT = {"edit", "codemod", "write"}


def main(run_dir):
    d = Path(run_dir)
    pos_n = defaultdict(int)
    pos_next = defaultdict(lambda: defaultdict(int))
    pos_src = defaultdict(float)
    pos_edit3 = defaultdict(int)
    for fp in sorted(d.glob("*_atelier_rep*.flow"))[:40]:
        s = seq(largest(fp))
        since = 0
        for i, (tool, inp, res) in enumerate(s):
            if tool in EDIT:
                since = 0
                continue
            if tool != "code_search":
                continue
            since += 1
            p = since if since <= 3 else 4  # bucket 4 = '4+'
            pos_n[p] += 1
            pos_src[p] += _src(res)
            nxt = s[i + 1][0] if i + 1 < len(s) else "<end>"
            pos_next[p][nxt if nxt in (EDIT | {"read", "code_search"}) else "other"] += 1
            if any(t in EDIT for t, _, _ in s[i + 1 : i + 4]):
                pos_edit3[p] += 1
    print("code_search by STREAK POSITION (searches since last edit; 4 = 4+)")
    print(f"{'pos':>4}{'count':>7}{'avg src ch':>12}{'->edit≤3':>10}{'next: edit / read / search / other':>38}")
    lbl = {1: "1st", 2: "2nd", 3: "3rd", 4: "4+"}
    for p in sorted(pos_n):
        n = pos_n[p]
        nx = pos_next[p]
        share = lambda k: f"{nx.get(k, 0) / n * 100:.0f}%"
        e = next(iter(EDIT))
        ed = sum(nx.get(k, 0) for k in EDIT)
        print(
            f"{lbl[p]:>4}{n:>7}{pos_src[p] / n:>12.0f}{pos_edit3[p] / n * 100:>9.0f}%   "
            f"edit {ed / n * 100:.0f}% / read {share('read')} / search {share('code_search')} / other {share('other')}"
        )
    print("\nREAD: total source payload returned by 1st-position vs 2nd+ searches")
    p1 = pos_src[1]
    p2plus = sum(pos_src[p] for p in pos_src if p >= 2)
    print(f"  1st-search source total: {p1:.0f}c   2nd+ search source total: {p2plus:.0f}c")
    if p1 + p2plus:
        print(
            f"  => outline-ing 2nd+ searches removes ~{p2plus / (p1 + p2plus) * 100:.0f}% of code_search SOURCE payload"
        )


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "reports/benchmark/codebench/swe50_final_5rep")
