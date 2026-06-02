# Phase 1: Grounded Terminal Loop MVP - Pattern Map

**Mapped:** 2026-06-02  
**Files analyzed:** 14  
**Analogs found:** 13 / 14

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `src/atelier/core/capabilities/grounded_loop/search_first.py` *(new, inferred)* | service | transform | `src/atelier/core/capabilities/tool_supervision/smart_search.py` + `src/atelier/core/capabilities/tool_supervision/search_read.py` | composite |
| `src/atelier/gateway/adapters/mcp_server.py` | route | request-response | `src/atelier/gateway/adapters/mcp_server.py` | exact |
| `src/atelier/core/capabilities/tool_supervision/smart_search.py` | service | transform | `src/atelier/core/capabilities/tool_supervision/smart_search.py` | exact |
| `src/atelier/core/capabilities/tool_supervision/search_read.py` | service | transform | `src/atelier/core/capabilities/tool_supervision/search_read.py` | exact |
| `src/atelier/core/capabilities/code_context/engine.py` | service | request-response | `src/atelier/core/capabilities/code_context/engine.py` | exact |
| `src/atelier/core/capabilities/semantic_file_memory/capability.py` | service | file-I/O | `src/atelier/core/capabilities/semantic_file_memory/capability.py` | exact |
| `src/atelier/core/capabilities/tool_supervision/bash_exec.py` | middleware | request-response | `src/atelier/core/capabilities/tool_supervision/bash_exec.py` | exact |
| `integrations/claude/plugin/hooks/pre_tool_use.py` | middleware | event-driven | `integrations/claude/plugin/hooks/pre_tool_use.py` | exact |
| `integrations/claude/plugin/hooks/user_prompt.py` | middleware | event-driven | `integrations/claude/plugin/hooks/user_prompt.py` | exact |
| `tests/core/capabilities/grounded_loop/test_search_first.py` *(new, inferred)* | test | transform | `tests/core/test_search_read.py` | exact |
| `tests/gateway/test_p0_mcp_surfaces.py` | test | request-response | `tests/gateway/test_p0_mcp_surfaces.py` | exact |
| `tests/gateway/test_mcp_tool_handlers.py` | test | request-response | `tests/gateway/test_mcp_tool_handlers.py` | exact |
| `tests/core/test_code_context.py` | test | request-response | `tests/core/test_code_context.py` | exact |
| `tests/infra/test_search_read_token_savings.py` / `tests/core/test_smart_search_baseline.py` | test | benchmark | `tests/infra/test_search_read_token_savings.py` + `tests/core/test_smart_search_baseline.py` | exact |

## Pattern Assignments

### `src/atelier/core/capabilities/grounded_loop/search_first.py` (service, transform)

**Analog:** `src/atelier/core/capabilities/tool_supervision/smart_search.py` + `src/atelier/core/capabilities/tool_supervision/search_read.py`

**Imports/composition pattern**  
Copy the existing capability-level composition shape, not gateway logic.

- `src/atelier/core/capabilities/tool_supervision/smart_search.py` lines 16-25
```python
from atelier.core.capabilities.repo_map import build_repo_map
from atelier.core.capabilities.repo_map.graph import (
    build_reference_graph,
    should_skip_path,
)
from atelier.core.capabilities.repo_map.pagerank import personalized_pagerank
from atelier.core.capabilities.tool_supervision.search_read import search_read, search_read_to_dict
from atelier.infra.code_intel.zoekt.adapter import get_zoekt_supervisor
```

**Core search-first flow**  
- `src/atelier/core/capabilities/tool_supervision/smart_search.py` lines 311-379
```python
def smart_search(...):
    _assert_safe_query(query, path)
    repo_root = _repo_root()
    search_path = _resolve_path(repo_root, path)
    ...
    payload: dict[str, Any] | None = _search_with_backend(...)
    if payload is None:
        chunk_result = search_read(
            query=query,
            path=str(search_path),
            max_files=max_files,
            max_chars_per_file=max_chars_per_file,
            include_outline=include_outline,
        )
        payload = search_read_to_dict(chunk_result, include_metadata=False)
```

