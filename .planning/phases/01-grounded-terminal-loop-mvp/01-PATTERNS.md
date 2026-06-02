# Phase 1: Grounded Terminal Loop MVP - Pattern Map

**Mapped:** 2026-06-02  
**Files analyzed:** 13  
**Analogs found:** 13 / 13

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `src/atelier/core/capabilities/grounded_loop/search_first.py` | service | request-response | self + `tests/core/capabilities/grounded_loop/test_search_first.py` | exact |
| `src/atelier/core/capabilities/tool_supervision/smart_search.py` | service | transform | self + `src/atelier/core/capabilities/tool_supervision/search_read.py` | exact |
| `src/atelier/core/capabilities/code_context/engine.py` | service | request-response | self + `tests/core/test_code_context.py` | exact |
| `src/atelier/gateway/adapters/mcp_server.py` | route | request-response | self + gateway MCP tests | exact |
| `integrations/claude/plugin/hooks/pre_tool_use.py` | middleware | event-driven | self + `tests/integrations/test_claude_grounded_loop_hooks.py` | exact |
| `integrations/claude/plugin/hooks/session_start.py` | middleware | event-driven | self + `src/atelier/core/capabilities/session_optimizer.py` | role-match |
| `integrations/claude/plugin/hooks/user_prompt.py` | middleware | event-driven | self + `tests/integrations/test_claude_grounded_loop_hooks.py` | exact |
| `docs/agent-os/modes/code.md` | config | transform | self | exact |
| `tests/core/capabilities/grounded_loop/test_search_first.py` | test | request-response | self | exact |
| `tests/gateway/test_p0_mcp_surfaces.py` | test | request-response | self | exact |
| `tests/gateway/test_mcp_tool_handlers.py` | test | request-response | self | exact |
| `tests/core/test_code_context.py` | test | request-response | self | exact |
| `tests/integrations/test_claude_grounded_loop_hooks.py` | test | event-driven | self | exact |

## Pattern Assignments

### `src/atelier/core/capabilities/grounded_loop/search_first.py`

**Analog:** `src/atelier/core/capabilities/grounded_loop/search_first.py`

**Keep the composition pattern; do not invent a new gateway/router layer.**

**Core pattern** (`search_first.py:23-77`):
```python
payload = smart_search(
    query=query,
    path=path,
    mode="chunks",
    max_files=max_files,
    max_chars_per_file=max_chars_per_file,
    include_outline=include_outline,
    budget_tokens=budget_tokens,
)
...
return {
    "discovery": {"tool": "search", "mode": "chunks"},
    "matches": enriched_matches,
    "calls_saved": _discovery_calls_saved(enriched_matches),
    "handoff": {
        "read": {"tool": "read"},
        "context": _context_follow_up(task=task, files=match_paths, mode="symbols"),
        "memory": _context_follow_up(task=task, files=match_paths, mode="procedures"),
        "explore": {"tool": "explore", "query": query, "seed_files": match_paths},
    },
}
```

**Primary test analog** (`tests/core/capabilities/grounded_loop/test_search_first.py:24-58,75-83`):
```python
assert payload["discovery"]["tool"] == "search"
assert payload["handoff"]["explore"] == {
    "tool": "explore",
    "query": "ReasonBlock",
    "seed_files": [match["path"] for match in payload["matches"]],
}
...
fake_search.assert_called_once_with(
    query="OrderService",
    path=".",
    mode="chunks",
    max_files=8,
    max_chars_per_file=1600,
    include_outline=True,
    budget_tokens=2000,
)
```

### `src/atelier/core/capabilities/tool_supervision/smart_search.py`

**Analogs:** `smart_search.py`, plus `search_read.py` for fallback/security

**Ranking/fallback pattern** (`smart_search.py:311-468`):
```python
if mode == "map":
    result = build_repo_map(repo_root, seed_files=seeds, budget_tokens=budget_tokens)
    ...

payload = _search_with_backend(...)
if payload is None:
    chunk_result = search_read(...)
    payload = search_read_to_dict(chunk_result, include_metadata=False)

fts_scores = _normalize_scores(_fts_rank(...))
semantic_scores = _normalize_scores(_semantic_rank(...))
graph_scores = _normalize_scores(_graph_rank(repo_root, seeds or rel_paths[:1]))
...
matches.sort(key=lambda item: (-score(item), str(item.get("path", ""))))
```

