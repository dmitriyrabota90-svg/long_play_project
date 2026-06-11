-- DRAFT ONLY. DO NOT APPLY.
-- Not an Alembic migration.
-- Phase 6.7B design reference for future supply-demand / production-stocks tables.
-- Phase 6.7C should implement reviewed schema through Alembic.

CREATE TABLE supply_demand_commodities (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NULL REFERENCES sources(id),
    source_commodity_code VARCHAR(100) NULL,
    source_commodity_name VARCHAR(255) NOT NULL,
    source_metric_code VARCHAR(100) NULL,
    source_metric_name VARCHAR(255) NOT NULL,
    commodity_family VARCHAR(100) NOT NULL,
    product_code VARCHAR(100) NULL,
    metric_name VARCHAR(100) NOT NULL,
    metric_group VARCHAR(100) NOT NULL,
    unit_hint VARCHAR(100) NULL,
    frequency VARCHAR(64) NOT NULL,
    relevance VARCHAR(32) NOT NULL,
    is_active BOOLEAN NOT NULL,
    metadata_json JSONB NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT uq_supply_demand_commodities_source_metric
        UNIQUE (source_id, source_commodity_code, source_metric_code, metric_name),
    CONSTRAINT ck_supply_demand_commodities_relevance
        CHECK (relevance IN ('direct', 'context', 'later')),
    CONSTRAINT ck_supply_demand_commodities_metric_group
        CHECK (
            metric_group IN (
                'production',
                'consumption_use',
                'processing',
                'trade',
                'stocks',
                'area_yield',
                'report_metadata',
                'quality',
                'unknown'
            )
        )
);

CREATE INDEX ix_supply_demand_commodities_family
    ON supply_demand_commodities (commodity_family);

CREATE INDEX ix_supply_demand_commodities_product_code
    ON supply_demand_commodities (product_code);

CREATE INDEX ix_supply_demand_commodities_metric_name
    ON supply_demand_commodities (metric_name);

CREATE INDEX ix_supply_demand_commodities_metric_group
    ON supply_demand_commodities (metric_group);

CREATE INDEX ix_supply_demand_commodities_is_active
    ON supply_demand_commodities (is_active);

CREATE TABLE supply_demand_observations (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    raw_response_id INTEGER NOT NULL REFERENCES raw_responses(id),
    collector_run_id INTEGER NOT NULL REFERENCES collector_runs(id),
    supply_demand_commodity_id INTEGER NOT NULL REFERENCES supply_demand_commodities(id),
    source_record_id VARCHAR(255) NULL,
    country_code VARCHAR(32) NOT NULL,
    country_name VARCHAR(255) NOT NULL,
    region_code VARCHAR(64) NULL,
    region_name VARCHAR(255) NULL,
    marketing_year VARCHAR(32) NOT NULL,
    marketing_year_start DATE NULL,
    marketing_year_end DATE NULL,
    report_month INTEGER NOT NULL,
    report_year INTEGER NOT NULL,
    report_published_at TIMESTAMP WITH TIME ZONE NULL,
    observed_period_start DATE NULL,
    observed_period_end DATE NULL,
    frequency VARCHAR(32) NOT NULL,
    estimate_type VARCHAR(32) NOT NULL,
    metric_value NUMERIC(18, 8) NOT NULL,
    metric_unit VARCHAR(100) NOT NULL,
    value_usd NUMERIC(18, 8) NULL,
    is_forecast BOOLEAN NOT NULL,
    is_revision BOOLEAN NOT NULL,
    published_at TIMESTAMP WITH TIME ZONE NULL,
    fetched_at TIMESTAMP WITH TIME ZONE NOT NULL,
    source_record_hash VARCHAR(64) NOT NULL,
    source_payload_hash VARCHAR(64) NOT NULL,
    metadata_json JSONB NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT uq_supply_demand_observations_identity
        UNIQUE (
            source_id,
            supply_demand_commodity_id,
            country_code,
            marketing_year,
            report_year,
            report_month,
            estimate_type
        ),
    CONSTRAINT ck_supply_demand_observations_estimate_type
        CHECK (estimate_type IN ('actual', 'estimate', 'forecast', 'projection', 'unknown')),
    CONSTRAINT ck_supply_demand_observations_frequency
        CHECK (frequency IN ('monthly_report', 'marketing_year', 'annual', 'quarterly', 'unknown')),
    CONSTRAINT ck_supply_demand_observations_report_month
        CHECK (report_month BETWEEN 1 AND 12),
    CONSTRAINT ck_supply_demand_observations_marketing_dates
        CHECK (marketing_year_end IS NULL OR marketing_year_start IS NULL OR marketing_year_end >= marketing_year_start),
    CONSTRAINT ck_supply_demand_observations_observed_dates
        CHECK (observed_period_end IS NULL OR observed_period_start IS NULL OR observed_period_end >= observed_period_start)
);

CREATE INDEX ix_supply_demand_obs_commodity_year
    ON supply_demand_observations (supply_demand_commodity_id, marketing_year);

CREATE INDEX ix_supply_demand_obs_country_year
    ON supply_demand_observations (country_code, marketing_year);

CREATE INDEX ix_supply_demand_obs_report_published
    ON supply_demand_observations (report_published_at);

