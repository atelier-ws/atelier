# Deferred Items — Phase 25 (CLI Decomposition)

Out-of-scope discoveries logged during execution. NOT fixed (per executor scope boundary).

## 25-04

- **Pre-existing test failure (out of scope):** `tests/gateway/test_cli.py::test_code_context_cli_round_trip`
  fails with a tree-sitter pyo3 threading panic
  (`PanicException: _native::Parser is unsendable, but sent to another thread`)
  originating in `core/capabilities/code_context/engine.py` →
  `infra/tree_sitter/tags.py`. None of these files are touched by Plan 25-04.
  This is an environmental/threading flake unrelated to the CLI command
  extraction. The other 25 CLI tests pass.

- **Dashboard `_age`/`_dur` empty-timestamp warnings (pre-existing, not a
  regression):** `atelier status` emits `ValueError: Invalid isoformat string: ''`
  caught by the moved broad-exception handler (`logging.exception("Recovered
  from broad exception handler")`) when a run record has an empty timestamp.
  The handler and functions were moved verbatim from app.py, so this behavior
  predates 25-04 (data condition in stored runs). The dashboard still renders
  fully. Left unchanged to preserve byte-identical behavior.
