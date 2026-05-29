# Phase 24: Stdout to Logging - Pattern Map

**Mapped:** 2026-05-29
**Files analyzed:** 19 print-bearing files (13 to modify, 7 benchmark files retained) + 1 test to harden + `pyproject.toml`
**Analogs found:** 13 / 13 (all in-repo; this is a same-pattern refactor, every file has a sibling analog)

> This phase is a print→logger refactor, not greenfield. The "analog" for each file is an
> already-correct sibling in the same package, or the existing logger primitive in the same file.
> All snippets below are real code in the working tree — copy them directly.

## File Classification

| Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---------------|------|-----------|----------------|---------------|
| `gateway/adapters/mcp_server.py` (L5456) | adapter / MCP entry-point | request-response (JSON-RPC stdio) | self — `_setup_file_logging` L5408, `_log` L370 | exact (in-file) |
| `gateway/hosts/registry.py` (L141) | infra / persistence | file-I/O (load) | `session_parsers/_common.py` logger L27 | role-match |
| `gateway/hosts/session_parsers/_common.py` (L748,754,757,765) | library / parser | batch / file-I/O | self — `logger` already at L27 | exact (in-file) |
| `gateway/hosts/session_parsers/claude.py` (L222,229,232,238) | library / parser | batch / file-I/O | `_common.py` L27 + L740-766 | exact |
| `gateway/hosts/session_parsers/cline.py` (L204,211,220,223) | library / parser | batch / file-I/O | `_common.py` L740-766 | exact |
| `gateway/hosts/session_parsers/codex.py` (L312,317,320,330,332) | library / parser | batch / file-I/O | `_common.py` L740-766 | exact |
| `gateway/hosts/session_parsers/copilot.py` (10 sites) | library / parser | batch / file-I/O | `_common.py` L740-766 | exact |
| `gateway/hosts/session_parsers/gemini.py` (L152,159,163,172) | library / parser | batch / file-I/O | `_common.py` L740-766 | exact |
| `gateway/hosts/session_parsers/goose.py` (L71,74) | library / parser | batch / file-I/O | `_common.py` L740-766 | exact |
| `gateway/hosts/session_parsers/kiro.py` (L84,88) | library / parser | batch / file-I/O | `_common.py` L740-766 | exact |
| `gateway/hosts/session_parsers/opencode.py` (L80,84) | library / parser | batch / file-I/O | `_common.py` L740-766 | exact |
| `infra/benchmarks/publisher.py` (L336,338) | infra / report builder | transform | `_common.py` logger L27 | role-match |
| `gateway/cli/app.py` (import commands) | CLI dispatcher | request-response | self — `click.echo(..., err=True)` L8572 | exact (in-file) |
| `tests/gateway/test_mcp_stdio_smoke.py` (L78-83) | test | request-response (subprocess) | `test_mcp_jsonrpc_e2e.py` L306 | exact |
| `pyproject.toml` (`per-file-ignores`) | config | n/a | self — existing ignore block L116-214 | exact |

**Out of scope (retain, do NOT convert):** 7 benchmark dev-CLIs under `src/benchmarks/**`
(`routing_replay_bench.py`, `savings_replay.py`, `report.py`, `code_intel/scale_decision_eval.py`,
`swe/savings_bench.py`, `swe/swebench_eval.py`, `tool_bench/__main__.py`). Their stdout is the
intended report channel and is never MCP-reachable.

## Pattern Assignments

### `gateway/hosts/session_parsers/_common.py` (library, batch) — THE CANONICAL ANALOG

This file already declares the module logger every other parser should copy. The progress prints
inside `import_paths_with_progress` are the model the per-host parsers duplicate.

**Module logger pattern** (already present, L7 + L27 — copy verbatim into parsers that lack it):
```python
import logging
...
logger = logging.getLogger(__name__)
```

