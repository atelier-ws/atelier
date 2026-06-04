from __future__ import annotations

from pathlib import Path

import pytest

from atelier.core.capabilities.source_projection import build_compact_projection
from atelier.gateway.adapters.mcp_server import tool_smart_edit, tool_smart_read


def test_default_reader_read_uses_compact_projection_for_safe_language(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(tmp_path))
    target = tmp_path / "sample.go"
    source = (
        "package   main\n\n"
        'import   "fmt"\n\n'
        "func   main()   {\n"
        '    message := "keep   quoted   spacing"\n'
        "    fmt.Println(   message   )\n"
        "}\n"
    )
    target.write_text(source, encoding="utf-8")

    payload = tool_smart_read({"path": str(target), "include_meta": True})

    assert payload["content"] != source
    assert "fmt.Println( message )" in payload["content"]
    assert payload["projection"]["view"] == "compact"
    assert payload["projection"]["transformed"] is True
    assert payload["projection_delta"]["saved_tokens"] > 0
    assert payload["projection_delta"]["lang"] == "go"
    assert payload["projection_mapping"]["projection_kind"] == "compact"
    assert payload["projection_mapping"]["segments"]


def test_expand_true_keeps_untransformed_text_and_skips_projection_delta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(tmp_path))
    target = tmp_path / "sample.go"
    source = 'package   main\nfunc   main()   { println("x") }\n'
    target.write_text(source, encoding="utf-8")

    payload = tool_smart_read({"path": str(target), "expand": True, "include_meta": True})

    assert payload["content"] == source
    assert payload["projection"]["view"] == "exact"
    assert payload["projection"]["untransformed_text"] is True
    assert payload["projection"]["transformed"] is False
    assert "projection_delta" not in payload


def test_explicit_range_keeps_untransformed_slice_and_skips_projection_delta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(tmp_path))
    target = tmp_path / "sample.go"
    source = 'package   main\nfunc   main()   { println("x") }\nreturn\n'
    target.write_text(source, encoding="utf-8")

    payload = tool_smart_read({"path": str(target), "range": "1-2", "include_meta": True})

    assert payload["content"] == 'package   main\nfunc   main()   { println("x") }'
    assert payload["projection"]["view"] == "range"
    assert payload["projection"]["untransformed_text"] is True
    assert payload["projection"]["body_complete"] is False
    assert "projection_delta" not in payload


def test_default_reader_read_keeps_unknown_language_untransformed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(tmp_path))
    target = tmp_path / "notes.txt"
    source = "keep    unknown    spacing\n"
    target.write_text(source, encoding="utf-8")

    payload = tool_smart_read({"path": str(target), "include_meta": True})

    assert payload["content"] == source
    assert payload["projection"]["view"] == "exact"
    assert payload["projection"]["transformed"] is False
    assert "projection_delta" not in payload


def test_projection_edit_descriptor_round_trips_through_gateway(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(tmp_path))
    target = tmp_path / "sample.go"
    source = 'package   main\n\nfunc   main()   {\n    println("hi")\n}\n'
    target.write_text(source, encoding="utf-8")
    projection = build_compact_projection(source, "go", path=str(target), include_mapping=True)

    assert projection.mapping is not None
    projected_start = projection.content.index("println")
    projected_end = projected_start + len("println")

    payload = tool_smart_edit(
        {
            "edits": [
                {
                    "kind": "projection",
                    "file_path": str(target),
                    "projection_kind": "compact",
                    "projection_mapping": projection.mapping.to_dict(),
                    "projected_start": projected_start,
                    "projected_end": projected_end,
                    "new_string": "fmt.Println",
                }
            ],
            "post_edit_hooks": False,
        }
    )

    assert payload["failed"] == []
    assert "fmt.Println" in target.read_text(encoding="utf-8")


