# Phase 25: CLI Decomposition - Research

**Researched:** 2026-05-29
**Domain:** Python CLI architecture (Click), large-module refactor, command-group decomposition
**Confidence:** HIGH (codebase-grounded; all claims verified against the live tree)

## Summary

`src/atelier/gateway/cli/app.py` is a 9,387-LOC / 339 KB god-object that registers
**~75 top-level commands/groups** (39 of them `@cli.group(...)`), defines **~130 private
helper functions**, contains **75 `subprocess` references** and **2 `sqlite3` references**,
and embeds real business logic (OpenMemory checkout/env/compose orchestration, docker-compose
runners, stack/servicectl/background daemon lifecycle, savings dashboards, benchmark runners).
This violates the CLAUDE.md invariant (`gateway/` entry points must stay thin; "New
capabilities go in `core/capabilities/`, not in ... `cli.py`") [VERIFIED: CLAUDE.md:51-55].

The phase is a **pure move/extract refactor** — command names, flags, and `--help` output
must remain byte-identical (QBL-CLI-04). The single highest-leverage structural change is to
turn `app.py` into a thin Click group plus subcommand registration, with each command group
living in `cli/commands/<group>.py` and extracted business logic relocated to `core/`/`infra/`
services. An existing weak help test (`tests/gateway/test_cli_help.py`) and the canonical
import path (`from atelier.gateway.cli import cli`) constrain the registration mechanism.

**Primary recommendation:** Adopt the **"central group + add_command at the bottom of
`app.py`"** registration pattern (each `cli/commands/<group>.py` builds and exports a
`click.Group`; `app.py` imports and `cli.add_command(...)`s them). Sequence one command group
per plan slice, lowest-coupling first (openmemory → stack/servicectl/background →
memory/context/bench/telemetry → savings/benchmark → final thinning pass). Lock the contract
with a **full `--help` command-tree snapshot test** added in Wave 0, before any code moves.

> **Planning resolution:** User direction is to execute the milestone autonomously from the
> existing project plan without additional approval prompts. The planner should lock the
> assumptions below as working decisions: preserve the dirty working tree as the behavioral
> baseline, use bundled lifecycle slices instead of 39 one-group plans, keep CLI-only helpers
> small/shared, move domain/process logic to core/infra/integration modules, and add explicit
> MCP-only suppression regression coverage.

## Project Constraints (from copilot-instructions.md / CLAUDE.md)

These carry the same authority as locked decisions. The planner must not recommend approaches
that contradict them.

- **Keep entry-point logic thin in `gateway/`** [VERIFIED: CLAUDE.md:51]. `cli.py`/`app.py` are
  dispatchers only.
- **New capabilities go in `core/capabilities/`, not in `mcp_server.py` or `cli.py`** — those
  files are dispatchers only [VERIFIED: CLAUDE.md:55]. Extracted business logic must land in
  `core/`/`infra/`, never in a new CLI helper module.
- **Surgical changes** [VERIFIED: CLAUDE.md:102]: "touch only what you must; don't improve
  adjacent code, refactor things that aren't broken, or delete unrelated dead code; match
  existing style; remove only the imports/variables/functions that *your* changes made unused."
  This directly reinforces the "no behavior change" scope of QBL-CLI-02/04.
- **Think before coding; present multiple interpretations; push back when simpler** [VERIFIED:
  CLAUDE.md:98].
