# Phase 25: CLI Decomposition - Pattern Map

**Mapped:** 2026-05-29
**Files analyzed:** ~10 new/modified (1 source god-object + new `cli/commands/` package + extended infra)
**Analogs found:** 7 / 7 (all patterns sourced from in-repo code)

> This phase is a **pure move/extract refactor** of `src/atelier/gateway/cli/app.py`
> (9,387 LOC, 393 `def`s, ~50 Click groups). The CLI surface — command names,
> flags, help text, output bytes — must stay **identical**. Every pattern below
> is extracted from the existing file so new modules copy conventions exactly.

---

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `src/atelier/gateway/cli/app.py` (shrink to thin group) | route / entrypoint | request-response (CLI dispatch) | itself (lines 1190-1204, 7122-7133) | self |
| `src/atelier/gateway/cli/commands/__init__.py` (new) | route (registration) | event-driven (import-time register) | `_register_swe_benchmark_group` (7122-7133) | exact |
| `src/atelier/gateway/cli/commands/openmemory.py` (new) | command module | request-response + subprocess | `openmemory_group` (4128-4188) | exact |
| `src/atelier/gateway/cli/commands/stack.py` (new) | command module | subprocess / process-control | `stack_group` (4486-4715), `servicectl_group` (7278-7533) | exact |
| `src/atelier/gateway/cli/commands/memory.py` (new) | command module | CRUD | `memory_group_cli` (8700-8910) | exact |
| `src/atelier/gateway/cli/commands/context.py` (new) | command module | transform / read | `context_cmd` (1588-1620) | exact |
| `src/atelier/gateway/cli/commands/bench.py` (new) | command module | batch / subprocess | `benchmark_group` (6315-7133) | exact |
| `src/atelier/gateway/cli/commands/telemetry.py` (new) | command module | CRUD (config toggles) | `telemetry_group` (1697-1804) | exact |
| `src/atelier/gateway/integrations/openmemory.py` (extend) | infra/service | file-I/O + subprocess (git/docker/make) | existing module (1-60) + helpers from app.py (399-526) | role-match |
| `tests/gateway/test_cli_command_tree.py` (new — snapshot) | test | snapshot | `test_cli_help.py`, `test_cli_import_progress.py` | role-match |

---

## Current CLI Entrypoint Structure & Registration Conventions

**Package layout (`src/atelier/gateway/cli/`):**
- `__init__.py` — re-exports `cli, main` from `app` (lines 1-5). Public import surface
  is `from atelier.gateway.cli import cli` / `main`. **Must stay stable** — all 18
  CLI test files import from here.
- `__main__.py` — `python -m atelier.gateway.cli` entry; calls `main()` (lines 1-10).
  Used by `stack_run` subprocess launches.
- `app.py` — the god-object. Everything else.

**Root group definition** (`app.py` lines 1190-1204):
```python
@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(version=atelier_version, prog_name="atelier")
@click.option(
    "--root",
    type=click.Path(path_type=Path),
    default=DEFAULT_ROOT,
    show_default=True,
    help="Atelier runtime data directory.",
)
@click.pass_context
def cli(ctx: click.Context, root: Path) -> None:
    """Atelier - Agent Reasoning Runtime."""
    ctx.ensure_object(dict)
    ctx.obj["root"] = root
```

**Registration conventions in use today (three flavors — preserve all):**
1. Inline decorator on the global `cli` object: `@cli.command("uninstall")`,
   `@cli.group("openmemory")` (the dominant pattern, ~50 groups).
2. Dev-gated decorators `@_dev_command(name)` / `@_dev_group(name)` (lines 1388-1421)
   — register on `cli` but wrap the callback with a runtime `_check_dev_mode` guard,
   and **drop the command entirely at import time** if the name is in
   `MCP_TOOL_ONLY_COMMANDS` / `MCP_TOOL_ONLY_GROUPS` (lines 1384-1385).
3. **External-module registration** (the analog for this whole refactor) —
   `_register_swe_benchmark_group()` (lines 7122-7133): import a Click group from a
   separate module and `parent.add_command(...)`, wrapped in try/except
   `ModuleNotFoundError` for resilient startup.

