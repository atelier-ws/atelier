# Phase 02: execution-kernel-mvp - Pattern Map

**Mapped:** 2026-06-03  
**Files analyzed:** 18  
**Analogs found:** 17 / 18

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `src/atelier/core/capabilities/autopilot/workflow_config.py` | model | transform | `src/atelier/core/capabilities/autopilot/workflow_config.py` | exact |
| `src/atelier/core/capabilities/autopilot/factory.py` | service | file-I/O | `src/atelier/core/capabilities/autopilot/factory.py` | exact |
| `src/atelier/core/capabilities/autopilot/<new session-workflow helper>.py` | utility | transform | `workflow_config.py` + `factory.py` | partial |
| `src/atelier/gateway/adapters/mcp_server.py` | gateway | request-response | `src/atelier/gateway/adapters/mcp_server.py` | exact |
| `src/atelier/infra/runtime/run_ledger.py` | service | event-driven | `src/atelier/infra/runtime/run_ledger.py` | exact |
| `src/atelier/core/capabilities/plugin_runtime.py` | service | event-driven | `src/atelier/core/capabilities/plugin_runtime.py` | exact |
| `src/atelier/infra/runtime/session_report.py` | service | transform | `src/atelier/infra/runtime/session_report.py` | exact |
| `integrations/claude/plugin/hooks/pre_tool_use.py` | middleware | request-response | `integrations/claude/plugin/hooks/pre_tool_use.py` | exact |
| `integrations/claude/plugin/hooks/user_prompt.py` | middleware | event-driven | `integrations/claude/plugin/hooks/user_prompt.py` | exact |
| `integrations/claude/plugin/hooks/session_start.py` | middleware | event-driven | `integrations/claude/plugin/hooks/session_start.py` | exact |
| `src/atelier/bench/mode.py` | utility | request-response | `src/atelier/bench/mode.py` | exact |
| `tests/core/test_autopilot.py` | test | transform | `tests/core/test_autopilot.py` | exact |
| `tests/gateway/test_mcp_workflow_state.py` | test | request-response | `tests/gateway/test_mcp_workflow_state.py` | exact |
| `tests/infra/test_run_ledger.py` | test | event-driven | `tests/infra/test_run_ledger.py` | exact |
| `tests/infra/test_session_report.py` | test | transform | `tests/infra/test_session_report.py` | exact |
| `tests/integrations/test_claude_grounded_loop_hooks.py` | test | event-driven | `tests/integrations/test_claude_grounded_loop_hooks.py` | exact |
| `tests/core/test_bench_mode.py` | test | request-response | `tests/core/test_bench_mode.py` | exact |
| `tests/gateway/test_claude_user_prompt_hook.py` | test | file-I/O | `tests/gateway/test_claude_user_prompt_hook.py` | exact |

## Pattern Assignments

### `src/atelier/core/capabilities/autopilot/workflow_config.py` (model, transform)

**Analog:** `src/atelier/core/capabilities/autopilot/workflow_config.py`

**Typed state pattern** (`35-73`):
```python
@dataclass(frozen=True)
class WorkflowState:
    current_step: str = "exploration"
    last_step: str = ""
    session_phase: str = "explore"
    sticky_window: int = 0
    advisory_emitted_steps: tuple[str, ...] = ()
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "current_step": self.current_step,
            "last_step": self.last_step,
            "session_phase": self.session_phase,
            "sticky_window": self.sticky_window,
            "advisory_emitted_steps": list(self.advisory_emitted_steps),
            "updated_at": self.updated_at,
        }
```

**Normalization pattern** (`91-111`):
```python
def workflow_state_from_mapping(
    raw: Mapping[str, Any] | None,
    config: WorkflowConfig | None = None,
) -> WorkflowState:
    cfg = config or default_workflow_config()
    data = raw if isinstance(raw, Mapping) else {}
    current = normalize_workflow_step(str(data.get("current_step") or data.get("workflow_step") or ""))
    ...
    return WorkflowState(
        current_step=current,
        last_step=last,
        session_phase=session_phase_for_step(current),
        sticky_window=sticky,
        advisory_emitted_steps=emitted,
        updated_at=str(data.get("updated_at") or ""),
    )
```

