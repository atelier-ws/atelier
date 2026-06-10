# Spec 08 — Memory Audit Viewer & Rollback

> Phase 2. Auditability is the moat the natives cannot match.

## Why

Anthropic's Dreaming is a black box. Codex's consolidation runs without user visibility. Gemini auto-memory writes without confirmation. Atelier's differentiator: **every memory fact has a why, a when, and can be rolled back.**

This is the trust signal that converts security-conscious teams.

## What — user-visible

```bash
# See what changed
$ atelier memory diff --since 24h
+ [claude-a3b8] "Pankaj prefers explicit type hints (Python 3.13+ syntax)"
  source: ~/.claude/projects/atelier/MEMORY.md:14
  added by: claude auto-memory
  at: 2026-05-15 09:14

- [codex-c2e1] "Always run pytest before committing"
  source: ~/.codex/memories/atelier-project.md (deleted)
  removed by: codex consolidation
  at: 2026-05-15 11:02

~ [gemini-f8d2] "Email: pankaj4u4m@gmail.com"
  changed at: 2026-05-15 13:45
  -- old: "User email: pankaj4u4m@gmail.com"
  ++ new: "Email: pankaj4u4m@gmail.com"

# Roll back
$ atelier memory rollback --fact-id codex-c2e1
Restored 1 fact. Source file updated: ~/.codex/memories/atelier-project.md

# Roll back a whole window
$ atelier memory rollback --since 24h
Will restore 3 changes:
  + codex-c2e1 (was removed)
  ~ gemini-f8d2 (revert content)
Confirm? (y/n)

# Inspect provenance
$ atelier memory why <fact-id>
Fact: claude-a3b8
Content: "Pankaj prefers explicit type hints (Python 3.13+ syntax)"
First seen: 2026-04-12 in session 3b1c4d
Confirmed in: 14 sessions (last confirmation 2026-05-15)
Source: claude auto-memory (~/.claude/...)
Related facts:
  - codex-9f4a: "Type hints required on all new functions"
  - gemini-22e0: "Python 3.13 syntax preferred"
```

## Where — files

| File | What changes |
|------|-------------|
| `src/atelier/core/capabilities/cross_vendor_memory/audit_log.py` | **New.** Append-only fact history. |
| `src/atelier/core/capabilities/cross_vendor_memory/snapshotter.py` | **New.** Periodic snapshot of memory state. |
| `src/atelier/core/capabilities/cross_vendor_memory/rollback.py` | **New.** Apply diff against vendor source files. |
| `src/atelier/gateway/adapters/cli.py` | Add `memory diff`, `memory rollback`, `memory why` subcommands |
| `tests/core/capabilities/cross_vendor_memory/test_audit_log.py` | **New.** |

## Audit log structure

Append-only JSONL at `~/.atelier/memory_audit/<vendor>.jsonl`:

```json
{"at": "...", "event": "added",   "fact_id": "claude-a3b8", "content": "...", "source": "..."}
{"at": "...", "event": "removed", "fact_id": "codex-c2e1", "previous_content": "..."}
{"at": "...", "event": "changed", "fact_id": "gemini-f8d2", "from": "...", "to": "..."}
```

A snapshotter runs every hour (cron-like), reads memory adapters (spec 03), and writes diffs to the audit log.

## Rollback mechanics

For each vendor:
- **Added** → delete the line from source
- **Removed** → re-insert at original line number (or append if unknown)
- **Changed** → revert content; if line number known, replace; else append-with-comment

Rollback writes to the vendor's own source file. **Always create a backup** at `~/.atelier/memory_backups/<vendor>/<file>-<timestamp>` before editing.

## Provenance ("why")

For each fact, compute on demand:
- First seen timestamp
- Last confirmation (most recent time the fact was still present in source)
- Confirmation count over time
- Cross-vendor matches (substring similarity ≥ 0.8 against facts in other vendors)

## Out of scope

- **Live edit UI** ("change this fact to ..."). Future.
- **Memory write-back across vendors** ("teach Claude what Codex knows"). Spec 14 / future.
- **Conflict resolution between vendors.** Show conflicts in `memory diff`, don't auto-merge.

## Acceptance criteria

- [ ] `atelier memory diff` shows added/removed/changed facts since a time window
- [ ] `atelier memory rollback --fact-id <id>` restores a single fact
- [ ] `atelier memory rollback --since <window>` restores a range with confirmation
- [ ] Backups created before any write to a vendor file
- [ ] `atelier memory why <id>` shows full provenance
- [ ] Audit log is append-only (never rewritten, never deleted) — verified by test
- [ ] Rollback never corrupts vendor file format — verified by tests for each vendor

## Open questions

1. Should the snapshotter run on cron (system) or as a daemon (process)? **Default: as a hook in `atelier` command itself — run if last snapshot >1h old. No system daemon required.**
2. What if a vendor file no longer exists during rollback? **Default: recreate the file with the restored fact, log warning.**

## Status

- [ ] Pending
- [ ] In progress
- [ ] Shipped
