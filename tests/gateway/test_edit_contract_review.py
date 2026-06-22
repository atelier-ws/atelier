"""Integration tests: post-edit contract-literal review wired into tool_smart_edit.

When an edit removes a quoted contract literal (config key, wire field, kwarg name),
the edit tool surfaces the remaining occurrences in *other* untouched files so the
agent finishes the rename at every parallel consumer -- the multi-site bug class
where a fix is needed in N code paths but only the handed-to file gets edited.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from atelier.gateway.adapters import mcp_server


def _astgrep_available() -> bool:
    try:
        from atelier.infra.code_intel.astgrep import AstGrepAdapter, AstGrepToolUnavailable

        try:
            AstGrepAdapter(Path(".")).search(pattern='"x"', language="python", limit=1)
        except AstGrepToolUnavailable:
            return False
        return True
    except Exception:  # noqa: BLE001
        return True


_requires_astgrep = pytest.mark.skipif(not _astgrep_available(), reason="ast-grep binary unavailable")

_BASE = "def get_connection_params(d):\n    return {'passwd': d['passwd']}\n"
_CLIENT = "def settings_to_args(d):\n    return ['--password', d['passwd']]\n"


def _setup_workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(tmp_path))
    (tmp_path / "db").mkdir(parents=True, exist_ok=True)
    (tmp_path / "db" / "base.py").write_text(_BASE, encoding="utf-8")
    (tmp_path / "db" / "client.py").write_text(_CLIENT, encoding="utf-8")


@_requires_astgrep
def test_edit_surfaces_parallel_consumer(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_workspace(tmp_path, monkeypatch)
    result = mcp_server.tool_smart_edit(
        {
            "edits": [
                {
                    "file_path": "db/base.py",
                    "old_string": "{'passwd': d['passwd']}",
                    "new_string": "{'password': d['password']}",
                }
            ],
            "post_edit_hooks": False,
        }
    )
    assert not result.get("failed")
    review = result.get("contract_review")
    assert review is not None, result
    assert review["status"] == "review_required"
    residuals = {r["removed"]: r for r in review["remaining_contract_consumers"]}
    assert "passwd" in residuals
    hit_paths = {m["path"] for m in residuals["passwd"]["matches"]}
    assert "db/client.py" in hit_paths  # parallel consumer surfaced
    assert "db/base.py" not in hit_paths  # the edited file is excluded


@_requires_astgrep
def test_off_switch_disables_review(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_workspace(tmp_path, monkeypatch)
    monkeypatch.setenv("ATELIER_CONTRACT_REVIEW", "0")
    result = mcp_server.tool_smart_edit(
        {
            "edits": [
                {
                    "file_path": "db/base.py",
                    "old_string": "{'passwd': d['passwd']}",
                    "new_string": "{'password': d['password']}",
                }
            ],
            "post_edit_hooks": False,
        }
    )
    assert not result.get("failed")
    assert "contract_review" not in result


@_requires_astgrep
def test_no_literal_removed_attaches_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _setup_workspace(tmp_path, monkeypatch)
    # Rename a local variable -- no quoted contract literal is removed.
    result = mcp_server.tool_smart_edit(
        {
            "edits": [
                {
                    "file_path": "db/base.py",
                    "old_string": "def get_connection_params(d):",
                    "new_string": "def get_connection_params(conf):",
                }
            ],
            "post_edit_hooks": False,
        }
    )
    assert not result.get("failed")
    assert "contract_review" not in result