**Ranking + budget pattern**  
- `src/atelier/core/capabilities/tool_supervision/smart_search.py` lines 413-461
```python
fts_scores = _normalize_scores(_fts_rank(...))
semantic_scores = _normalize_scores(_semantic_rank(...))
graph_scores = _normalize_scores(_graph_rank(...))
...
matches.sort(key=lambda item: (-score(item), str(item.get("path", ""))))
response = {
    "matches": final_matches,
    "mode": mode,
    "backend": backend,
    "index_age_seconds": payload.get("index_age_seconds"),
    "cache_hit": False,
    "tokens_saved": max(0, (final_naive - final_rendered) // 4),
}
```

**Search-read fallback details**  
- `src/atelier/core/capabilities/tool_supervision/search_read.py` lines 334-455
```python
def search_read(...):
    _assert_safe_args(query, path)
    ...
    hits_per_file = _parse_grep_output(grep_output)
    sorted_files = sorted(hits_per_file.keys())[:max_files]
    ...
    snippets = _cluster_snippets(linenos, lines, context=context_lines)
    if len(linenos) > 5:
        snippets = snippets[:3]
        if include_outline:
            outline = _file_outline(fpath, content, lang)
    ...
    return SearchReadResult(
        matches=matches,
        total_tokens=total_tokens,
        tokens_saved_vs_naive=tokens_saved,
        cache_hit=cache_hit,
        backend="ripgrep",
    )
```

**Use this for Phase 1:** new orchestration should live in `core/capabilities/`, call existing search/read/code-intel surfaces, and return budgeted structured payloads.

---

### `src/atelier/gateway/adapters/mcp_server.py` (route, request-response)

**Analog:** `src/atelier/gateway/adapters/mcp_server.py`

**Thin gateway registration pattern**  
- lines 93-140
```python
def mcp_tool(...):
    ...
    ArgsModel = create_model(f"{func.__name__}_Args", **field_defs)
    schema = ArgsModel.model_json_schema()
    ...
    def handler_wrapper(args: dict[str, Any]) -> Any:
        validated = ArgsModel.model_validate(args)
        return func(**validated.model_dump())
```

**Search tool dispatch stays thin**  
- lines 4814-4895
```python
def tool_smart_search(...):
    if mode == "map":
        if not seed_files:
            raise ValueError("seed_files is required when mode='map'")
    elif query is None:
        raise ValueError("query is required for ranked search; use grep for regex/glob search")
    from atelier.core.capabilities.tool_supervision.smart_search import smart_search

    payload = smart_search(...)
    ts = int(payload.pop("tokens_saved", 0) or 0)
    if ts > 0:
        _tool_call_tokens_saved.value = ts
```

**Semantic escalation alias pattern**  
- lines 3747-3905 and 4282-4378
```python
def tool_symbols(...):
    """Search the SCIP code index for symbols by name or description."""
    ...
    if op == "search":
        ...
        search_payload = cast(dict[str, Any], engine.tool_search(query, **search_kwargs))
        if view == "target":
            search_payload = _code_search_target_view(search_payload, query=query)
```

```python
@mcp_tool(name="node")
def tool_node(...): ...

@mcp_tool(name="callers")
def tool_callers(...): ...

@mcp_tool(name="callees")
def tool_callees(...): ...

@mcp_tool(name="impact")
def tool_impact(...): ...

@mcp_tool(name="explore")
def tool_explore(...): ...

@mcp_tool(name="usages")
def tool_usages(...): ...
```

**Context seeding pattern**  
- lines 1042-1177
```python
def tool_get_context(...):
    if mode == "symbols":
        engine = _code_context_engine(".")
        return cast(dict[str, Any], engine.tool_context(...))
    ...
    led.record_tool_call("get_context", {...})
    ...
    payload = rt.get_context(..., agent_id=agent_id, recall=recall)
    result["bootstrap"] = bootstrap
```

