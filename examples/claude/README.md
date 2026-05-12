# Claude Code Example

## Install

```bash
cd atelier
uv sync --all-extras
atelier init
```

## Config

Point Claude Code at `atelier-mcp` and set `ATELIER_ROOT=.atelier`.

## Commands

```bash
atelier context --task "Fix Shopify publish" --domain Agent.shopify.publish
atelier check-plan --task "Fix Shopify publish" --domain Agent.shopify.publish --step "Parse product handle from PDP URL"
```

## Benchmark

```bash
atelier benchmark run --prompt "Fix Shopify publish" --json
```

## Troubleshooting

- If the server is not visible, verify the MCP command uses `atelier-mcp` from the repo root.
- If plans never block, confirm your store was seeded with `atelier init`.
