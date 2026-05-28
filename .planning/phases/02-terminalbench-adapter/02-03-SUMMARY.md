---
phase: 02-terminalbench-adapter
plan: "03"
subsystem: benchmarks/terminalbench
tags: [testing, unit-tests, terminalbench, bench-mode, TB-04, TB-05]
dependency_graph:
  requires:
    - "02-01"  # agent_adapter.py, AdapterResult, parse_stream_jsonl
    - "02-02"  # runner.py, RunRecord, write_records, write_transcript
  provides:
    - "benchmarks/terminalbench/tests/__init__.py"
    - "benchmarks/terminalbench/tests/test_agent_adapter.py"
    - "benchmarks/terminalbench/tests/test_runner.py"
    - "benchmarks/terminalbench/tests/test_modes.py"
  affects:
    - "benchmarks/terminalbench/agent_adapter.py"
    - "benchmarks/terminalbench/runner.py"
tech_stack:
  added: []
  patterns:
    - "pytest with monkeypatch for env-var isolation (T-02-09 mitigation)"
    - "tmp_path fixture for hermetic file I/O tests"
    - "In-process imports inside test bodies to isolate import side effects"
key_files:
  created:
    - "benchmarks/terminalbench/tests/__init__.py"
    - "benchmarks/terminalbench/tests/test_agent_adapter.py"
    - "benchmarks/terminalbench/tests/test_runner.py"
    - "benchmarks/terminalbench/tests/test_modes.py"
  modified: []
decisions:
  - "shlex_escape_test: assert shlex.quote(instruction) in cmd rather than raw-not-in-cmd — raw instruction is necessarily a substring of its shell-quoted form"
  - "package_install: ran `uv pip install -e .` from benchmarks/ to make terminalbench importable during pytest (package was not pre-installed in editable mode)"
  - "27_tests: plan estimated 25 tests; added 2 extra (test_agent_run_commands_flags + test_agent_env_includes_api_key) for completeness — both from plan behavior specs"
metrics:
  duration: "229 seconds"
  completed: "2026-05-28"
  tasks_completed: 2
  files_created: 4
  files_modified: 0
---

# Phase 2 Plan 03: TerminalBench Adapter — Unit Tests Summary

Unit test suite for the TerminalBench adapter: 27 tests covering NDJSON stream-json parsing, AdapterResult TB-04 schema, RunRecord JSONL serialisation, atomic transcript writes, and TB-05 mode-difference acceptance criterion.

## What Was Built

**Task 1 — test_agent_adapter.py (14 tests)**

Stream-json parsing tests using the live-captured result line from RESEARCH.md:
- Happy path: all 10 fields correctly extracted (input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens, cost_usd, latency_ms, latency_api_ms, num_turns, is_error, stop_reason)
- No-result-line fallback: returns `{"error": "no_result_line"}` with zeros
- Malformed lines: silently skipped, valid result still extracted
- Empty file: gracefully returns zero-result dict

AtelierClaudeAgent env/command tests:
- ATELIER_BENCH_MODE="on"/"off" propagation verified
- ATELIER_DEV_MODE excluded from container env (PITFALLS.md #3b)
- ANTHROPIC_API_KEY forwarded from host env
- FORCE_AUTO_BACKGROUND_TASKS + ENABLE_BACKGROUND_TASKS present
- _run_agent_commands: tee to CONTAINER_STREAM_LOG, --output-format stream-json, --verbose, --dangerously-skip-permissions, --allowedTools flags
- shlex.quote applied to instruction

AdapterResult TB-04 schema test: all 25 required fields present in to_dict() output.

**Task 2 — test_runner.py (7 tests) + test_modes.py (6 tests)**

Runner tests:
- RunRecord.to_jsonl() round-trips through json.loads with all fields
- write_records creates JSONL file; multiple-row output produces correct line count
- write_transcript: correct filename format `<task>__<mode>__rep<N>.json`
- Transcript content valid JSON with all 25 TB-04 fields
- Atomic write: no .tmp file left on disk
- Parent directory creation on first run

TB-05 mode-difference tests (acceptance criterion):
- `test_mode_on_and_off_envs_differ` — **PRIMARY TB-05 ASSERTION** passes
- make_arm_env(BenchMode.ON) vs make_arm_env(BenchMode.OFF) produce different ATELIER_ROOT and ATELIER_BENCH_MODE values

## Test Results

```
27 passed, 0 failed, 0 errors, 0 skipped — 2.31s
```

Root regression suite also passes: `48 passed, 5 warnings` in tests/core + tests/gateway.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] terminalbench not importable in pytest**
- **Found during:** Task 1 first test run
- **Issue:** `ModuleNotFoundError: No module named 'terminalbench'` — the benchmarks package was not installed editably in its own venv
- **Fix:** Ran `uv pip install -e .` from `benchmarks/` to register the `terminalbench` package in the venv's site-packages
- **Files modified:** None (venv state only)
- **Commit:** N/A (pre-commit step)

**2. [Rule 1 - Bug] test_agent_run_commands_shlex_escape assertion logic**
- **Found during:** Task 1 first test run
- **Issue:** The plan's initial assertion `assert instruction not in cmd` is always false — `shlex.quote(instruction)` contains `instruction` as a substring; the raw string appears inside the quoted form
- **Fix:** Changed assertion to `assert shlex.quote(instruction) in cmd` and `assert quoted != instruction` (verifies quoting was actually applied)
- **Files modified:** test_agent_adapter.py
- **Commit:** included in Task 1 commit

**3. [Rule 1 - Bug] Nested `with` blocks in test_mode_atelier_root_independent**
- **Found during:** Task 2 commit (pre-commit ruff SIM117 check)
- **Issue:** Nested `with tempfile.TemporaryDirectory(...) as tmp1: with ... as tmp2:` flagged by ruff SIM117
- **Fix:** Collapsed into single `with (...) as tmp1, (...) as tmp2:` parenthesized form
- **Files modified:** test_modes.py
- **Commit:** included in Task 2 commit (applied by black formatter)

## Known Stubs

None — all tests assert real behaviour; no placeholder assertions.

## Threat Flags

None — test files add no new network endpoints, auth paths, or trust-boundary surface.

## Self-Check: PASSED

- benchmarks/terminalbench/tests/__init__.py ✅
- benchmarks/terminalbench/tests/test_agent_adapter.py ✅
- benchmarks/terminalbench/tests/test_runner.py ✅
- benchmarks/terminalbench/tests/test_modes.py ✅
- Commits: 21ec2bc (Task 1), fbd8d49 (Task 2) ✅
