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

1. Show current values: `atelier settings show`.
2. Change one: `atelier settings set <key> <on|off>` (accepts on/off/true/false/1/0).
3. Map the user's words to a key, e.g. "turn off attribution" → `atelier settings set attribution off`; "hide tips" → `atelier settings set statusLineTips off`.
4. Tell the user changes apply on the next Claude Code session start. For `spinnerVerbs`/`statusLine`/`attribution`, suggest `/reload-plugins` or a restart to pick it up immediately.
5. Attribution detail: enabling sets `includeCoAuthoredBy=false` (suppressing Claude's trailer). To also stamp commits with the Atelier co-author line, run `bash ${CLAUDE_PLUGIN_ROOT}/scripts/install_attribution_hook.sh` inside the target repo.

## Guardrails

- Only set keys from the table above; `atelier settings set` rejects unknown keys.
- Confirm the exact key when the request is ambiguous.
