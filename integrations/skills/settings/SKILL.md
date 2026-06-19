---
name: settings
description: View or change Atelier plugin settings (attribution, spinner verbs, status line, tips) in plain English.
---

# Atelier settings

Manage the local Atelier plugin toggles in `~/.atelier/plugin_settings.json`.
Interpret the user's plain-English request and apply it with the `atelier
settings` CLI — never hand-edit `~/.claude/settings.json`.

## Available toggles

| Key | Default | What it controls |
|-----|---------|------------------|
| `attribution` | on | `Co-Authored-By: atelier-agent[bot]` on commits + suppress Claude's default trailer |
| `spinnerVerbs` | on | Atelier-themed spinner verbs |
| `statusLine` | on | Master toggle for the Atelier status line |
| `statusLineSession` | on | Session savings in the status line |
| `statusLineLifetime` | on | Lifetime savings in the status line |
| `statusLineTips` | on | Rotating feature tips in the status line |
| `statusLineShare` | on | Referral hint in the status line |
| `alwaysLoadTools` | on | Load Atelier MCP tools up-front vs deferring behind ToolSearch |

## Operating loop

1. Run `atelier settings show` to get current values.
2. If no change was requested, render the current state as a markdown table directly in your response (key | on/off | what it controls) — do NOT just ask "what would you like to change?"; the table IS the useful output.
3. To change a setting: `atelier settings set <key> <on|off>` (accepts on/off/true/false/1/0).
4. Map plain-English requests to keys, e.g. "turn off attribution" → `atelier settings set attribution off`; "hide tips" → `atelier settings set statusLineTips off`.
5. After a change, confirm the new value and note that most settings apply on the next session start; for `spinnerVerbs`/`statusLine`/`attribution` suggest `/reload-plugins` to pick it up immediately.
6. Attribution detail: enabling sets `includeCoAuthoredBy=false` (suppressing Claude's default trailer). To also stamp commits with the Atelier co-author line, run `bash ${CLAUDE_PLUGIN_ROOT}/scripts/install_attribution_hook.sh` inside the target repo.

## Guardrails

- Only set keys from the table above; `atelier settings set` rejects unknown keys.
- Confirm the exact key when the request is ambiguous.
