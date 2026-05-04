# Atelier Review Repair Mode

Use this task file when a plan or patch is failing repeatedly:

1. Load context with `atelier_get_reasoning_context`.
2. Load current run state with `atelier_get_run_ledger`.
3. If failure repeats, call `atelier_rescue_failure` with exact error signature and recent actions.
4. Apply smallest valid fix.
5. Re-run validation and call `atelier_record_trace`.
