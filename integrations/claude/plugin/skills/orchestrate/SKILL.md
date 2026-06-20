---
name: orchestrate
description: Launch a single structured run by choosing subagent versus isolated execution and compiling it into the right runtime surface.
---

> **Already-active guard:** If you can read this, `atelier:orchestrate` is already loaded — do NOT call `Skill("atelier:orchestrate")` again. The Skill tool says "do not invoke a skill that is already running" — seeing this text IS that signal.

   - use a direct child subagent/background task when the task does not need durable workflow state
4. If you use `workflow`, compile the smallest valid workflow spec and call `workflow` with `op="run"`.
5. If the user wants an isolated/background run, prefer the host's background-task surface.
6. Return the resulting `run_id`, task handle, or child-run handle and tell the user how to inspect progress.

## Questions to gather

Use `AskUserQuestion` to collect what you need — batch multiple unknowns into a single call (up to 4 questions). Gather until these are clear:

- the exact goal/deliverable
- launch mode: `subagent` or `isolated`
- whether the run should be durable/resumable or just executed once
- the workflow shape if a prompt workflow is needed
- whether plan review / approval gating is required

## `workflow` runtime contract

Use the `workflow` MCP tool truthfully:

- `op="run"` starts a fresh workflow run
- `op="status"` returns the persisted run state; `op="inspect"` returns a fuller per-step view of it
- `op="resume"` continues a persisted run
- `op="pause"` and `op="stop"` only update persisted workflow state; they do **not** interrupt a live synchronous execution already in flight

## Guardrails

- Keep the workflow spec minimal and concrete.
- Do not force `workflow` onto one-step work.
- Use **`isolated`** as the launch-mode label for detached/background execution. Durability is a separate concern.
- If the current host has no safe background-task surface for the user's requested isolated launch, say so plainly and fall back only with the user's approval.
