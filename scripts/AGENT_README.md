# atelier/scripts

Host install and verification entrypoints for Atelier integrations.

- `install_agent_clis.sh` dispatches host installs for Claude, Codex, opencode, Copilot, and Gemini. By default installers write user/global config; pass `--workspace DIR` for project-local artifacts.
- `verify_agent_clis.sh` runs host verifiers and summarizes pass/skip/fail.
- Codex flows:
  `install_codex.sh` installs global `~/.codex/*` by default, or workspace `.codex/*`, root `AGENTS.md`, `bin/atelier-codex`, and `.codex/tasks/*.md` with `--workspace DIR`. Verification is embedded in the install script.
- Copilot flows:
  `install_copilot.sh` merges VS Code user MCP/tasks by default, or workspace `.vscode/mcp.json`, `.github/copilot-instructions.md`, chat mode, and tasks with `--workspace DIR`. Verification is embedded in the install script.
- Claude canonical scripts: `install_claude.sh` installs the plugin and uses Claude user MCP scope by default; with `--workspace DIR` it writes project `.mcp.json`.
- `verify_atelier_*` scripts validate local runtime/MCP/service/Postgres surfaces.
- `phase_t_hardening.sh` runs the T1-T6 hardening suite and writes reports to `.atelier/reports/phase_t/`.

Repo-level install matrix and usage patterns: `atelier/AGENT_README.md`.