- `.github/copilot-instructions.md` defers to `docs/agent-os/taste-invariants.md` as source of
  truth [VERIFIED: .github/copilot-instructions.md:62-66].

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| QBL-CLI-01 | `app.py` becomes a thin Click group + registration surface | "Recommended Project Structure" + "Registration Pattern" sections give the exact mechanism; target < ~500 LOC, zero `subprocess`/sqlite/business logic |
| QBL-CLI-02 | Command groups move into `cli/commands/` modules without changing names, flags, or help output | Full command map (39 groups + standalone commands) + per-slice boundaries; "Don't Hand-Roll" snapshot strategy guards the surface |
| QBL-CLI-03 | OpenMemory/stack/telemetry/other non-CLI logic moves to core/infra/integration services | "Architectural Responsibility Map" + "Business-Logic Clusters → Relocation Targets" table maps each helper cluster to a destination module |
| QBL-CLI-04 | CLI help output before/after is byte-equivalent (or differences documented) | "Help-Output Equivalence Strategy" section: full `--help` tree snapshot test added in Wave 0, asserted after every slice |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Command parsing, flag/arg definition, help text | `gateway/cli` (CLI) | — | Click surface; the ONLY thing that stays in the cli package |
| CLI telemetry session begin/finish/interrupt | `core/service/telemetry` | `gateway/cli` (thin call) | `core/service/telemetry/` already owns emit/config/store; CLI helpers `_begin/_finish/_emit_cli_*` are thin wrappers |
| OpenMemory checkout / env-file gen / compose / make | `gateway/integrations` (new module) or `infra/` | `gateway/cli` (thin) | Self-contained infra orchestration; `integrations/openmemory.py` exists but is an **MCP client**, not lifecycle — needs a sibling module, not extension of the client |
| docker-compose / Letta lifecycle (`_run_compose`, `_letta_compose_file`) | `infra/runtime` or `gateway/integrations` | `gateway/cli` (thin) | Process/compose orchestration is infra, not CLI |
| Stack lifecycle (pidfiles, frontend deps, status payloads) | `infra/runtime` | `gateway/cli` (thin) | Daemon process management; mirrors existing `infra/runtime/*` modules |
| servicectl / background / systemd lifecycle | `infra/runtime` | `gateway/cli` (thin) | OS-level service control belongs in infra |
| Savings/dashboard rendering (`_render_dashboard*`, `_k/_usd/_age`) | `core/capabilities/reporting` | `gateway/cli` (thin) | Reporting capability already exists; formatting helpers are domain logic |
| Benchmark runners (`_run_benchmark_*`) | `infra/benchmarks` / `atelier.bench` | `gateway/cli` (thin) | `infra/benchmarks/` + `atelier.bench` already own benchmark execution |
| zoekt install/index/serve helpers | `infra/code_intel/zoekt` | `gateway/cli` (thin) | `infra/code_intel/zoekt/{binary,indexer,server,client}.py` already exist — reuse |
| code-context CLI (`_code_context_engine`) | `core/capabilities/code_context` | `gateway/cli` (thin) | Engine already lives in capabilities |
| memory CLI helpers (`_make_memory_registry`, redaction) | `core/capabilities/*memory*` | `gateway/cli` (thin) | Domain logic |

## Standard Stack

This is an internal refactor — **no new external packages are installed.** The existing
toolchain is reused as-is.

### Core (already in the project)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `click` | (pinned in `uv.lock`) | CLI framework — groups, commands, options, help, `CliRunner` | Already the CLI's foundation; idiomatic group composition supports decomposition cleanly [VERIFIED: app.py:31, imports] |
| `pytest` + `pytest-xdist` | (pinned) | Test runner; `-n auto --dist=loadfile` | Existing suite invocation in Makefile [VERIFIED: Makefile:88-93] |
| `ruff` | (pinned) | Lint (`make lint`) | [VERIFIED: Makefile:107] |
| `mypy --strict` | (pinned) | Type-checking (`make typecheck`) | [VERIFIED: Makefile:122] |
| `black --check` | (pinned) | Format check | [VERIFIED: Makefile format-check] |

**Installation:** None. No `npm install` / `pip install` step in this phase.

> **Package Legitimacy Audit — N/A.** This phase installs zero external packages. It only
> moves existing first-party code between modules. No slopcheck/registry verification required.

### Click composition primitives to use (no new deps)
- `click.Group` / `@click.group()` — each `cli/commands/<group>.py` exposes one.
- `group.add_command(cmd)` and `cli.add_command(group)` — explicit registration (preferred over
  re-decorating against a shared global `cli` to avoid import-order fragility).
- `CliRunner().invoke(cli, ["--help"])` and `cli.get_help(ctx)` — already used by the existing
  `help` command (`help_cmd`, app.py:1206-1230) and by tests; the basis for the snapshot guard.

## Architecture Patterns

### System Architecture Diagram (target end-state)