**Monotonic transition pattern** (`118-146`, `149-174`):
```python
if _STEP_RANK.get(candidate, 0) < _STEP_RANK.get(prior_state.current_step, 0):
    return prior_state.current_step
...
return (
    WorkflowState(
        current_step=current,
        last_step=prior_state.current_step if changed else prior_state.last_step,
        session_phase=session_phase_for_step(current),
        sticky_window=step_cfg.sticky_window,
        advisory_emitted_steps=tuple(sorted(emitted)),
        updated_at=datetime.now(UTC).isoformat(),
    ),
    step_cfg,
    emit_advisory,
)
```

---

### `src/atelier/core/capabilities/autopilot/factory.py` (service, file-I/O)

**Analog:** `src/atelier/core/capabilities/autopilot/factory.py`

**Workspace state path + read pattern** (`134-149`):
```python
def _session_state_path(store_root: str, workspace: str) -> Path:
    import hashlib
    ws_hash = hashlib.sha256(str(Path(workspace).resolve()).encode("utf-8")).hexdigest()[:12]
    return Path(store_root) / "workspaces" / ws_hash / "session_state.json"

def _read_session_state(store_root: str, workspace: str) -> dict[str, Any]:
    path = _session_state_path(store_root, workspace)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}
```

**Atomic write pattern** (`152-170`):
```python
with tempfile.NamedTemporaryFile(
    mode="w",
    dir=path.parent,
    suffix=".tmp",
    delete=False,
    encoding="utf-8",
) as tmp:
    json.dump(state, tmp, indent=2)
    tmp_path = tmp.name
Path(tmp_path).replace(path)
```

**Workflow persistence pattern** (`191-221`):
```python
session_state = _read_session_state(store_root, workspace)
workflow_config = default_workflow_config()
prior_workflow = workflow_state_from_mapping(session_state.get("workflow"), workflow_config)
workflow_state, step_cfg, emit_advisory = advance_workflow_state(...)
session_state["workflow"] = workflow_state.to_dict()
...
enriched_payload.update(
    {
        "workflow_step": workflow_state.current_step,
        "session_phase": workflow_state.session_phase,
        "workflow_share_context": step_cfg.share_context,
        "workflow_sticky_window": step_cfg.sticky_window,
        "workflow_vote_advisory": emit_advisory,
    }
)
...
_write_session_state(store_root, workspace, session_state)
```

---

### `src/atelier/core/capabilities/autopilot/<new session-workflow helper>.py` (utility, transform)

**Analog:** use `workflow_config.py` for typed state and `factory.py` for persistence

**Copy from `workflow_config.py`** (`35-73`, `91-111`): typed dataclass + `to_dict()` + `from_mapping` normalization.  
**Copy from `factory.py`** (`134-170`, `191-221`): hashed workspace path + atomic JSON writes + enrich-before-persist flow.

**Planner note:** no exact existing analog for a structured “current task / outputs / review decision” helper; extend the existing dataclass/normalization style rather than inventing a new storage subsystem.

---

### `src/atelier/gateway/adapters/mcp_server.py` (gateway, request-response)

**Analog:** `src/atelier/gateway/adapters/mcp_server.py`

**Workspace state helpers** (`596-635`):
```python
def _workspace_session_state_file() -> Path:
    import hashlib
    ws = str(Path(os.environ.get("CLAUDE_WORKSPACE_ROOT") or os.getcwd()).resolve())
    ws_hash = hashlib.sha256(ws.encode()).hexdigest()[:12]
    return _atelier_root() / "workspaces" / ws_hash / "session_state.json"

def _read_workspace_session_state() -> dict[str, Any]:
    ...
def _write_workspace_session_state(state: dict[str, Any]) -> None:
    ...
```

**Trace/event recording seam** (`1910-1941`):
```python
if event_type:
    led.record("note", f"event:{redact(event_type)}", _redact_json_strings(event_payload))

trace = Trace.model_validate(payload)
rt.store.record_trace(trace)
...
led.close(status=status)
led.persist()
rtc.persist()
```

**Edit diff capture pattern** (`2678-2719`, `2886-2936`):
```python
snapshots = _snapshot_paths(paths)
...
if not result.get("failed") and not result.get("rolled_back"):
    ...
    _compute_and_record_diffs(snapshots)
```

