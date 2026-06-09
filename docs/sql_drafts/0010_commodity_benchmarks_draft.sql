-- DRAFT ONLY. DO NOT APPLY.
-- Not an Alembic migration.
-- Phase 6.2B design reference for commodity_benchmarks.
-- Phase 6.2C should implement this only after review.

CREATE TABLE commodity_benchmarks (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    raw_response_id INTEGER NOT NULL REFERENCES raw_responses(id),
    collector_run_id INTEGER NOT NULL REFERENCES collector_runs(id),
    benchmark_code VARCHAR(100) NOT NULL,
    external_id VARCHAR(255) NOT NULL,
    benchmark_name VARCHAR(255) NOT NULL,
    benchmark_category VARCHAR(100) NOT NULL,
    commodity_family VARCHAR(100) NOT NULL,
    geography VARCHAR(100) NOT NULL,
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
    CONSTRAINT uq_commodity_bench_source_code_freq_period
        UNIQUE (source_id, benchmark_code, frequency, period_start, period_end),
    CONSTRAINT ck_commodity_benchmarks_period_order
        CHECK (period_end >= period_start),
    CONSTRAINT ck_commodity_benchmarks_frequency
        CHECK (frequency IN ('daily', 'weekly', 'monthly'))
);

CREATE INDEX ix_commodity_bench_source_benchmark_period
    ON commodity_benchmarks (source_id, benchmark_code, period_start, period_end);

CREATE INDEX ix_commodity_bench_benchmark_observed
    ON commodity_benchmarks (benchmark_code, observed_at);

CREATE INDEX ix_commodity_bench_category_observed
    ON commodity_benchmarks (benchmark_category, observed_at);

CREATE INDEX ix_commodity_bench_family_observed
    ON commodity_benchmarks (commodity_family, observed_at);

CREATE INDEX ix_commodity_bench_fetched_at
    ON commodity_benchmarks (fetched_at);

CREATE INDEX ix_commodity_bench_raw_response_id
    ON commodity_benchmarks (raw_response_id);

CREATE INDEX ix_commodity_bench_collector_run_id
    ON commodity_benchmarks (collector_run_id);

CREATE INDEX ix_commodity_bench_source_record_hash
    ON commodity_benchmarks (source_record_hash);