**Validation/fallback pattern** (`search_read.py:164-171,355-356,448-455`):
```python
if _SHELL_METACHARS_RE.search(pattern):
    raise ValueError("search_read rejected: shell metacharacters not allowed in query")
...
_assert_safe_args(query, path)
...
return SearchReadResult(
    matches=matches,
    total_tokens=total_tokens,
    tokens_saved_vs_naive=tokens_saved,
    cache_hit=cache_hit,
    backend="ripgrep",
)
```

**Primary test analog** (`tests/gateway/test_p0_mcp_surfaces.py:41-84`):
```python
result = tool_smart_search({...})
assert result["backend"] == "zoekt"
assert isinstance(result["index_age_seconds"], int)
assert "matches" in result
```

### `src/atelier/core/capabilities/code_context/engine.py`

**Analog:** `src/atelier/core/capabilities/code_context/engine.py`

**Grounded semantic escalation stays in core** (`engine.py:905-1043`):
```python
normalized_seed_files = [self._normalize_file_arg(seed) for seed in seed_files or []]
...
items = self._dedupe_search_items(items)
items = self._prioritize_grounded_search_items(items, seed_files=normalized_seed_files)
...
payload = self._pack_items_payload(
    items,
    budget_tokens=effective_budget_tokens,
    extra_payload={"mode": resolved_mode, "snippet": effective_snippet},
)
```

**Explore/context pattern** (`engine.py:1506-1687`, `1756-1803`):
```python
ranked_symbols = sorted(
    raw_symbols,
    key=lambda record: (
        0 if record.file_path in seed_set else 1,
        -(record.score or 0.0),
        record.file_path,
        record.start_line,
    ),
)
...
raw = self.context_pack(
    task=task,
    seed_files=normalized_seeds,
    budget_tokens=effective_budget_tokens,
    max_symbols=max_symbols,
    auto_index=False,
)
```

**Related follow-up tools remain explicit** (`engine.py:1805-1865`, `1943-1982`):
```python
raw_payload = self.impact(...).model_dump(mode="json")
compact_payload = self._compact_impact_payload(raw_payload, budget_tokens=effective_budget_tokens)
...
payload = self.find_references(
    query=query,
    symbol_id=symbol_id,
    ...
    budget_tokens=effective_budget_tokens,
)
```

**Primary test analogs**
- `tests/core/test_code_context.py:1558-1567`
```python
payload = engine.tool_search(... seed_files=["legacy/orders.py"] ...)
assert payload["items"][0]["path"] == "legacy/orders.py"
```
- `tests/core/test_code_context.py:1910-1929`
```python
payload = engine.tool_explore("OrderService", ..., budget_tokens=6000)
assert payload["entry_points"]
assert payload["files"]
assert payload["relationships"]["callers"] is not None
```
- `tests/core/test_code_context.py:1998-2010`
```python
payload = engine.tool_explore("OrderService", ..., budget_tokens=320)
assert payload["total_tokens"] <= 320
assert "entry_points" in payload
```

### `src/atelier/gateway/adapters/mcp_server.py`

**Analog:** `src/atelier/gateway/adapters/mcp_server.py`

**Thin-plumbing rule: keep schemas/descriptions/delegation here, not ranking logic.**

**Context and code-intel pass-through** (`mcp_server.py:1042-1100`, `4247-4368`):
```python
if mode == "symbols":
    engine = _code_context_engine(".")
    return cast(
        dict[str, Any],
        engine.tool_context(
            task=task,
            seed_files=files or [],
            budget_tokens=token_budget or 4000,
            max_symbols=max_blocks,
        ),
    )
...
def _tool_symbols_alias_handler(args: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = _raw_tool_symbols_handler(args)
    if isinstance(result, dict) and "calls_saved" not in result:
        ...
```

**Search wrapper pattern** (`mcp_server.py:4818-4902`):
```python
"""Search by ranked query or repo-map construction, then hand off to node/explore-style code intel."""
if mode == "map":
    if not seed_files:
        raise ValueError("seed_files is required when mode='map'")
elif query is None:
    raise ValueError("query is required for ranked search; use grep for regex/glob search")

payload = smart_search(...)
if include_meta:
    return payload
payload.pop("cache_hit", None)
payload.pop("backend", None)
payload.pop("index_age_seconds", None)
payload.pop("total_tokens", None)
```

