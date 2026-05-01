# Workers

Workers handle background processing tasks for Atelier — primarily failure analysis, eval running, and periodic summarization.

## Starting Workers

```bash
cd atelier && make worker
# or
uv run atelier worker start
```

## What Workers Do

Workers are optional. All core operations (check-plan, record-trace, run-rubric) are synchronous and do not require workers.

Workers process:

- **Failure clustering**: periodically re-clusters failure traces to surface patterns
- **Eval execution**: runs eval cases in the background when triggered
- **Savings summarization**: computes token and call savings metrics

## Worker Configuration

Workers use the same environment variables as the rest of Atelier (see [docs/installation.md](../installation.md)).

Workers require a running store (SQLite or PostgreSQL). For PostgreSQL, workers can run concurrently on multiple machines without coordination.

## Without Workers

If workers are not running:

- Failure clustering is done on-demand via `atelier analyze-failures`
- Eval runs are triggered manually via `atelier eval run`
- Savings metrics are computed at query time via `atelier savings`

For most development workflows, workers are not needed.