**`main()` wrapper** (lines 8454-8519) — wraps `cli(...)` with bench-mode bootstrap,
telemetry session begin/finish, and SIGINT/SIGTERM handlers. Do **not** move this; it
stays in `app.py` and remains the package entrypoint.

---

## Pattern Assignments

### `src/atelier/gateway/cli/commands/__init__.py` (registration, event-driven)

**Analog:** `_register_swe_benchmark_group` in `app.py` lines 7122-7133.

**Registration pattern to copy** (lines 7122-7133):
```python
def _register_swe_benchmark_group() -> None:
    try:
        from benchmarks.swe.run_swe_bench import swe as swe_benchmark_group
    except ModuleNotFoundError:
        # Keep CLI startup resilient when benchmark modules are not present
        return
    benchmark_group.add_command(swe_benchmark_group)

_register_swe_benchmark_group()
```

**How to apply:** each new `commands/<group>.py` exports its top-level Click group
object (e.g. `openmemory_group`). `app.py` (or a `register(cli)` function in this
`__init__.py`) imports each and calls `cli.add_command(<group>)`. This reproduces the
existing tree **byte-identically** because `add_command` preserves the group name and
help string. Prefer explicit `cli.add_command(group)` over implicit import side
effects so help-tree ordering and the dev-gating logic stay observable.

---

### `src/atelier/gateway/cli/commands/openmemory.py` (command module, request-response + subprocess)

**Analog:** `openmemory_group` + commands in `app.py` lines 4128-4188.

**Group + command skeleton to copy verbatim** (lines 4128-4148):
```python
@cli.group("openmemory")
def openmemory_group() -> None:
    """Manage the self-hosted OpenMemory sidecar."""


@openmemory_group.command("up")
@click.pass_context
def openmemory_up(ctx: click.Context) -> None:
    """Clone/update OpenMemory and start its local MCP stack."""
    root = ctx.obj["root"]
    missing = [name for name in ("git", "docker", "make") if not shutil.which(name)]
    if missing:
        raise click.ClickException(f"OpenMemory requires: {', '.join(missing)}")
    ...
    _ensure_openmemory_checkout(root)
    _ensure_openmemory_service_env(root)
    _write_openmemory_env_files(root)
    _run_openmemory_make(root, "build")
    _run_openmemory_make(root, "up")
    click.echo(f"OpenMemory started at ...")
```

**Decomposition note:** when extracted, replace the bare `@cli.group(...)` with a
module-local group object (`openmemory_group = click.Group("openmemory", ...)` or keep
`@click.group("openmemory")`), and register it from `__init__.py`. The command bodies
keep `ctx.obj["root"]` access and `click.echo`/`ClickException` exactly as-is.

**Business logic to relocate to infra** (`app.py` lines 399-526 → extend
`integrations/openmemory.py`):
- `_letta_compose_file` / `_run_compose` (399-404) — docker-compose orchestration.
- `_ensure_openmemory_service_env` (457-476), `_ensure_openmemory_checkout` (479-493),
  `_write_openmemory_env_files` (496-515), `_run_openmemory_make` (518-526) — git
  checkout, env-file generation, make/docker invocation.
- Path helpers `_openmemory_*` (421-446).

After extraction the command becomes a thin wrapper: `from atelier.gateway.integrations
import openmemory as om; om.ensure_checkout(root)`.

---

### `src/atelier/gateway/cli/commands/memory.py` (command module, CRUD)

**Analog:** `memory_group_cli` lines 8700-8910 (the `@cli.group("memory")` inspection
group) and the lazy-import registry helper.

**Lazy-import-inside-callback pattern** (lines 8705-8717) — keep heavy imports inside
the function body to protect CLI startup latency:
```python
def _make_memory_registry(cwd: Path | None = None) -> Any:
    from atelier.core.capabilities.cross_vendor_memory import MemoryRegistry
    from atelier.core.capabilities.cross_vendor_memory.claude_adapter import ClaudeAdapter
    ...
    return MemoryRegistry(adapters=[ClaudeAdapter(), CodexAdapter(), GeminiAdapter(cwd=cwd or Path.cwd())])
```

