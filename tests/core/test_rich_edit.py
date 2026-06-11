from __future__ import annotations

import json
from pathlib import Path

from atelier.core.capabilities.source_projection import build_compact_projection
from atelier.core.capabilities.tool_supervision.rich_edit import apply_rich_edits


def test_rich_edit_sequential_same_file_and_line_range(tmp_path: Path) -> None:
    path = tmp_path / "code.py"
    path.write_text("first\nsecond\nthird\n", encoding="utf-8")

    result = apply_rich_edits(
        [
            {"file_path": "code.py#2", "old_string": "second", "new_string": "middle"},
            {"file_path": "code.py", "old_string": "middle", "new_string": "SECOND"},
        ],
        repo_root=tmp_path,
    )

    assert result["failed"] == []
    assert path.read_text(encoding="utf-8") == "first\nSECOND\nthird\n"


def test_rich_edit_multiline_replacement_preserves_terminal_newline(tmp_path: Path) -> None:
    path = tmp_path / "guide.md"
    path.write_text("before\nold one\nold two\nafter\n", encoding="utf-8")

    result = apply_rich_edits(
        [
            {
                "file_path": "guide.md",
                "old_string": "old one\nold two\n",
                "new_string": "new one\nnew two\n",
            }
        ],
        repo_root=tmp_path,
    )

    assert result["failed"] == []
    assert path.read_text(encoding="utf-8") == "before\nnew one\nnew two\nafter\n"


def test_rich_edit_typography_placeholder_fuzzy_and_indent(tmp_path: Path) -> None:
    path = tmp_path / "code.py"
    path.write_text("def f():\n    value = “old”\n    keep = 1\n", encoding="utf-8")

    result = apply_rich_edits(
        [
            {"file_path": "code.py", "old_string": 'value = "old"', "new_string": 'value = "new"'},
            {
                "file_path": "code.py",
                "old_string": "value = ...\n    keep = 1",
                "new_string": "value = 2\nkeep = 3",
            },
        ],
        repo_root=tmp_path,
    )

    assert result["failed"] == []
    assert "    keep = 3" in path.read_text(encoding="utf-8")


def test_rich_edit_atomic_rollback_and_protected_paths(tmp_path: Path) -> None:
    path = tmp_path / "file.txt"
    path.write_text("original\n", encoding="utf-8")
    (tmp_path / ".atelier").mkdir()
    (tmp_path / ".atelier" / "state.txt").write_text("do not touch\n", encoding="utf-8")

    result = apply_rich_edits(
        [
            {"file_path": "file.txt", "old_string": "original", "new_string": "changed"},
            {"file_path": ".atelier/state.txt", "old_string": "do", "new_string": "DO"},
        ],
        repo_root=tmp_path,
        atomic=True,
    )

    assert result["rolled_back"] is True
    assert path.read_text(encoding="utf-8") == "original\n"


def test_rich_edit_notebook_cell_operations_clear_outputs(tmp_path: Path) -> None:
    path = tmp_path / "nb.ipynb"
    path.write_text(
        json.dumps(
            {
                "cells": [
                    {
                        "cell_type": "code",
                        "metadata": {},
                        "source": "print(1)",
                        "outputs": [{"name": "stdout"}],
                        "execution_count": 3,
                    }
                ],
                "metadata": {},
                "nbformat": 4,
                "nbformat_minor": 5,
            }
        ),
        encoding="utf-8",
    )

    result = apply_rich_edits(
        [
            {"file_path": "nb.ipynb#cell=0", "overwrite": True, "new_string": "print(2)"},
            {
                "file_path": "nb.ipynb#cell=0",
                "cell_action": "insert_after",
                "cell_type": "markdown",
                "new_string": "# note",
            },
        ],
        repo_root=tmp_path,
    )

    assert result["failed"] == []
    notebook = json.loads(path.read_text(encoding="utf-8"))
    assert notebook["cells"][0]["source"] == "print(2)"
    assert notebook["cells"][0]["outputs"] == []
    assert notebook["cells"][1]["cell_type"] == "markdown"


