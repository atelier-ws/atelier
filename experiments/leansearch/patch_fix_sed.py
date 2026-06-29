"""Fix read_range handler: parse 'file:Lx-Ly' spec and call read with {path, range}."""

MCP = "/home/pankaj/Projects/leanchain/atelier-leansearch/src/atelier/gateway/adapters/mcp_server.py"

old = (
    '        _rr_spec = str(policy.rewrite_payload.get("spec") or "").strip()\n'
    "        if _rr_spec:\n"
    "            try:\n"
    '                _rr = cast(dict[str, Any], TOOLS["read"]["handler"]({"files": [_rr_spec]}))\n'
    '                _rr_out = _rr.get("content") if isinstance(_rr, dict) else str(_rr)\n'
    "            except Exception as _rr_exc:  # noqa: BLE001\n"
    '                _rr_out = f"[read] {_rr_exc}"\n'
    '            return {"stdout": str(_rr_out or ""), "stderr": "", "exit_code": 0, "truncated": False, "lines_omitted": 0, "duration_ms": 0}\n'
)
new = (
    '        _rr_spec = str(policy.rewrite_payload.get("spec") or "").strip()\n'
    '        if _rr_spec and ":" in _rr_spec:\n'
    '            _rr_fp, _, _rr_rng = _rr_spec.rpartition(":")\n'
    "            _rr_target = Path(_rr_fp) if Path(_rr_fp).is_absolute() else (Path(effective_cwd) / _rr_fp).resolve()\n"
    "            try:\n"
    '                _rr = cast(dict[str, Any], TOOLS["read"]["handler"]({"path": str(_rr_target), "range": _rr_rng}))\n'
    '                _rr_out = _rr.get("content") if isinstance(_rr, dict) else str(_rr)\n'
    "            except Exception as _rr_exc:  # noqa: BLE001\n"
    '                _rr_out = f"[read] {_rr_exc}"\n'
    '            return {"stdout": str(_rr_out or ""), "stderr": "", "exit_code": 0, "truncated": False, "lines_omitted": 0, "duration_ms": 0}\n'
)
t = open(MCP, encoding="utf-8").read()
if "_rr_fp, _, _rr_rng" in t:
    print("already fixed")
elif old in t:
    open(MCP, "w", encoding="utf-8").write(t.replace(old, new, 1))
    print("read_range handler fixed")
else:
    print("NOT FOUND")