**HAZARD — two groups named "memory":** there are two distinct `memory` groups.
1. `memory_group` registered via `@_dev_group("memory")` (lines 3856-4089) — session
   memory ops (upsert/get/list/archive/recall). Because `"memory"` is in
   `MCP_TOOL_ONLY_GROUPS` (line 1385), `_dev_group` returns a `_DummyGroup` and these
   commands are **never registered on the real CLI** — they are MCP-tool-only.
2. `memory_group_cli` registered via `@cli.group("memory")` (lines 8700-8910) — the
   *real* `atelier memory` group (list/show/share/find/paths).

When splitting, do **not** merge these. Preserve the `_dev_group`/`_DummyGroup`
suppression of #1 or the help tree changes and live MCP behavior breaks. Verify with
`atelier memory --help` before/after.

---

### `src/atelier/gateway/cli/commands/context.py` (command module, transform/read)

**Analog:** `context_cmd` lines 1588-1620 (registered via `@_dev_command("context")`).

**Dev-gated command pattern** (lines 1588-1614):
```python
@_dev_command("context")
@click.option("--task", required=True, help="Task description.")
...
@click.pass_context
def context_cmd(ctx, task, ...):
    """Render the context block to inject into an agent prompt."""
    _check_dev_mode("context")
    from atelier.core.foundation.retriever import TaskContext, retrieve
    ...
```

Note the **belt-and-suspenders** dev gate: `_dev_command` wraps the callback AND the
body calls `_check_dev_mode("context")` again. `"context"` is in
`MCP_TOOL_ONLY_COMMANDS` (line 1384) so `_dev_command` returns `lambda f: f` and the
command is never added to `cli` — it exists only as a callable for the MCP path.
**Preserve this dual behavior on move.**

---

### `src/atelier/gateway/cli/commands/stack.py` (command module, subprocess/process-control)

**Analog:** `stack_group` (4486-4715) and `servicectl_group` (7278-7533).

These contain `subprocess`, sqlite, PID files (`_stack_pid_path` 533-538), and the
**hidden `run` subcommand** `@stack_group.command("run", hidden=True)` (line 4591) and
`@servicectl_group.command("run", hidden=True)` (line 7484). See Hazards for hidden
commands. Process-control helpers like `_signal_process_group` (line 650) and the
`background install` systemd flow (lines 7534+) are the heaviest logic — extract pure
helpers to `infra/`, keep Click wiring thin.

---

### `src/atelier/gateway/cli/commands/telemetry.py` (command module, CRUD config toggles)

**Analog:** `telemetry_group` (1697-1804) with nested `telemetry_lexical_group` subgroup
(1774-1804).

**Nested-subgroup pattern** to copy (group → subgroup → command):
```python
@cli.group("telemetry")
def telemetry_group() -> None: ...

@telemetry_group.group("lexical")
def telemetry_lexical_group() -> None: ...

@telemetry_lexical_group.command("on")
def ...: ...
```
On extraction, the parent `telemetry_group` object owns its `.group()`/`.command()`
children, so moving the whole block to one module keeps the nesting intact.

**Do NOT move** the session telemetry helpers `_begin_cli_telemetry` /
`_finish_cli_telemetry` / `_emit_cli_interrupted` / `_cli_command_name` (lines 165-266).
These belong to `main()` lifecycle, not the `telemetry` command group. Leave them in
`app.py` (or extract to a `cli/_telemetry.py` shared helper if `main()` is split too).

---

### `src/atelier/gateway/integrations/openmemory.py` (infra/service — EXTEND)

**Analog:** existing module header lines 1-60. It is stdlib-only, `from __future__
import annotations`, module-level `logger = logging.getLogger(__name__)`, env-var
helpers (`_default_user_id` 42-52), and a typed error class
`OpenMemoryMCPError(RuntimeError)` (55-56).

**Extend, don't duplicate** (plan §Scope line 26): add the checkout/env/compose
functions extracted from `app.py` (399-526) as public functions here. Match the
existing style: stdlib `subprocess`/`urllib`, `logger` not `print`, env-var reads via
`os.environ.get(...).strip()`. Raise `click.ClickException` only from the CLI wrapper,
not the infra function — infra should raise a domain error and let the command convert.

---

## Shared Patterns