def test_rich_edit_peer_level_def_not_indented(tmp_path: Path) -> None:
    path = tmp_path / "code.py"
    path.write_text(
        "def test_foo() -> None:\n    resp = call()\n    assert resp\n",
        encoding="utf-8",
    )

    result = apply_rich_edits(
        [
            {
                "file_path": "code.py",
                "old_string": "def test_foo() -> None:\n    resp = call()\n    assert resp",
                "new_string": (
                    "def test_foo(mp) -> None:\n"
                    "    mp.setenv('X', '1')\n"
                    "    resp = call()\n"
                    "    assert resp\n"
                    "\n"
                    "\n"
                    "def test_bar(mp) -> None:\n"
                    "    mp.delenv('X', raising=False)"
                ),
            }
        ],
        repo_root=tmp_path,
    )

    assert result["failed"] == []
    text = path.read_text(encoding="utf-8")
    # peer-level def must stay at column 0
    assert "\ndef test_bar(mp) -> None:\n" in text
    # body lines must be indented
    assert "    mp.setenv" in text


def test_rich_edit_projection_descriptor_applies_exact_span(tmp_path: Path) -> None:
    path = tmp_path / "code.go"
    source = 'package   main\n\nfunc   main()   {\n    println("hi")\n}\n'
    path.write_text(source, encoding="utf-8")
    projection = build_compact_projection(source, "go", path=str(path), include_mapping=True)

    assert projection.mapping is not None
    projected_start = projection.content.index("println")
    projected_end = projected_start + len("println")

    result = apply_rich_edits(
        [
            {
                "kind": "projection",
                "file_path": str(path),
                "projection_kind": "compact",
                "projection_mapping": projection.mapping.to_dict(),
                "projected_start": projected_start,
                "projected_end": projected_end,
                "new_string": "fmt.Println",
            }
        ],
        repo_root=tmp_path,
    )

    assert result["failed"] == []
    assert "fmt.Println" in path.read_text(encoding="utf-8")


def test_rich_edit_projection_descriptor_rejects_stale_mapping(tmp_path: Path) -> None:
    path = tmp_path / "code.go"
    source = 'package   main\n\nfunc   main()   {\n    println("hi")\n}\n'
    path.write_text(source, encoding="utf-8")
    projection = build_compact_projection(source, "go", path=str(path), include_mapping=True)
    path.write_text(source.replace("println", "panic"), encoding="utf-8")

    assert projection.mapping is not None
    projected_start = projection.content.index("println")
    projected_end = projected_start + len("println")

    result = apply_rich_edits(
        [
            {
                "kind": "projection",
                "file_path": str(path),
                "projection_kind": "compact",
                "projection_mapping": projection.mapping.to_dict(),
                "projected_start": projected_start,
                "projected_end": projected_end,
                "new_string": "fmt.Println",
            }
        ],
        repo_root=tmp_path,
    )

    assert result["rolled_back"] is True
    assert result["failed"][0]["code"] == "stale_projection_mapping"
    assert "re-read" in result["failed"][0]["hint"].lower()
    assert "stale" in result["failed"][0]["error"]
    assert result["failed"][0]["retry_with"] == {
        "tool": "read",
        "path": str(path),
        "expand": True,
        "include_meta": True,
    }


def test_rich_edit_projection_descriptor_supports_exact_cursor_insertion(tmp_path: Path) -> None:
    path = tmp_path / "code.go"
    source = 'package   main\n\nfunc   main()   {\n    println("hi")\n}\n'
    path.write_text(source, encoding="utf-8")
    projection = build_compact_projection(source, "go", path=str(path), include_mapping=True)

    assert projection.mapping is not None
    projected_start = projection.content.index("println")

    result = apply_rich_edits(
        [
            {
                "kind": "projection",
                "file_path": str(path),
                "projection_kind": "compact",
                "projection_mapping": projection.mapping.to_dict(),
                "projected_start": projected_start,
                "projected_end": projected_start,
                "new_string": "log.",
            }
        ],
        repo_root=tmp_path,
    )

    assert result["failed"] == []
    assert "log.println" in path.read_text(encoding="utf-8")


