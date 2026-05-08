# Codex Integration

Atelier integrates with Codex via a packaged plugin, a local marketplace entry,
an AGENTS identity block, a preflight wrapper, and reusable task templates.
Installs are global by default; pass `--workspace DIR` for project-local files.

## Setup

```bash
cd atelier
uv sync --all-extras
make install
make verify
```

## Installed Artifacts

- Global: `~/.codex/plugins/atelier/`, `~/.agents/plugins/marketplace.json`, `~/.codex/AGENTS.md`, and `~/.local/bin/atelier-codex`
- Workspace: `<workspace>/.codex/plugins/atelier/`, `<workspace>/.agents/plugins/marketplace.json`, `<workspace>/AGENTS.md`, `<workspace>/bin/atelier-codex`, and `.codex/tasks/*.md`

The plugin bundles the shared Atelier skills, including the optional `openai-docs`
skill, plus a packaged `.mcp.json` config that the installer rewrites to a
repo-pinned MCP wrapper.

## Wrapper Flow

```bash
./bin/atelier-codex --task "Fix checkout price mismatch" --domain beseam.shopify.publish
```

The wrapper enforces:

1. `reasoning`
2. `lint`
3. Optional rubric gate via `--rubric`, which maps to `verify`

## MCP Tools

Canonical MCP names:

- `reasoning`, `lint`, `route`, `rescue`, `trace`, `verify`
- `memory`, `search`, `read`, `edit`, `compact`, `atelier_repo_map`

## OpenAI Docs Skill

Use `openai-docs` when the task is specifically about official OpenAI docs,
latest-model selection, GPT-5.5 migration, or prompt rewrites.

Do not assume Atelier itself needs a GPT-5.5 migration just because this skill is
installed. In this repo, active OpenAI usage is limited to optional embeddings and
examples unless you intentionally change an OpenAI-backed surface.

CLI-only workflows include `atelier sql inspect`, `atelier lesson inbox`, `atelier consolidation inbox`, `atelier report`, `atelier proof show`, and `atelier route contract`.

## References

Codex task and reference templates live under `integrations/codex/`.