**Model/workflow carry-forward pattern** (`5646-5678`):
```python
workflow = _workflow_state_from_workspace()
session_state: dict[str, Any] = {
    "prior_errors": len(led.errors_seen) + len(led.repeated_failures),
    "cache_affinity_model": _latest_cache_affinity_model(led),
    "turn_number": turn_number,
    "recent_tool_calls": recent_tool_calls,
    ...
}
workflow_step = str(workflow.get("current_step") or workflow.get("workflow_step") or "").strip()
if workflow_step:
    session_state["workflow_step"] = workflow_step
session_phase = str(workflow.get("session_phase") or "").strip()
if session_phase:
    session_state["session_phase"] = session_phase
```

**Dispatcher seam for benchmark-only edit gate** (`5712-5771`, `5801-5855`):
```python
if method == "tools/call":
    name = params.get("name") or ""
    ...
    route_payload, route_state, route_workflow, route_step = _prepare_model_recommendation(...)
    handler: Callable[[dict[str, Any]], dict[str, Any]] = spec["handler"]
    ...
    try:
        with active_model_override(wrapper_model or None):
            result = handler(args)
    finally:
        _finalize_model_recommendation(...)

    with contextlib.suppress(Exception):
        outcome_capture.advance(
            led.session_id,
            tool_name=name,
            is_error=False,
            is_read_tool=name in _READ_TOOLS,
            writer=_make_outcome_writer(led),
        )
```

**Use this seam for Phase 2:** insert benchmark-only grounding check immediately before `handler(args)` for `edit`/write paths.

---

### `src/atelier/infra/runtime/run_ledger.py` (service, event-driven)

**Analog:** `src/atelier/infra/runtime/run_ledger.py`

**Plan/state fields** (`43-66`):
```python
self.current_plan: list[str] = []
self.files_touched: list[str] = []
self.tools_called: list[str] = []
...
self.current_blockers: list[str] = []
self.next_required_validation: str | None = None
```

**Event append pattern** (`70-116`):
```python
def set_plan(self, plan: list[str]) -> None:
    self.current_plan = list(plan)
    self.updated_at = _utcnow()

def record(self, kind: str, summary: str, payload: dict[str, Any] | None = None) -> LedgerEvent:
    event = LedgerEvent(kind=kind, summary=summary, payload=payload or {})
    self.events.append(event)
    self.updated_at = _utcnow()
    return event
```

**File-event pattern** (`164-171`):
```python
def record_file_event(self, path: str, event: str, diff: str | None = None) -> LedgerEvent:
    if path and path not in self.files_touched:
        self.files_touched.append(path)
    kind = "file_revert" if event == "revert" else "file_edit"
    payload = {"path": path, "event": event}
    if diff:
        payload["diff"] = diff
    return self.record(kind, f"{event}:{path}", payload)
```

**Checkpoint/event mirroring pattern** (`255-289`):
```python
ckpt = Checkpoint.create(...)
store = CheckpointStore(root or self._root)
store.save(ckpt)
self.record(
    "checkpoint",
    f"step={step_id} tool={tool_name} route={model_route}",
    ckpt.to_dict(),
)
```

**Snapshot persistence pattern** (`392-439`):
```python
return {
    "session_id": self.session_id,
    ...
    "current_plan": list(self.current_plan),
    ...
    "events": [to_jsonable(e) for e in self.events],
}
...
path.write_text(json.dumps(self.snapshot(), indent=2), encoding="utf-8")
```

---

### `src/atelier/core/capabilities/plugin_runtime.py` (service, event-driven)

**Analog:** `src/atelier/core/capabilities/plugin_runtime.py`

**Session-event append pattern** (`1191-1208`):
```python
record = {
    "at_ms": _now_ms(payload),
    "event": event,
    "tool_name": payload.get("tool_name"),
    "subagent_type": ...,
}
with path.open("a", encoding="utf-8") as handle:
    handle.write(json.dumps(record, sort_keys=True) + "\n")
```

**Session stats mutation pattern** (`1211-1268`):
```python
state.setdefault("event_counts", {})
...
event = str(payload.get("hook_event_name") or payload.get("event") or "")
if event:
    state["event_counts"][event] = int(state["event_counts"].get(event, 0) or 0) + 1
...
if event == "PostToolUse":
    tool_name = str(payload.get("tool_name") or "")
    state["total_tool_calls"] = int(state.get("total_tool_calls", 0)) + 1
    ...
path.write_text(json.dumps(state, indent=2), encoding="utf-8")
_append_session_event(root, session_id, payload)
```