def test_rich_edit_fuzzy_similarity_floor_rejects_bad_match(tmp_path: Path) -> None:
    path = tmp_path / "mod.py"
    original = "def target():\n    return ACTUAL_DISK_VALUE\n"
    path.write_text(original, encoding="utf-8")

    result = apply_rich_edits(
        [
            {
                "file_path": "mod.py",
                "old_string": "def target():\n    return OLD\n",
                "new_string": "def target():\n    return NEW\n",
            }
        ],
        repo_root=tmp_path,
    )

    assert result["failed"], "low-similarity fuzzy match must be rejected"
    assert "not found" in result["failed"][0]["error"]
    assert path.read_text(encoding="utf-8") == original


def test_rich_edit_noop_when_edit_already_applied(tmp_path: Path) -> None:
    path = tmp_path / "mod.py"
    path.write_text("x = 1\n", encoding="utf-8")
    edit = {"file_path": "mod.py", "old_string": "x = 1", "new_string": "x = 2"}

    first = apply_rich_edits([dict(edit)], repo_root=tmp_path)
    assert first["failed"] == []
    assert first["applied"][0]["match_mode"] == "exact"

    second = apply_rich_edits([dict(edit)], repo_root=tmp_path)
    assert second["failed"] == []
    assert second["applied"][0]["match_mode"] == "noop"
    assert second["applied"][0]["already_applied"] is True
    assert path.read_text(encoding="utf-8") == "x = 2\n"


def test_rich_edit_noop_when_formatter_rewrapped_new_string(tmp_path: Path) -> None:
    path = tmp_path / "mod.py"
    formatted = "result = compute(\n    alpha_value,\n    beta_value,\n    gamma_value,\n    delta_value,\n)\n"
    path.write_text(formatted, encoding="utf-8")

    result = apply_rich_edits(
        [
            {
                "file_path": "mod.py",
                "old_string": "result = build(alpha_value, beta_value, gamma_value, delta_value)",
                "new_string": "result = compute(alpha_value, beta_value, gamma_value, delta_value)",
            }
        ],
        repo_root=tmp_path,
    )

    assert result["failed"] == []
    assert result["applied"][0]["match_mode"] == "noop"
    assert result["applied"][0]["already_applied"] is True
    assert path.read_text(encoding="utf-8") == formatted


def test_rich_edit_atomic_failure_reports_already_applied(tmp_path: Path) -> None:
    path_a = tmp_path / "a.py"
    path_a.write_text("x = 2\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def target():\n    return ACTUAL_DISK_VALUE\n", encoding="utf-8")

    result = apply_rich_edits(
        [
            {"file_path": "a.py", "old_string": "x = 1", "new_string": "x = 2"},
            {
                "file_path": "b.py",
                "old_string": "def missing():\n    return OLD\n",
                "new_string": "def missing():\n    return NEW\n",
            },
        ],
        repo_root=tmp_path,
    )

    assert result["rolled_back"] is True
    assert result["failed"]
    assert result["already_applied"] == ["a.py"]
    assert path_a.read_text(encoding="utf-8") == "x = 2\n"


def test_rich_edit_scoped_not_found_reports_already_applied(tmp_path: Path) -> None:
    path = tmp_path / "mod.py"
    content = (
        "import os\n\n\ndef helper():\n    return os.environ\n\n\n"
        "result = compute(\n    alpha_value,\n    beta_value,\n    gamma_value,\n    delta_value,\n)\n"
    )
    path.write_text(content, encoding="utf-8")

    result = apply_rich_edits(
        [
            {
                "file_path": "mod.py#1-2",
                "old_string": "result = build(alpha_value, beta_value, gamma_value, delta_value)",
                "new_string": "result = compute(alpha_value, beta_value, gamma_value, delta_value)",
            }
        ],
        repo_root=tmp_path,
    )

    assert result["failed"]
    assert result["failed"][0]["already_applied"] is True
    assert "do not retry" in result["failed"][0]["hint"]
    assert "retry_with" not in result["failed"][0]
    assert path.read_text(encoding="utf-8") == content


