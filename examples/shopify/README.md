# Shopify Domain Example

## Install

```bash
cd atelier
uv sync --all-extras
atelier init
```

## Config

Use the Shopify publish reasonblocks, rubrics, and traces under the `Agent.shopify.publish` domain.

## Commands

```bash
atelier context --task "Publish Shopify product" --domain Agent.shopify.publish
atelier check-plan --task "Publish Shopify product" --domain Agent.shopify.publish --step "Parse product handle from PDP URL"
```

## Benchmark

```bash
atelier benchmark run --prompt "Publish Shopify product safely" --json
```

## Troubleshooting

- If Atelier does not block handle-based workflows, inspect whether the publish rubric pack is installed.
- Use trace recording after every failed publish flow so rescue procedures can stabilize.
