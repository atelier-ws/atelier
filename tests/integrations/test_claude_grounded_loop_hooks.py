from __future__ import annotations

import io
import json

from integrations.claude.plugin.hooks import pre_tool_use, user_prompt


def test_pre_tool_use_risky_edit_gets_grounded_batching_nudge(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(pre_tool_use, "_is_dev_mode", lambda: True)
    monkeypatch.setattr(
        pre_tool_use.sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "tool_name": "Edit",
                    "tool_input": {"file_path": "shopify/catalog/product.py"},
                }
            )
        ),
    )

    assert pre_tool_use.main() == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["decision"] == "ask"
    assert "search" in payload["reason"]
    assert "read" in payload["reason"]
    assert "batch" in payload["reason"]


def test_pre_tool_use_low_risk_edit_stays_soft_and_allows_through(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(pre_tool_use, "_is_dev_mode", lambda: True)
    monkeypatch.setattr(
        pre_tool_use.sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "tool_name": "Edit",
                    "tool_input": {"file_path": "src/runtime.py"},
                }
            )
        ),
    )

    assert pre_tool_use.main() == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == {"decision": "allow"}


def test_user_prompt_hook_emits_grounded_batching_nudge_without_hiding_compact_warning(
    tmp_path,
    monkeypatch,
    capsys,
) -> None:
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text("x" * 600_000, encoding="utf-8")
    monkeypatch.setattr(user_prompt, "_persist_last_user_prompt", lambda prompt: None)
    monkeypatch.setattr(user_prompt, "_active_session_id", lambda: None)
    monkeypatch.setattr(
        user_prompt.sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "prompt": "update auth.py and billing.py to share token parsing",
                    "transcript_path": str(transcript),
                }
            )
        ),
    )

    assert user_prompt.main() == 0

    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
    assert len(lines) == 2
    assert "Context estimated" in lines[0]["content"]
    assert "search" in lines[1]["content"]
    assert "batch" in lines[1]["content"]


def test_user_prompt_hook_skips_grounded_nudge_for_already_grounded_prompt(
    monkeypatch,
    capsys,
) -> None:
    monkeypatch.setattr(user_prompt, "_persist_last_user_prompt", lambda prompt: None)
    monkeypatch.setattr(user_prompt, "_active_session_id", lambda: None)
    monkeypatch.setattr(
        user_prompt.sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "prompt": "search auth.py and read billing.py before editing token parsing",
                }
            )
        ),
    )

    assert user_prompt.main() == 0

    assert capsys.readouterr().out == ""
