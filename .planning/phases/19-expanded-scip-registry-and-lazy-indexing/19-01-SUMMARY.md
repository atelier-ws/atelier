# Phase 19 Plan 01 Summary — Expanded SCIP registry discovery

## Completed

- Added bare SCIP fallback binary names for Go, Rust, Java, Ruby, C, and C++ in the canonical language registry.
- Preserved legacy `ATELIER_SCIP_PYTHON_BIN` and `ATELIER_SCIP_TYPESCRIPT_BIN` env-var contracts.
- Added explicit SCIP binary specs for Python, TypeScript, JavaScript, Go, Rust, Java, Ruby, C, and C++.
- Added registry-driven `discover_scip_binaries()` discovery.
- Added tests for env vars, fallback commands, Rust subcommand metadata, env override precedence, and C/C++ shared Clang discovery.

## Validation

- `uv run ruff check src/atelier/infra/code_intel/languages.py src/atelier/infra/code_intel/scip/binaries.py src/atelier/infra/code_intel/scip/indexer.py tests/infra/code_intel/scip`
- `uv run mypy --strict src/atelier/infra/code_intel/languages.py src/atelier/infra/code_intel/scip/binaries.py src/atelier/infra/code_intel/scip/indexer.py`
- `uv run pytest tests/infra/code_intel/scip -q`