**Current print sites to convert** (L748-766):
```python
def import_paths_with_progress(source, paths, import_fn, size_limit=_SIZE_LIMIT_BYTES):
    total = len(paths)
    print(f"[atelier] {source}: discovering sessions (found {total})")   # L748 → logger.info
    imported: list[str] = []
    for i, path in enumerate(paths):
        try:
            size = path.stat().st_size
            if size > size_limit:
                print(f"[atelier] {source}: skipping massive session ...")  # L754 → logger.warning
                continue
            if i % 10 == 0 and i > 0:
                print(f"[atelier] {source}: importing {i}/{total}...")       # L757 → logger.info
            ...
        except Exception as exc:
            import traceback as _tb
            _tb.print_exc()                                                   # → logger.exception
            print(f"[atelier] skipping {source} session {path.name}: {exc}")  # L765 → logger.warning
```

**Target conversion** (preserve `[atelier]` prefix so existing UX/log scraping is unchanged):
```python
logger.info("[atelier] %s: discovering sessions (found %d)", source, total)
logger.warning("[atelier] %s: skipping massive session %s (%.1fMB)", source, path.name, size / 1e6)
logger.info("[atelier] %s: importing %d/%d...", source, i, total)
logger.exception("[atelier] skipping %s session %s", source, path.name)  # replaces _tb.print_exc + print
```
Level choice (RESEARCH §discretion): discovery/progress → `info`; size-skip → `warning`;
exception path → `logger.exception(...)` (captures traceback, replaces both `_tb.print_exc()` and
the follow-up `print`). Use `%`-style lazy args, not f-strings, for logger calls.

**Redaction guard** (`redact` already imported at `_common.py` L24): if any converted message
interpolates session content (not just counts/paths), wrap it: `logger.debug("... %s", redact(payload))`.

---

### `gateway/hosts/session_parsers/{claude,cline,codex,copilot,gemini,goose,kiro,opencode}.py` (library, batch)

**Analog:** `_common.py` (logger declaration L27, progress shape L740-766).

These 8 parsers each carry a hand-rolled `import_all` loop that mirrors `_common.py` but prints.
`claude.py` is representative (L218-239):
```python
all_sessions = list(find_claude_sessions(root))
total = len(all_sessions)
if total > 0:
    print(f"[atelier] claude: discovering sessions (found {total})")   # → logger.info
...
        if size > _SIZE_LIMIT_BYTES:
            print(f"[atelier] claude: skipping massive session ...")     # → logger.warning
            continue
        if i % 10 == 0 and i > 0:
            print(f"[atelier] claude: importing {i}/{total}...")          # → logger.info
...
    except Exception as exc:
        _traceback.print_exc()                                            # → logger.exception
        print(f"[atelier] skipping claude session {jsonl_path.name}: {exc}")
```

**Action per file:**
1. Add `import logging` (if absent) and `logger = logging.getLogger(__name__)` at module scope
   (copy `_common.py` L27). `_common.py` already has it — do NOT re-add there.
2. Convert each `print(...)` to the matching `logger.{info,warning}` per the level mapping above.
3. Replace `_traceback.print_exc()` + trailing `print` pairs with one `logger.exception(...)`;
   the `import traceback as _traceback` may then be removable (verify no other use first).

---

### `gateway/hosts/registry.py` (infra, file-I/O)

**Analog:** `_common.py` logger pattern (L27). This file has NO module logger yet.

**Current** (L130-141):
```python
def _load(self) -> None:
    with self._lock:
        for file in self.storage_dir.glob("*.json"):
            try:
                ...
            except Exception as e:
                # Log warning but continue
                print(f"Warning: Failed to load {file}: {e}")   # L141
```

**Target:**
```python
import logging                       # add to import block (L3-9)
logger = logging.getLogger(__name__) # add after imports (~L12)
...
            except Exception as e:                                  # (Phase-23 left this broad; keep BLE001 ignore)
                logger.warning("Failed to load %s: %s", file, e, exc_info=True)
```
Note: the `BLE001` ignore stays — only `T201` is being cleared here.

---

### `infra/benchmarks/publisher.py` (infra, transform)

**Analog:** `_common.py` logger pattern. No module logger present.

