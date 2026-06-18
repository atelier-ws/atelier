from __future__ import annotations

import json
from pathlib import Path

from benchmarks.codebench import multiswe


def _row(
    org: str,
    repo: str,
    number: int,
    *,
    language: str,
    difficulty: str | None,
    n_files: int,
) -> dict:
    fix_patch = "".join(f"diff --git a/f{i}.py b/f{i}.py\n--- a/f{i}.py\n+++ b/f{i}.py\n" for i in range(n_files))
    return {
        "org": org,
        "repo": repo,
        "number": number,
        "title": f"Fix {repo} bug",
        "body": f"Resolves #{number - 1}.",
        "base": {"sha": f"sha-{number}"},
        "resolved_issues": [{"number": number - 1, "title": "It breaks", "body": "Steps to repro."}],
        "fix_patch": fix_patch,
        "test_patch": "diff --git a/t.py b/t.py\n",
        "f2p_tests": {"test_a": {}, "test_b": {}},
        "p2p_tests": {"test_c": {}},
        "instance_id": f"{org}__{repo}-{number}",
        "difficulty": difficulty,
        "language": language,
    }


def _write(tmp_path: Path, rows: list[dict]) -> Path:
    path = tmp_path / "data.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return path


def test_image_ref_lowercases_and_uses_m_separator() -> None:
    assert multiswe.image_ref("BurntSushi", "ripgrep", 1294) == "mswebench/burntsushi_m_ripgrep:pr-1294"


def test_changed_file_count_counts_diff_headers() -> None:
    patch = "diff --git a/x b/x\n...\ndiff --git a/y b/y\n..."
    assert multiswe.changed_file_count(patch) == 2
    assert multiswe.changed_file_count("") == 0


def test_problem_statement_includes_linked_issue_and_excludes_patch() -> None:
    row = _row("o", "r", 10, language="go", difficulty="1h - 4h", n_files=2)
    statement = multiswe.build_problem_statement(row)
    assert "# Fix r bug" in statement
    assert "Steps to repro." in statement
    assert "Issue #9" in statement
    assert "diff --git" not in statement


def test_load_filters_trivial_and_single_file(tmp_path: Path) -> None:
    rows = [
        _row("o", "big", 2, language="go", difficulty="1h - 4h", n_files=3),  # keep
        _row("o", "trivial", 3, language="go", difficulty="≤15mins", n_files=4),  # drop: trivial
        _row("o", "single", 4, language="go", difficulty="1h - 4h", n_files=1),  # drop: single-file
    ]
    insts = multiswe.load_instances(_write(tmp_path, rows))
    assert [i.repo for i in insts] == ["big"]
    inst = insts[0]
    assert inst.image == "mswebench/o_m_big:pr-2"
    assert inst.base_sha == "sha-2"
    assert inst.repo_url == "https://github.com/o/big"
    assert inst.f2p_tests == ("test_a", "test_b")
    assert inst.patch_row("PATCH") == {"org": "o", "repo": "big", "number": 2, "fix_patch": "PATCH"}


def test_load_respects_language_and_per_language_limit(tmp_path: Path) -> None:
    rows = [
        _row("o", "go1", 10, language="go", difficulty="1h - 4h", n_files=2),
        _row("o", "go2", 20, language="go", difficulty="1h - 4h", n_files=2),
        _row("o", "rs1", 30, language="rust", difficulty="1h - 4h", n_files=2),
    ]
    path = _write(tmp_path, rows)
    assert {i.language for i in multiswe.load_instances(path, languages=["go"])} == {"go"}
    limited = multiswe.load_instances(path, per_language_limit=1)
    by_lang = sorted((i.language, i.repo) for i in limited)
    assert by_lang == [("go", "go1"), ("rust", "rs1")]
