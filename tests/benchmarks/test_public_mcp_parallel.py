from __future__ import annotations

import importlib
import sys
import types
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _ensure_benchmarks_package() -> None:
    benchmarks_pkg = types.ModuleType("benchmarks")
    benchmarks_pkg.__path__ = [str(ROOT / "benchmarks")]
    mcp_pkg = types.ModuleType("benchmarks.mcp_tools")
    mcp_pkg.__path__ = [str(ROOT / "benchmarks" / "mcp_tools")]
    sys.modules["benchmarks"] = benchmarks_pkg
    sys.modules["benchmarks.mcp_tools"] = mcp_pkg


def _load(module_name: str) -> ModuleType:
    _ensure_benchmarks_package()
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


EXPORTER = _load("benchmarks.mcp_tools.export_public_mcp_csv")


def test_plan_suite_shards_covers_each_suite_once() -> None:
    shards = EXPORTER._plan_suite_shards(None, jobs=3)

    flattened = [name for shard in shards for name in shard]
    expected = [name for name, _size, _runner in EXPORTER._suite_specs()]

    assert sorted(flattened) == sorted(expected)
    assert len(flattened) == len(set(flattened))


def test_plan_suite_shards_rejects_unknown_suite() -> None:
    with pytest.raises(ValueError, match="Unknown MCP suite"):
        EXPORTER._plan_suite_shards(["unknown-suite"], jobs=2)


def test_select_suite_specs_expands_code_alias() -> None:
    specs = EXPORTER._select_suite_specs(["code"])
    names = [name for name, _size, _runner in specs]

    assert "symbols" in names
    assert "node" in names
    assert "callers" in names
    assert "code" not in names


def test_summarize_rows_adds_total_row() -> None:
    summary = EXPORTER._summarize_rows(
        [
            {
                "tool": "search",
                "passed": True,
                "baseline_tokens": 100,
                "tokens_saved": 25,
                "effective_tokens": 75,
                "savings_pct": 25.0,
            },
            {
                "tool": "search",
                "passed": False,
                "baseline_tokens": 120,
                "tokens_saved": 20,
                "effective_tokens": 100,
                "savings_pct": 16.67,
            },
        ]
    )

    assert summary[0]["tool"] == "search"
    assert summary[0]["cases"] == 2
    assert summary[-1]["tool"] == "TOTAL"
    assert summary[-1]["passed"] == 1


def test_repo_workspace_root_uses_cached_snapshot(monkeypatch, tmp_path: Path) -> None:
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    snapshot_root = tmp_path / "snapshot"
    calls: list[tuple[Path, Path, str, str]] = []

    monkeypatch.setattr(EXPORTER, "_REPO_SNAPSHOT_ROOT", None)
    monkeypatch.setattr(EXPORTER, "_repo_root", lambda: repo_root)
    monkeypatch.setattr(EXPORTER, "default_benchmark_root", lambda root: root.parent / "benchmarks")
    monkeypatch.setattr(EXPORTER, "repo_cache_key", lambda root: "abc123")

    def fake_prepare(repo: Path, cache_root: Path, *, name: str, cache_key: str) -> Path:
        calls.append((repo, cache_root, name, cache_key))
        return snapshot_root

    monkeypatch.setattr(EXPORTER, "prepare_cached_repo_snapshot", fake_prepare)

    assert EXPORTER._repo_workspace_root() == snapshot_root
    assert EXPORTER._repo_workspace_root() == snapshot_root
    assert calls == [
        (
            repo_root,
            repo_root.parent / "benchmarks" / "mcp-cache" / "snapshots",
            "public-mcp-repo",
            "abc123",
        )
    ]
