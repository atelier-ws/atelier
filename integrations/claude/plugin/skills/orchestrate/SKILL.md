---
name: orchestrate
description: Launch a single structured run by choosing subagent versus isolated execution and compiling it into the right runtime surface.
---

> **Active** — do not call `Skill("atelier:orchestrate")` again.

# Orchestrate

This skill runs a **single structured multi-step task** end-to-end — think of it as "Claude with a plan": it chooses the right execution surface (a background task, a durable workflow, or a direct subagent), runs the steps, and hands back a result or a `run_id` you can track.

When invoked, tell the user: "I'll coordinate this as a single structured run. Let me ask a few things to set it up correctly." Then gather inputs via `AskUserQuestion`.

## Operating loop

1. Ground the request: confirm the goal, expected deliverable, and acceptance signal.
2. Ask whether the launch mode should be **`subagent`** or **`isolated`** if the user has not already decided.
3. Choose the narrowest execution surface that matches the ask:
   - use the **`workflow`** MCP tool for durable, prompt-driven workflow runs
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
