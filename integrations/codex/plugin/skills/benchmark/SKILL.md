---
description: Run the Atelier eval suite in dry-run mode and summarise pass/fail per case.
argument-hint: "[--apply]"
---

Run the Atelier benchmark.

1. Default to dry-run. Run `atelier benchmark --json` (no writes).
2. If `$1` is exactly `--apply`, ask the user to confirm in chat before
   re-running with `atelier benchmark --apply --json`.
3. Render a table: `case_id | domain | expected | observed | result`.
4. Print the totals line: `passed/total` and the list of failing
   `case_id`s, if any.

Never `--apply` without explicit user confirmation in this turn.
