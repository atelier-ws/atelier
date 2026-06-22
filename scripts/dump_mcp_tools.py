"""Dump the live tools/list payload to docs/mcp_tools_dump.json."""

import json
import sys

sys.path.insert(0, "src")
from atelier.gateway.adapters.mcp_server import TOOLS, _tool_description, _tool_visible_to_llm

tools = [
    {"name": n, "description": _tool_description(s), "inputSchema": s.get("inputSchema", {})}
    for n, s in sorted(TOOLS.items())
    if _tool_visible_to_llm(n, s)
]

out = "docs/mcp_tools_dump.json"
with open(out, "w") as f:
    json.dump(tools, f, indent=2)
print(f"wrote {len(tools)} tools to {out}")