CREATE INDEX ix_supply_demand_obs_published_at
    ON supply_demand_observations (published_at);

CREATE INDEX ix_supply_demand_obs_fetched_at
    ON supply_demand_observations (fetched_at);

CREATE INDEX ix_supply_demand_obs_raw_response_id
    ON supply_demand_observations (raw_response_id);

CREATE INDEX ix_supply_demand_obs_collector_run_id
    ON supply_demand_observations (collector_run_id);

CREATE INDEX ix_supply_demand_obs_record_hash
    ON supply_demand_observations (source_record_hash);

CREATE TABLE supply_demand_revisions (
    id INTEGER PRIMARY KEY,
    supply_demand_observation_id INTEGER NOT NULL REFERENCES supply_demand_observations(id),
    revision_number INTEGER NOT NULL,
    old_metric_value NUMERIC(18, 8) NULL,
    new_metric_value NUMERIC(18, 8) NULL,
    old_source_record_hash VARCHAR(64) NOT NULL,
    new_source_record_hash VARCHAR(64) NOT NULL,
    revision_reason VARCHAR(64) NOT NULL,
    detected_at TIMESTAMP WITH TIME ZONE NOT NULL,
    metadata_json JSONB NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT uq_supply_demand_revisions_obs_number
        UNIQUE (supply_demand_observation_id, revision_number),
    CONSTRAINT ck_supply_demand_revisions_reason
        CHECK (
            revision_reason IN (
                'source_revision',
                'report_restatement',
                'corrected_estimate',
                'parser_change',
                'unknown'
            )
        )
);

CREATE INDEX ix_supply_demand_revisions_observation_id
    ON supply_demand_revisions (supply_demand_observation_id);

CREATE INDEX ix_supply_demand_revisions_detected_at
    ON supply_demand_revisions (detected_at);

CREATE INDEX ix_supply_demand_revisions_reason
    ON supply_demand_revisions (revision_reason);

CREATE TABLE product_supply_demand_weights (
    id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id),
    supply_demand_commodity_id INTEGER NOT NULL REFERENCES supply_demand_commodities(id),
    weight NUMERIC(18, 8) NOT NULL,
    relevance VARCHAR(32) NOT NULL,
    role VARCHAR(64) NOT NULL,
    effective_from DATE NOT NULL,
    effective_to DATE NULL,
    is_active BOOLEAN NOT NULL,
    metadata_json JSONB NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT uq_product_supply_demand_weights_identity
        UNIQUE (product_id, supply_demand_commodity_id, role, effective_from),
    CONSTRAINT ck_product_supply_demand_weights_relevance
        CHECK (relevance IN ('direct', 'context', 'later')),
    CONSTRAINT ck_product_supply_demand_weights_dates
        CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

CREATE INDEX ix_product_supply_demand_weights_product_active
    ON product_supply_demand_weights (product_id, is_active);

CREATE INDEX ix_product_supply_demand_weights_commodity_active
    ON product_supply_demand_weights (supply_demand_commodity_id, is_active);

CREATE INDEX ix_product_supply_demand_weights_effective
    ON product_supply_demand_weights (effective_from, effective_to);

CREATE TABLE daily_supply_demand_features (
    id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id),
    feature_date DATE NOT NULL,
    production_volume NUMERIC(18, 8) NULL,
    domestic_consumption NUMERIC(18, 8) NULL,
    food_use NUMERIC(18, 8) NULL,
    feed_use NUMERIC(18, 8) NULL,
    crush_volume NUMERIC(18, 8) NULL,
    exports_volume NUMERIC(18, 8) NULL,
    imports_volume NUMERIC(18, 8) NULL,
    beginning_stocks NUMERIC(18, 8) NULL,
    ending_stocks NUMERIC(18, 8) NULL,
    stock_to_use_ratio NUMERIC(18, 8) NULL,
    planted_area NUMERIC(18, 8) NULL,
    harvested_area NUMERIC(18, 8) NULL,
    yield_value NUMERIC(18, 8) NULL,
    production_forecast_revision NUMERIC(18, 8) NULL,
    ending_stocks_revision NUMERIC(18, 8) NULL,
    stock_to_use_revision NUMERIC(18, 8) NULL,
    forecast_month INTEGER NULL,
    marketing_year VARCHAR(32) NULL,
    report_published_at TIMESTAMP WITH TIME ZONE NULL,
    supply_demand_as_of_date DATE NULL,
    reporting_lag_days INTEGER NULL,
    missing_flags JSONB NULL,
    metadata_json JSONB NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT uq_daily_supply_demand_features_product_date
        UNIQUE (product_id, feature_date),
    CONSTRAINT ck_daily_supply_demand_features_as_of
        CHECK (supply_demand_as_of_date IS NULL OR supply_demand_as_of_date <= feature_date)
);

CREATE INDEX ix_daily_supply_demand_features_product_date
    ON daily_supply_demand_features (product_id, feature_date);

CREATE INDEX ix_daily_supply_demand_features_feature_date
    ON daily_supply_demand_features (feature_date);

CREATE INDEX ix_daily_supply_demand_features_as_of
    ON daily_supply_demand_features (supply_demand_as_of_date);

CREATE INDEX ix_daily_supply_demand_features_marketing_year
    ON daily_supply_demand_features (marketing_year);