**Current** (L335-338):
```python
def _print_dry_run(report_dir, md_content, json_content) -> None:
    print(f"[dry-run] Would write {report_dir / 'benchmark.md'} ({len(md_content)} bytes)")  # L336
    json_str = json.dumps(json_content)
    print(f"[dry-run] Would write {report_dir / 'benchmark.json'} ({len(json_str)} bytes)")   # L338
```

**Target** (library should not print; route to logger.info):
```python
import logging
logger = logging.getLogger(__name__)
...
def _print_dry_run(report_dir, md_content, json_content) -> None:
    logger.info("[dry-run] Would write %s (%d bytes)", report_dir / "benchmark.md", len(md_content))
    logger.info("[dry-run] Would write %s (%d bytes)", report_dir / "benchmark.json", len(json.dumps(json_content)))
```
(Discretion: alternatively surface dry-run lines from the CLI `benchmark publish` command via
`click.echo`. Either clears T201 and removes the `infra/benchmarks/publisher.py` ignore entry.)

---

### `gateway/adapters/mcp_server.py` (MCP entry-point) — STDIO SAFETY CRITICAL

**Analog:** in-file primitives — `_log = logging.getLogger("atelier.mcp")` (L370) and
`_setup_file_logging` (L5408-5428) which routes `atelier.mcp` to `~/.atelier/mcp/mcp.log`,
never stdout.

**The one print** (L5454-5457) — user-facing `--version`, returns BEFORE the stdio loop:
```python
argv = sys.argv[1:]
if "--version" in argv or "-V" in argv:
    print(f"atelier-mcp {SERVER_VERSION}")   # L5456 — pre-loop, user-facing
    return
```

**Recommended target** (keep it user-facing on stdout, just clear T201):
```python
if "--version" in argv or "-V" in argv:
    sys.stdout.write(f"atelier-mcp {SERVER_VERSION}\n")
    return
```
**Do NOT** convert this to `_log.info(...)` — that would send version text to the file log and
break `atelier-mcp --version` terminal UX (RESEARCH Pitfall 3). Acceptable alternatives:
`# noqa: T201  # version flag, returns before stdio loop` if keeping `print`. Either way, the
early `return` before the JSON-RPC loop MUST be preserved.

**Reuse, don't rebuild:** any *server-context* diagnostic in this file uses the existing `_log`
(file-routed, e.g. L5450 `_log.debug(..., exc_info=True)`), never stdout.

---

### `tests/gateway/test_mcp_stdio_smoke.py` (test) — HARDEN for QBL-LOG-04

**Analog:** `test_mcp_jsonrpc_e2e.py` L306 (strict per-line parse).

**Current lenient parse** (L78-83) — silently swallows stray banners:
```python
for line in result.stdout.splitlines():
    line = line.strip()
    if not line:
        continue
    try:
        msg = json.loads(line)
        if "id" in msg:
            responses[msg["id"]] = msg
    except Exception:
        pass            # ← a stray print is swallowed; test still passes
```

**Strict pattern to copy from e2e L306:**
```python
responses = [json.loads(line) for line in result.stdout.splitlines() if line.strip()]
```

**Target hardening** (assert every stdout line is a JSON object — proves no non-protocol leak):
```python
for line in result.stdout.splitlines():
    if not line.strip():
        continue
    msg = json.loads(line)                       # no try/except — stray text now fails the test
    assert isinstance(msg, dict), f"non-object on stdout: {line!r}"
    if "id" in msg:
        responses[msg["id"]] = msg
```
Marker note: this test is `@pytest.mark.slow` — run with `-m ""`.

---

## Shared Patterns

### Module logger declaration (apply to every non-CLI file lacking one)
**Source:** `gateway/hosts/session_parsers/_common.py` L7, L27
```python
import logging
logger = logging.getLogger(__name__)
```
**Apply to:** `registry.py`, `publisher.py`, and the 8 session parsers missing it.
**Do NOT add to:** `_common.py` (has it), `mcp_server.py` (use existing `_log` at L370).