```
                       atelier <argv>
                            │
                            ▼
        ┌──────────────────────────────────────────┐
        │  gateway/cli/app.py  (THIN, < ~500 LOC)    │
        │  • @click.group cli (root: --root option)  │
        │  • help_cmd (full-tree help)               │
        │  • _dev_command/_dev_group registration    │
        │    scaffolding + MCP_TOOL_ONLY_* gates     │
        │  • imports command groups, add_command(s)  │
        └──────────────────────────────────────────┘
              │ add_command()    ▲ import (after cli defined)
              ▼                  │
   ┌─────────────────────────────────────────────────────────┐
   │  gateway/cli/commands/                                    │
   │  openmemory.py  stack.py  servicectl.py  background.py    │
   │  memory.py  context.py  bench.py  telemetry.py  ...       │
   │  (each: Click commands = THIN wrappers calling services)  │
   └─────────────────────────────────────────────────────────┘
              │ calls
              ▼
   ┌─────────────────────────────────────────────────────────┐
   │  Business logic (relocated, behavior-identical)           │
   │  core/service/telemetry/   core/capabilities/reporting/   │
   │  core/capabilities/code_context/  infra/runtime/          │
   │  infra/benchmarks/  infra/code_intel/zoekt/               │
   │  gateway/integrations/openmemory_lifecycle.py (new)       │
   └─────────────────────────────────────────────────────────┘
```

A reader traces: `atelier openmemory up` → `app.py` dispatches to the `openmemory` group in
`commands/openmemory.py` → the `up` command (thin) calls the relocated lifecycle service
(checkout/env/compose). No behavior changes anywhere on this path.

### Recommended Project Structure
```
src/atelier/gateway/cli/
├── __init__.py          # unchanged: re-exports `cli`, `main` (canonical import path)
├── __main__.py          # unchanged: python -m entry point
├── app.py               # THIN: root group, help, dev-registration scaffolding, add_command()
└── commands/            # NEW package
    ├── __init__.py
    ├── openmemory.py     # slice 1
    ├── stack.py          # slice 2
    ├── servicectl.py     # slice 2 (sibling lifecycle)
    ├── background.py     # slice 2 (sibling lifecycle)
    ├── memory.py         # slice 3
    ├── telemetry.py      # slice 3
    ├── bench.py          # slice 3
    ├── context.py        # slice 3
    ├── savings.py        # slice 4 (savings/dashboard)
    ├── benchmark.py      # slice 4
    └── ... (remaining groups)
```

Where genuinely shared CLI-only helpers remain (e.g. `_emit`, `_load_store`, `_project_root`,
telemetry-session wrappers), put them in a small `cli/commands/_shared.py` (or keep in `app.py`
if truly registration-adjacent) — **but pure business logic must go to core/infra, not
`_shared.py`** per the CLAUDE.md invariant.

### Pattern 1: Group module exports a Click Group; app.py registers it
**What:** Each `commands/<group>.py` defines its own `@click.group("name")` and attaches
subcommands; `app.py` imports the group object and calls `cli.add_command(group)`.
**When to use:** Standard groups (`openmemory`, `stack`, `memory`, `bench`, `telemetry`, etc.).
**Why preferred over the global-`cli` decorator pattern:** decouples module import order from
registration side-effects, makes each module independently testable, and avoids circular
imports (the command module does not need to import `cli` from `app.py`).

```python
# Source: idiomatic Click composition (verified against existing app.py group usage)
# src/atelier/gateway/cli/commands/openmemory.py
import click

@click.group("openmemory")
def openmemory_group() -> None:
    """Manage the OpenMemory MCP service."""

@openmemory_group.command("up")
@click.pass_context
def up(ctx: click.Context) -> None:
    from atelier.gateway.integrations.openmemory_lifecycle import bring_up  # relocated logic
    bring_up(ctx.obj["root"])
```
```python
# src/atelier/gateway/cli/app.py  (bottom of file, AFTER `cli` is defined)
from atelier.gateway.cli.commands.openmemory import openmemory_group
cli.add_command(openmemory_group)
```

