---
name: knowledge
description: View or curate the review knowledge base — repo lessons + personal notes/suppress/boost that the live reviewer applies.
---

# Review knowledge base

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

## Operating loop

1. To add a rule the reviewer should enforce, append a short sentence to `notes` (or run `atelier knowledge extract` to populate them automatically).
2. To stop the reviewer flagging something, append a short phrase to `suppress`.
3. To emphasise an area, append to `boost`.
4. Changes apply on the next review (live pass on edit, deep pass every N edits, or on-demand `review`). No restart needed.

## Guardrails

- Keep entries short and concrete — they are injected verbatim into the reviewer prompt.
- `suppress` silences a finding class for everyone using this overlay; use it for settled team decisions, not to hide real issues.
