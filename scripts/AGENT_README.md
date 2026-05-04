# atelier/scripts

Host install and verification entrypoints for Atelier integrations.

- `install_agent_clis.sh` dispatches host installs for Claude, Codex, opencode, Copilot, and Gemini.
- `verify_agent_clis.sh` runs host verifiers and summarizes pass/skip/fail.
- Codex flows:
  `install_codex.sh` installs `.codex/*`, `AGENTS.atelier.md`, `bin/atelier-codex`, and `.codex/tasks/*.md`. Verification is embedded in the install script.
- Copilot flows:
  `install_copilot.sh` merges `.vscode/mcp.json`, appends `.github/copilot-instructions.md`, installs chat mode, and merges `.vscode/tasks.json` presets. Verification is embedded in the install script.
- Claude canonical scripts: `install_claude.sh` (with embedded verification) and `verify_claude.sh`.
- `verify_atelier_*` scripts validate local runtime/MCP/service/Postgres surfaces.
- `phase_t_hardening.sh` runs the T1-T6 hardening suite and writes reports to `.atelier/reports/phase_t/`.

Repo-level install matrix and usage patterns: `atelier/AGENT_README.md`.
