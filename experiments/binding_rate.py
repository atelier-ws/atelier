"""Does the agent OBEY a nudge? Measure the next action after each channel.

The captured flows already carry the live atelier's nudges in tool results:
  - gather  -> '... spiraling'      (weak text channel)
  - churn/history -> 'FIXME (convergence):'    (must-act channel; persona says
                                                'fix every FIXME')
For every nudged result we look at the agent's NEXT tool call: an edit/codemod
means it OBEYED (stopped gathering, acted); another read/search/bash means it
IGNORED. Binding rate = obeyed / fired.

PYTHONPATH=src uv run --project benchmarks python experiments/binding_rate.py <run_dir>
"""

import json
import sys
from collections import Counter
from pathlib import Path

from mitmproxy.io import FlowReader


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
    """Ordered (short_name, result_text) in execution order."""
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
                pending[b.get("id")] = str(b.get("name") or "").split("__")[-1].lower()
            elif b.get("type") == "tool_result":
                nm = pending.get(b.get("tool_use_id"))
                if nm is None:
                    continue
                inner = b.get("content")
                if isinstance(inner, list):
                    txt = " ".join(i.get("text", "") for i in inner if isinstance(i, dict))
                else:
                    txt = str(inner or "")
                out.append((nm, txt))
    return out


EDIT = {"edit", "codemod", "write"}


def channel_of(result_text):
    if "FIXME (convergence)" in result_text:
        return "FIXME(churn/hist)"
    if "[atelier]" in result_text and (
        "spiraling" in result_text or "with 0 edits" in result_text or "STOP GATHERING" in result_text
    ):
        return "[atelier](gather)"
    return None


def main(run_dir):
    d = Path(run_dir)
    fired = Counter()
    obeyed = Counter()  # immediate next action is an edit
    within3 = Counter()  # an edit within the next 3 actions
    first_fire = Counter()  # first encounter of the channel in a rep
    first_within3 = Counter()
    next_kind = {}
    for f in sorted(d.glob("*_atelier_rep*.flow")):
        evs = _events(_largest_request_messages(f))
        seen_ch = set()
        for i, (_nm, res) in enumerate(evs):
            ch = channel_of(res)
            if ch is None:
                continue
            fired[ch] += 1
            nxt = evs[i + 1][0] if i + 1 < len(evs) else "<end>"
            next_kind.setdefault(ch, Counter())[nxt] += 1
            nxt3 = [t for t, _ in evs[i + 1 : i + 4]]
            edit_soon = any(t in EDIT for t in nxt3)
            if nxt in EDIT:
                obeyed[ch] += 1
            if edit_soon:
                within3[ch] += 1
            if ch not in seen_ch:
                seen_ch.add(ch)
                first_fire[ch] += 1
                if edit_soon:
                    first_within3[ch] += 1
    print("channel              fired  edit@next  edit≤3  FIRST-fire only: edit≤3   (n)")
    for ch in ("FIXME(churn/hist)", "[atelier](gather)"):
        n = fired[ch]
        if not n:
            print(f"  {ch:20} 0")
            continue
        e1 = 100 * obeyed[ch] / n
        e3 = 100 * within3[ch] / n
        ff = first_fire[ch]
        ff3 = 100 * first_within3[ch] / ff if ff else 0
        print(f"  {ch:20} {n:>4}   {e1:>5.0f}%   {e3:>5.0f}%        {ff3:>5.0f}%            ({ff})")
    print("\n(edit@next = immediate next action is edit; edit≤3 = an edit within next 3 actions;")
    print(" FIRST-fire only = the agent's FIRST encounter of that nudge in a rep -- the cleanest")
    print(" 'did the warning land before the spiral set in' signal.)")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "reports/benchmark/codebench/swe50_final_5rep")