**Use this for Phase 1:** change schema/description/dispatch here only; keep actual grounding logic in core.

---

### `src/atelier/core/capabilities/code_context/engine.py` (service, request-response)

**Analog:** `src/atelier/core/capabilities/code_context/engine.py`

**Search budget/cache/escalation pattern**  
- lines 903-1039
```python
def tool_search(...):
    effective_budget_tokens = ...
    if auto_index and scope != "deleted":
        self._ensure_indexed()
    self._sync_symbol_intel()
    ...
    hit, cached = self._cache_get("code.search", cache_args)
    if hit and cached is not None:
        return self._mark_cache_hit(cached)
    ...
    payload = self._pack_items_payload(..., extra_payload={"mode": resolved_mode, "snippet": effective_snippet})
    self._cache_set("code.search", cache_args, payload)
    return payload
```

**Explore as one-call escalation pattern**  
- lines 1498-1683
```python
def tool_explore(...):
    raw_symbols = self.search_symbols(query, limit=bounded_max_symbols, snippet="none", auto_index=False)
    ...
    files_payload.append(file_entry)
    ...
    relationships = {"callers": [], "callees": [], "usages": []}
    if include_relationships:
        for symbol in trimmed_symbols[:3]:
            callers = self.tool_callers(...)
            callees = self.tool_callees(...)
            references = self.find_references(...)
```

**Context-pack pattern for search -> semantic hop**  
- lines 1748-1799
```python
def tool_context(...):
    raw = self.context_pack(...)
    payload = self._pack_single_payload(
        raw.model_dump(mode="json"),
        budget_tokens=effective_budget_tokens,
        essential_keys=_CONTEXT_ESSENTIAL_KEYS,
        ...
        base_tokens_saved=raw.tokens_saved_vs_full_files,
    )
```

**Dedicated usages/call-graph wrappers**  
- lines 1922-2030
```python
def tool_usages(...):
    payload = self.find_references(...)
    if "error" not in payload:
        self._cache_set("code.usages", cache_args, payload)

def tool_callers(...):
    return self._tool_call_graph("callers", ...)

def tool_callees(...):
    return self._tool_call_graph("callees", ...)
```

**Use this for Phase 1:** do not replace these tools with more fuzzy search; route grounded search results into them.

---

### `src/atelier/core/capabilities/semantic_file_memory/capability.py` (service, file-I/O)

**Analog:** `src/atelier/core/capabilities/semantic_file_memory/capability.py`

**Smart read mode-selection pattern**  
- lines 281-394
```python
def smart_read(...):
    if range_spec:
        ...
        result.update({"mode": "range", "range": f"{start}-{end}", "content": content, ...})
        return result

    if not expand and effective_loc > outline_threshold and language == "python":
        ...
        result.update({"mode": "outline", "outline": outline.model_dump(mode="json"), ...})
        return result
    ...
    result.update({"mode": "full", "content": source, "tokens_saved": ...})
```

**Use this for Phase 1:** preserve cheap grounded reads via range/outline/full, not by inventing a second read path.

---

### `src/atelier/core/capabilities/tool_supervision/bash_exec.py` (middleware, request-response)

**Analog:** `src/atelier/core/capabilities/tool_supervision/bash_exec.py`

**Shell rewrite policy pattern**  
- lines 56-113 and 133-172
```python
def _rewrite_cat(tokens: list[str]) -> CommandPolicyDecision:
    return CommandPolicyDecision(
        category="file-read",
        action="rewrite",
        reason="Use Atelier read for file content access",
        rewrite_target="read",
        rewrite_payload={"file_path": tokens[1]},
    )
...
if head == "cat":
    return _rewrite_cat(tokens)
if head in {"rg", "grep"}:
    return _rewrite_search(tokens, head)
```

