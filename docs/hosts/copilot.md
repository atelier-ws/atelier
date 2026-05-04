# VS Code Copilot Integration

Atelier integrates with Copilot Chat through workspace MCP config, instruction injection, chat mode, and task presets.

## Setup

```bash
cd atelier
uv sync --all-extras
make install
make verify
```

## Installed Artifacts

- `.vscode/mcp.json`
- `.github/copilot-instructions.md` (Atelier section appended)
- `.github/chatmodes/atelier.chatmode.md`
- `.vscode/tasks.json` (Atelier task presets merged)

## Usage

In Copilot Chat, ask explicitly for Atelier MCP tools when you need plan/context/rubric checks.

Example:

```text
Use atelier_check_plan on this plan before editing files.
```

## MCP Tool Names

Canonical: `check_plan`, `get_reasoning_context`, `rescue_failure`, `run_rubric_gate`, `record_trace`.

Compatibility aliases also exist (`atelier_check_plan`, `atelier_get_reasoning_context`, etc.) for host prompts and older docs.

## Fallback

If MCP is unavailable, use copy-paste context guidance in `docs/copy-paste/copilot-instructions.md`.
