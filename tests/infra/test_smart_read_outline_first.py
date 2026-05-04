from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from click.testing import CliRunner

from atelier.gateway.adapters.cli import cli
from atelier.gateway.adapters.mcp_server import _handle


def _seed_store(tmp_path: Path, monkeypatch: Any) -> Path:
    root = tmp_path / ".atelier"
    result = CliRunner().invoke(cli, ["--root", str(root), "init"])
    assert result.exit_code == 0, result.output
    monkeypatch.setenv("ATELIER_ROOT", str(root))
    return root


def _smart_read(args: dict[str, Any]) -> dict[str, Any]:
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {"name": "atelier_smart_read", "arguments": args},
    }
    resp = _handle(req)
    assert resp is not None
    assert "result" in resp, resp
    payload = json.loads(resp["result"]["content"][0]["text"])
    assert isinstance(payload, dict)
    return payload


def test_smart_read_outline_first_for_large_python_file(tmp_path: Path, monkeypatch: Any) -> None:
    _seed_store(tmp_path, monkeypatch)

    target = tmp_path / "large_module.py"
    lines = ["import os", "", "class Demo:", "    def run(self):", "        return 1", ""]
    lines.extend(f"value_{i} = {i}" for i in range(1, 620))
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")

    outline_payload = _smart_read({"file_path": str(target)})
    assert outline_payload["mode"] == "outline"
    assert isinstance(outline_payload.get("outline"), dict)
    assert outline_payload["outline"]["lang"] == "python"
    assert outline_payload["tokens_saved"] > 0

    full_payload = _smart_read({"file_path": str(target), "expand": True})
    assert full_payload["mode"] == "full"
    assert isinstance(full_payload.get("content"), str)
    assert "value_619 = 619" in full_payload["content"]

    range_payload = _smart_read({"file_path": str(target), "range": "42-118"})
    assert range_payload["mode"] == "range"
    content_lines = range_payload["content"].splitlines()
    assert len(content_lines) == 77


def test_smart_read_small_file_defaults_to_full(tmp_path: Path, monkeypatch: Any) -> None:
    _seed_store(tmp_path, monkeypatch)

    target = tmp_path / "small.py"
    target.write_text("def ping():\n    return 'pong'\n", encoding="utf-8")

    payload = _smart_read({"file_path": str(target)})
    assert payload["mode"] == "full"
    assert "def ping()" in payload["content"]
