# Plan: split `gateway/adapters/mcp_server.py`

## Why

`mcp_server.py` is 7,664 lines / ~34K tokens. Session mining (May–Jun 2026, 350
Claude Code sessions) showed it is the single most expensive file in real usage:

- re-read 264× in one month (next worst file: 77×)
- 15× native-`Read` hard failures ("exceeds maximum allowed tokens"), each a wasted turn
- every agent task touching one tool pays outline/context cost for all ~19 tools

It also violates the repo invariant that gateway files are *dispatchers only*:
renderers, the test-contract gate, path suggestion, savings accounting, and
workflow execution logic all live inline today.

## Target shape

```
src/atelier/gateway/adapters/
  mcp_server.py          # thin shim: re-exports public names (TOOLS, serve, main,
                         # render_tool_result_text, mcp_tool) — keeps all existing
                         # imports and monkeypatch targets working
  mcp/
    protocol.py          # mcp_tool decorator, TOOLS registry, request dispatch,
                         # serve()/main(), JSON-RPC plumbing            (~119–260, 7100–7664)
    session.py           # ledger/session-state/savings accounting:
                         # _get_ledger, _append_*_savings, smart_state,
                         # workspace session bridge                    (~369–2120)
    rendering.py         # render_tool_result_text + _render_read_md/_render_grep_md/
                         # _render_search_md/_render_shell_text, dedup resource keys
    tools_read.py        # read tool, _smart_read_single, directory listing,
                         # not-found suggestions
    tools_edit.py        # edit schema, test-contract gate, snapshots/diffs,
                         # _SESSION_CREATED_FILES
    tools_shell.py       # shell tool + background session handling
    tools_code_intel.py  # symbols/node/callers/callees/impact/explore/usages/pattern
    tools_agent.py       # agent + workflow tools, owned-route selection (~831–1660)
    tools_context.py     # context/rescue/trace/verify/compact/sql/web_fetch
```

Logic that is genuinely domain logic (not dispatch) moves down to
`core/capabilities/` instead of into `mcp/` — candidates: the test-contract
gate (→ `tool_supervision`), path suggestions (→ `semantic_file_memory`),
savings accounting (→ a small `core/foundation` module).

## Constraints

- **No behavior change.** This is a mechanical move; every module keeps its
  function names. The shim re-exports so `from atelier.gateway.adapters.mcp_server
  import X` keeps working for tests, CLI runtime, and integrations.
- **Import cycles**: `protocol.py` must not import tool modules at top level;
  tools register themselves via `mcp_tool` at import time, so `mcp/__init__.py`
  imports tool modules once, in a fixed order.
- **Process-global state** (`_SESSION_CREATED_FILES`, savings counters,
  `_REGISTRY` users) must keep exactly one instance — keep them in the module
  that owns them and re-export; never copy.
- **CLI runtime** imports `render_tool_result_text`, `_read_dedup_resource`,
  `TOOLS` — these go through the shim unchanged.

## Phases

1. **Carve `rendering.py` + `tools_read.py`** (lowest coupling, highest read-cost
   payoff) → verify: `uv run pytest tests/gateway/test_mcp_tool_handlers.py
   tests/gateway/test_p0_mcp_surfaces.py tests/gateway/cli/test_runtime.py -q`
2. **Carve `tools_edit.py` + `tools_shell.py`** → same suite plus
   `tests/core/test_rich_edit.py tests/core/test_batch_edit_atomicity.py`.
3. **Carve `session.py` + `protocol.py`**; `mcp_server.py` becomes the shim →
   full `make lint && make typecheck && make test`.
4. **Carve remaining tool modules** (`tools_agent.py`, `tools_code_intel.py`,
   `tools_context.py`) → full gate again, plus one live smoke:
   `atelier mcp` handshake + read/edit/shell round-trip in a scratch workspace.
5. **Optional follow-up**: push gate/suggestion/savings logic down to
   `core/capabilities/` (separate PR; behavior-preserving refactor of each).

## Verification gate (every phase)

- `make lint && make typecheck`
- targeted pytest for the carved area, full `make test` at phases 3–4
- `python -c "from atelier.gateway.adapters.mcp_server import TOOLS; assert len(TOOLS) >= 19"`
- grep guard: no file under `gateway/adapters/mcp/` exceeds 1,500 lines.

## Risks

- Hidden import-order dependencies (decorator side effects) — mitigated by the
  fixed import list in `mcp/__init__.py` and the TOOLS-count assertion.
- Tests that monkeypatch `atelier.gateway.adapters.mcp_server.X` — the shim
  re-export keeps the attribute path alive; patching the shim still patches the
  single shared object as long as modules bind late (`from ... import` at call
  sites inside functions, which is already the dominant style in this file).
