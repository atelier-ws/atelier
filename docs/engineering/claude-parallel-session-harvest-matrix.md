# Claude Parallel-Session Harvest Matrix

This matrix is the Phase 36 source of truth for what Claude session surfaces are
currently harvested, what is only inferred, and what must be verified before
any new path scanning is added.

| Session type | Transcript location | Currently harvested? | Proof in repo | Follow-up |
| --- | --- | --- | --- | --- |
| Foreground | `~/.claude/projects/<workspace>/*.jsonl` | Yes | `find_claude_sessions()` scans project roots in `src/atelier/gateway/hosts/session_parsers/claude.py`. | Keep covered by discovery/import tests. |
| Subagent | `~/.claude/projects/<workspace>/<session>/subagents/*.jsonl` | Yes | `ClaudeImporter.import_session()` appends `subagents/*.jsonl` under the parent session directory before parsing. | Keep merged into the parent import; verify dedup if new sources are added later. |
| Background / agent-view | Unverified; likely under `~/.claude/jobs/<id>/...` if persisted | Unknown | No current Claude importer path scans `~/.claude/jobs/`; roadmap explicitly forbids speculative scanning before verification. | Verify whether a durable transcript exists and only then add a scanner. |
| Teammate | Unverified; may mirror foreground `projects/` output or another host-managed surface | Unknown | No dedicated teammate-path detection exists today beyond the generic project scan. | Confirm the persisted artifact location first; add logical-session dedup if the same session appears in multiple roots. |
| Workflow agent | Per-agent transcript unverified; final workflow report may be the only persisted artifact | Unknown | No current import path captures workflow-agent artifacts, and roadmap notes intermediate workflow state may never persist as transcripts. | Document the limitation if no per-agent transcript exists; capture the final workflow report instead where available. |

## Current gate

Phase 36 HARV-02 stays blocked until the unknown rows above are verified with
real persisted artifacts. Do not add `~/.claude/jobs/*` scanning or any other
new Claude transcript root based only on inference.
