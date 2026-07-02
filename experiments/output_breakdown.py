"""What IS atelier's +30% output/turn? Narration vs tool-args vs thinking.

Parses the assistant RESPONSES in each flow and attributes generated chars to:
  - text     : prose narration between tool calls ("Now I'll add ...")
  - tool_args: the tool_use input JSON (edit old/new, bash commands, ...)
  - thinking : extended-thinking blocks
so we trim the right thing. Handles both SSE-streamed and plain-JSON responses.
Chars ~ 4/token. Per-turn = per assistant response.

PYTHONPATH=src uv run --project benchmarks python experiments/output_breakdown.py <run_dir>
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

from mitmproxy.io import FlowReader


def _decode_response(flow):
    """Return (text_ch, args_ch, thinking_ch, args_by_tool) for one response."""
    text = args = think = 0
    by_tool = defaultdict(int)
    try:
        flow.response.decode(strict=False)
        raw = flow.response.content
    except Exception:
        return 0, 0, 0, by_tool
    if not raw:
        return 0, 0, 0, by_tool
    # plain JSON response
    try:
        resp = json.loads(raw.decode("utf-8", "ignore"))
        for blk in resp.get("content", []):
            t = blk.get("type")
            if t == "text":
                text += len(blk.get("text", ""))
            elif t == "thinking":
                think += len(blk.get("thinking", ""))
            elif t == "tool_use":
                s = len(json.dumps(blk.get("input", {}), ensure_ascii=False))
                args += s
                by_tool[str(blk.get("name", "?")).split("__")[-1].lower()] += s
        return text, args, think, by_tool
    except (json.JSONDecodeError, ValueError):
        pass
    # SSE stream
    cur_name = "?"
    for line in raw.decode("utf-8", "ignore").splitlines():
        if not line.startswith("data: "):
            continue
        try:
            ch = json.loads(line[6:])
        except (json.JSONDecodeError, ValueError):
            continue
        tp = ch.get("type")
        if tp == "content_block_start":
            cb = ch.get("content_block", {})
            cb.get("type")
            cur_name = str(cb.get("name", "?")).split("__")[-1].lower()
        elif tp == "content_block_delta":
            dl = ch.get("delta", {})
            dt = dl.get("type")
            if dt == "text_delta":
                text += len(dl.get("text", ""))
            elif dt == "thinking_delta":
                think += len(dl.get("thinking", ""))
            elif dt == "input_json_delta":
                s = len(dl.get("partial_json", ""))
                args += s
                by_tool[cur_name] += s
    return text, args, think, by_tool


def analyze_arm(run_dir, arm, sample=12):
    d = Path(run_dir)
    flows = sorted(d.glob(f"*_{arm}_rep*.flow"))[:sample]
    tot = defaultdict(float)
    turns = 0
    by_tool = defaultdict(float)
    for fp in flows:
        with open(fp, "rb") as fh:
            try:
                fl = list(FlowReader(fh).stream())
            except Exception:
                continue
        for flow in fl:
            if not flow.request or "v1/messages" not in flow.request.url or not flow.response:
                continue
            tx, ar, th, bt = _decode_response(flow)
            if tx + ar + th == 0:
                continue
            turns += 1
            tot["text"] += tx
            tot["args"] += ar
            tot["think"] += th
            for k, v in bt.items():
                by_tool[k] += v
    return tot, turns, by_tool


def main(run_dir):
    print(f"{'category/turn':14}{'baseline':>12}{'atelier':>12}{'premium':>12}")
    data = {}
    for arm in ("baseline", "atelier"):
        tot, turns, bt = analyze_arm(run_dir, arm)
        data[arm] = (
            {k: v / max(turns, 1) for k, v in tot.items()},
            turns,
            {k: v / max(turns, 1) for k, v in bt.items()},
        )
    for cat, lbl in [("text", "narration"), ("args", "tool-args"), ("think", "thinking")]:
        b = data["baseline"][0].get(cat, 0)
        a = data["atelier"][0].get(cat, 0)
        pr = f"{(a - b) / b * 100:+.0f}%" if b else "n/a"
        print(f"{lbl:14}{b:>10.0f}c{a:>10.0f}c{pr:>12}")
    bt_b = sum(data["baseline"][0].values())
    bt_a = sum(data["atelier"][0].values())
    print(f"{'TOTAL out/turn':14}{bt_b:>10.0f}c{bt_a:>10.0f}c{(bt_a - bt_b) / max(bt_b, 1) * 100:>+11.0f}%")
    print(f"\n(turns sampled: baseline {data['baseline'][1]}, atelier {data['atelier'][1]})")
    print("\n=== tool-args chars/turn by tool ===")
    keys = sorted(set(data["baseline"][2]) | set(data["atelier"][2]))
    print(f"{'tool':14}{'baseline':>12}{'atelier':>12}")
    for k in keys:
        print(f"{k:14}{data['baseline'][2].get(k, 0):>11.0f}c{data['atelier'][2].get(k, 0):>11.0f}c")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "reports/benchmark/codebench/swe50_final_5rep")