**Read/edit wrapper pattern** (`mcp_server.py:2527-2635`, `2861-2944`):
```python
payload = cap.smart_read(target, range_spec=range, expand=expand)
...
result = apply_rich_edits(edits, atomic=atomic, repo_root=repo_root)
...
if applied_count > 1:
    result.setdefault("calls_saved", applied_count - 1)
```

**Primary test analogs**
- `tests/gateway/test_mcp_tool_handlers.py:1345-1358`
```python
fake_engine.tool_search.assert_called_once_with(
    "OrderService",
    ...
    seed_files=["src/orders.py"],
    ...
    budget_tokens=220,
)
```
- `tests/gateway/test_p0_mcp_surfaces.py:86-100`
```python
assert "grep" in search_tool["description"]
assert "node" in search_tool["description"]
assert "explore" in search_tool["description"]
assert "mode='map'" in properties["seed_files"]["description"]
```
- `tests/gateway/test_p0_mcp_surfaces.py:197-205`
```python
assert "backend" not in payload
fake_engine.tool_search.assert_called_once_with(... seed_files=None, ...)
```

### `integrations/claude/plugin/hooks/pre_tool_use.py`

**Analog:** `integrations/claude/plugin/hooks/pre_tool_use.py`

**Advisory-only hook pattern** (`pre_tool_use.py:62-90`):
```python
try:
    payload = json.loads(sys.stdin.read() or "{}")
except (json.JSONDecodeError, TypeError):
    return 0  # fail-open
...
if not target or not _is_risky(target):
    print(json.dumps({"decision": "allow"}))
    return 0
...
print(json.dumps({"decision": "ask", "reason": msg}))
```

**Primary test analog** (`tests/integrations/test_claude_grounded_loop_hooks.py:27-33,54-57`):
```python
assert payload["decision"] == "ask"
assert "search" in payload["reason"]
assert "read" in payload["reason"]
assert "batch" in payload["reason"]
...
assert payload == {"decision": "allow"}
```

### `integrations/claude/plugin/hooks/session_start.py`

**Analogs:** `session_start.py`, plus `session_optimizer.py`

**Fail-open session bootstrap pattern** (`session_start.py:87-104`, `179-224`):
```python
def _apply_session_bootstrap(payload: dict[str, Any]) -> bool:
    ...
    with suppress(Exception):
        apply_session_start_files(...)
        return True
    return False
...
try:
    payload = json.loads(sys.stdin.read() or "{}")
except (json.JSONDecodeError, TypeError):
    return 0
...
_append_session_start_event(session_id, source, model, cwd, transcript_path)
```

**Optimizer guidance analog** (`session_optimizer.py:95-105`):
```python
return {
    "hookSpecificOutput": {"hookEventName": "SessionStart"},
    "additionalContext": render_session_optimizer_guidance(host),
    "message": "Atelier budget optimizer active",
    "optimizer": {
        "host": normalize_optimizer_host(host),
        "root": root,
        "rules": session_optimization_rules(),
    },
}
```

### `integrations/claude/plugin/hooks/user_prompt.py`

**Analog:** `integrations/claude/plugin/hooks/user_prompt.py`

**Soft ergonomic nudge pattern** (`user_prompt.py:195-247`):
```python
def _emit_compact_warning(pct: int) -> None:
    msg = (
        f"[Atelier] Context estimated at ~{pct}% of window. "
        "Call mcp__atelier__compact now, then tell the user to run /compact "
        "before starting multi-step work."
    )
...
def _emit_grounded_batching_nudge() -> None:
    msg = "[Atelier] Ground multi-file changes with search or read first, then batch related edits in one edit call."
...
if _looks_like_multi_file_edit_prompt(prompt):
    _emit_grounded_batching_nudge()
```

**Primary test analog** (`tests/integrations/test_claude_grounded_loop_hooks.py:60-88,91-111`):
```python
lines = [json.loads(line) for line in capsys.readouterr().out.splitlines() if line.strip()]
assert len(lines) == 2
assert "Context estimated" in lines[0]["content"]
assert "search" in lines[1]["content"]
assert "batch" in lines[1]["content"]
...
assert capsys.readouterr().out == ""
```

### `docs/agent-os/modes/code.md`

**Analog:** `docs/agent-os/modes/code.md`

