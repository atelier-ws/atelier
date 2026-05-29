# M4 — Decompose `cli/app.py` god-object

> Risk: High (large surface, many entry points). Highest structural leverage.
> Depends on M3 (print/logging settled in CLI first).

## Problem

`src/atelier/gateway/cli/app.py` is 9,309 LOC / 335 KB with **393** function
defs and ~261 logic constructs (loops, `subprocess`, sqlite). This directly
violates the CLAUDE.md invariant *"Keep entry-point logic thin here"* and the
architecture rule *"New capabilities go in `core/capabilities/`, not in
`mcp_server.py` or `cli.py`."* It contains real business logic — OpenMemory
checkout/env-file generation (`_ensure_openmemory_*`, `_write_openmemory_env_files`),
docker-compose orchestration (`_run_compose`, `_letta_compose_file`), and
telemetry session handling.

## Scope

In:
- Split `app.py` into a `cli/commands/` package, one module per command group
  (e.g. `memory.py`, `openmemory.py`, `stack.py`, `context.py`, `bench.py`,
  `telemetry.py`). `app.py` becomes a thin Click group that imports and
  registers subcommands.
- Relocate non-CLI business logic to `core/` or `infra/` services:
  - OpenMemory checkout/env/compose → an `infra/` or `gateway/integrations/`
    service module (much of `integrations/openmemory.py` already exists — extend
    it rather than duplicate).
  - Telemetry session helpers → reuse existing telemetry module if present.

Out:
- Behavior changes. This is a pure move/extract refactor; CLI surface (command
  names, flags, output) must stay byte-identical.
- Decomposing `mcp_server.py` and `code_context/engine.py` — separate future
  plans; note them but do not start here.

## Strategy (parallel-safe)

Do **one command group per PR/subagent run**. This keeps review tractable and
lets multiple subagents work without colliding. Suggested order (lowest
coupling first):

1. `openmemory.py` + extract its infra logic (largest, most self-contained).
2. `stack.py` (compose/services).
3. `memory.py`, `context.py`, `bench.py`, `telemetry.py`.
4. Final pass: confirm `app.py` is registration-only.

## Files

- `src/atelier/gateway/cli/app.py` (source)
- `src/atelier/gateway/cli/commands/` (new package)
- `src/atelier/gateway/integrations/openmemory.py` (existing — extend)
- Relevant `core/`/`infra/` service targets for extracted logic

## Steps (per command group)

1. Identify the group's functions in `app.py` (use
   `mcp__atelier__grep`/`symbols`).
2. Check callers/usages before moving anything:
   `mcp__atelier__usages` / `mcp__atelier__impact` on each function.
3. Move command definitions to `cli/commands/<group>.py`; register them on the
   group in `app.py`.
4. Extract pure business logic to the appropriate `core`/`infra` module; the
   command becomes a thin wrapper that calls it.
5. Update imports; delete the now-dead code from `app.py`.
6. Run validation; repeat for next group.

## Validation

```bash
make lint && make typecheck && make test
uv run atelier --help            # full command tree intact
uv run atelier <group> --help    # each migrated group resolves
```
Diff the `--help` output (full command tree) before vs after — it must be
identical. Add a test that snapshots the top-level command list if none exists.

## Done when

- `app.py` contains only Click group wiring + subcommand registration (target
  < ~500 LOC, zero `subprocess`/sqlite/business logic).
- Each command group lives in its own `cli/commands/` module.
- Extracted business logic lives in `core`/`infra`; CLI surface unchanged.
