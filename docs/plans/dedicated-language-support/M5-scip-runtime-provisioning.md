# M5 — SCIP Indexers in the Atelier Runtime Environment

**Goal:** Ship/bootstrap SCIP indexers so semantic intel works out of the box.
This is the user's explicit ask: "include SCIP index in the atelier runtime
environment." Today `install.sh` installs Node + npm globals but no indexers,
and `indexer.py::available_binaries` only *discovers* what's already on `PATH`.

## Files to touch

- `scripts/install.sh` — install indexers into Atelier-managed dirs.
- `src/atelier/infra/code_intel/scip/binaries.py` — search Atelier-managed
  install dirs, not just `PATH`.
- Possibly a new `scip/bootstrap.py` for lazy on-demand install.

## Decision: bundle vs. fetch (resolve open question #1)

`code-intel/M1` leaned **fetch-on-first-use with a checksum allowlist**. Recommend
keeping that, tiered by toolchain cost:

- **Tier 1 (install-time, cheap, no extra toolchain):** `scip-python`,
  `scip-typescript` via the existing `npm install -g --prefix "$ATELIER_NODE_DIR"` block in `install.sh`. These reuse the Node that Atelier
  already provisions — lowest-friction win.
- **Tier 2 (lazy, on first index of that language):** `scip-go`, `scip-ruby`,
  `scip-clang` (single-binary or single-package installs). Fetch into
  `~/.atelier/bin/` (or `$ATELIER_INSTALL_DIR/bin`) with a checksum allowlist;
  skip gracefully offline.
- **Tier 3 (document, don't auto-install):** `rust-analyzer scip`, `scip-java`
  — they piggyback on heavy toolchains (rustup, JDK+coursier) the user likely
  already has. Detect and use if present; print a one-line install hint if not.

## Approach

1. In `install.sh`, alongside the existing eslint/ts-morph npm block, add
   `scip-python` + `scip-typescript` to the global npm install into
   `$ATELIER_NODE_DIR`. Add `$ATELIER_NODE_DIR/bin` (already on PATH for hosts)
   discovery in `binaries.py`.
2. Define Atelier-managed binary dirs (e.g. `~/.atelier/bin`) and make
   `discover_scip_binary` search them before `PATH`.
3. Add a lazy bootstrap (`ensure_scip_binary(language)`) used by the indexing
   path from M4: if a Tier-2 indexer is missing, fetch it (checksum-verified)
   on first use; if Tier-3 is missing, return `None` + a logged hint.
4. Surface availability: extend whatever the CLI/MCP status output is (the
   `available_binaries()` consumer) so users can see which languages have
   semantic intel ready.

## Verify

- Fresh-install smoke test (or dry-run of `install.sh`): `scip-python` and
  `scip-typescript` resolve from the Atelier-managed dir without a
  system-global install.
- `discover_scip_binaries()` finds the Atelier-managed binaries.
- Offline test: lazy bootstrap of a Tier-2 indexer fails closed (no crash, no
  partial binary) and the language degrades to tree-sitter/tags.
- `bash -n scripts/install.sh` and a guarded `ATELIER_DRY_RUN=1` run.
