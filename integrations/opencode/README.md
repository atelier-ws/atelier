# opencode Integration

Support level: **MCP config** — MCP server registration in `opencode.jsonc`.

## What gets installed

| Component  | Location after install                    | Description                             |
| ---------- | ----------------------------------------- | --------------------------------------- |
| MCP server | Merged into `opencode.jsonc` in workspace | Wired to `scripts/atelier_mcp_stdio.sh` |

opencode reads `opencode.jsonc` from the workspace root. The installer merges the atelier MCP entry.

`smart_read`, `smart_search`, and `cached_grep` are default-on when the Atelier
agent profile is installed. They augment repeated reads/searches but do not
replace opencode-native file reads, shell search, `rg`, or `grep`. Set
`ATELIER_CACHE_DISABLED=1` to bypass Atelier caching.

## Install

```bash
make install
```

## Verify

```bash
make verify
```

## Source

Config source: `atelier/opencode/`
Full guide: `docs/hosts/opencode-install.md`
