"""Dump the full call->result trajectory of a flow (largest request has the whole
conversation). Shows what each tool RETURNED, to spot why an agent re-searches.
"""

from __future__ import annotations

import json
import sys


def largest_request(path: str):
    from mitmproxy.io import FlowReader

    best = None
    with open(path, "rb") as fh:
        for flow in FlowReader(fh).stream():
            req = getattr(flow, "request", None)
            if req is None:
                continue
            host = (req.pretty_host or "").lower()
            if not any(h in host for h in ("anthropic", "claude", "bedrock")):
                continue
            try:
                body = req.content
            except ValueError:
                body = req.raw_content
            if not body:
                continue
            try:
                j = json.loads(body)
            except Exception:
                continue
            n = len(j.get("messages") or [])
            if best is None or n > best[0]:
                best = (n, j)
    return best[1] if best else None


def text_of(content) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out = []
        for b in content:
            if isinstance(b, dict):
                out.append(b.get("text") or b.get("content") or "")
            else:
                out.append(str(b))
        return " ".join(str(x) for x in out)
    return str(content)


def main() -> None:
    path = sys.argv[1]
    rt = int(sys.argv[2]) if len(sys.argv) > 2 else 220
    j = largest_request(path)
    if not j:
        print("no request")
        return
    print(f"===== {path.split('/')[-1]}  ({len(j.get('messages') or [])} messages) =====")
    for m in j.get("messages") or []:
        role = m.get("role")
        for b in m.get("content") or []:
            if not isinstance(b, dict):
                continue
            t = b.get("type")
            if t == "text" and role == "assistant":
                tx = (b.get("text") or "").strip().replace("\n", " ")
                if tx:
                    print(f"  [assistant] {tx[:rt]}")
            elif t == "tool_use":
                nm = (b.get("name") or "?").replace("mcp__plugin_atelier_atelier__", "a:")
                inp = json.dumps(b.get("input") or {})[:rt].replace("\n", " ")
                print(f"  >> CALL {nm}  {inp}")
            elif t == "tool_result":
                res = text_of(b.get("content")).replace("\n", " ")
                ln = len(res)
                print(f"     << RESULT ({ln} chars) {res[:rt]}")


if __name__ == "__main__":
    main()