### Pattern 2: Preserve the dev-gating scaffolding
**What:** `_dev_command`/`_dev_group` (app.py:1388-1421) register against the global `cli` and
gate execution via `_check_dev_mode`; `MCP_TOOL_ONLY_COMMANDS`/`MCP_TOOL_ONLY_GROUPS`
(app.py:1384-1385) suppress registration of `memory`/`route`/`context`/etc. as CLI commands
entirely.
**Critical:** `memory` and `route` groups are **MCP-tool-only** — `_dev_group` returns a
`_DummyGroup` for them so they never appear in the CLI tree [VERIFIED: app.py:1384-1385,
1406-1421]. Any relocation MUST preserve this suppression or the `--help` snapshot will change.
**Recommendation:** Keep `_dev_command`/`_dev_group`/`_DummyGroup`/`_check_dev_mode`/the
`MCP_TOOL_ONLY_*` frozensets in `app.py` (they are registration scaffolding, not business
logic). Command modules using dev-gating import these helpers from `app.py` — the one accepted
direction of `app.py`→command coupling. (Note: this is the inverse of Pattern 1's import
direction; resolve by having `app.py` expose the scaffolding and command modules import it, or
move the scaffolding to `cli/commands/_dev.py` to break the cycle.)

### Anti-Patterns to Avoid
- **Re-home business logic into `cli/commands/_shared.py`:** violates CLAUDE.md:55. Shared
  *CLI* helpers are fine; shared *domain* logic goes to core/infra.
- **Changing flag order, help strings, defaults, or group docstrings:** any of these mutates
  `--help` output and breaks QBL-CLI-04.
- **Importing `cli` into every command module (global-decorator pattern):** creates import-order
  fragility and circular imports at this scale. Prefer `add_command`.
- **"While I'm here" cleanups:** explicitly forbidden by CLAUDE.md:102 ("surgical changes").
- **Duplicating `integrations/openmemory.py`:** it is an MCP *client*, not lifecycle. Add a new
  sibling lifecycle module rather than bloating the client.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Verifying help output is unchanged | Manual eyeballing / per-command asserts | A full recursive `--help` command-tree snapshot test | Only a complete tree snapshot catches accidental flag/group drops across 75 commands |
| OpenMemory MCP RPC | New client code | `gateway/integrations/openmemory.py` `OpenMemoryClient` / `get_client()` | Already exists [VERIFIED: openmemory.py:59-199] |
| zoekt binary/index/serve | Reimplemented shell wrappers | `infra/code_intel/zoekt/{binary,indexer,server,client}.py` | Already exist [VERIFIED: dir listing] |
| Telemetry emit/config/store | New telemetry helpers | `core/service/telemetry/{emit,config,local_store,schema}.py` | Already exist [VERIFIED: dir listing] |
| Benchmark execution | New runners | `infra/benchmarks/*` + `atelier.bench.bootstrap` | Already imported by app.py [VERIFIED: app.py:35] |
| Recursive Click tree walk | Custom AST/regex parsing of app.py | `click.Group.list_commands()` + `get_command()` recursion via `CliRunner` | The `help_cmd` already walks the tree this way [VERIFIED: app.py:1206-1230] |

**Key insight:** Most "business logic" in `app.py` has a destination module that *already
exists* — the work is largely *extract-and-delegate*, not *design-from-scratch*. The one
genuinely missing module is OpenMemory **lifecycle** (checkout/env/compose/make), which has no
home yet (the existing `openmemory.py` is the runtime MCP client).

## Runtime State Inventory

This is a refactor (move/extract) phase, so the inventory matters — but the refactor changes
*code layout only*, not stored data, service config, or registrations. Verified explicitly:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | **None affected.** No DB keys, collection names, or user_ids are renamed. SQLite usage in `app.py` (2 refs) reads/writes existing stores via `ContextStore` — moving the calling code does not touch schema or data. | None — verified by `grep -c sqlite3` = 2, both via `ContextStore` paths |
| Live service config | **None affected.** The `openmemory`/`stack`/`servicectl`/`background`/`systemd` commands *generate* config (env files, compose, unit files) at runtime; the generation logic moves but its output must be byte-identical. Systemd/launchd unit names are module-level constants (`CONTROLLER_UNIT`, `STACK_UNIT`, etc., app.py:111-124) that move verbatim. | Move constants verbatim; verify generated env/unit content unchanged (diff a sample) |
| OS-registered state | **None changed at refactor time.** systemd/launchd labels (`com.atelier.*`, `atelier-*.service`) are constants moved verbatim. No re-registration occurs from the refactor itself; users' already-installed units keep working because names are preserved. | None — but verify constants are not renamed during the move |
| Secrets/env vars | **None renamed.** Env var names read by the CLI (`ATELIER_DEV_MODE`, root path env, OpenMemory env-file keys) are string literals moved verbatim. | None — verify no literal changes during extraction |
| Build artifacts / installed packages | The new `cli/commands/` package adds modules under the already-installed `atelier` package. Editable install (`uv`) picks them up without reinstall. No stale egg-info risk because the top-level package name is unchanged. | None — confirm `uv run atelier --help` works post-move (already in Validation) |