**Progress/nudge fanout pattern** (`1536-1577`):
```python
def build_session_progress_optimization_output(root: str | Path, payload: dict[str, Any]) -> dict[str, Any]:
    event = str(payload.get("hook_event_name") or payload.get("event") or "")
    if event not in {"PostToolUse", "PostToolUseFailure"}:
        return {"no_output": True}
    ...
    if session_stats_need_no_edit_notice(updated, now_ms=now_ms):
        outputs.append({...})
    updated, quality_output = _maybe_emit_quality_notice(updated, now_ms=now_ms)
    outputs.append(quality_output)
    updated, loop_output = _maybe_emit_loop_notice(root, updated, now_ms=now_ms)
    outputs.append(loop_output)
```

---

### `src/atelier/infra/runtime/session_report.py` (service, transform)

**Analog:** `src/atelier/infra/runtime/session_report.py`

**Ledger snapshot -> report pattern** (`423-556`):
```python
raw_events: list[dict[str, Any]] = snapshot.get("events") or []
...
routing_downtiered, routing_saved, lesson_applications, cost_cap_fired = _read_routing_savings(raw_events)
compact_count, compact_saved = _read_compact_savings(session_id, root)
compression_count, compression_saved, compression_rows = _read_context_compression_savings(session_id, root)
total_saved = round(routing_saved + compact_saved + compression_saved, 6)

return SessionReport(
    session_id=session_id,
    ...
    routing_downtiered_turns=routing_downtiered,
    routing_savings_usd=routing_saved,
    compact_events=compact_count,
    compact_savings_estimate_usd=compact_saved,
    ...
)
```

**Human-facing render pattern** (`614-705`):
```python
lines.append("Atelier savings")
if report.routing_downtiered_turns:
    lines.append(...)
...
if report.compact_events:
    lines.append(...)
...
lines.append(f"  {'Total saved this session:':<32}{_fmt_cost(report.total_atelier_savings_usd).rjust(cost_w)}")
```

Use this for new workflow/progress/report surfaces instead of adding a parallel formatter.

---

### `integrations/claude/plugin/hooks/pre_tool_use.py` (middleware, request-response)

**Analog:** `integrations/claude/plugin/hooks/pre_tool_use.py`

**Fail-open parse + allowlist pattern** (`62-80`):
```python
try:
    payload = json.loads(sys.stdin.read() or "{}")
except (json.JSONDecodeError, TypeError):
    return 0

if not _is_dev_mode():
    print(json.dumps({"decision": "allow"}))
    return 0

tool_name = str(payload.get("tool_name") or payload.get("tool") or "").lower()
if tool_name and tool_name not in {"edit", "multiedit", "write"}:
    print(json.dumps({"decision": "allow"}))
    return 0
```

**Host interception decision pattern** (`77-90`):
```python
tool_input = payload.get("tool_input", {}) or {}
target = tool_input.get("file_path") or tool_input.get("path") or tool_input.get("filename") or ""
if not target or not _is_risky(target):
    print(json.dumps({"decision": "allow"}))
    return 0

msg = (
    f"Atelier: `{target}` is in a risky domain ... Ground the change with `search` or `read` ..."
)
print(json.dumps({"decision": "ask", "reason": msg}))
```

Use same shape for benchmark-mode hard block or ask/deny decisions.

---

### `integrations/claude/plugin/hooks/user_prompt.py` (middleware, event-driven)

**Analog:** `integrations/claude/plugin/hooks/user_prompt.py`

**Atomic session-state write pattern** (`46-85`):
```python
def _session_state_path() -> Path:
    ...
    return root / "workspaces" / h / "session_state.json"

def _write_session_state(state: dict[str, Any]) -> None:
    ...
    with tempfile.NamedTemporaryFile(...):
        json.dump(state, tmp, indent=2)
        tmp_path = tmp.name
    Path(tmp_path).replace(path)
```

**Grounding nudge pattern** (`208-221`):
```python
def _looks_like_multi_file_edit_prompt(prompt: str) -> bool:
    ...
    if any(term in lowered for term in _GROUNDED_TERMS):
        return False
    ...
def _emit_grounded_batching_nudge() -> None:
    msg = "[Atelier] Ground multi-file changes with search or read first, then batch related edits in one edit call."
    sys.stdout.write(json.dumps({"type": "context", "content": msg}) + "\n")
```

