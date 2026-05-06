# Codex Integration

Atelier integrates with Codex via MCP config, skill packs, a preflight wrapper, and reusable task templates. Installs are global by default; pass `--workspace DIR` for project-local files.

## Setup

```bash
cd atelier
uv sync --all-extras
make install
make verify
```

## Installed Artifacts

- Global: `~/.codex/skills/atelier/`, `~/.codex/AGENTS.md`, `~/.local/bin/atelier-codex`, and `codex mcp add`
- Workspace: `<workspace>/.codex/skills/atelier/`, `<workspace>/.codex/mcp.json`, `<workspace>/AGENTS.md`, `<workspace>/bin/atelier-codex`, and `.codex/tasks/*.md`

## Wrapper Flow

```bash
./bin/atelier-codex --task "Fix checkout price mismatch" --domain beseam.shopify.publish
```

The wrapper enforces:

1. `context`
2. `check-plan`
3. Optional rubric gate via `--rubric`

## MCP Tools

Canonical MCP names:

- `reasoning`, `lint`, `route`, `rescue`, `trace`, `verify`
- `memory`, `search`, `read`, `edit`, `compact`, `atelier_repo_map`

CLI-only workflows include `atelier sql inspect`, `atelier lesson inbox`, `atelier consolidation inbox`, `atelier report`, `atelier proof show`, and `atelier route contract`.

## References

Codex task and reference templates live under `integrations/codex/`.
