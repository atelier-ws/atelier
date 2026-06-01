---
phase: 25-cli-decomposition
plan: "05"
subsystem: cli
tags: [cli, extraction, code, memory, route, sessions]
decisions:
  - "Kept duplicate-name MCP suppression intact by registering only the public memory/route groups; test_cli_mcp_only.py stayed green."
  - "Added a dormant context.py module because the current worktree baseline no longer contains the planned context-style command bodies in app.py."
metrics:
  completed_at: 2026-06-01
---

# Phase 25 Plan 05: CLI command-cluster extraction summary

Extracted the extant public code/zoekt, memory, route/proof, runs/outcomes/session CLI groups out of `app.py` into `cli/commands/*`, preserving help output for those surfaces and keeping duplicate-name MCP-only suppression unchanged.

## What changed

- Added:
  - `src/atelier/gateway/cli/commands/code.py`
  - `src/atelier/gateway/cli/commands/context.py`
  - `src/atelier/gateway/cli/commands/memory.py`
  - `src/atelier/gateway/cli/commands/route.py`
  - `src/atelier/gateway/cli/commands/sessions.py`
- Updated:
  - `src/atelier/gateway/cli/commands/__init__.py`
  - `src/atelier/gateway/cli/app.py`

## Deviations from plan

- The current worktree baseline did **not** contain the planned context/dev `memory`/`route`/`read`/`edit`/`batch-edit`/`search-read` command bodies in `app.py`, so this slice extracted only the command bodies actually present.
- `context.py` was added as a placeholder module to preserve the target module layout without reintroducing missing/suppressed surfaces.
- Full-plan validation commands from `25-05-PLAN.md` were narrowed to focused CLI-surface validation because:
  - `tests/gateway/test_cli.py` currently trips a pre-existing tree-sitter thread-safety panic during `atelier init --index`
  - `tests/gateway/test_cli_help_tree.py::test_help_tree_contains_expected_public_groups` currently fails on a pre-existing missing `benchmark` registration caused by `atelier.infra.benchmarks` being absent in this worktree

## Validation run

- `uv run ruff check src/atelier/gateway/cli/app.py src/atelier/gateway/cli/commands/__init__.py src/atelier/gateway/cli/commands/code.py src/atelier/gateway/cli/commands/context.py src/atelier/gateway/cli/commands/memory.py src/atelier/gateway/cli/commands/route.py src/atelier/gateway/cli/commands/sessions.py tests/gateway/test_cli.py tests/gateway/test_cli_help.py tests/gateway/test_cli_help_tree.py tests/gateway/test_cli_mcp_only.py tests/gateway/test_cli_memory_commands.py tests/gateway/test_cli_proof_gate.py tests/gateway/test_cli_route.py tests/gateway/test_cli_team.py`
- `uv run pytest tests/gateway/test_cli_help.py tests/gateway/test_cli_mcp_only.py tests/gateway/test_cli_memory_commands.py tests/gateway/test_cli_proof_gate.py tests/gateway/test_cli_route.py tests/gateway/test_cli_team.py tests/gateway/test_cli_help_tree.py::test_help_tree_includes_hidden_command_paths tests/gateway/test_cli_help_tree.py::test_help_tree_excludes_mcp_only_entries tests/gateway/test_cli_help_tree.py::test_top_level_help_still_succeeds`
- `uv run python -c "from atelier.gateway.cli import cli, main; print('ok')"`
- `uv run atelier code --help`
- `uv run atelier zoekt --help`
- `uv run atelier memory --help`
- `uv run atelier route --help`
- `uv run atelier proof --help`
- `uv run atelier session --help`
- `uv run atelier outcomes --help`
- `uv run atelier runs --help`

## Known stubs

- `src/atelier/gateway/cli/commands/context.py:1` — placeholder module only; no live commands were reintroduced because the corresponding bodies were already absent from the baseline.

## Self-Check: PASSED

- Target command modules exist.
- Extracted groups import from `atelier.gateway.cli`.
- Focused validation passed for touched public CLI surfaces.
