# V2 to V3 Migration

## Summary

V3 hardens memory, benchmark, and context-compression behavior without adding new host integrations. The main operator actions are selecting a single memory backend, re-embedding legacy stub vectors, and moving savings claims to the replay benchmark.

## Steps

1. Back up `.atelier/atelier.db`.
2. Upgrade Atelier and run the normal store initialization path.
3. Run a dry re-embed scan:

```bash
uv run atelier --root .atelier reembed --dry-run --json
```

4. Re-embed legacy rows when the scan reports `legacy_stub` data:

```bash
uv run atelier --root .atelier reembed --json
```

5. Choose a memory backend. Omit configuration for SQLite, or set `ATELIER_MEMORY_BACKEND=letta` after starting the Letta sidecar.
6. Run consolidation periodically or manually:

```bash
uv run atelier --root .atelier consolidate --since 7d --json
```

7. Use `make bench-savings-honest` for context-savings measurement.

## Notes

- `stub_embedding` is removed from runtime code and rejected by storage for new memory rows.
- Letta is not a fallback cache; it is a primary backend when selected.
- Historical V2 savings docs remain as correction-marked archival references.
