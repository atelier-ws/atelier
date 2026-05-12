# Copilot Example

## Install

```bash
cd atelier
uv sync --all-extras
atelier init
```

## Config

Add an MCP server entry pointing to `atelier-mcp` with `ATELIER_ROOT=.atelier`.

## Commands

```bash
atelier task "Audit Shopify publish flow" --domain Agent.shopify.publish
atelier run-rubric rubric_shopify_publish < checks.json
```

## Benchmark

```bash
atelier benchmark report --input .atelier/benchmarks/runtime/latest.json
```

## Troubleshooting

- If Copilot shows tool errors, restart the MCP connection after changing env vars.
- If rubric runs fail, confirm the rubric exists with `atelier rubric list`.
