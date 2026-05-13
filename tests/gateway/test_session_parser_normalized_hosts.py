from __future__ import annotations

import pytest

from atelier.gateway.hosts.session_parsers._common import (
    build_normalized_jsonl,
    make_assistant_message,
    make_session_line,
    make_tool_call,
    make_user_message,
)
from atelier.gateway.hosts.session_parsers._session_parser import parse_session_turns


@pytest.mark.parametrize("host", ["qwen", "kiro", "roo-code", "antigravity", "goose", "cursor-agent"])
def test_parse_session_turns_supports_normalized_import_hosts(host: str) -> None:
    content = build_normalized_jsonl(
        [
            make_session_line("sess-1", timestamp="2026-05-11T00:00:00Z", title="demo"),
            make_user_message("build a parser", timestamp="2026-05-11T00:00:01Z"),
            make_assistant_message(
                model="gpt-5",
                input_tokens=120,
                output_tokens=40,
                thinking_tokens=10,
                texts=["Running command"],
                thinking_texts=["Need to inspect the schema first."],
                tool_calls=[
                    make_tool_call("bash", {"command": "pytest -q"}),
                    make_tool_call("edit", {"path": "src/app.py", "content": "patch"}),
                ],
                timestamp="2026-05-11T00:00:02Z",
            ),
        ]
    )

    turns = parse_session_turns(content, host)

    assert [turn["kind"] for turn in turns] == [
        "user_message",
        "agent_message",
        "thinking",
        "shell_command",
        "file_edit",
    ]
    assert turns[3]["content"] == "pytest -q"
    assert turns[4]["summary"].startswith("edit(")