**Hook main flow** (`229-266`):
```python
prompt: str = payload.get("prompt", "") or ""
if not prompt.strip():
    return 0
...
if transcript_path:
    pct = _estimate_context_pct(transcript_path)
    if pct is not None and pct >= _COMPACT_WARN_PCT:
        _emit_compact_warning(pct)
if _looks_like_multi_file_edit_prompt(prompt):
    _emit_grounded_batching_nudge()
...
_persist_last_user_prompt(stored_prompt)
...
_append_prompt_event(session_id, stored_prompt)
```

---

### `integrations/claude/plugin/hooks/session_start.py` (middleware, event-driven)

**Analog:** `integrations/claude/plugin/hooks/session_start.py`

**Session bridge pattern** (`39-63`):
```python
def _session_state_path() -> Path:
    ...
    return root / "workspaces" / h / "session_state.json"

def _write_session_state(updates: dict[str, Any]) -> None:
    ...
    state = _read_session_state()
    state.update(updates)
    p.write_text(json.dumps(state, indent=2), encoding="utf-8")
```

**Run-file note append pattern** (`121-171`):
```python
events: list[dict[str, Any]] = data.setdefault("events", [])
events.append(
    {
        "kind": "note",
        "at": datetime.datetime.now(datetime.UTC).isoformat(),
        "summary": f"session {source} — {model or 'unknown model'}",
        "payload": {
            "session_id": session_id,
            "source": source,
            "model": model,
            "cwd": cwd,
            "transcript_path": transcript_path,
            "event": "SessionStart",
        },
    }
)
```

**Bootstrapping pattern** (`191-220`):
```python
if session_id_raw:
    state_update: dict[str, Any] = {
        "session_id": session_id_raw,
        "atelier_root": str(_atelier_root()),
    }
    if model:
        state_update["model"] = model
    if transcript_path:
        state_update["transcript_path"] = transcript_path
    _write_session_state(state_update)
...
_append_session_start_event(session_id, source, model, cwd, transcript_path)
...
run_and_emit("session_start", {"cwd": cwd})
```

---

### `src/atelier/bench/mode.py` (utility, request-response)

**Analog:** `src/atelier/bench/mode.py`

**Singleton env gate pattern** (`24-37`):
```python
def bootstrap() -> None:
    global _mode
    if _mode is not None:
        return
    raw = os.environ.get("ATELIER_BENCH_MODE", "on").strip().lower()
    _mode = BenchMode.OFF if raw == "off" else BenchMode.ON

def is_off() -> bool:
    if _mode is None:
        bootstrap()
    return _mode == BenchMode.OFF
```

**Subprocess env propagation pattern** (`47-61`):
```python
def make_arm_env(atelier_root: Path, *, mode: BenchMode | None = None) -> dict[str, str]:
    env: dict[str, str] = dict(os.environ)
    env["ATELIER_ROOT"] = str(atelier_root)
    ...
    env["ATELIER_BENCH_MODE"] = mode_to_use.value
    return env
```

Use this instead of ad hoc benchmark env parsing.

---

### Test file patterns

#### `tests/core/test_autopilot.py`
**Analog:** same file  
Use direct state/assertion style for workflow monotonicity and persisted JSON (`263-340`):
```python
planning, _, emit_advisory = advance_workflow_state(...)
execution, _, _ = advance_workflow_state("post_edit", {"touched_files": ["src/a.py"]}, planning, config)
...
payload = json.loads(files[0].read_text(encoding="utf-8"))
assert payload["workflow"]["current_step"] == "planning"
assert payload["workflow"]["session_phase"] == "transition"
```

#### `tests/gateway/test_mcp_workflow_state.py`
**Analog:** same file  
Use hashed workspace fixture + persisted session state assertions (`17-98`):
```python
monkeypatch.setenv("ATELIER_ROOT", str(root))
monkeypatch.setenv("CLAUDE_WORKSPACE_ROOT", str(workspace))
...
path.write_text(json.dumps({"workflow": {...}}), encoding="utf-8")
state = _model_recommendation_state(led, {})
assert state["workflow_step"] == "planning"
```