### Output emission
**Source:** `_emit` in `app.py` lines 335-339. **Apply to:** every command that returns
data.
```python
def _emit(data: Any, *, as_json: bool) -> None:
    if as_json:
        click.echo(json.dumps(data, indent=2, ensure_ascii=False, default=str))
    else:
        click.echo(data)
```
Commands accept `--json`/`as_json` and call `_emit(result, as_json=as_json)`. This is
a cross-cutting helper — keep it importable from a shared `cli` module (e.g. leave in
`app.py` and import, or move to `cli/_emit.py`) so every extracted module reuses the
exact same formatting (byte-identical output is a hard requirement).

### Error handling
**Source:** throughout — `raise click.ClickException(...)` for user-facing failures
(e.g. lines 1356, 4140, 4142); subprocess errors wrapped as in `uninstall`
(lines 1369-1371): `except subprocess.CalledProcessError as exc: raise
click.ClickException(...) from exc`. **Apply to:** all extracted command modules.

### Dev-mode gating
**Source:** `_check_dev_mode` (1579-1582), `_dev_command`/`_dev_group` (1388-1421),
`MCP_TOOL_ONLY_COMMANDS`/`MCP_TOOL_ONLY_GROUPS` (1384-1385). **Apply to:** any moved
command currently using `@_dev_command`/`@_dev_group`. These decorators reference the
module-global `cli` object — when commands move to a new module the decorator must
still register on the same `cli` instance, OR switch to defining a local group and
registering via `__init__.py`. Either way preserve the MCP-only suppression sets.

### Lazy heavy imports inside callbacks
**Source:** seen in `reembed` (1431), `context_cmd` (1615), `_make_memory_registry`
(8705-8717), telemetry helpers (188-195). **Apply to:** all extracted modules — keep
`core.*`/`infra.*` imports inside the function body, not at module top, to preserve CLI
startup latency and avoid import cycles when modules register on `cli`.

### Import-progress logging (Phase 24)
**Source:** `_ensure_import_progress_logging` (74-100) + module constants
`_IMPORT_PROGRESS_LOGGER` / `_IMPORT_PROGRESS_HANDLER_FLAG` (70-71). **Apply to:** the
host-import commands (claude/codex/gemini/copilot/opencode `import`, lines 2150-2433).
The handler routes session-parser `logger.info(...)` progress to **stderr**, is
idempotent (refreshes stream rather than adding duplicate handlers), and sets
`propagate = False`. Tests assert progress on stderr and **not** on stdout
(`test_cli_import_progress.py` lines 52-56). If these commands move, the constants and
the `_ensure_import_progress_logging` call must move/import with them and the
idempotency test (`test_import_progress_handler_is_idempotent`, lines 62-75) must still
import the symbols from wherever they land — currently `from atelier.gateway.cli.app
import (_IMPORT_PROGRESS_LOGGER, _ensure_import_progress_logging)`. Keep them re-exported
from `app` or update the test import path in lockstep.

### Testing pattern
**Source:** `CliRunner().invoke(cli, [...])` across all `tests/gateway/test_cli*.py`.
Conventions:
- `from atelier.gateway.cli import cli` (public surface — keep stable).
- `_invoke(root, *args)` helper passing `["--root", str(root), *args]`
  (`test_cli_import_progress.py` 37-39, `test_cli.py` 23-26).
- **`os.environ["ATELIER_DEV_MODE"] = "1"` set BEFORE importing `cli`** so
  `@_dev_command` registration sees dev mode (`test_cli.py` lines 11-18). This is an
  **import-time side effect** — see Hazards.
- Assert `result.exit_code == 0, result.output`; parse JSON via `json.loads(result.output)`.
- stderr/stdout separation checked via `result.stderr` / `result.stdout`.

---

## Hazards

### 1. Dirty WIP in `app.py` (uncommitted)
`git diff` shows **34 insertions / 1 deletion** uncommitted in `app.py` — new helpers
`_subprocess_output` (after line 136) and `_systemd_user_bus_unavailable`, plus a
rewrite of the `background install` `daemon-reload` flow (~lines 7711-7736) to tolerate
an unavailable systemd user bus. `tests/gateway/test_cli.py` also has +39 uncommitted
lines. **Action:** commit or stash this WIP BEFORE starting the move/extract, or carry
it forward intact. A blind line-range cut of the `background`/`systemd` group will drop
or corrupt this in-flight change. Re-diff after the refactor to confirm the WIP
survived byte-for-byte.

