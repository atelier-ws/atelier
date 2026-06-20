"""Per-turn trajectory tracer: dump the tool-call sequence of a flow so we can
see exactly where an agent spends turns (and waste).
"""

from __future__ import annotations

import json
import sys


def turns(path: str):
    from mitmproxy.io import FlowReader

    out = []
    with open(path, "rb") as fh:
        for flow in FlowReader(fh).stream():
            resp = getattr(flow, "response", None)
            req = getattr(flow, "request", None)
            if resp is None or req is None:
                continue
            host = (req.pretty_host or "").lower()
            if not any(h in host for h in ("anthropic", "claude", "bedrock")):
                continue
            ct = (resp.headers.get("content-type", "") or "").lower()
            try:
                body = resp.content
            except ValueError:
                body = resp.raw_content
            if not body or ("event-stream" not in ct and b"data:" not in body[:256]):
                continue
            # reconstruct blocks
            btype: dict = {}
            bname: dict = {}
            binput: dict = {}
            text = ""
            model = "?"
            for raw in body.split(b"\n"):
                if not raw.startswith(b"data:"):
                    continue
                try:
                    ev = json.loads(raw[5:].strip() or b"{}")
                except Exception:
                    continue
                t = ev.get("type")
                if t == "message_start":
                    model = (ev.get("message") or {}).get("model", "?")
                elif t == "content_block_start":
                    i = ev.get("index")
                    cb = ev.get("content_block") or {}
                    btype[i] = cb.get("type")
                    if cb.get("type") == "tool_use":
                        bname[i] = cb.get("name")
                        binput[i] = ""
                elif t == "content_block_delta":
                    i = ev.get("index")
                    d = ev.get("delta") or {}
                    if d.get("type") == "text_delta":
                        text += d.get("text") or ""
                    elif d.get("type") == "input_json_delta":
                        binput[i] = binput.get(i, "") + (d.get("partial_json") or "")
            tools = []
            for i in sorted(bname):
                nm = (bname[i] or "?").replace("mcp__plugin_atelier_atelier__", "a:")
                arg = binput.get(i, "")[:90].replace("\n", " ")
                tools.append(f"{nm}({arg})")
            if model.startswith("claude-haiku"):
                continue  # skip cheap helper calls
            out.append((text.strip()[:120].replace("\n", " "), tools))
    return out


def main() -> None:
    for f in sys.argv[1:]:
        rows = turns(f)
        print(f"\n===== {f.split('/')[-1]}  ({len(rows)} opus turns) =====")
        for n, (text, tools) in enumerate(rows, 1):
            tl = "  |  ".join(tools) if tools else "(no tool / final)"
            print(f" T{n:02d}: {tl}")
            if text:
                print(f"      “{text}”")


if __name__ == "__main__":
    main()