#### `tests/infra/test_run_ledger.py`
**Analog:** same file  
Use snapshot-first assertions (`10-61`):
```python
led.set_plan(["step 1", "step 2"])
led.record_command("pytest", ok=False, error_signature="abc123")
...
snap = led.snapshot()
assert snap["current_plan"] == ["step 1", "step 2"]
```

#### `tests/infra/test_session_report.py`
**Analog:** same file  
Use savings-aggregation tests over synthetic ledger events (`138-336`):
```python
events = [_model_rec_event(cost_saved_usd=0.05), ...]
downtiered, saved, lesson_applications, cost_cap_fired = _read_routing_savings(events)
assert abs(saved - 0.08) < 1e-6
...
jl.write_text(json.dumps({"session_id": "abc123", "lever": "session_compaction", "cost_saved_usd": 0.30}) + "\n")
report = build_report(snap, tmp_path)
assert report.compact_events == 1
```

#### `tests/integrations/test_claude_grounded_loop_hooks.py`
**Analog:** same file  
Use `stdin` patch + captured JSON lines for hook behavior (`9-111`):
```python
monkeypatch.setattr(pre_tool_use.sys, "stdin", io.StringIO(json.dumps({...})))
assert pre_tool_use.main() == 0
payload = json.loads(capsys.readouterr().out)
assert payload["decision"] == "ask"
```

#### `tests/core/test_bench_mode.py`
**Analog:** same file  
Use env-reset fixture + singleton assertions (`36-210`):
```python
monkeypatch.setattr(_bm, "_mode", None)
monkeypatch.delenv("ATELIER_BENCH_MODE", raising=False)
...
assert is_off() is True
```

#### `tests/gateway/test_claude_user_prompt_hook.py`
**Analog:** same file  
Use subprocess hook invocation and direct `session_state.json` inspection (`14-44`):
```python
subprocess.run([sys.executable, str(HOOK)], input=json.dumps(payload), ...)
session_state = atelier_root / "workspaces" / workspace_hash / "session_state.json"
data = json.loads(session_state.read_text(encoding="utf-8"))
assert data["last_user_prompt"] == "fix the auth flow"
```

---

## Shared Patterns

### Workspace live-state persistence
**Sources:**  
- `src/atelier/core/capabilities/autopilot/factory.py:134-170`  
- `src/atelier/gateway/adapters/mcp_server.py:596-635`  
- `integrations/claude/plugin/hooks/user_prompt.py:46-85`

**Apply to:** all workflow/task live-state changes

```python
ws_hash = hashlib.sha256(str(Path(workspace).resolve()).encode("utf-8")).hexdigest()[:12]
path = Path(store_root) / "workspaces" / ws_hash / "session_state.json"
...
with tempfile.NamedTemporaryFile(..., dir=path.parent, delete=False, encoding="utf-8") as tmp:
    json.dump(state, tmp, indent=2)
    tmp_path = tmp.name
Path(tmp_path).replace(path)
```

**Note:** prefer atomic temp-file replace when mutating shared hook/MCP state.

---

### Typed workflow normalization
**Source:** `src/atelier/core/capabilities/autopilot/workflow_config.py:56-111`

**Apply to:** any new plan-review/current-task/task-output substate

```python
@dataclass(frozen=True)
class WorkflowState: ...
...
data = raw if isinstance(raw, Mapping) else {}
current = normalize_workflow_step(str(data.get("current_step") or data.get("workflow_step") or ""))
```

**Note:** normalize unknown/stale JSON input before using it.

---

### RunLedger event mirroring
**Sources:**  
- `src/atelier/infra/runtime/run_ledger.py:103-171`  
- `src/atelier/gateway/adapters/mcp_server.py:1910-1941`

**Apply to:** workflow transitions, plan approval/revision, current-task progress, benchmark edit blocks

```python
led.record("note", "event:...", payload)
...
led.record_file_event(path=path, event="edit", diff=diff_text)
...
led.persist()
```

**Note:** keep `session_state.json` as live state, `RunLedger` as durable audit/report input.

---

### Reporting fanout
**Sources:**  
- `src/atelier/core/capabilities/plugin_runtime.py:1211-1268`  
- `src/atelier/core/capabilities/plugin_runtime.py:1536-1577`  
- `src/atelier/infra/runtime/session_report.py:423-556`

