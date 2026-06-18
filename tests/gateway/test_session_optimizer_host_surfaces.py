from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]

HOST_CONFIGS = ["claude", "codex", "copilot", "antigravity", "opencode"]


def test_all_host_configs_include_session_optimization_template() -> None:
    for host in HOST_CONFIGS:
        path = ROOT / f"src/atelier/gateway/hosts/configs/{host}.yaml"
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        templates = {item["name"]: item["template"] for item in data["prompt_templates"]}

        assert "session-optimization" in templates
        assert "smallest viable plan" in templates["session-optimization"]
        assert "do not retry a third time" in templates["session-optimization"]
