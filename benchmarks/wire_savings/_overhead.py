"""Measure the per-turn FIXED overhead (system prompt + tool schemas) that gets
re-billed as cache_read every turn -- the dominant cost lever vs baseline.

Scans ALL model requests in a flow and reports the representative agent turn
(the one carrying the largest tool surface), broken down system vs per-tool.
"""

from __future__ import annotations

import glob
import json


def iter_requests(path: str):
    from mitmproxy.io import FlowReader

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
                yield req, json.loads(body)
            except Exception:
                continue


def sys_chars(system) -> int:
    if isinstance(system, str):
        return len(system)
    if isinstance(system, list):
        return sum(len(b.get("text", "")) if isinstance(b, dict) else len(str(b)) for b in system)
    return 0


def analyze(label: str, path: str) -> None:
    best = None
    nreq = 0
    models = set()
    for req, j in iter_requests(path):
        nreq += 1
        models.add(j.get("model", "?"))
        ntools = len(j.get("tools") or [])
        if best is None or ntools > len(best[1].get("tools") or []):
            best = (req, j)
    if best is None:
        print(f"\n[{label}] no JSON requests parsed ({path})")
        return
    j = best[1]
    sc = sys_chars(j.get("system"))
    tools = j.get("tools") or []
    tc = len(json.dumps(tools))
    print(f"\n===== {label} =====  ({path.split('/')[-1]})")
    print(f"  requests in flow: {nreq}   models: {sorted(models)}")
    print(f"  system prompt : {sc:>7,} chars  (~{sc // 4:>6,} tok)")
    print(f"  tool schemas  : {tc:>7,} chars  (~{tc // 4:>6,} tok)   [{len(tools)} tools]")
    print(f"  FIXED PREFIX  : {sc + tc:>7,} chars  (~{(sc + tc) // 4:>6,} tok)  <- cache_read EVERY turn")
    sizes = sorted(((len(json.dumps(t)), t.get("name", "?")) for t in tools), reverse=True)
    print("  tool schemas by size (chars):")
    for n, name in sizes:
        print(f"      {n:>6,}  {name}")


def main() -> None:
    d = "reports/benchmark/codebench/swe12_20260619T055432Z"
    for arm, lab in (
        ("baseline", "BASELINE (Claude Code default tools)"),
        ("atelier", "ATELIER (MCP surface + persona)"),
    ):
        fs = sorted(glob.glob(f"{d}/django__django-13344_{arm}_rep1.flow"))
        if fs:
            analyze(lab, fs[0])


if __name__ == "__main__":
    main()
