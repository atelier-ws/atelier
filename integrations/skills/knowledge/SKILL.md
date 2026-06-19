---
name: knowledge
description: View or curate Atelier's knowledge layers — the review overlay (repo lessons + notes/suppress/boost the live reviewer applies) and session-recall indexing health (the background importer that powers memory/recall).
---

# Knowledge base

This skill shows and manages the rules that Atelier's live reviewer applies to every diff — things like "always check authz on new endpoints" or "suppress import-ordering findings". It also surfaces the **session index** (past conversations indexed for recall), which is the primary knowledge layer for most users.

**You run the read-only diagnostics below yourself and synthesize a plain-English answer — never hand the user a list of commands to run.** When invoked with no specific request, gather the state (session-recall health first, then overlay contents) and report a synthesized status. Don't echo the commands, and don't ask "what would you like to change?"; do the work and give the answer. The synthesized status IS the useful output.

---

The live/automated reviewer applies three knowledge layers when it reviews a
diff — commit the first two to **distribute learning across the team**:

- **repo lessons** — `.lessons/blocks/*.md` (commit them; every clone gets them).
- **team overlay** — `.atelier/review.json` in the repo (commit it: every teammate's reviewer applies these `notes`/`boost`/`suppress`).
- **personal overlay** — `~/.atelier/review_overlay.json` (per-user, not shared).

## Overlay shape (`~/.atelier/review_overlay.json`)

```json
{
  "notes": ["New endpoints must check authz", "Prefer dependency injection over globals"],
  "boost": ["security", "data loss"],
  "suppress": ["line length", "import ordering"]
}
```

- `notes` — repo-specific rules the reviewer must apply.
- `boost` — areas to weight more heavily.
- `suppress` — finding classes the team has decided NOT to flag.

## Auto-extraction from .lessons

`atelier knowledge extract` distils durable review rules from this repo's
`.lessons/blocks` and merges them into the overlay `notes`. Pick the backend and
cap the spend:

```bash
atelier knowledge extract --host auto            # Atelier's owned model/routing
atelier knowledge extract --host ollama --model llama3.1   # local, free
atelier knowledge extract --scope personal       # per-user instead of team
atelier knowledge extract --dry-run              # preview without writing
```

Hosts: `auto` (owned agent-spawn), `claude`, `codex`, `ollama` (needs `--model`).
`--scope` defaults to **repo** — rules land in the committable team overlay
(`.atelier/review.json`); commit it so the whole team gets them. `--scope
personal` keeps them per-user. `--max-spend <usd>` is a hard cap — the run aborts
before spending if the estimate exceeds it (`ollama`/`codex` are treated as
free). The installer can also run this once if you opt in (`ATELIER_KB_EXTRACT=1`).

## Session indexing (recall / memory)

Atelier indexes past sessions so the reviewer and memory tools can recall
context from prior conversations. When no lessons or overlay rules exist yet,
this is the **primary active knowledge layer** — always check and surface it.

### Check status

```bash
# Background importer health — cross-platform, no systemd assumptions.
atelier servicectl status        # add --json for every field
```

Health is a **recent `last_tick_at`** (the loop ticks about once a minute) and a
recent `last_session_import_at`. The `running` flag only tracks the *detached*
controller — on a systemd install it can read `false` while the service is
actually active, so trust the timestamps (or `systemctl --user is-active
atelier-controller`) over that flag.

```bash
# How many past sessions are indexed for semantic recall.
python3 -c "import json,pathlib; p=pathlib.Path('~/.atelier/recall/index_state.json').expanduser(); print('indexed for recall:', len(json.loads(p.read_text())) if p.exists() else 0)"
```

Recall coverage is **windowed by design** (recent sessions, capped per run), so a
small indexed count next to a large transcript pile is normal — not a stall.

### Restart the importer

If your diagnostics show `last_tick_at` is stale (more than a few minutes old),
run the right restart yourself, then confirm it advanced — don't tell the user
to do it:

```bash
# systemd install (Linux):
systemctl --user restart atelier-controller   # or: atelier systemd restart

# otherwise (detached controller):
atelier servicectl start
atelier servicectl status                      # confirm last_tick_at advances
```

### Manual import

```bash
atelier import               # all new sessions, all hosts
atelier import --host claude # Claude only
atelier import --force       # re-import everything (slow)
atelier recall index         # (re)index recent sessions for semantic recall
```

### How it works

The background controller — `atelier-controller` (systemd/launchd) or the
detached `atelier servicectl` loop — runs `servicectl run`, importing new host
sessions about once a minute (the same work as `atelier import`). Semantic
recall is a separate layer: indexed sessions are tracked in
`~/.atelier/recall/index_state.json` (session → timestamp map) and snippets land
in `~/.atelier/recall.db`, populated at session start and by `atelier recall
index`.

---

## Operating loop

1. **Always** run `atelier servicectl status` and the recall index-count snippet
   yourself (both read-only), then synthesize the result for the user in plain
   English: importer freshness (`last_tick_at` recent vs stale) and the
   recall-indexed count. Don't paste the commands for the user to run. This is
   the only active knowledge layer for most users.
2. To add a review rule, append a short sentence to `notes` (or run
   `atelier knowledge extract` to populate them automatically).
3. To stop the reviewer flagging something, append a short phrase to `suppress`.
4. To emphasise an area, append to `boost`.
5. Changes apply on the next review (live pass on edit, deep pass every N edits,
   or on-demand `review`). No restart needed.

## Guardrails

- Keep entries short and concrete — they are injected verbatim into the reviewer prompt.
- `suppress` silences a finding class for everyone using this overlay; use it for settled team decisions, not to hide real issues.
