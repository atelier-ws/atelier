---
description: "Use when: showing or changing Atelier smart-tool mode, settings, tool-mode, off, shadow, or on."
allowed-tools: "Bash(atelier tool-mode *)"
---

Inspect or change Atelier smart-tool mode.

1. If no mode is supplied, run `atelier tool-mode show` and explain `off`, `shadow`, and `on` in one line each.
2. If the mode is `off`, `shadow`, or `on`, ask for confirmation before running `atelier tool-mode set <mode>`.
3. Reject any other mode.

Never change mode without confirmation in the current turn.