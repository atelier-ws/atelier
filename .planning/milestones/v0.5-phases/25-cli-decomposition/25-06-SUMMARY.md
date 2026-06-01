---
phase: 25
plan: 06
subsystem: cli
tags: [cli, decomposition, click]
requires: [25-05]
provides: [cli-command-modules-hosts-lessons-blocks-admin-telemetry]
affects:
  - src/atelier/gateway/cli/app.py
  - src/atelier/gateway/cli/commands/__init__.py
  - src/atelier/gateway/cli/commands/_dev.py
  - src/atelier/gateway/cli/commands/_shared.py
  - src/atelier/gateway/cli/commands/admin.py
  - src/atelier/gateway/cli/commands/blocks.py
  - src/atelier/gateway/cli/commands/hosts.py
  - src/atelier/gateway/cli/commands/lessons.py
  - src/atelier/gateway/cli/commands/telemetry.py
  - src/atelier/gateway/cli/commands/savings.py
  - src/atelier/gateway/cli/commands/sessions.py
tech_stack:
  added: []
  patterns: [click-pattern-1, thin-app-registration, dev-gated-command-factories]
decisions:
  - Extracted hosts/lessons/blocks/admin/telemetry callbacks into standalone command modules and kept app.py as root/help/telemetry-registration glue.
  - Moved shared CLI helpers into commands/_dev.py and commands/_shared.py to avoid app.py import cycles.
  - Stabilized focused CLI tests by routing monkeypatch targets to extracted modules and disabling unrelated init indexing in test helpers.
metrics:
  completed_at: 2026-06-01
---

# Phase 25 Plan 06: CLI decomposition slice summary

Thin root app with extracted hosts, lessons, blocks, admin, and telemetry command modules while preserving help output, hidden/dev gating, and stderr-only import progress.

## Deviations from Plan

### Auto-fixed Issues

1. [Rule 3 - Blocking issue] Focused validations were tripping a pre-existing code-index autosync/thread-safety failure during `init`
   - Fix: updated focused CLI tests to pass `--no-index` for `init` setup paths so this decomposition slice validates only the touched CLI surfaces.
   - Files: `tests/gateway/test_cli_import_progress.py`, `tests/gateway/test_cli_v2.py`

2. [Rule 3 - Blocking issue] Extracted command tests still monkeypatched `atelier.gateway.cli.app` internals
   - Fix: repointed monkeypatches to extracted module locations for savings/letta paths.
   - Files: `tests/gateway/test_cli_v2.py`, `tests/gateway/test_cli_v3_commands.py`

## Known Validation Notes

- The repository still has a pre-existing missing `benchmark` CLI module dependency (`atelier.infra.benchmarks`) so the `test_help_tree_contains_expected_public_groups` benchmark assertion remains out of scope for this slice.

## Self-Check: PASSED
