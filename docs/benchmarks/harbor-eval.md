# Atelier Harbor Eval

Run Atelier on official [Harbor](https://harborframework.com) benchmark datasets
(including terminal-bench-core) for cost-quality comparison.

## Prerequisites

- **Docker** installed and running
- **Harbor**: `pip install harbor` or `uv add harbor --project benchmarks`
- API credentials in environment (see below)

## Quick start

```bash
# Anthropic API key
export ANTHROPIC_API_KEY=sk-ant-...

# Run 5 tasks from terminal-bench-core:
atelier eval harbor --limit 5

# A/B comparison (atelier augmentation on vs off):
atelier eval harbor --agent atelier          --limit 5 --output evals/harbor/on
atelier eval harbor --agent atelier-baseline --limit 5 --output evals/harbor/off

# With Bedrock credentials:
export AWS_BEARER_TOKEN_BEDROCK=...
export AWS_REGION=us-east-1
atelier eval harbor --agent atelier-bedrock --limit 5
```

## Command reference

```
atelier eval harbor [OPTIONS]

Options:
  -d, --dataset TEXT    Harbor dataset (default: terminal-bench/terminal-bench-core@0.1.1)
  --limit INTEGER       Max tasks to run (default: 5)
  --agent TEXT          Agent arm: atelier | atelier-baseline | atelier-bedrock
  --model TEXT          Model to use inside container
  --parallel INTEGER    Parallel trials (default: 1)
  --output TEXT         Output directory for results
```

## Agent arms

| Arm | Description |
|-----|-------------|
| `atelier` | Full Atelier augmentation (routing, memory, MCP) |
| `atelier-baseline` | `ATELIER_BENCH_MODE=off` — baseline without Atelier |
| `atelier-bedrock` | Atelier via AWS Bedrock |

The two-arm comparison proves Atelier's value-add over a clean baseline.

## Custom Harbor agent

The adapter is at `benchmarks/harbor/atelier_agent.py`. Run it directly:

```bash
harbor run -d "terminal-bench/terminal-bench-core@0.1.1" \
    --agent-import-path benchmarks.harbor.atelier_agent:AtelierHarborAgent \
    --limit 5
```

## Relationship to mini eval

| Command | Purpose |
|---------|---------|
| `atelier eval mini --dry-run` | Offline schema validation, no Docker needed |
| `atelier eval mini --limit 5` | Live local repo tasks, cheap, no Docker |
| `atelier eval harbor --limit 5` | Official Harbor datasets in Docker containers |
| `make proof-cost-quality` | Deterministic proof gate (zero live calls) |

Start with `atelier eval mini --dry-run` to verify setup, then escalate to
`atelier eval harbor` for credible published results.

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `ANTHROPIC_API_KEY` | For `atelier` arm | Anthropic API key |
| `AWS_BEARER_TOKEN_BEDROCK` | For `atelier-bedrock` arm | Bedrock bearer token |
| `AWS_REGION` | For `atelier-bedrock` arm | AWS region |
| `ATELIER_BENCH_VERSION` | No | Atelier version to install (default: latest) |
| `ATELIER_BENCH_MODEL` | No | Default model (default: claude-sonnet-4-5) |