**Compact execution result pattern**  
- lines 175-257
```python
def run_command(...):
    policy = classify_command(command)
    if policy.action == "block":
        return RunResult(..., policy_reason=policy.reason, ...)
    ...
    stdout_compact, lines_omitted, chars_omitted = _head_tail_lines(...)
    return RunResult(
        stdout=stdout_compact,
        stderr=stderr_compact,
        exit_code=exit_code,
        truncated=lines_omitted > 0,
        rewrite_target=policy.rewrite_target,
        rewrite_payload=policy.rewrite_payload,
    )
```

**Use this for Phase 1:** keep host shell behavior aligned with Search-first defaults via rewrite/advice, not hard rewrites in random places.

---

### `integrations/claude/plugin/hooks/pre_tool_use.py` and `integrations/claude/plugin/hooks/user_prompt.py` (middleware, event-driven)

**Analog:** same files

**Soft grounding nudge pattern**  
- `integrations/claude/plugin/hooks/pre_tool_use.py` lines 62-84
```python
def main() -> int:
    ...
    if not _is_dev_mode():
        print(json.dumps({"decision": "allow"}))
        return 0
    ...
    msg = (
        f"Atelier: `{target}` is in a risky domain ... "
        "Call `context` with your current goal before editing."
    )
    print(json.dumps({"decision": "ask", "reason": msg}))
```

**Compact/host nudge pattern**  
- `integrations/claude/plugin/hooks/user_prompt.py` lines 193-243
```python
def _emit_compact_warning(pct: int) -> None:
    msg = (
        f"[Atelier] Context estimated at ~{pct}% of window. "
        "Call mcp__atelier__compact now, then tell the user to run /compact "
        "before starting multi-step work."
    )
    sys.stdout.write(json.dumps({"type": "context", "content": msg}) + "\n")

...
if transcript_path:
    pct = _estimate_context_pct(transcript_path)
    if pct is not None and pct >= _COMPACT_WARN_PCT:
        _emit_compact_warning(pct)
```

**Use this for Phase 1:** keep nudges soft and host-edge only; reserve hard edit gates for Phase 2.

---

### Tests for Phase 1 (benchmark-first, non-bloated)

**Unit test pattern for new search-first composition**  
- `tests/core/test_search_read.py` lines 133-304
```python
result = search_read(query="ReasonBlock", path=str(tmp_path))
assert isinstance(result, SearchReadResult)
...
assert result.cache_hit is False
assert second.cache_hit is True
...
with pytest.raises(ValueError, match="search_read rejected"):
    search_read(query="foo; rm -rf /", path=str(tmp_path))
```

**Benchmark-baseline assertions**  
- `tests/infra/test_search_read_token_savings.py` lines 105-172
```python
naive_tokens = _naive_token_count(grep_output, file_contents)
inflated_full_read_tokens = _count_tokens(grep_output + "".join(file_contents.values()))
...
assert naive_tokens == _count_tokens(grep_output)
assert inflated_full_read_tokens > naive_tokens
assert result.tokens_saved_vs_naive == max(0, naive_tokens - smart_tokens)
```

- `tests/core/test_smart_search_baseline.py` lines 12-31
```python
assert _naive_bytes_for_matches(matches, mode="chunks") == len(str(path))
...
assert baseline == len("\n".join(lines[:_CLAUDE_READ_LINE_LIMIT]))
```

**Gateway contract tests**  
- `tests/gateway/test_p0_mcp_surfaces.py` lines 41-98
```python
result = tool_smart_search({... "include_meta": True})
assert result["backend"] == "zoekt"
...
search_tool = TOOLS["search"]
assert "query" in search_tool["description"]
assert "grep" in search_tool["description"]
assert "path" in properties
assert "file_path" not in properties
```

