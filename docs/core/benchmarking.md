# Core Benchmarking

Atelier benchmarks runtime efficiency against baseline host behavior.

## CLI

- `atelier benchmark-core`
- `atelier benchmark-runtime`
- `atelier benchmark-host`

## Runtime metrics

- total tool calls
- avoided tool calls
- token savings
- retries prevented
- loops prevented
- successful rescues
- validation catches
- context reduction
- task success rate

## Notes

`benchmark-runtime` emits capability-focused efficiency metrics.
`benchmark-core` runs prompt/task benchmark rounds.
`benchmark-host` verifies host integration health.
