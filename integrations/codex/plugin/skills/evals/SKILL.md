---
description: List, run, or promote Atelier eval cases.
argument-hint: "list | run <case_id> | promote <case_id>"
---

Manage the Atelier eval suite.

Parse `$ARGUMENTS`:

- `list` → run `atelier eval list --json` and print
  `case_id | domain | status | expected_status` rows.
- `run <case_id>` → run `atelier eval run <case_id> --json`. Print
  observed status, matched/unmet expectations, and ledger snapshot path.
- `promote <case_id>` → ask for confirmation, then run
  `atelier eval promote <case_id>`. Promotion moves a `draft` case to
  `active` so it runs in the standing benchmark.

If `$ARGUMENTS` is empty or unrecognised, print the usage line above and
stop. Do not invent case IDs.
