---
name: orchestrate
description: Launch a single structured run by choosing subagent versus isolated execution and compiling it into the right runtime surface.
---

# Orchestrate

This skill runs a **single structured multi-step task** end-to-end — think of it as "Claude with a plan": it chooses the right execution surface (a background task, a durable workflow, or a direct subagent), runs the steps, and hands back a result or a `run_id` you can track.

When invoked, gather inputs via `AskUserQuestion`.

## Operating loop

1. Ground the request: confirm the goal, expected deliverable, and acceptance signal.
2. Pick the narrowest execution surface (ask via `AskUserQuestion` only when the user's intent doesn't decide it):
   - durable/resumable run → the **`workflow`** MCP tool: compile the smallest valid spec and call `workflow` with `op="run"`
   - **`isolated`** (detached/background) → the host's background-task surface
   - otherwise → a direct child subagent
3. Return the resulting `run_id`, task handle, or child-run handle and tell the user how to inspect progress.

## Questions to gather

Use `AskUserQuestion` to collect what you need — batch multiple unknowns into a single call (up to 4 questions). Gather until these are clear:

- the exact goal/deliverable
- launch mode: durable workflow, isolated/background, or direct subagent
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
- Use **`isolated`** as the launch-mode label for detached/background execution.
- If the current host has no safe background-task surface for the user's requested isolated launch, say so plainly and fall back only with the user's approval.
