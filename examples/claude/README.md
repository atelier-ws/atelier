# Claude Code Example

## Install

```bash
cd atelier
uv sync --all-extras
uv run atelier init
```

## Config

Point Claude Code at `uv run atelier-mcp` and set `ATELIER_ROOT=.atelier`.

## Commands

```bash
uv run atelier context --task "Fix Shopify publish" --domain Agent.shopify.publish
uv run atelier check-plan --task "Fix Shopify publish" --domain Agent.shopify.publish --step "Parse product handle from PDP URL"
```

## Benchmark

```bash
uv run atelier benchmark run --prompt "Fix Shopify publish" --json
```

## Troubleshooting

- If the server is not visible, verify the MCP command uses `uv run atelier-mcp` from the repo root.
- If plans never block, confirm your store was seeded with `uv run atelier init`.
