"""Make the read both-args recovery robust: if the symbol can't be resolved (no
index / not found), fall back to reading the file(s) instead of raising."""

MCP = "/home/pankaj/Projects/leanchain/atelier-leansearch/src/atelier/gateway/adapters/mcp_server.py"
t = open(MCP, encoding="utf-8").read()
old = (
    "        if isinstance(symbol, list):\n"
    '            return {"symbols": [_op_node(**_parse_symbol(s), path=_scope_path) for s in symbol]}\n'
    "        return _op_node(**_parse_symbol(symbol), path=_scope_path)\n"
)
new = (
    "        try:\n"
    "            if isinstance(symbol, list):\n"
    '                return {"symbols": [_op_node(**_parse_symbol(s), path=_scope_path) for s in symbol]}\n'
    "            return _op_node(**_parse_symbol(symbol), path=_scope_path)\n"
    "        except Exception:  # noqa: BLE001 -- symbol unresolved -> read the file(s) instead\n"
    "            symbol = None\n"
)
if "symbol unresolved -> read the file" in t:
    print("already has fallback")
elif old in t:
    open(MCP, "w", encoding="utf-8").write(t.replace(old, new, 1))
    print("added fallback: symbol-not-found -> read the file(s)")
else:
    print("ANCHOR NOT FOUND")
    raise SystemExit
