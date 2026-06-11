"""Tests for the OpenCode prompt-time Atelier nudge plugin."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PLUGINS = ROOT / "integrations" / "opencode" / "plugins"


def test_opencode_nudge_helper_emits_multi_file_guidance(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["ATELIER_ROOT"] = str(tmp_path / ".atelier")
    result = subprocess.run(
        [sys.executable, str(PLUGINS / "atelier_nudge.py")],
        input=json.dumps({"session_id": "s1", "prompt": "Update auth.py and billing.py together"}),
        text=True,
        capture_output=True,
        check=True,
        env=env,
    )

    output = json.loads(result.stdout)
    assert "ground multi-file changes" in output["additionalContext"]


def test_opencode_javascript_plugin_mutates_user_text(tmp_path: Path) -> None:
    env = os.environ.copy()
    env["ATELIER_ROOT"] = str(tmp_path / ".atelier")
    script = f"""
import {{ AtelierNudge }} from {json.dumps((PLUGINS / 'atelier-nudge.js').as_uri())}
const hooks = await AtelierNudge()
const output = {{ parts: [{{ type: 'text', text: 'Update auth.py and billing.py together' }}] }}
await hooks['chat.message']({{ sessionID: 's1' }}, output)
console.log(JSON.stringify(output))
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        text=True,
        capture_output=True,
        check=True,
        env=env,
    )

    output = json.loads(result.stdout)
    assert "<atelier-nudge>" in output["parts"][0]["text"]
    assert "ground multi-file changes" in output["parts"][0]["text"]
