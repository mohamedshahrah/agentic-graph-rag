-- Config / transactional store. Applied on startup (idempotent).

CREATE TABLE IF NOT EXISTS projects (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- API keys are stored only as hashes. `kind`: secret (ingest) or public (identify).
CREATE TABLE IF NOT EXISTS api_keys (
    id          BIGSERIAL PRIMARY KEY,
    project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    key_hash    TEXT NOT NULL UNIQUE,
    kind        TEXT NOT NULL DEFAULT 'secret',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS api_keys_hash_idx ON api_keys(key_hash);

-- Per-model pricing, versioned by effective date (latest <= now wins).
CREATE TABLE IF NOT EXISTS model_pricing (
    provider        TEXT NOT NULL,
    model           TEXT NOT NULL,
    input_per_1k    NUMERIC NOT NULL,
    output_per_1k   NUMERIC NOT NULL,
    effective_from  DATE NOT NULL DEFAULT '2020-01-01',
    PRIMARY KEY (provider, model, effective_from)
);

CREATE TABLE IF NOT EXISTS notification_channels (
    id          BIGSERIAL PRIMARY KEY,
    project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    kind        TEXT NOT NULL,          -- webhook | slack | log
    target      TEXT NOT NULL DEFAULT '',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS alert_rules (
    id               BIGSERIAL PRIMARY KEY,
    project_id       TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name             TEXT NOT NULL,
    type             TEXT NOT NULL,     -- error_rate | cost_spike | latency_p95 | volume
    threshold        DOUBLE PRECISION NOT NULL,
    window_seconds   INTEGER NOT NULL DEFAULT 300,
    cooldown_seconds INTEGER NOT NULL DEFAULT 900,
    channel_id       BIGINT REFERENCES notification_channels(id) ON DELETE SET NULL,
    enabled          BOOLEAN NOT NULL DEFAULT TRUE,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS alert_events (
    id          BIGSERIAL PRIMARY KEY,
    rule_id     BIGINT NOT NULL REFERENCES alert_rules(id) ON DELETE CASCADE,
    project_id  TEXT NOT NULL,
    value       DOUBLE PRECISION NOT NULL,
    message     TEXT NOT NULL,
    fired_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS alert_events_fired_idx ON alert_events(project_id, fired_at DESC);
