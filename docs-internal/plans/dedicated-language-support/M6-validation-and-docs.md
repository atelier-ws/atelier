# M6 — Validation, Benchmarks & Docs

**Goal:** Prove the expanded coverage works and is honest about savings, then
document it. Closes the plan.

## Files to touch

- `tests/core/` and `tests/infra/` — consolidate per-language fixtures.
- Benchmark harness under `src/atelier/bench/` or the existing savings A/B
  plan (`docs/plans/savings-honest-ab/`).
- Docs: `docs/architecture/README.md` (the SCIP language list table),
  `README.md` / `QUICK_REFERENCE.md` language-support section,
  `docs/installation.md` (SCIP provisioning).

## Tasks

1. **Fixture matrix.** One small representative source file per recognized
   language under a shared fixtures dir. Parametrized tests assert: correct
   `_detect_language`; outline `kind` (`treesitter` where configured, `generic`
   otherwise); non-empty definition tags for tree-sitter languages.
2. **Honest-savings benchmark.** For each newly-dedicated language (shell,
   yaml, toml, json, sql), measure outline token savings vs. the generic path
   and vs. full file. Confirm the 25% guard behaves (dedicated outline only
   ships when it genuinely beats the bar). Record results next to the existing
   savings A/B artifacts.
3. **SCIP availability report.** A test/CLI check listing which languages have
   a discoverable indexer after install, matching the M4/M5 matrix.
4. **Docs.** Update the architecture SCIP-language list (currently shows
   "scip-go · scip-rust · scip-java · …" as aspirational) to reflect reality,
   and document the tiered provisioning model from M5. Run
   `make sync-agent-context` if any agent-os source docs change.

## Verify

- `make pre-commit` (format + lint + typecheck + docs + test) green.
- `make docs-check && make check-agent-context`.
- Benchmark artifact committed; numbers show dedicated > generic where claimed.
