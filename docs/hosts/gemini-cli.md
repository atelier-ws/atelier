# Gemini CLI Integration

Atelier integrates with Gemini CLI through MCP wiring plus Atelier command presets. Installs are global by default; pass `--workspace DIR` for project-local files.

## Setup

```bash
cd atelier
uv sync --all-extras
make install
make verify
```

## Installed Artifacts

- Global: `~/.gemini/settings.json`, `~/.gemini/commands/atelier/*.toml`, and `~/.gemini/GEMINI.md`
- Workspace: `<workspace>/.gemini/settings.json`, `<workspace>/.gemini/commands/atelier/*.toml`, and `<workspace>/GEMINI.md` when `--workspace DIR` is used

## Notes

- Gemini requires absolute paths in MCP settings.
- Re-run `make install` if the Atelier repo path changes.

## MCP Tool Names

Canonical MCP names: `reasoning`, `lint`, `route`, `rescue`, `trace`, `verify`, `memory`, `read`, `edit`, `search`, `compact`, `atelier_repo_map`.

CLI-only workflows include `atelier lesson inbox`, `atelier consolidation inbox`, `atelier report`, and `atelier proof show`.
