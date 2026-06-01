# Phase 24 Validation Plan: Stdout to Logging

## Scope Decision

Phase 24 converts non-CLI runtime/server/background `print()` calls to logging or stderr
diagnostics and keeps benchmark scripts as intentional dev CLIs. Benchmark stdout remains the
report channel and stays T201-ignored; CLI decomposition is deferred to Phase 25.

## Requirement Gates

| Requirement | Validation |
|-------------|------------|
| QBL-LOG-01 | Preserve the fresh 97-call inventory from `24-RESEARCH.md`; executor re-runs T20 with ignores disabled and records final buckets in `24-04-SUMMARY.md`. |
| QBL-LOG-02 | Non-CLI `print()` calls in gateway/session-parser/publisher runtime surfaces are replaced by module logging or explicit stderr diagnostics. |
| QBL-LOG-03 | User-facing CLI and benchmark stdout boundaries are explicit: `cli/app.py` remains T20-clean via Click, benchmarks remain the only T201 findings after ignores are disabled. |
| QBL-LOG-04 | MCP stdio smoke strictly rejects every non-empty stdout line that is not JSON object framing. |

## Focused Commands

```bash
uv run ruff check src --select T20 --config 'lint.per-file-ignores={}'
uv run ruff check src --select T20
uv run ruff check src
uv run pytest tests/gateway/test_mcp_stdio_smoke.py -m "" -q
uv run pytest tests/gateway/test_p0_mcp_surfaces.py tests/gateway/test_mcp_jsonrpc_e2e.py -q
uv run pytest tests/gateway/test_cli*.py -k import -q
```

## Expected Final T20 Shape

With ignores disabled, executable `print()` findings should be limited to intentional benchmark
dev-CLI files under `src/benchmarks/**` and the `atelier-mcp --version` terminal output if it
remains implemented as `print()` with a targeted allowlist. With normal lint configuration,
`uv run ruff check src --select T20` must pass.

## Known Baseline

Broad repository format/typecheck failures from unrelated dirty files are not Phase 24 scope.
Record them during verification, but do not edit unrelated files to make broad gates pass.
