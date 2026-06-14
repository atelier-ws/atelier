---
name: knowledge
description: View or curate the review knowledge base — repo lessons + personal notes/suppress/boost that the live reviewer applies.
---

# Review knowledge base

The live/automated reviewer applies two knowledge layers when it reviews a diff:

- **repo lessons** — the first heading of each `.lessons/blocks/*.md` (conventions learned in this repo).
- **personal overlay** — `~/.atelier/review_overlay.json`, which you curate.

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
atelier knowledge extract --dry-run              # preview without writing
```

Hosts: `auto` (owned agent-spawn), `claude`, `codex`, `ollama` (needs `--model`).
`--max-spend <usd>` is a hard cap — the run aborts before spending if the
estimate exceeds it (`ollama`/`codex` are treated as free). The installer can
also run this once if you opt in (`ATELIER_KB_EXTRACT=1`).

## Operating loop

1. To add a rule the reviewer should enforce, append a short sentence to `notes` (or run `atelier knowledge extract` to populate them automatically).
2. To stop the reviewer flagging something, append a short phrase to `suppress`.
3. To emphasise an area, append to `boost`.
4. Changes apply on the next review (live pass on edit, deep pass every N edits, or on-demand `review`). No restart needed.

## Guardrails

- Keep entries short and concrete — they are injected verbatim into the reviewer prompt.
- `suppress` silences a finding class for everyone using this overlay; use it for settled team decisions, not to hide real issues.