### 2. Help-output stability (byte-identical requirement)
Plan §Validation (lines 69-75): diff full `--help` tree before vs after; it **must be
identical**. Risks:
- **Group ordering** in `--help` follows registration/insertion order. `add_command`
  appends — register groups in the *same order* they currently appear, or Click's
  command list reorders and the diff fails.
- **Docstrings = help text.** Each group/command help string comes from the function
  docstring (e.g. `"""Manage the self-hosted OpenMemory sidecar."""`). Copy docstrings
  verbatim.
- `context_settings={"help_option_names": ["-h", "--help"]}` on the root group (line
  1190) and `ignore_unknown_options` on `help` (line 1206) must be preserved.
- The custom `help` command (1206-1231) walks `cli.get_command(...)` over the live tree
  — it keeps working only if subcommands are registered on the same `cli` object.
- **Action:** capture `uv run atelier --help` and `atelier <group> --help` for every
  group into a snapshot BEFORE refactoring. No command-tree snapshot test exists today
  (only `test_cli_help.py` checks 4 substrings) — add `test_cli_command_tree.py` that
  asserts the full top-level command list, as the plan requests (line 75).

### 3. Import side effects & registration timing
- Commands are registered at **module import time** via decorators on the global `cli`.
  If `commands/*.py` modules are not imported, their commands vanish from the tree.
  `app.py` (or `commands/__init__.py`) must import every command module eagerly so the
  tree is fully populated before `cli()` runs.
- `ATELIER_DEV_MODE` must be set before import for `_dev_command` registration
  (`test_cli.py` 11-12). Moving dev commands to a new module means that module's import
  is now the gating point — ensure import order in `app.py`/`__init__.py` does not read
  `is_dev_mode()` earlier than tests/callers expect.
- `_register_swe_benchmark_group()` runs at import (line 7133) and tolerates
  `ModuleNotFoundError`. Replicate this resilience for any optionally-present module.
- Avoid import cycles: command modules importing `cli` from `app`, while `app` imports
  the command modules. Resolve with a `register(cli)` function called at the end of
  `app.py`, or define groups locally and add them — do not have `app` import a module
  that imports `app` at top level.

### 4. Hidden commands
Two `hidden=True` subcommands exist: `@stack_group.command("run", hidden=True)` (4591)
and `@servicectl_group.command("run", hidden=True)` (7484); plus a hidden alias group
`@cli.group("systemd", hidden=True)` (8069). These are invoked by `stack_run` and
service supervisors. They **do not appear in `--help`** so a help-diff will NOT catch
their loss. **Action:** explicitly verify `atelier stack run --help`,
`atelier servicectl run --help`, and `atelier systemd ...` resolve after the move; add a
direct invocation test. Preserve `hidden=True` exactly.

### 5. Duplicate "memory" group name (see memory.py assignment)
`@_dev_group("memory")` (3856) → `_DummyGroup` (never on real CLI) vs.
`@cli.group("memory")` (8700) → the live group. Easy to accidentally merge into one
real `atelier memory` group, which would expose dev-only commands and alter the help
tree. Keep them separate and verify the live `atelier memory --help` is unchanged.

### 6. Shared global state references
Many helpers reference module globals (`cli`, `logger`, `DEFAULT_ROOT`, the
`*_UNIT`/`*_LABEL` constants lines 111-120, `MCP_*` sets). Extracted modules must import
these from a single source of truth, not redefine them, to avoid drift. Prefer keeping
constants/`_emit`/dev-gate helpers in `app.py` (or a `cli/_shared.py`) and importing.

---

## No Analog Found

None. Every target pattern has an in-repo source; this is a refactor of existing code,
so all analogs live inside `app.py` itself or `integrations/openmemory.py`.

---

## Metadata

**Analog search scope:** `src/atelier/gateway/cli/`, `src/atelier/gateway/integrations/`,
`tests/gateway/test_cli*.py`, `CLAUDE.md`, `docs/plans/quality-and-benchmark-lift/`.
**Files scanned:** `app.py` (targeted ranges), `__init__.py`, `__main__.py`,
`integrations/openmemory.py`, 4 test files, plan doc, `git status`/`git diff`.
**Pattern extraction date:** 2026-05-29
