"""Extract every computation (bash->python) run this session + its real output
from the transcript JSONL, so the numbers can be audited against memory.
"""

import json
import re
import sys

TRANSCRIPT = (
    "/home/pankaj/.claude/projects/-home-pankaj-Projects-leanchain-atelier/a2cfa40f-2bd5-4758-a9cb-7f3a135c1efe.jsonl"
)

# output lines worth keeping (numbers / cost / token / benchmark vocabulary)
KEEP = re.compile(
    r"\$|%|\bturns?\b|cost|token|cheaper|sav|median|mean|MRR|correct|baseline|atelier|"
    r"redundant|overlap|per.file|per.call|dedup|outline|spiral|\bKB\b|\bc\b|budget|cache",
    re.IGNORECASE,
)
IS_COMPUTE = re.compile(r"python|uv run|experiments/|results\.jsonl|\.flow", re.IGNORECASE)


def blocks(msg):
    c = msg.get("content")
    return c if isinstance(c, list) else []


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in content)
    return str(content or "")


def main():
    pend = {}  # tool_use_id -> command
    n = 0
    for line in open(TRANSCRIPT, encoding="utf-8", errors="ignore"):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = obj.get("message") or {}
        for b in blocks(msg):
            if not isinstance(b, dict):
                continue
            if b.get("type") == "tool_use":
                name = str(b.get("name", ""))
                if name.split("__")[-1] in ("bash",):
                    cmd = (b.get("input") or {}).get("command", "")
                    if cmd and IS_COMPUTE.search(cmd):
                        pend[b.get("id")] = cmd
            elif b.get("type") == "tool_result":
                tid = b.get("tool_use_id")
                if tid in pend:
                    cmd = pend.pop(tid)
                    out = text_of(b.get("content"))
                    keep = [ln for ln in out.splitlines() if KEEP.search(ln)]
                    if not keep:
                        continue
                    n += 1
                    print(f"\n{'=' * 78}\n#{n}  CMD: {cmd[:300].replace(chr(10), ' ')}")
                    print("-" * 78)
                    for ln in keep[:30]:
                        print("  " + ln[:200])
                    if len(keep) > 30:
                        print(f"  ... (+{len(keep) - 30} more numeric lines)")
    print(f"\n\n[total computation results captured: {n}]", file=sys.stderr)


if __name__ == "__main__":
    main()