def test_rich_edit_parse_gate_rolls_back_corrupt_python(tmp_path: Path) -> None:
    path = tmp_path / "mod.py"
    original = "value = 1\n"
    path.write_text(original, encoding="utf-8")

    result = apply_rich_edits(
        [{"file_path": "mod.py", "old_string": "value = 1", "new_string": "def broken(:"}],
        repo_root=tmp_path,
    )

    assert result["failed"]
    assert "parse error" in result["failed"][0]["error"]
    assert path.read_text(encoding="utf-8") == original


def test_rich_edit_retry_hint_targets_failing_file(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("alpha = 1\n", encoding="utf-8")
    path_b = tmp_path / "b.py"
    path_b.write_text("def target():\n    return ACTUAL_DISK_VALUE\n", encoding="utf-8")

    result = apply_rich_edits(
        [
            {"file_path": "a.py", "old_string": "alpha = 1", "new_string": "alpha = 2"},
            {
                "file_path": "b.py",
                "old_string": "def target():\n    return OLD\n",
                "new_string": "def target():\n    return NEW\n",
            },
        ],
        repo_root=tmp_path,
    )

    assert result["failed"]
    hint = result["failed"][0].get("retry_with")
    assert hint is not None, "not-found failure must ship a retry_with hint"
    assert hint["path"].startswith("b.py#L1-")
    assert "ACTUAL_DISK_VALUE" in hint["old_string"]


def test_rich_edit_fuzzy_line_snap_preserves_trailing_newline(tmp_path: Path) -> None:
    """Session replay (daemon.py incident): fuzzy window ends at a def signature.

    new_string has no trailing newline; the line-snapped replacement must not
    glue the following body line onto the signature (which parses and would
    slip past the parse gate).
    """
    path = tmp_path / "mod.py"
    original = "# ---- helpers ----\ndef alpha():\n    return 1\n\ndef beta():\n    return 2\n"
    path.write_text(original, encoding="utf-8")

    result = apply_rich_edits(
        [
            {
                "file_path": "mod.py",
                # comment drift (dash count) forces the fuzzy rung
                "old_string": "# --- helpers ---\ndef alpha():\n    return 1\n\ndef beta():",
                "new_string": "# --- helpers ---\ndef alpha():\n    return 99\n\ndef beta():",
            }
        ],
        repo_root=tmp_path,
    )

    assert result["failed"] == []
    assert result["applied"][0]["match_mode"] == "fuzzy"
    text = path.read_text(encoding="utf-8")
    assert "return 99" in text
    assert "def beta():\n    return 2\n" in text, "body must stay on its own line"
    assert "def beta():    return 2" not in text


def test_rich_edit_parse_gate_catches_misindented_insertion(tmp_path: Path) -> None:
    """Session replay (runtime.py incident): constants landing inside a tuple.

    A replacement whose new_string carries wrong indentation must be rolled
    back by the parse gate instead of being written silently.
    """
    path = tmp_path / "mod.py"
    original = 'NAMES = (\n    "read",\n    "search",\n)\n'
    path.write_text(original, encoding="utf-8")

    result = apply_rich_edits(
        [
            {
                "file_path": "mod.py",
                "old_string": '    "search",\n)',
                "new_string": '    "search",\n)\n\n    SAFE = frozenset(NAMES) - {"edit"}',
            }
        ],
        repo_root=tmp_path,
    )

    assert result["failed"]
    assert "parse error" in result["failed"][0]["error"]
    assert path.read_text(encoding="utf-8") == original


def test_rich_edit_ambiguous_normalized_match_fails_with_candidates(tmp_path: Path) -> None:
    path = tmp_path / "mod.py"
    original = "def a():\n    x  = 1\n\ndef b():\n    x =  1\n"
    path.write_text(original, encoding="utf-8")

    result = apply_rich_edits(
        [{"file_path": "mod.py", "old_string": "x   =   1", "new_string": "x = 2"}],
        repo_root=tmp_path,
    )

    assert result["failed"]
    assert "ambiguous" in result["failed"][0]["error"]
    assert path.read_text(encoding="utf-8") == original