- `tests/gateway/test_mcp_tool_handlers.py` lines 860-877 and 1237-1312
```python
read_payload = _result(_call("read", {"path": str(target)}))
search_payload = _result(_call("search", {"query": "needle", "path": str(tmp_path)}))
grep_payload = _result(_call("grep", {"path": str(target), "content_regex": "needle"}))
```

```python
payload = tool_code({... "op": "search", "mode": "semantic", "budget_tokens": 220})
fake_engine.tool_search.assert_called_once_with(..., budget_tokens=220)
```

**Semantic-regression tests**  
- `tests/core/test_code_context.py` lines 1306-1362 and 1887-1985
```python
payload = engine.tool_search("func", limit=20, budget_tokens=255)
assert payload["total_tokens"] <= 255
...
payload = engine.tool_usages(query="OrderService", budget_tokens=4000)
assert payload["reference_count"] >= 1
...
payload = engine.tool_explore("OrderService", ..., budget_tokens=6000)
assert payload["entry_points"]
assert payload["relationships"]["callers"] is not None
```

## Shared Patterns

### Thin gateway, core-owned behavior
**Sources:** `src/atelier/gateway/adapters/mcp_server.py` lines 93-140, 4814-4895  
**Apply to:** all Phase 1 public tool changes

```python
def mcp_tool(...):
    ...
    def handler_wrapper(args: dict[str, Any]) -> Any:
        validated = ArgsModel.model_validate(args)
        return func(**validated.model_dump())

payload = smart_search(...)
```

### Memory/bootstrap preservation
**Sources:** `src/atelier/core/runtime/engine.py` lines 88-214; `src/atelier/core/service/bootstrap_context.py` lines 112-128; `src/atelier/core/capabilities/archival_recall/capability.py` lines 60-107  
**Apply to:** any search-first simplification that touches context seeding

```python
bootstrap_context, bootstrap_blocks = render_bootstrap_context(memory_store, bootstrap_repo_id)
...
passages, _ = capability.recall(agent_id=agent_id, query=task, top_k=3)
memory_context = render_memory_facts_for_agent(fact_blocks) + render_memory_for_agent(scoped_passages)
context = reasonblock_context + bootstrap_context + memory_context
```

### Grounded batch edits only after search/read
**Sources:** `src/atelier/gateway/adapters/mcp_server.py` lines 2861-2945; `src/atelier/core/capabilities/tool_supervision/rich_edit.py` lines 245-340; `src/atelier/core/capabilities/tool_supervision/post_edit_hooks.py` lines 231-318  
**Apply to:** low-roundtrip editing work in Phase 1

```python
result = apply_rich_edits(edits, atomic=atomic, repo_root=repo_root)
...
if not result.get("failed") and not result.get("rolled_back"):
    hook_result = run_post_edit_hooks(...)
...
if applied_count > 1:
    result.setdefault("calls_saved", applied_count - 1)
```

### Traceability and benchmark evidence
**Sources:** `src/atelier/infra/runtime/run_ledger.py` lines 118-171, 191-240, 293-429; `tests/infra/test_search_read_token_savings.py` lines 105-172  
**Apply to:** any Phase 1 savings or roundtrip claim

```python
def record_tool_call(...):
    return self.record("tool_call", f"{tool}({signature})", {...})

def record_call(...):
    self.token_count += rec.input_tokens + rec.output_tokens
    return self.record("tool_call", f"llm:{operation}({model})", {...})
```

## No Exact Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| `src/atelier/core/capabilities/grounded_loop/search_first.py` | service | transform | No dedicated `grounded_loop/` package exists yet; compose from `smart_search.py`, `search_read.py`, and `code_context/engine.py` rather than inventing a new style. |

## Metadata

**Analog search scope:** `src/atelier/gateway/adapters/`, `src/atelier/core/capabilities/`, `src/atelier/core/runtime/`, `src/atelier/core/service/`, `integrations/claude/plugin/hooks/`, `tests/core/`, `tests/gateway/`, `tests/infra/`  
**Files scanned:** 25 targeted files  
**Pattern extraction date:** 2026-06-02
