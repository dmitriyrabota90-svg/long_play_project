-- DRAFT ONLY. DO NOT APPLY.
-- Not an Alembic migration.
-- Phase 6.5B design reference for future trade/import-export tables.
-- Phase 6.5C should implement reviewed schema through Alembic.

CREATE TABLE trade_commodity_codes (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NULL REFERENCES sources(id),
    code_system VARCHAR(64) NOT NULL,
    commodity_code VARCHAR(64) NOT NULL,
    commodity_name VARCHAR(255) NOT NULL,
    hs_code VARCHAR(64) NULL,
    hs_revision VARCHAR(32) NOT NULL,
    commodity_family VARCHAR(100) NOT NULL,
    product_code VARCHAR(100) NULL,
    relevance VARCHAR(32) NOT NULL,
    unit_hint VARCHAR(100) NULL,
    is_active BOOLEAN NOT NULL,
    metadata_json JSONB NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT uq_trade_codes_system_code_rev
        UNIQUE (code_system, commodity_code, hs_revision),
    CONSTRAINT ck_trade_commodity_codes_relevance
        CHECK (relevance IN ('direct', 'context', 'later'))
);

CREATE INDEX ix_trade_commodity_codes_family
    ON trade_commodity_codes (commodity_family);

CREATE INDEX ix_trade_commodity_codes_product_code
    ON trade_commodity_codes (product_code);

CREATE INDEX ix_trade_commodity_codes_hs_code
    ON trade_commodity_codes (hs_code);

CREATE INDEX ix_trade_commodity_codes_is_active
    ON trade_commodity_codes (is_active);

CREATE TABLE trade_flows (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    raw_response_id INTEGER NOT NULL REFERENCES raw_responses(id),
    collector_run_id INTEGER NOT NULL REFERENCES collector_runs(id),
    trade_commodity_code_id INTEGER NOT NULL REFERENCES trade_commodity_codes(id),
    source_record_id VARCHAR(255) NULL,
    reporter_code VARCHAR(32) NOT NULL,
    reporter_name VARCHAR(255) NOT NULL,
    partner_code VARCHAR(32) NOT NULL,
    partner_name VARCHAR(255) NOT NULL,
    flow_direction VARCHAR(32) NOT NULL,
    trade_period VARCHAR(32) NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    frequency VARCHAR(32) NOT NULL,
    quantity NUMERIC(18, 8) NULL,
    quantity_unit VARCHAR(100) NULL,
    trade_value_usd NUMERIC(18, 8) NULL,
    trade_value_local NUMERIC(18, 8) NULL,
    currency VARCHAR(16) NULL,
    unit_value_usd NUMERIC(18, 8) NULL,
    net_weight_kg NUMERIC(18, 8) NULL,
    gross_weight_kg NUMERIC(18, 8) NULL,
    published_at TIMESTAMP WITH TIME ZONE NULL,
    fetched_at TIMESTAMP WITH TIME ZONE NOT NULL,
    source_record_hash VARCHAR(64) NOT NULL,
    source_payload_hash VARCHAR(64) NOT NULL,
    metadata_json JSONB NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT uq_trade_flows_identity
        UNIQUE (
            source_id,
            trade_commodity_code_id,
            reporter_code,
            partner_code,
            flow_direction,
            frequency,
            period_start,
            period_end
        ),
    CONSTRAINT ck_trade_flows_direction
        CHECK (flow_direction IN ('export', 'import', 're_export', 're_import', 'unknown')),
    CONSTRAINT ck_trade_flows_frequency
        CHECK (frequency IN ('monthly', 'annual', 'quarterly', 'unknown')),
    CONSTRAINT ck_trade_flows_period_order
        CHECK (period_end >= period_start)
);

CREATE INDEX ix_trade_flows_code_period
    ON trade_flows (trade_commodity_code_id, period_start);

CREATE INDEX ix_trade_flows_reporter_period
    ON trade_flows (reporter_code, period_start);

CREATE INDEX ix_trade_flows_partner_period
    ON trade_flows (partner_code, period_start);

CREATE INDEX ix_trade_flows_direction_period
    ON trade_flows (flow_direction, period_start);

CREATE INDEX ix_trade_flows_source_fetched
    ON trade_flows (source_id, fetched_at);

CREATE INDEX ix_trade_flows_raw_response_id
    ON trade_flows (raw_response_id);

CREATE INDEX ix_trade_flows_collector_run_id
    ON trade_flows (collector_run_id);

CREATE INDEX ix_trade_flows_record_hash
    ON trade_flows (source_record_hash);

CREATE TABLE product_trade_code_weights (
    id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id),
    trade_commodity_code_id INTEGER NOT NULL REFERENCES trade_commodity_codes(id),
    weight NUMERIC(18, 8) NOT NULL,
    relevance VARCHAR(32) NOT NULL,
    role VARCHAR(64) NOT NULL,
    effective_from DATE NOT NULL,
    effective_to DATE NULL,
    is_active BOOLEAN NOT NULL,
    metadata_json JSONB NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT uq_product_trade_code_weights_identity
        UNIQUE (product_id, trade_commodity_code_id, role, effective_from),
    CONSTRAINT ck_product_trade_code_weights_relevance
        CHECK (relevance IN ('direct', 'context', 'later')),
    CONSTRAINT ck_product_trade_code_weights_dates
        CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

CREATE INDEX ix_product_trade_weights_product_active
    ON product_trade_code_weights (product_id, is_active);

CREATE INDEX ix_product_trade_weights_code_active
    ON product_trade_code_weights (trade_commodity_code_id, is_active);

CREATE INDEX ix_product_trade_weights_effective
    ON product_trade_code_weights (effective_from, effective_to);

CREATE TABLE daily_trade_features (
    id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id),
    feature_date DATE NOT NULL,
    export_volume_1m NUMERIC(18, 8) NULL,
    export_volume_3m_avg NUMERIC(18, 8) NULL,
    export_volume_12m_sum NUMERIC(18, 8) NULL,
    import_volume_1m NUMERIC(18, 8) NULL,
    import_volume_3m_avg NUMERIC(18, 8) NULL,
    import_volume_12m_sum NUMERIC(18, 8) NULL,
    net_export_volume_1m NUMERIC(18, 8) NULL,
    export_value_usd_1m NUMERIC(18, 8) NULL,
    import_value_usd_1m NUMERIC(18, 8) NULL,
    average_export_unit_value_usd NUMERIC(18, 8) NULL,
    average_import_unit_value_usd NUMERIC(18, 8) NULL,
    china_import_volume_1m NUMERIC(18, 8) NULL,
    major_exporter_volume_1m NUMERIC(18, 8) NULL,
    major_importer_volume_1m NUMERIC(18, 8) NULL,
    trade_balance_proxy NUMERIC(18, 8) NULL,
    trade_yoy_change NUMERIC(18, 8) NULL,
    trade_as_of_date DATE NULL,
    reporting_lag_days INTEGER NULL,
    missing_flags JSONB NULL,
    metadata_json JSONB NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT uq_daily_trade_features_product_date
        UNIQUE (product_id, feature_date),
    CONSTRAINT ck_daily_trade_features_as_of
        CHECK (trade_as_of_date IS NULL OR trade_as_of_date <= feature_date)
);

CREATE INDEX ix_daily_trade_features_product_date
    ON daily_trade_features (product_id, feature_date);

CREATE INDEX ix_daily_trade_features_feature_date
    ON daily_trade_features (feature_date);

CREATE INDEX ix_daily_trade_features_as_of
    ON daily_trade_features (trade_as_of_date);
