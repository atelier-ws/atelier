# SWE-agent Example

## Install

```bash
cd atelier
uv sync --all-extras
uv run atelier init
```

## Config

```python
from atelier.gateway.adapters.sweagent_adapter import SWEAgentAdapter

adapter = SWEAgentAdapter(root=".atelier", mode="shadow")
```

## Commands

```python
report = adapter.benchmark_report()
clusters = adapter.failure_clusters()
```

## Benchmark

```bash
uv run atelier benchmark compare --input .atelier/benchmarks/runtime/latest.json --input other.json
```

## Troubleshooting

- Use benchmark JSON outputs for cross-run comparison.
- Keep the adapter in `shadow` mode until you trust the pack/rubric set.
