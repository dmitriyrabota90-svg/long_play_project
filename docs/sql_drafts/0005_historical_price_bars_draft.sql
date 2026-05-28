-- DRAFT ONLY. DO NOT APPLY.
-- Not an Alembic migration.
-- Phase 4.4 design draft for future review.

CREATE TABLE historical_price_bars (
    id SERIAL PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id),
    source_id INTEGER NOT NULL REFERENCES sources(id),
    raw_response_id INTEGER NOT NULL REFERENCES raw_responses(id),
    collector_run_id INTEGER NOT NULL REFERENCES collector_runs(id),
    external_code VARCHAR(100) NOT NULL,
    endpoint_alias VARCHAR(50) NOT NULL,
    bar_date DATE NOT NULL,
    bar_timeframe VARCHAR(50) NOT NULL,
    open_price NUMERIC(18, 6),
    high_price NUMERIC(18, 6),
    low_price NUMERIC(18, 6),
    close_price NUMERIC(18, 6),
    price NUMERIC(18, 6),
    volume NUMERIC(24, 6),
    currency VARCHAR(16) NOT NULL,
    unit VARCHAR(100) NOT NULL,
    observed_at TIMESTAMP WITH TIME ZONE NOT NULL,
    published_at TIMESTAMP WITH TIME ZONE,
    fetched_at TIMESTAMP WITH TIME ZONE NOT NULL,
    source_record_hash VARCHAR(64) NOT NULL,
    source_payload_hash VARCHAR(64) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT uq_historical_price_bars_product_source_endpoint_timeframe_date
        UNIQUE (product_id, source_id, endpoint_alias, bar_timeframe, bar_date)
);

CREATE INDEX ix_historical_price_bars_product_bar_date
    ON historical_price_bars (product_id, bar_date);

CREATE INDEX ix_historical_price_bars_source_fetched_at
    ON historical_price_bars (source_id, fetched_at);

CREATE INDEX ix_historical_price_bars_product_source_timeframe_bar_date
    ON historical_price_bars (product_id, source_id, bar_timeframe, bar_date);

CREATE INDEX ix_historical_price_bars_raw_response_id
    ON historical_price_bars (raw_response_id);

CREATE INDEX ix_historical_price_bars_collector_run_id
    ON historical_price_bars (collector_run_id);
