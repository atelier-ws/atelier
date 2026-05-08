---
description: Show or change Atelier smart-tool mode (off | shadow | on) for the workspace.
argument-hint: "[off | shadow | on]"
---

Inspect or change the Atelier smart-tool mode.

- If `$1` is empty: run `atelier tool-mode show` and print the current
  mode plus a one-line explanation:
  - `off` — smart tools are disabled; native tools run as-is.
  - `shadow` — smart tools record savings counters but do not change
    behaviour. **Default.**
  - `on` — smart tools may serve cached results and apply token-budget
    truncation.
- If `$1` is `off`, `shadow`, or `on`: ask the user to confirm, then run
  `atelier tool-mode set $1`. Print the new mode.

Reject any other value with a one-line error. Do not silently change
mode without confirmation.