**The canonical question — "after every file is updated, what runtime systems still have the
old string cached/stored/registered?":** Nothing. This refactor renames no runtime-visible
identifier; it only relocates Python functions. The risk surface is *behavioral drift in
generated output and the `--help` tree*, not stale runtime state.

## Dirty-Worktree Risk (MUST READ before planning)

- **`src/atelier/gateway/cli/app.py` is already modified in the working tree before Phase 25.**
  `git status --short` reports it as `M` (tracked, modified), with an uncommitted diff of
  **+34/-1 lines** vs HEAD [VERIFIED: `git diff --stat`]. The file also shows unusual
  permissions (`-rw-------`).
- **Do NOT discard or overwrite these uncommitted changes.** The phase must build on the
  current working-tree state of `app.py`, not on the HEAD version. A naive "rewrite app.py from
  scratch" approach would silently drop the in-flight +34 lines.
- **Many other files are dirty too** (`.planning/*`, `AGENTS.md`, `CLAUDE.md`, `README.md`,
  deleted `benchmarks/linear_vs_per_agent/*`, deleted `docs/plans/phase-linear-cache-reuse/*`,
  many `docs/*`). These are unrelated to Phase 25 and **out of scope** — do not touch them.
- **Recommendation for the planner:** The first plan task should (1) capture a baseline `--help`
  snapshot from the *current working tree* (not HEAD), and (2) treat `app.py`'s current content
  as the authoritative source for what to extract. Commit boundaries should be per-slice so the
  in-flight changes and the refactor remain reviewable separately.
- **Pre-flight check the planner should encode:** `git stash list` and confirm no stash is
  expected to be reapplied; verify `uv run atelier --help` succeeds *before* starting (proves
  the dirty `app.py` is importable).

## Out of Scope (do not start here)

- **Behavior changes of any kind.** Pure move/extract; CLI surface byte-identical
  [VERIFIED: M4 spec "Out" section].
- **Decomposing `mcp_server.py`** — separate future plan; note only [VERIFIED: M4 spec].
- **Decomposing `code_context/engine.py`** — separate future plan; note only [VERIFIED: M4 spec].
- **The unrelated dirty files** listed above (`docs/*`, deleted benchmarks, `.planning/*`).
- **Improving/refactoring extracted logic** beyond the mechanical move (CLAUDE.md:102 surgical
  rule). If a helper is ugly, move it ugly.
- **Renaming any command, flag, group, env var, unit name, or label.**
- **Reducing the number of subprocess calls or "fixing" the 2 sqlite usages** — move them as-is.

## Common Pitfalls

### Pitfall 1: Import-order / circular-import breakage
**What goes wrong:** Command modules importing `cli` from `app.py` while `app.py` imports the
command modules → circular import; or registration side-effects not firing because a module
is never imported.
**Why it happens:** The current code registers via module-level `@cli.command`/`@cli.group`
decorators against a global `cli`. Splitting naively preserves that coupling.
**How to avoid:** Use Pattern 1 (`add_command` from `app.py`, command modules export groups,
no `import cli` in command modules). For dev-gated commands that *must* use the scaffolding,
isolate `_dev_command`/`_dev_group`/`_DummyGroup`/`MCP_TOOL_ONLY_*` into `cli/commands/_dev.py`
so both `app.py` and command modules import *downward* from it.
**Warning signs:** `ImportError`/`partially initialized module` at `from atelier.gateway.cli
import cli`; commands missing from `--help`.

