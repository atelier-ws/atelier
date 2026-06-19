from __future__ import annotations

import importlib
import io
import json
from pathlib import Path
from typing import Any, cast

import pytest

from integrations.claude.plugin.hooks import pre_tool_use, user_prompt

PRE_TOOL_USE = cast(Any, pre_tool_use)
USER_PROMPT = cast(Any, user_prompt)


def _session_state_path(root: Path, workspace: Path) -> Path:
    import hashlib

    workspace_hash = hashlib.sha256(str(workspace.resolve()).encode("utf-8")).hexdigest()[:12]
    return root / "workspaces" / workspace_hash / "session_state.json"


def _write_session_state(root: Path, workspace: Path, state: dict[str, object]) -> None:
    path = _session_state_path(root, workspace)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def _set_bench_mode(monkeypatch: pytest.MonkeyPatch, mode: str | None) -> None:
    if mode is None:
        monkeypatch.delenv("ATELIER_BENCH_MODE", raising=False)
    else:
        monkeypatch.setenv("ATELIER_BENCH_MODE", mode)
    bench_mode = importlib.import_module("atelier.bench.mode")
    monkeypatch.setattr(bench_mode, "_mode", None)


def test_pre_tool_use_risky_edit_always_allowed(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        PRE_TOOL_USE.sys,
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
    assert payload == {"decision": "allow"}


def test_pre_tool_use_blocks_benchmark_risky_edit_without_grounding(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / ".atelier"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("ATELIER_ROOT", str(root))
    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(workspace))
    _set_bench_mode(monkeypatch, "on")
    _write_session_state(root, workspace, {"session_id": "bench-session"})
    monkeypatch.setattr(
        PRE_TOOL_USE.sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "session_id": "bench-session",
                    "tool_name": "Edit",
                    "tool_input": {"file_path": "shopify/catalog/product.py"},
                }
            )
        ),
    )

    assert pre_tool_use.main() == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["decision"] == "block"
    assert "ground" in payload["reason"].lower()


def test_pre_tool_use_allows_grounded_benchmark_risky_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / ".atelier"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("ATELIER_ROOT", str(root))
    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(workspace))
    _set_bench_mode(monkeypatch, "on")
    _write_session_state(
        root,
        workspace,
        {
            "session_id": "bench-session",
            "grounding_evidence": [
                {
                    "session_id": "bench-session",
                    "tool": "read",
                    "path": "shopify/catalog/product.py",
                    "recorded_at": "2026-06-03T00:00:00Z",
                }
            ],
        },
    )
    monkeypatch.setattr(
        PRE_TOOL_USE.sys,
        "stdin",
        io.StringIO(
            json.dumps(
                {
                    "session_id": "bench-session",
                    "tool_name": "Edit",
                    "tool_input": {"file_path": "shopify/catalog/product.py"},
                }
            )
        ),
    )

    assert pre_tool_use.main() == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == {"decision": "allow"}


def test_pre_tool_use_allows_benchmark_off_even_for_risky_edit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / ".atelier"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("ATELIER_ROOT", str(root))
    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(workspace))
    _set_bench_mode(monkeypatch, "off")
    monkeypatch.setattr(
        PRE_TOOL_USE.sys,
        "stdin",
        io.StringIO(json.dumps({"tool_name": "Edit", "tool_input": {"file_path": "shopify/catalog/product.py"}})),
    )

    assert pre_tool_use.main() == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == {"decision": "allow"}


def test_user_prompt_hook_emits_compaction_nudge_as_ui_only_system_message(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    # The grounded-batching nudge was intentionally removed (commit b27437c):
    # the compaction nudge is now UI-only advice for the user (systemMessage),
    # never injected into model context, and no separate batching nudge fires.
    # Occupancy is read from the transcript's real ``usage`` numbers, so the
    # fixture carries a usage block above the 100k compaction floor rather than
    # raw bytes.
    transcript = tmp_path / "transcript.jsonl"
    transcript.write_text(
        json.dumps(
            {
                "message": {
                    "model": "claude-sonnet-4-5",
                    "usage": {
                        "input_tokens": 150_000,
                        "cache_read_input_tokens": 0,
                        "cache_creation_input_tokens": 0,
                    },
                }
            }
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(user_prompt, "_persist_last_user_prompt", lambda prompt: None)
    monkeypatch.setattr(user_prompt, "_read_session_state", lambda: {})
    monkeypatch.setattr(user_prompt, "_write_session_state", lambda state: None)
    monkeypatch.setattr(
        USER_PROMPT.sys,
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
    # Exactly one UI-only message: the compaction nudge. No grounded-batching nudge.
    assert len(lines) == 1
    assert "systemMessage" in lines[0]
    assert "content" not in lines[0]
    assert "additionalContext" not in json.dumps(lines[0])
    assert "/compact" in lines[0]["systemMessage"]
    assert "Context is" in lines[0]["systemMessage"]


def test_user_prompt_hook_skips_grounded_nudge_for_already_grounded_prompt(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(user_prompt, "_persist_last_user_prompt", lambda prompt: None)
    monkeypatch.setattr(
        USER_PROMPT.sys,
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


def test_user_prompt_hook_blocks_after_noop_cap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """After _NOOP_CAP consecutive no-op retry prompts the hook returns 2 + blocks."""
    root = tmp_path / ".atelier"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("ATELIER_ROOT", str(root))
    monkeypatch.setenv("ATELIER_STORE_ROOT", str(root))
    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(workspace))

    noop = user_prompt._NOOP_PROMPT
    cap = user_prompt._NOOP_CAP

    # First (cap - 1) calls should pass through.
    for i in range(cap - 1):
        monkeypatch.setattr(USER_PROMPT.sys, "stdin", io.StringIO(json.dumps({"prompt": noop})))
        rc = user_prompt.main()
        assert rc == 0, f"Expected 0 on call {i + 1}, got {rc}"
        capsys.readouterr()  # discard

    # The cap-th call must block.
    monkeypatch.setattr(USER_PROMPT.sys, "stdin", io.StringIO(json.dumps({"prompt": noop})))
    rc = user_prompt.main()
    assert rc == 2
    out = capsys.readouterr().out
    payload = json.loads(out.strip())
    assert payload["decision"] == "block"
    assert "no-op" in payload["reason"].lower() or "stuck" in payload["reason"].lower()


def test_user_prompt_hook_resets_noop_count_on_real_prompt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A real user prompt resets the no-op counter so a later noop streak starts fresh."""
    root = tmp_path / ".atelier"
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("ATELIER_ROOT", str(root))
    monkeypatch.setenv("ATELIER_STORE_ROOT", str(root))
    monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(workspace))

    noop = user_prompt._NOOP_PROMPT
    cap = user_prompt._NOOP_CAP

    # Drive the counter to (cap - 1).
    for _ in range(cap - 1):
        monkeypatch.setattr(USER_PROMPT.sys, "stdin", io.StringIO(json.dumps({"prompt": noop})))
        user_prompt.main()
        capsys.readouterr()

    # Real prompt resets the counter.
    monkeypatch.setattr(USER_PROMPT.sys, "stdin", io.StringIO(json.dumps({"prompt": "fix the auth flow"})))
    rc = user_prompt.main()
    assert rc == 0
    capsys.readouterr()

    # A fresh noop streak must not block until the cap is hit again.
    for i in range(cap - 1):
        monkeypatch.setattr(USER_PROMPT.sys, "stdin", io.StringIO(json.dumps({"prompt": noop})))
        rc = user_prompt.main()
        assert rc == 0, f"Expected 0 on call {i + 1} after reset, got {rc}"
        capsys.readouterr()
