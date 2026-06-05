-- DRAFT ONLY. DO NOT APPLY.
-- Not an Alembic migration.
-- Phase 6.1B design reference for energy_prices.
-- Phase 6.1C implementation lives in migrations/versions/0008_energy_prices.py.

CREATE TABLE energy_prices (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    raw_response_id INTEGER NOT NULL REFERENCES raw_responses(id),
    collector_run_id INTEGER NOT NULL REFERENCES collector_runs(id),
    instrument_code VARCHAR(100) NOT NULL,
    instrument_name VARCHAR(255) NOT NULL,
    instrument_category VARCHAR(100) NOT NULL,
    external_id VARCHAR(100) NOT NULL,
    frequency VARCHAR(32) NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    observed_at TIMESTAMP WITH TIME ZONE NOT NULL,
    published_at TIMESTAMP WITH TIME ZONE NULL,
    fetched_at TIMESTAMP WITH TIME ZONE NOT NULL,
    value NUMERIC(18, 8) NOT NULL,
    currency VARCHAR(16) NULL,
    unit VARCHAR(100) NOT NULL,
    normalized_value NUMERIC(18, 8) NULL,
    normalized_currency VARCHAR(16) NULL,
    normalized_unit VARCHAR(100) NULL,
    source_record_hash VARCHAR(64) NOT NULL,
    source_payload_hash VARCHAR(64) NOT NULL,
    metadata_json JSONB NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT uq_energy_source_instr_freq_period
        UNIQUE (source_id, instrument_code, frequency, period_start, period_end),
    CONSTRAINT ck_energy_prices_period_order
        CHECK (period_end >= period_start),
    CONSTRAINT ck_energy_prices_frequency
        CHECK (frequency IN ('daily', 'weekly', 'monthly'))
);

CREATE INDEX ix_energy_source_instr_period
    ON energy_prices (source_id, instrument_code, period_start, period_end);

CREATE INDEX ix_energy_instr_observed
    ON energy_prices (instrument_code, observed_at);

CREATE INDEX ix_energy_category_observed
    ON energy_prices (instrument_category, observed_at);

CREATE INDEX ix_energy_fetched_at
    ON energy_prices (fetched_at);

CREATE INDEX ix_energy_raw_response_id
    ON energy_prices (raw_response_id);

CREATE INDEX ix_energy_collector_run_id
    ON energy_prices (collector_run_id);

CREATE INDEX ix_energy_source_record_hash
    ON energy_prices (source_record_hash);
