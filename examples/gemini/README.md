# Gemini CLI Example

## Install

```bash
cd atelier
uv sync --all-extras
make install-gemini
```

## Config

Configure Gemini CLI to launch `uv run atelier-mcp` and pass `ATELIER_ROOT=.atelier`.

## Commands

```bash
uv run atelier context --task "Repair failed crawl" --domain Agent.crawl
uv run atelier record-trace --input trace.json
```

## Benchmark

```bash
uv run atelier benchmark export --input .atelier/benchmarks/runtime/latest.json --output benchmark.md --format markdown
```

## Troubleshooting

- If Gemini reads stale data, clear or re-seed `.atelier`.
- If trace ingestion fails, validate the JSON payload shape first.
