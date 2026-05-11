CREATE TABLE IF NOT EXISTS external_analytics_runs (
    id              TEXT PRIMARY KEY,
    tool            TEXT NOT NULL,
    period          TEXT NOT NULL,
    source          TEXT NOT NULL DEFAULT 'manual',
    command_display TEXT NOT NULL DEFAULT '',
    ok              INTEGER NOT NULL DEFAULT 0,
    returncode      INTEGER,
    summary_json    TEXT NOT NULL DEFAULT '{}',
    payload_json    TEXT NOT NULL DEFAULT '{}',
    stdout          TEXT NOT NULL DEFAULT '',
    stderr          TEXT NOT NULL DEFAULT '',
    collected_at    TEXT NOT NULL,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_external_analytics_runs_tool_at
    ON external_analytics_runs(tool, collected_at DESC);

CREATE INDEX IF NOT EXISTS ix_external_analytics_runs_ok_at
    ON external_analytics_runs(ok, collected_at DESC);

CREATE INDEX IF NOT EXISTS ix_external_analytics_runs_period_at
    ON external_analytics_runs(period, collected_at DESC);