**Apply to:** any new workflow/progress events that should show up in hooks/status/report/dashboard

```python
state["event_counts"][event] = int(state["event_counts"].get(event, 0) or 0) + 1
...
outputs.append(quality_output)
outputs.append(loop_output)
...
report = build_report(snapshot, root)
```

---

### Benchmark-mode detection
**Source:** `src/atelier/bench/mode.py:24-61`

**Apply to:** all benchmark-only edit gating

```python
raw = os.environ.get("ATELIER_BENCH_MODE", "on").strip().lower()
_mode = BenchMode.OFF if raw == "off" else BenchMode.ON
```

---

### MCP + Claude edit interception seams
**Sources:**  
- `src/atelier/gateway/adapters/mcp_server.py:5712-5771`  
- `src/atelier/gateway/adapters/mcp_server.py:5801-5855`  
- `integrations/claude/plugin/hooks/pre_tool_use.py:72-90`

**Apply to:** EXEC-05 benchmark-only edit discipline

```python
if method == "tools/call":
    name = params.get("name") or ""
    ...
    result = handler(args)
```

```python
tool_name = str(payload.get("tool_name") or payload.get("tool") or "").lower()
if tool_name and tool_name not in {"edit", "multiedit", "write"}:
    print(json.dumps({"decision": "allow"}))
    return 0
```

**Note:** MCP seam is the hard backend gate; Claude hook is the host-native front-door.

---

### Grounding-evidence shape
**Source:** `src/atelier/core/capabilities/grounded_loop/search_first.py:23-77`

**Apply to:** benchmark edit gate evidence checks

```python
"follow_up": {
    "read": {"tool": "read", "path": match_path},
    "context": _context_follow_up(task=task, files=[match_path], mode="symbols"),
}
...
"handoff": {
    "read": {"tool": "read"},
    "context": _context_follow_up(task=task, files=match_paths, mode="symbols"),
    "memory": _context_follow_up(task=task, files=match_paths, mode="procedures"),
    "explore": {"tool": "explore", "query": query, "seed_files": match_paths},
}
```

**Note:** treat `search`, `read`, `context(mode="symbols")`, `explore`, `node`, `callers`, `callees`, `usages`, `impact` as grounding evidence; do not reuse `_READ_TOOLS` as the whole truth.

---

### Checkpoint / handover carry-forward
**Sources:**  
- `src/atelier/infra/runtime/checkpoint.py:37-90`  
- `src/atelier/infra/runtime/checkpoint.py:118-124`  
- `src/atelier/infra/runtime/context_compressor.py:119-181`  
- `src/atelier/infra/runtime/context_compressor.py:514-543`

**Apply to:** resume/handover support for current task state

```python
@dataclass
class Checkpoint:
    session_id: str
    step_id: int
    transaction_id: str
    tool_name: str
    model_route: str
    input_hash: str
    output_hash: str
    compact_state: str = ""
```

```python
class HandoverPacket:
    ...
    @classmethod
    def from_ledger(cls, ledger: RunLedger, compact_state: CompactState, *, workspace_root: Path | None = None) -> HandoverPacket:
        decisions = _dedupe_preserve_order([...])
        next_steps = _extract_next_steps(ledger)
        context = _handover_context(ledger, compact_state, workspace_root=workspace_root)
```

**Note:** checkpoints currently store hashes + compact text, not structured task outputs; keep structured outputs in workspace live state.

---

## Eval-Parity Runner/Defaults/Solver Addendum

Added after the Eval implementation parity audit. These patterns guide 02-04, 02-05, and 02-06.

### `src/atelier/core/capabilities/workflow_schema.py`

**Role:** model, validation  
**Analog:** `src/atelier/core/capabilities/autopilot/workflow_config.py`

- Define validated workflow and step records for `agent`, `tool`, and `shell`.
- Validate `next_steps`, `fork_from`, prompt/command/tool requirements, output ids, JSON output flags, and timeout fields before execution.
- Keep definitions serializable so defaults can bootstrap and test fixtures can round-trip them.

### `src/atelier/core/capabilities/workflow_context.py`

**Role:** utility, persistence  
**Analog:** `autopilot/factory.py` workspace-state helpers plus `RunLedger` event snapshots.

