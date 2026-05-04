# Atelier Codex Preflight

Use this task file to force an Atelier preflight before implementation:

1. Run `atelier_get_reasoning_context` with task, domain, files, and likely tools.
2. Run `atelier_memory_recall` to check archival memory for relevant past findings before reading files.
3. Draft a concrete plan.
4. Run `atelier_check_plan`.
5. If status is `blocked`, revise plan and re-run.
6. If domain is high risk (`beseam.shopify.publish`, `beseam.pdp.schema`, `beseam.catalog.fix`, `beseam.tracker.classification`), run `atelier_run_rubric_gate` before finalizing.
7. Record the run with `atelier_record_trace`.
8. Archive key findings with `atelier_memory_archive` for future runs.

Default tool posture: use `atelier_search_read` (Atelier augmentation) for repeated context
reads/searches to save tokens; `smart_read`, `smart_search`, and `cached_grep` for repeatable
single-file reads and grep patterns. Leave native `Read`, shell `rg`, `grep`, and direct file
access available for exact raw inspection. The kill switch is `ATELIER_CACHE_DISABLED=1`.
