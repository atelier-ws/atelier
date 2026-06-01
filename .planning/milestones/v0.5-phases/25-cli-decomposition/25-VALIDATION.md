# Phase 25: CLI Decomposition Validation

## Contract

Phase 25 is a pure move/extract refactor. It passes only if `src/atelier/gateway/cli/app.py`
becomes a thin Click root/registration surface, command groups live under
`src/atelier/gateway/cli/commands/`, non-CLI business/process logic is relocated to
core/infra/integration modules, and the CLI command/help surface remains equivalent to the
current dirty working-tree baseline unless a difference is explicitly documented.

## Requirement Gates

| Requirement | Gate |
| --- | --- |
| QBL-CLI-01 | `app.py` contains root `cli`, `main()`, dev/MCP registration scaffolding, telemetry wrapper glue, and command registration only; no direct `subprocess` or `sqlite3` imports/usages remain. Target LOC is under ~500 unless a documented residual registration helper forces a small overage. |
| QBL-CLI-02 | Migrated command groups are implemented in `gateway/cli/commands/` modules and registered via `add_command` without changing command names, option names, defaults, hidden flags, or help strings. |
| QBL-CLI-03 | OpenMemory, stack/servicectl/background/systemd, benchmark, reporting, telemetry, and other non-CLI logic moves to existing or new core/infra/gateway integration services. CLI modules are thin wrappers. |
| QBL-CLI-04 | Recursive CLI help/tree snapshot captured from the current dirty working-tree baseline remains byte-equivalent after each extraction slice, or any difference is recorded as intentional in the relevant summary and verification. |

## Required Automated Checks

Run at the end of every slice unless the plan specifies a narrower equivalent:

```bash
uv run atelier --help
uv run pytest tests/gateway/test_cli_help.py tests/gateway/test_cli_help_tree.py -q
uv run pytest tests/gateway/test_cli.py -q
uv run ruff check src/atelier/gateway/cli src/atelier/gateway/integrations src/atelier/infra src/atelier/core
```

Run at final phase verification:

```bash
uv run pytest tests/gateway/test_cli*.py -q
uv run ruff check src
make lint
make typecheck
make test
```

Known unrelated baseline failures from earlier phases must be recorded, not fixed, unless a
Phase 25 change causes them.

## Dirty Worktree Safety

- Treat the current dirty `src/atelier/gateway/cli/app.py` as the extraction source.
- Before editing any dirty file, record `git diff -- <file>` in the plan summary.
- Stage only Phase 25 hunks; never stage unrelated pre-existing WIP from `app.py` or tests.
- Do not use `git restore`, `git reset --hard`, or destructive cleanup.

## Manual/Structural Checks

- `memory` and `route` MCP-tool-only groups remain absent from top-level CLI help.
- Hidden `stack run`, `servicectl run`, and systemd/background operational commands remain invocable as before.
- Generated OpenMemory env files, compose invocations, and service unit literals are moved verbatim.
- `from atelier.gateway.cli import cli, main` remains stable.