- Store step outputs in canonical workspace workflow state, not a new sidecar store.
- Provide copy-on-write forked context from prior steps.
- Resolve template variables from prior step outputs through a structured map, not ad hoc string scraping.

### `src/atelier/core/capabilities/workflow_runner.py`

**Role:** service, orchestration  
**Analog:** Eval `executeWorkflow`, adapted to Atelier's core/gateway split.

- Execute a validated DAG with injected `agent`, `tool`, and `shell` handlers so tests do not need model/network access.
- Persist step records with output, parsed JSON, status, duration, usage/cost fields, and artifact references.
- Batch only explicitly safe read/search/code-intel tool steps; serialize writes, shell mutations, and interactive decisions.
- Emit workflow step start/done/fail events through `RunLedger`.

### `src/atelier/core/capabilities/default_definitions.py`

**Role:** model, registry  
**Analog:** `scripts/render_mode_surfaces.py` mode loading and frontmatter rendering, plus existing generated host surface tests.

- Canonicalize agent/skill/runtime roles before rendering them into host-specific artifacts.
- Include role ids for `code`, `general`, `explore`, `plan`, `execute`, `review`, `research`, and `solve`.
- Store or reference name, description, prompt source/body, tool allow/deny policy, model/provider tier where owned, effort, max turns/tokens, workflow usage, and host projections.
- Runtime-only roles do not need every host projection, but they must still be inspectable and consumable by the owned runner/solver.

### `scripts/render_mode_surfaces.py`

**Role:** renderer, generated host surfaces  
**Analog:** existing mode-doc renderer.

- Continue rendering current Claude, OpenCode, Antigravity, shared skill, and Codex skill surfaces.
- Read role/projection metadata from canonical defaults where possible.
- Preserve host-specific schema constraints, especially Claude plugin auto-discovery of agents/skills/hooks/MCP.
- Provide or preserve check mode so generated files can be verified in tests/CI.

### `tests/gateway/test_agent_cli_install_artifacts.py`

**Role:** static distribution contract  
**Analog:** existing install artifact tests.

- Extend existing checks to prove generated files are present and synced with canonical defaults.
- Keep tests host-CLI-free.
- Cover plugin manifests, agents, skills, workflows, MCP templates, and installer staging behavior.

### `src/atelier/core/capabilities/workflow_defaults.py`

**Role:** utility, bootstrap  
**Analog:** Eval non-overwriting default bootstrap.

- Embed or reference minimal default workflow/solver/agent definitions.
- Write missing files only and never overwrite project-local user changes.
- Return deterministic created/skipped/invalid receipts.

### `src/atelier/core/capabilities/benchmark_solver.py`

**Role:** service, benchmark runtime  
**Analog:** Eval solver profile plus headless workflow artifacts, adapted to TerminalBench arms.

- Consume solver rules from canonical defaults; do not duplicate solver prompt/rule text locally.
- Persist benchmark attempts with task prompt, changed files, failed commands, harness feedback, raw artifact paths, and retry count.
- Generate retry context from harness evidence and explicitly prevent blind repetition of failed commands.
- Keep provider/Docker execution injectable in tests.

### `benchmarks/terminalbench/agent_adapter.py`

**Role:** benchmark seam  
**Analog:** existing Claude-host adapter, with an added owned-solver arm.

- Preserve the existing Claude baseline and Atelier-hook arms unchanged.
- Add an explicit owned-solver mode that invokes the benchmark solver runtime.
- Emit artifacts into the existing benchmark run directory shape so aggregate/report tooling can consume them later.

---

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| `src/atelier/core/capabilities/autopilot/<new session-workflow helper>.py` | utility | transform | No exact existing module stores structured “plan review + current task + prior task outputs” as canonical typed substate; current analogs split between `workflow_config.py` and `factory.py`. |

## Metadata

**Analog search scope:** `src/atelier/core/capabilities/autopilot/`, `src/atelier/gateway/adapters/mcp_server.py`, `src/atelier/infra/runtime/`, `integrations/claude/plugin/hooks/`, `src/atelier/bench/`, relevant `tests/` files  
**Files scanned:** 18 targeted files + repo-wide `rg` over `src/`, `integrations/`, `tests/`  
**Pattern extraction date:** 2026-06-03

### Ready for Planning
Pattern mapping complete. Planner can now reference these analogs directly when composing phase plans.