**Source-of-truth guidance pattern** (`code.md:11-15,39-45`):
```markdown
1. **Context**: Call `context` ...
2. **Implement**: Use Atelier MCP tools ...
3. **Record**: Call `trace` ...
...
- Use `grep` or `search` first for regex, glob, ranked discovery, and file/path lookup.
- Use `read` first for file reads and exact ranges.
- Use `edit` first for deterministic writes and grouped edits.
- Use `shell` only for commands with no better Atelier equivalent ...
```

**Planner note:** if host guidance changes, edit this source doc, then regenerate; do **not** patch generated Claude agent artifacts directly.

## Shared Patterns

### Core-owned grounding; gateway stays thin
**Source:** `src/atelier/core/capabilities/grounded_loop/search_first.py:33-40`, `src/atelier/core/capabilities/code_context/engine.py:1029-1042`, `src/atelier/gateway/adapters/mcp_server.py:4882-4902`
```python
payload = smart_search(...)
items = self._prioritize_grounded_search_items(items, seed_files=normalized_seed_files)
payload = smart_search(...)
payload.pop("backend", None)
```
Apply to all Phase 1 changes: put search ranking, seed-file biasing, and semantic escalation in `core`; keep `mcp_server.py` to contract/plumbing only.

### Preserve explicit search -> read/context/explore handoff
**Source:** `src/atelier/core/capabilities/grounded_loop/search_first.py:60-76`
```python
"handoff": {
    "read": {"tool": "read"},
    "context": _context_follow_up(..., mode="symbols"),
    "memory": _context_follow_up(..., mode="procedures"),
    "explore": {"tool": "explore", "query": query, "seed_files": match_paths},
}
```
Apply to search-first UX changes; do not turn search into a dead-end snippet viewer.

### Keep `search`, `grep`, and `shell` distinct
**Sources:** `mcp_server.py:4867-4874`, `bash_exec.py:100-127,157-186`
```python
- Use `grep` instead when you need regex, glob, type filters...
...
return CommandPolicyDecision(... rewrite_target="search", rewrite_payload={"query": pattern, "path": path})
...
return CommandPolicyDecision(... rewrite_target="grep", rewrite_payload=payload)
```
Apply to MCP descriptions, hook nudges, and docs: ranked search is default grounding, `grep` remains explicit escape hatch, `shell` is only for no-equivalent commands.

### Hook changes must stay advisory and fail-open
**Sources:** `pre_tool_use.py:63-66,79-90`, `user_prompt.py:240-247`, `session_start.py:213-224`
```python
return 0  # fail-open
print(json.dumps({"decision": "ask", "reason": msg}))
...
if _looks_like_multi_file_edit_prompt(prompt):
    _emit_grounded_batching_nudge()
```
Apply to all Claude hook changes in Phase 1; no blocking gates.

### Ledger/session continuity uses atomic append-style updates
**Sources:** `session_start.py:156-171`, `post_tool_use.py:138-179`
```python
with tempfile.NamedTemporaryFile(..., delete=False, encoding="utf-8") as tmp:
    json.dump(data, tmp, indent=2)
    tmp_path = tmp.name
Path(tmp_path).replace(run_file)
```
Apply to hook-side session/run state writes.

## Primary Test Analogs

- `tests/core/capabilities/grounded_loop/test_search_first.py` — locks search-first composition and explicit handoffs.
- `tests/gateway/test_p0_mcp_surfaces.py` — locks MCP schema wording, metadata visibility, and explore/search surface shape.
- `tests/gateway/test_mcp_tool_handlers.py` — locks gateway pass-through into core, especially `seed_files` with no gateway ranking logic.
- `tests/core/test_code_context.py` — locks grounded seed-file prioritization, explore payload shape, and budget compaction.
- `tests/integrations/test_claude_grounded_loop_hooks.py` — locks hook nudges as soft/advisory and skips redundant nudges when already grounded.

## No Analog Found

None. All likely Phase 1 rerun surfaces already exist and should be edited surgically in place.

## Metadata

**Analog search scope:** `src/atelier/core/capabilities/grounded_loop/`, `src/atelier/core/capabilities/tool_supervision/`, `src/atelier/core/capabilities/code_context/`, `src/atelier/gateway/adapters/`, `integrations/claude/plugin/hooks/`, `docs/agent-os/modes/`, `tests/core/`, `tests/gateway/`, `tests/integrations/`  
**Files scanned:** 17  
**Pattern extraction date:** 2026-06-02
