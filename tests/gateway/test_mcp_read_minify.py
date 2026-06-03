from __future__ import annotations

from pathlib import Path

import pytest

from atelier.gateway.adapters.mcp_server import tool_smart_read


def test_default_reader_read_minifies_safe_language(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
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
    assert payload["minification_delta"]["saved_tokens"] > 0
    assert payload["minification_delta"]["lang"] == "go"


def test_expand_true_keeps_exact_bytes_and_skips_minification_delta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(tmp_path))
    target = tmp_path / "sample.go"
    source = 'package   main\nfunc   main()   { println("x") }\n'
    target.write_text(source, encoding="utf-8")

    payload = tool_smart_read({"path": str(target), "expand": True, "include_meta": True})

    assert payload["content"] == source
    assert "minification_delta" not in payload


def test_explicit_range_keeps_exact_slice_and_skips_minification_delta(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(tmp_path))
    target = tmp_path / "sample.go"
    source = 'package   main\nfunc   main()   { println("x") }\nreturn\n'
    target.write_text(source, encoding="utf-8")

    payload = tool_smart_read({"path": str(target), "range": "1-2", "include_meta": True})

    assert payload["content"] == 'package   main\nfunc   main()   { println("x") }'
    assert "minification_delta" not in payload


def test_default_reader_read_keeps_unknown_language_conservative(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(tmp_path))
    target = tmp_path / "notes.txt"
    source = "keep    unknown    spacing\n"
    target.write_text(source, encoding="utf-8")

    payload = tool_smart_read({"path": str(target), "include_meta": True})

    assert payload["content"] == source
    assert "minification_delta" not in payload