### Pitfall 2: Silent `--help` drift
**What goes wrong:** A moved command loses a flag, a group docstring changes, or a dev-gated
command leaks into the CLI tree (or a `MCP_TOOL_ONLY` group stops being suppressed).
**Why it happens:** 75 commands; manual review misses one.
**How to avoid:** Full recursive `--help` snapshot test created in Wave 0 from the *current
working tree*, asserted after every slice. Diff must be empty (or the diff is an explicitly
documented intentional change per QBL-CLI-04).
**Warning signs:** Snapshot diff non-empty; `memory`/`route` appearing in top-level `--help`.

### Pitfall 3: Generated-output drift (env files, compose, unit files)
**What goes wrong:** Extracting `_write_openmemory_env_files` / systemd unit generation subtly
changes whitespace, key order, or path resolution.
**Why it happens:** `_project_root()`/`_openmemory_dir()` path helpers rely on call-site
context; moving them can change resolved paths.
**How to avoid:** Add focused tests that snapshot generated env-file / compose / unit content
before extraction, assert byte-identical after. Move path-root helpers (`_project_root`,
`_repo_root`, `_openmemory_dir`, `_stack_dir`, etc.) as a cohesive unit, not piecemeal.
**Warning signs:** Diff in generated `*.env`, compose file, or `.service`/`.plist` content.

### Pitfall 4: Dev-mode test setup coupling
**What goes wrong:** Tests set `ATELIER_DEV_MODE=1` *before* importing `cli` so dev commands
register [VERIFIED: tests/gateway/test_cli.py:11-19]. If registration moves to lazy/post-import
`add_command`, that ordering assumption can break.
**How to avoid:** Keep dev registration eager at `app.py` import time (call `add_command` at
module bottom, still gated by `MCP_TOOL_ONLY_*` and `is_dev_mode` checks as today). Run the
full `tests/gateway/test_cli*.py` set after each slice.
**Warning signs:** `test_cli.py` reports missing dev commands; `_check_dev_mode` errors.

## Code Examples

### Recursive full-tree help snapshot (the QBL-CLI-04 guard)
```python
# Source: built on existing help_cmd tree-walk (app.py:1206-1230) + Click CliRunner
# tests/gateway/test_cli_help_tree.py  (NEW — Wave 0)
from __future__ import annotations
import os
os.environ["ATELIER_DEV_MODE"] = "1"  # match existing test_cli.py ordering
import click
from click.testing import CliRunner
from atelier.gateway.cli import cli

def _walk(cmd: click.Command, path: list[str], out: list[str]) -> None:
    ctx = click.Context(cmd, info_name=path[-1] if path else cmd.name)
    out.append(f"{' '.join(path)}\n{cmd.get_help(ctx)}")
    if isinstance(cmd, click.Group):
        for name in sorted(cmd.list_commands(ctx)):
            sub = cmd.get_command(ctx, name)
            if sub is not None:
                _walk(sub, [*path, name], out)

def render_help_tree() -> str:
    out: list[str] = []
    _walk(cli, ["atelier"], out)
    return "\n\n=====\n\n".join(out)

def test_full_help_tree_renders_deterministically() -> None:
    assert render_help_tree() == render_help_tree()
```
> Do not commit a fixture generated from the dirty working tree. Later extraction slices should
> capture a temporary pre-edit output from `render_help_tree()` and compare it to a temporary
> post-edit output in the same dirty checkout.