def test_projection_edit_descriptor_supports_multi_span_replacements(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(tmp_path))
    target = tmp_path / "sample.go"
    source = 'package   main\n\nfunc   main()   {\n    println("hi")\n    println("bye")\n}\n'
    target.write_text(source, encoding="utf-8")
    projection = build_compact_projection(source, "go", path=str(target), include_mapping=True)

    assert projection.mapping is not None
    first = projection.content.index("println")
    second = projection.content.index("println", first + 1)

    payload = tool_smart_edit(
        {
            "edits": [
                {
                    "kind": "projection",
                    "file_path": str(target),
                    "projection_kind": "compact",
                    "projection_mapping": projection.mapping.to_dict(),
                    "projected_ranges": [
                        {
                            "projected_start": first,
                            "projected_end": first + len("println"),
                            "new_string": "fmt.Println",
                        },
                        {
                            "projected_start": second,
                            "projected_end": second + len("println"),
                            "new_string": "fmt.Println",
                        },
                    ],
                }
            ],
            "post_edit_hooks": False,
        }
    )

    assert payload["failed"] == []
    assert target.read_text(encoding="utf-8").count("fmt.Println") == 2


def test_projection_edit_descriptor_rejects_overlapping_multi_span_replacements(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(tmp_path))
    target = tmp_path / "sample.go"
    source = 'package   main\n\nfunc   main()   {\n    println("hi")\n}\n'
    target.write_text(source, encoding="utf-8")
    projection = build_compact_projection(source, "go", path=str(target), include_mapping=True)

    assert projection.mapping is not None
    start = projection.content.index("println")

    payload = tool_smart_edit(
        {
            "edits": [
                {
                    "kind": "projection",
                    "file_path": str(target),
                    "projection_kind": "compact",
                    "projection_mapping": projection.mapping.to_dict(),
                    "projected_ranges": [
                        {
                            "projected_start": start,
                            "projected_end": start + 4,
                            "new_string": "fmt.",
                        },
                        {
                            "projected_start": start + 2,
                            "projected_end": start + len("println"),
                            "new_string": "Println",
                        },
                    ],
                }
            ],
            "post_edit_hooks": False,
        }
    )

    assert payload["rolled_back"] is True
    assert payload["failed"][0]["code"] == "overlapping_projected_ranges"
    assert payload["failed"][0]["retry_with"]["tool"] == "read"
    assert "non-overlapping exact spans" in payload["failed"][0]["hint"]


def test_projection_edit_descriptor_requires_span_or_projected_ranges(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(tmp_path))
    target = tmp_path / "sample.go"
    source = 'package   main\n\nfunc   main()   {\n    println("hi")\n}\n'
    target.write_text(source, encoding="utf-8")
    projection = build_compact_projection(source, "go", path=str(target), include_mapping=True)

    assert projection.mapping is not None
    payload = tool_smart_edit(
        {
            "edits": [
                {
                    "kind": "projection",
                    "file_path": str(target),
                    "projection_kind": "compact",
                    "projection_mapping": projection.mapping.to_dict(),
                }
            ],
            "post_edit_hooks": False,
        }
    )

    assert payload["rolled_back"] is True
    assert payload["failed"][0]["code"] == "missing_projection_span"


def test_projection_edit_descriptor_returns_guidance_for_ambiguous_span(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(tmp_path))
    target = tmp_path / "sample.go"
    source = "package   main\n"
    target.write_text(source, encoding="utf-8")
    projection = build_compact_projection(source, "go", path=str(target), include_mapping=True)

    assert projection.mapping is not None
    ambiguous = projection.content.index(" ") + 1

    payload = tool_smart_edit(
        {
            "edits": [
                {
                    "kind": "projection",
                    "file_path": str(target),
                    "projection_kind": "compact",
                    "projection_mapping": projection.mapping.to_dict(),
                    "projected_start": ambiguous,
                    "projected_end": ambiguous,
                    "new_string": "log.",
                }
            ],
            "post_edit_hooks": False,
        }
    )

    assert payload["rolled_back"] is True
    assert payload["failed"][0]["code"] == "ambiguous_projected_range"
    retry_with = payload["failed"][0]["retry_with"]
    assert retry_with["tool"] == "read"
    assert retry_with["path"] == str(target)
    assert retry_with["range"] == "L1-L1"
    assert retry_with["include_meta"] is True
    assert retry_with["selection_context"]["line_range"] == "L1-L1"
    assert "whitespace" in retry_with["selection_context"]["segment_kinds"]
    assert retry_with["selection_context"]["before"] == "package"
    assert retry_with["selection_context"]["after"] == "main"
    assert "range=L1-L1" in payload["failed"][0]["hint"]
