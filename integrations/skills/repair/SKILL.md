---
name: repair
description: Activate repair specialist mode for repeated failures. Captures the failing signal, calls rescue, applies the fix, and records a postmortem. Trigger when the same approach has failed twice.
---

# Repair mode

Systematic repair specialist. Activate when the same approach has failed twice.

## Operating loop

1. **Capture** the exact failing signal: command output, error text, file and line.
2. **Rescue** — call `rescue` with the error and recent actions. Apply the recommendation exactly.
3. **Validate** — run the narrowest command that would prove the fix worked.
4. **Escalate** — if the same failure persists after the rescue, stop and report. Do not retry a third time.
5. **Record** — call `record` with `agent: "atelier:repair"`. Include a postmortem in `learnings`.

## Hard rules

- Never retry the same approach a third time. Change strategy or escalate.
- The failing signal must be captured verbatim before calling rescue.
- Do not modify unrelated files during repair.
