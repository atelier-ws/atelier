# Phase T Hardening Execution

This document maps the Phase T1-T6 objective to runnable Atelier commands.

## Run All Phases

```bash
make phase-t-hardening
```

Outputs:

- `.atelier/reports/phase_t/<timestamp>.report.txt`
- `.atelier/reports/phase_t/<timestamp>.summary.json`

## T1 — Full System Validation

```bash
make phase-t1
```

Covers:

- core checks (plan checker, retriever, rubric, rescue/failure analyzer, context compressor, monitors, run ledger, savings)
- storage checks (SQLite + Postgres-gated tests)
- host adapter checks
- service + worker checks
- pack lifecycle checks
- security checks (redaction + abuse defenses)

## T2 — Golden Dogfood Scenarios

```bash
make phase-t2
```

Runs `tests/test_golden_fixtures.py` for real scenario validation.

## T3 — Benchmark Suite

```bash
make benchmark-core
make benchmark-hosts
make benchmark-packs
make benchmark-full
```

These commands correspond to:

- `atelier benchmark-core`
- `atelier benchmark-hosts`
- `atelier benchmark-packs`
- `atelier benchmark-full`

## T4 — Install + Deploy Verification

```bash
make phase-t4
```

Runs:

- `scripts/verify_atelier_service.sh`
- `scripts/verify_atelier_mcp_stdio.sh`
- `scripts/verify_atelier_local.sh`
- `scripts/verify_atelier_postgres.sh`
- `scripts/verify_agent_clis.sh`

## T5 — Documentation Audit

```bash
make phase-t5
```

Runs docs integrity tests from `tests/test_docs.py`.

## T6 — Production Readiness Checklist

```bash
make phase-t6
```

Validates presence and structure of `docs/production-readiness.md`.
