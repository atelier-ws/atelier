from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / "integrations" / "claude" / "plugin" / "hooks" / "user_prompt.py"


def test_user_prompt_hook_persists_last_user_prompt(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    atelier_root = tmp_path / ".atelier"
    env = os.environ.copy()
    env.update(
        {
            "ATELIER_ROOT": str(atelier_root),
            "ATELIER_STORE_ROOT": str(atelier_root),
            "CLAUDE_WORKSPACE_ROOT": str(workspace),
        }
    )

    payload = {
        "hook_event_name": "UserPromptSubmit",
        "prompt": "fix the auth flow",
        "transcript_path": str(tmp_path / "transcript.jsonl"),
    }
    subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=True,
        env=env,
    )

    workspace_hash = hashlib.sha256(str(workspace.resolve()).encode("utf-8")).hexdigest()[:12]
    session_state = atelier_root / "workspaces" / workspace_hash / "session_state.json"
    data = json.loads(session_state.read_text(encoding="utf-8"))
    assert data["last_user_prompt"] == "fix the auth flow"