### Per-group resolution smoke (matches M4 Validation)
```python
def test_each_group_resolves() -> None:
    r = CliRunner()
    for group in ("openmemory", "stack", "memory", "bench", "telemetry"):
        res = r.invoke(cli, [group, "--help"], env={"ATELIER_DEV_MODE": "1"})
        assert res.exit_code == 0, (group, res.output)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Single 9.3k-LOC `app.py` with global-`cli` decorators | `cli/commands/` package of group modules + `add_command` registration | This phase | Reviewable per-group; honors thin-entrypoint invariant |
| Business logic inline in CLI | Delegated to existing `core/`/`infra/` services + one new OpenMemory lifecycle module | This phase | Matches `core/capabilities/` placement rule |

**Deprecated/outdated:** Nothing is being deprecated — names and behavior are preserved.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `add_command` (Pattern 1) is preferred over the existing global-`cli` decorator pattern | Architecture Patterns | If the team prefers preserving decorator style, slices change shape (still viable, more import-order risk) |
| A2 | OpenMemory **lifecycle** logic should live in a NEW `gateway/integrations/openmemory_lifecycle.py` rather than extending the MCP-client `openmemory.py` | Responsibility Map / Don't Hand-Roll | If reviewers want it in `infra/`, the destination path changes (logic identical) |
| A3 | Stack/servicectl/background lifecycle belongs in `infra/runtime` | Responsibility Map | Could instead live under `gateway/integrations`; destination only |
| A4 | The `app.py` < ~500 LOC target is the success bar | Summary / QBL-CLI-01 | From M4 spec ("target < ~500 LOC"); treat as a goal, not a hard gate |
| A5 | A full-tree help renderer/invariant test is acceptable to add (none exists today beyond the weak `test_cli_help.py`) | Help Equivalence | Do not commit a dirty-baseline fixture; use live pre/post comparisons during extraction slices |
| A6 | The in-flight dirty change in `app.py` is intentional and must be preserved, not reverted | Dirty-Worktree Risk | Resolved by autonomous directive: preserve dirty working-tree behavior and stage only Phase 25 hunks |

## Open Questions

All open questions are resolved for planning by the autonomous execution directive:

1. **Should the dirty `app.py` (+34/-1 uncommitted lines) be the baseline, or HEAD?**
   - What we know: `app.py` is `M` with uncommitted changes; permissions are `-rw-------`.
   - What's unclear: whether those changes are part of Phase 24 follow-up or stray edits.
   - Resolution: **Preserve the working tree** and baseline the `--help` snapshot from it.
2. **Slice granularity: one PR per group, or grouped lifecycle slices?**
   - M4 says "one command group per PR/subagent run." 39 groups → 39 slices is heavy.
   - Resolution: Bundle related lifecycle groups into tractable sequential slices; keep
     `openmemory` standalone.
3. **Where do shared CLI-only helpers (`_emit`, `_load_store`, `_project_root`) live?**
   - Resolution: `cli/commands/_shared.py` for CLI-only glue; domain logic to core/infra.
4. **Does `route`/`memory` MCP-only suppression need a regression test of its own?**
   - Resolution: Yes — assert these groups are absent from top-level `--help` to lock the
     `_DummyGroup` behavior.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `uv` | `make lint/typecheck/test`, `uv run atelier` | Assume ✓ (project standard) | — | Run pytest/ruff/mypy directly |
| `pytest` (+xdist) | Test suite | ✓ (in `uv.lock`) | — | `pytest` without `-n auto` |
| `ruff`, `mypy`, `black` | lint/typecheck/format gates | ✓ (in `uv.lock`) | — | — |
| `docker` / `docker compose` | `openmemory`/`stack`/`letta` **runtime** commands | Not required for refactor | — | Refactor + help/import tests don't execute compose; runtime is out of scope to exercise |

**Missing dependencies with no fallback:** None — this is a code-layout refactor; the
validation path (lint/typecheck/test/`--help`) needs no external services.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (+ pytest-xdist, `-n auto --dist=loadfile`) |
| Config file | `pyproject.toml` (`[tool.pytest.ini_options]`) + Makefile targets |
| Quick run command | `uv run pytest tests/gateway/test_cli.py tests/gateway/test_cli_help.py -x` |
| Full suite command | `make test` (`uv run pytest -q -ra --durations=0 -n auto --dist=loadfile`) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| QBL-CLI-01 | `app.py` thin: zero subprocess/sqlite/business logic | unit/grep | `! grep -qE 'subprocess|sqlite3' src/atelier/gateway/cli/app.py && wc -l src/atelier/gateway/cli/app.py` | ❌ Wave 0 (add an assertion test) |
| QBL-CLI-02 | Groups resolve from new modules; names/flags unchanged | integration | `uv run pytest tests/gateway/test_cli.py -x` | ✅ extend |
| QBL-CLI-03 | Business logic importable from core/infra targets | unit | `uv run pytest tests/gateway/test_cli_coverage.py -x` | ✅ extend |
| QBL-CLI-04 | Full `--help` tree byte-equivalent | snapshot | `uv run pytest tests/gateway/test_cli_help_tree.py -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/gateway/test_cli.py tests/gateway/test_cli_help_tree.py -x` + `uv run atelier --help` succeeds.
- **Per wave (slice) merge:** `make lint && make typecheck && uv run pytest tests/gateway/ -q`.
- **Phase gate:** `make lint && make typecheck && make test` green; `--help` snapshot diff empty.

### Wave 0 Gaps
- [ ] `tests/gateway/test_cli_help_tree.py` — full recursive `--help` snapshot (covers QBL-CLI-04). **Baseline must be captured from the current dirty working tree.**
- [ ] `tests/gateway/test_cli_thinness.py` — asserts `app.py` has no `subprocess`/`sqlite3` and is under the LOC budget at phase end (covers QBL-CLI-01).
- [ ] Regression assertion that `memory`/`route` are absent from top-level `--help` (locks `_DummyGroup` suppression).
- [ ] No new framework install needed — pytest/CliRunner already present.

## Security Domain

This is an internal CLI refactor with **no behavior change** and **no new external input
surface, network endpoint, auth path, or crypto**. Security posture is preserved by the
byte-identical-behavior constraint.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No auth code introduced or changed |
| V3 Session Management | no | CLI telemetry "sessions" are not security sessions; behavior unchanged |
| V4 Access Control | partial | Dev-mode gating (`_check_dev_mode`, `MCP_TOOL_ONLY_*`) MUST be preserved exactly — a refactor bug could expose dev commands |
| V5 Input Validation | no-change | Click option/arg validation moves verbatim |
| V6 Cryptography | no | None present in moved code |

### Known Threat Patterns for this refactor
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Dev-only command leaks into prod CLI tree | Elevation of Privilege | Preserve `MCP_TOOL_ONLY_*` + `is_dev_mode`/`_check_dev_mode`; add regression test asserting suppressed groups absent from `--help` |
| `subprocess` call argument drift during move (command injection surface) | Tampering | Move subprocess argument construction verbatim; no string-built shell commands introduced; snapshot generated-output tests |

## Sources

### Primary (HIGH confidence)
- Live codebase (verified via grep/view this session): `src/atelier/gateway/cli/app.py`
  (structure, 75 commands, 39 groups, ~130 helpers, 75 subprocess / 2 sqlite refs, dev
  scaffolding at 1374-1421, MCP_TOOL_ONLY at 1384-1385).
- `src/atelier/gateway/integrations/openmemory.py` (MCP client API, lines 38-444).
- `src/atelier/core/service/telemetry/`, `infra/runtime/`, `infra/code_intel/zoekt/`,
  `core/capabilities/` (relocation targets — directory listings).
- `tests/gateway/test_cli.py`, `tests/gateway/test_cli_help.py` (existing test patterns).
- `Makefile` (lint/typecheck/test targets), `pyproject.toml` (ruff per-file-ignores incl.
  `app.py = ["BLE001"]` at line 188).
- `CLAUDE.md` (architecture invariants, lines 51-55, 98, 102).
- `docs/plans/quality-and-benchmark-lift/M4-cli-decomposition.md` (phase spec).
- `.planning/ROADMAP.md` + `.planning/REQUIREMENTS.md` (QBL-CLI-01..04).
- `git status --short` / `git diff --stat` (dirty-worktree state of `app.py`: +34/-1).

### Secondary (MEDIUM confidence)
- Idiomatic Click `add_command` group-composition pattern (training knowledge; consistent with
  the project's existing `@cli.group`/`add_command` usage). [ASSUMED] for "preferred" claim.

### Tertiary (LOW confidence)
- None.

## Metadata

**Confidence breakdown:**
- Command/helper map & boundaries: HIGH — directly enumerated from `app.py`.
- Relocation targets: HIGH for existing modules (telemetry, zoekt, runtime, capabilities);
  MEDIUM for the new OpenMemory lifecycle module path (A2) and stack→infra/runtime placement (A3).
- Registration pattern recommendation: MEDIUM — sound and Click-idiomatic, but the team may
  prefer preserving the decorator style (A1).
- Help-equivalence strategy: HIGH — built on the existing `help_cmd` tree-walk + CliRunner.

**Research date:** 2026-05-29
**Valid until:** 2026-06-28 (30 days — stable internal refactor; revisit if `app.py` changes
substantially or the dirty working-tree state is committed/reverted)
