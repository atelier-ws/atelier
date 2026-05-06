from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from atelier.gateway.adapters.cli import cli


def _invoke(root: Path, *args: str) -> tuple[int, str]:
    runner = CliRunner()
    res = runner.invoke(cli, ["--root", str(root), *args])
    return res.exit_code, res.output


def test_bench_runtime(tmp_path: Path) -> None:
    root = tmp_path / ".atelier"
    code, out = _invoke(root, "init")
    assert code == 0, out

    code, out = _invoke(root, "bench", "runtime", "--json")
    assert code == 0, out
    metrics = json.loads(out)
    assert "total_tool_calls" in metrics


def test_search_smart_blocks(tmp_path: Path) -> None:
    root = tmp_path / ".atelier"
    code, out = _invoke(root, "init")
    assert code == 0, out

    code, out = _invoke(root, "search", "shopify", "--limit", "3")
    assert code == 0, out
    # search returns tab-separated text lines (id\tdomain\ttitle)
    assert len(out.strip()) > 0


def test_read_smart_and_edit_smart(tmp_path: Path) -> None:
    root = tmp_path / ".atelier"
    code, out = _invoke(root, "init")
    assert code == 0, out

    target = tmp_path / "module.py"
    target.write_text("def f():\n    return 1\n", encoding="utf-8")

    code, out = _invoke(root, "read", str(target), "--max-lines", "20")
    assert code == 0, out
    payload = json.loads(out)
    assert payload["language"] == "python"

    edit_file = tmp_path / "edits.json"
    edit_file.write_text(
        json.dumps([{"path": str(target), "find": "return 1", "replace": "return 2"}]),
        encoding="utf-8",
    )

    code, out = _invoke(root, "edit", "--input", str(edit_file))
    assert code == 0, out
    edit_payload = json.loads(out)
    assert edit_payload["applied"] == 1
    assert "return 2" in target.read_text(encoding="utf-8")
