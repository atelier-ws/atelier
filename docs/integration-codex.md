# Codex integration

## 1. AGENTS.md

Add this to your repo's `AGENTS.md` (see the [Atelier AGENTS.md](https://github.com/pankaj4u4m/atelier/blob/main/AGENTS.md) for the full template):

```
# Agent Reasoning Runtime
Before editing code:
1. Call `get_reasoning_context` with the task, likely files, and known errors.
2. Draft a plan.
3. Call `check_plan` before modifying files.
4. If the same test/command fails twice, call `rescue_failure`.
5. After finishing, call `record_trace`.

Never ignore high-severity Reasoning Runtime warnings.
Never store secrets or hidden chain-of-thought in traces.
```

## 2. MCP server config

Codex CLI / IDE configuration:

```json
&#123;
  "mcpServers": &#123;
    "atelier": &#123;
      "command": "uv",
      "args": ["run", "atelier-mcp"],
      "cwd": "/abs/path/to/repo/atelier",
      "env": &#123; "ATELIER_ROOT": ".atelier" &#125;
    &#125;
  &#125;
&#125;
```

## 3. First-time setup

```bash
cd atelier
uv sync --all-extras
uv run atelier init   # creates .atelier/ + seeds 10 blocks + 5 rubrics
```

## 4. Smoke test

```bash
uv run atelier check-plan \
  --task "Fix Shopify publish validation" \
  --domain beseam.shopify.publish \
  --step "Parse product handle from PDP URL" \
  --step "Use handle to update metafields"
# Expect: status BLOCKED + suggested plan that uses the Product GID.
```

## 5. Tool reference

| Tool                    | Required input                      | Returns                                |
| ----------------------- | ----------------------------------- | -------------------------------------- |
| `get_reasoning_context` | `task`                              | injection text                         |
| `check_plan`            | `task`, `plan`                      | `status`, `warnings`, `suggested_plan` |
| `rescue_failure`        | `task`, `error`                     | `rescue`, `matched_blocks`             |
| `record_trace`          | `agent`, `domain`, `task`, `status` | `id`                                   |
| `extract_reasonblock`   | `trace_id`                          | candidate block + confidence           |
| `run_rubric_gate`       | `rubric_id`, `checks`               | `status`, `outcomes`                   |
