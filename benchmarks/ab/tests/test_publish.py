"""Tests for ab.publish — PUB-01 through PUB-03."""

import json
import tempfile
from pathlib import Path

from ab.publish import _docusaurus_frontmatter, _reproduce_sh, assemble_post

_CONFIG = {
    "run_id": "test-run",
    "suite": "terminalbench",
    "tasks": ["task-a", "task-b"],
    "n_reps": 3,
    "model": ["claude-sonnet-4-5"],
    "modes": ["on", "off"],
    "seed": 42,
    "started_at": "2024-05-28T12:00:00Z",
}

_SUMMARY = {
    "created_at": "2024-05-28T12:30:00Z",
    "cells": {},
}


def _make_run_dir(tmp_path: Path) -> Path:
    run_dir = tmp_path / "test-run"
    run_dir.mkdir()
    (run_dir / "config.json").write_text(json.dumps(_CONFIG))
    (run_dir / "summary.json").write_text(json.dumps(_SUMMARY))
    raw_dir = run_dir / "raw"
    raw_dir.mkdir()
    (raw_dir / "task-a__on__rep1.json").write_text("{}")
    (raw_dir / "task-a__off__rep1.json").write_text("{}")
    plots_dir = run_dir / "plots"
    plots_dir.mkdir()
    (plots_dir / "pass_rate.png").write_bytes(b"\x89PNG")
    (run_dir / "report.md").write_text("# Report\n\nThis is the body.\n")
    return run_dir


def test_reproduce_sh_contains_commit_sha():
    """PUB-02: reproduce.sh contains the exact CLI command + commit SHA."""
    content = _reproduce_sh(_CONFIG, commit_sha="abc1234")
    assert "# Commit: abc1234" in content
    assert "atelier bench run" in content
    assert "--suite terminalbench" in content
    assert "--tasks task-a" in content
    assert "--tasks task-b" in content
    assert "--n 3" in content
    assert "--seed 42" in content


def test_reproduce_sh_is_executable_shell():
    """PUB-02: reproduce.sh starts with shebang and has set -euo pipefail."""
    content = _reproduce_sh(_CONFIG, commit_sha="abc1234")
    assert content.startswith("#!/usr/bin/env bash")
    assert "set -euo pipefail" in content


def test_docusaurus_frontmatter_fields():
    """PUB-03: index.md has valid Docusaurus frontmatter."""
    fm = _docusaurus_frontmatter(_CONFIG, _SUMMARY, "abc1234")
    assert fm.startswith("---")
    assert fm.strip().endswith("---")
    assert 'title: "' in fm
    assert 'date: "2024-05-28"' in fm
    assert 'authors: ["atelier-bench"]' in fm
    assert '"benchmark"' in fm
    assert '"terminalbench"' in fm
    assert "custom_edit_url: null" in fm


def test_assemble_post_creates_all_files():
    """PUB-01: publish creates index.md, plots/, transcripts/, reproduce.sh."""
    with tempfile.TemporaryDirectory() as d:
        run_dir = _make_run_dir(Path(d))
        out_dir = Path(d) / "blog" / "test-post"
        assemble_post(run_dir, out_dir, commit_sha="abc1234")

        assert (out_dir / "index.md").exists()
        assert (out_dir / "reproduce.sh").exists()
        assert (out_dir / "plots").is_dir()
        assert (out_dir / "transcripts").is_dir()


def test_assemble_post_index_has_frontmatter_and_truncate():
    """PUB-03: index.md has frontmatter + <!-- truncate -->."""
    with tempfile.TemporaryDirectory() as d:
        run_dir = _make_run_dir(Path(d))
        out_dir = Path(d) / "blog" / "test-post"
        assemble_post(run_dir, out_dir, commit_sha="abc1234")

        content = (out_dir / "index.md").read_text()
        assert content.startswith("---")
        assert "<!-- truncate -->" in content
        assert "# Report" in content


def test_assemble_post_reproduce_sh_executable():
    """PUB-02: reproduce.sh is chmod +x."""
    with tempfile.TemporaryDirectory() as d:
        run_dir = _make_run_dir(Path(d))
        out_dir = Path(d) / "blog" / "test-post"
        assemble_post(run_dir, out_dir, commit_sha="abc1234")

        sh_path = out_dir / "reproduce.sh"
        assert sh_path.stat().st_mode & 0o111  # executable bit


def test_assemble_post_copies_plots():
    """PUB-01: publish copies plot files."""
    with tempfile.TemporaryDirectory() as d:
        run_dir = _make_run_dir(Path(d))
        out_dir = Path(d) / "blog" / "test-post"
        assemble_post(run_dir, out_dir, commit_sha="abc1234")

        assert (out_dir / "plots" / "pass_rate.png").exists()


def test_assemble_post_missing_config_raises():
    """PUB-01: publish raises FileNotFoundError when config.json missing."""
    with tempfile.TemporaryDirectory() as d:
        empty_dir = Path(d) / "empty"
        empty_dir.mkdir()
        out_dir = Path(d) / "out"
        try:
            assemble_post(empty_dir, out_dir)
            raise AssertionError("should have raised")
        except FileNotFoundError:
            pass