### Logger level mapping (apply to all converted progress/diagnostic prints)
| Old print intent | New call |
|------------------|----------|
| progress / discovery | `logger.info("...", *args)` |
| skip / recoverable problem | `logger.warning("...", *args)` |
| caught exception (`except`) | `logger.exception("...")` (replaces `traceback.print_exc()` + print) |
| verbose internal detail | `logger.debug("...", *args)` |
Use `%`-style lazy interpolation, not f-strings, inside logger calls.

### CLI user-facing output stays on stdout/stderr via click
**Source:** `gateway/cli/app.py` L8572 (and 8 other `err=True` sites; 511 `click.echo` total)
```python
click.echo("No sessions found - run any AI command first.", err=True)  # stderr diagnostic
click.echo(f"imported {len(ids)} claude sessions")                      # stdout user result (L2172)
```
**Apply to:** the CLI `import` command path. **Critical caveat (RESEARCH Pitfall 1):** `cli/app.py`
declares `logger = logging.getLogger(__name__)` (L65) but attaches **no handler / no basicConfig**.
A bare `logger.info()` conversion of parser progress would vanish (root defaults to WARNING).
The conversion MUST be paired with an explicit INFO-level **stderr** `StreamHandler` attached in the
import command path (minimal, NOT CLI decomposition — that is Phase 25). Add a test asserting
progress appears on `capsys.readouterr().err` and NOT `.out`.

### MCP file-logging primitive (reuse, never rebuild)
**Source:** `mcp_server.py` `_setup_file_logging` L5408-5428
```python
mcp_logger = logging.getLogger("atelier.mcp")
mcp_logger.addHandler(logging.FileHandler(str(log_path), encoding="utf-8"))
mcp_logger.setLevel(logging.DEBUG)
```
**Apply to:** all MCP server-context diagnostics — they go through `_log` (already file-routed),
guaranteeing stdout carries only JSON-RPC frames.

### T201 per-file-ignore shrink (config)
**Source:** `pyproject.toml` L116-214 `[tool.ruff.lint.per-file-ignores]`
**Apply after code fixes — 19 → 7 T201 entries:**
- **Demote `["BLE001","T201"]` → `["BLE001"]`** (9): `mcp_server.py`, `registry.py`, and
  `_common.py`, `claude.py`, `cline.py`, `codex.py`, `copilot.py`, `gemini.py`, `opencode.py`.
- **Remove entry entirely** (3 T201-only): `goose.py`, `kiro.py`, `infra/benchmarks/publisher.py`.
- **Retain** (7 benchmark dev-CLIs): `benchmarks/swe/routing_replay_bench.py`,
  `benchmarks/swe/savings_replay.py`, `benchmarks/tool_bench/report.py` (all keep both BLE001+T201),
  `benchmarks/code_intel/scale_decision_eval.py`, `benchmarks/swe/savings_bench.py`,
  `benchmarks/swe/swebench_eval.py`, `benchmarks/tool_bench/__main__.py` (T201 only).
- **Discretion (RESEARCH §boundary):** the 7 benchmark T201 entries MAY be collapsed to one glob
  `"src/benchmarks/**/*.py" = ["T201"]` (documents intent, future-proofs) — but the BLE001 entries on
  `routing_replay_bench.py`, `savings_replay.py`, `report.py` must be preserved separately.
- **Verify:** `uv run ruff check src --select T20 --config 'lint.per-file-ignores={}'` should show
  only `src/benchmarks/**` after fixes; `uv run ruff check src` must stay green.

## No Analog Found

None. Every modified file has an in-repo analog (canonical: `_common.py`). The phase wires existing
primitives (module loggers, click err-stream, file logger, strict subprocess parse) — RESEARCH
"Don't Hand-Roll" confirms nothing new is built.

## Metadata

**Analog search scope:** `src/atelier/gateway/{adapters,hosts,cli}/`, `src/atelier/infra/benchmarks/`,
`tests/gateway/`, `pyproject.toml`
**Files scanned:** 9 source files + 2 test files + pyproject (targeted reads, no full-file loads of
the 5400-line `mcp_server.py`)
**Pattern extraction date:** 2026-05-29
**Authoritative count:** 97 `print()` / 19 files (AST + ruff 0.15.14), per RESEARCH — not the
inflated grep figure of 132/35.
