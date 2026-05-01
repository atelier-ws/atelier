# atelier/scripts

Shell entrypoints for Atelier install and verification workflows.

- `install_agent_clis.sh` dispatches host installs across Claude, Codex, opencode, Copilot, and Gemini.
- `verify_agent_clis.sh` runs the matching host verification scripts and summarizes pass/skip/fail.
- Claude uses the canonical scripts:
  `install_claude.sh` and `verify_claude.sh`.
- Legacy wrapper scripts remain for older local commands.
- `verify_claude_plugin_dev.sh` validates the local Claude plugin layout without installing it.
- `verify_atelier_*` scripts cover local runtime, MCP stdio, service, Postgres, and opencode checks.
- `phase_t_hardening.sh` runs the Phase T1-T6 hardening suite and emits a timestamped report + JSON summary under `.atelier/reports/phase_t/`.

Read [../AGENT_README.md](/home/pankaj/Projects/leanchain/e-commerce/atelier/AGENT_README.md) for the repo-level install matrix and expected commands.
