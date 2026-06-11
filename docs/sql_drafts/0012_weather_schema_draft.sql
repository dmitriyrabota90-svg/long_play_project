-- DRAFT ONLY. DO NOT APPLY.
-- Not an Alembic migration.
-- Phase 6.3B design reference for future weather tables.
-- Phase 6.3C should implement reviewed schema through Alembic.

CREATE TABLE weather_regions (
    id INTEGER PRIMARY KEY,
    region_code VARCHAR(100) NOT NULL,
    region_name VARCHAR(255) NOT NULL,
    country VARCHAR(100) NOT NULL,
    country_code VARCHAR(2) NULL,
    crop VARCHAR(100) NOT NULL,
    commodity_family VARCHAR(100) NOT NULL,
    role VARCHAR(100) NOT NULL,
    priority VARCHAR(32) NOT NULL,
    latitude NUMERIC(10, 6) NOT NULL,
    longitude NUMERIC(10, 6) NOT NULL,
    spatial_model VARCHAR(64) NOT NULL,
    aggregation_strategy VARCHAR(100) NOT NULL,
    is_active BOOLEAN NOT NULL,
    metadata_json JSONB NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT uq_weather_regions_code
        UNIQUE (region_code),
    CONSTRAINT ck_weather_regions_priority
        CHECK (priority IN ('high', 'medium', 'later')),
    CONSTRAINT ck_weather_regions_latitude
        CHECK (latitude >= -90 AND latitude <= 90),
    CONSTRAINT ck_weather_regions_longitude
        CHECK (longitude >= -180 AND longitude <= 180)
);

CREATE INDEX ix_weather_regions_region_code
    ON weather_regions (region_code);

CREATE INDEX ix_weather_regions_country_crop
    ON weather_regions (country, crop);

CREATE INDEX ix_weather_regions_family
    ON weather_regions (commodity_family);

CREATE INDEX ix_weather_regions_active
    ON weather_regions (is_active);

CREATE INDEX ix_weather_regions_priority
    ON weather_regions (priority);

CREATE TABLE weather_observations (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    raw_response_id INTEGER NOT NULL REFERENCES raw_responses(id),
    collector_run_id INTEGER NOT NULL REFERENCES collector_runs(id),
    region_id INTEGER NOT NULL REFERENCES weather_regions(id),
    source_region_key VARCHAR(255) NOT NULL,
    observation_date DATE NOT NULL,
    observed_at TIMESTAMP WITH TIME ZONE NOT NULL,
    fetched_at TIMESTAMP WITH TIME ZONE NOT NULL,
    frequency VARCHAR(32) NOT NULL,
    temperature_2m_mean NUMERIC(18, 8) NULL,
    temperature_2m_min NUMERIC(18, 8) NULL,
    temperature_2m_max NUMERIC(18, 8) NULL,
    precipitation_sum NUMERIC(18, 8) NULL,
    snowfall_sum NUMERIC(18, 8) NULL,
    relative_humidity_mean NUMERIC(18, 8) NULL,
    wind_speed_mean NUMERIC(18, 8) NULL,
    wind_speed_max NUMERIC(18, 8) NULL,
    soil_moisture NUMERIC(18, 8) NULL,
    evapotranspiration NUMERIC(18, 8) NULL,
    shortwave_radiation NUMERIC(18, 8) NULL,
    source_record_hash VARCHAR(64) NOT NULL,
    source_payload_hash VARCHAR(64) NOT NULL,
    metadata_json JSONB NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT uq_weather_obs_source_region_date_freq
        UNIQUE (source_id, region_id, observation_date, frequency),
    CONSTRAINT ck_weather_obs_frequency
        CHECK (frequency IN ('daily'))
);

CREATE INDEX ix_weather_obs_region_date
    ON weather_observations (region_id, observation_date);

CREATE INDEX ix_weather_obs_source_date
    ON weather_observations (source_id, observation_date);

CREATE INDEX ix_weather_obs_fetched_at
    ON weather_observations (fetched_at);

CREATE INDEX ix_weather_obs_raw_response_id
    ON weather_observations (raw_response_id);

CREATE INDEX ix_weather_obs_collector_run_id
    ON weather_observations (collector_run_id);

CREATE INDEX ix_weather_obs_record_hash
    ON weather_observations (source_record_hash);

CREATE TABLE weather_daily_features (
    id INTEGER PRIMARY KEY,
    region_id INTEGER NOT NULL REFERENCES weather_regions(id),
    feature_date DATE NOT NULL,
    temperature_7d_mean NUMERIC(18, 8) NULL,
    temperature_30d_mean NUMERIC(18, 8) NULL,
    temperature_min_7d NUMERIC(18, 8) NULL,
    temperature_max_7d NUMERIC(18, 8) NULL,
    precipitation_7d_sum NUMERIC(18, 8) NULL,
    precipitation_14d_sum NUMERIC(18, 8) NULL,
    precipitation_30d_sum NUMERIC(18, 8) NULL,
    heat_stress_days_7d INTEGER NULL,
    heat_stress_days_30d INTEGER NULL,
    frost_days_7d INTEGER NULL,
    frost_days_30d INTEGER NULL,
    drought_proxy_30d NUMERIC(18, 8) NULL,
    growing_degree_days_7d NUMERIC(18, 8) NULL,
    growing_degree_days_30d NUMERIC(18, 8) NULL,
    weather_as_of_date DATE NULL,
    missing_flags JSONB NULL,
    metadata_json JSONB NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT uq_weather_daily_region_date
        UNIQUE (region_id, feature_date)
);

CREATE INDEX ix_weather_daily_features_region_date
    ON weather_daily_features (region_id, feature_date);

CREATE INDEX ix_weather_daily_features_as_of
    ON weather_daily_features (weather_as_of_date);

CREATE TABLE product_weather_region_weights (
    id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id),
    region_id INTEGER NOT NULL REFERENCES weather_regions(id),
    weight NUMERIC(18, 8) NOT NULL,
    role VARCHAR(100) NOT NULL,
    effective_from DATE NOT NULL,
    effective_to DATE NULL,
    is_active BOOLEAN NOT NULL,
    metadata_json JSONB NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT uq_product_weather_region_effective
        UNIQUE (product_id, region_id, role, effective_from),
    CONSTRAINT ck_product_weather_weight_nonnegative
        CHECK (weight >= 0),
    CONSTRAINT ck_product_weather_effective_range
        CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

CREATE INDEX ix_product_weather_product_active
    ON product_weather_region_weights (product_id, is_active);

CREATE INDEX ix_product_weather_region_active
    ON product_weather_region_weights (region_id, is_active);

CREATE INDEX ix_product_weather_effective
    ON product_weather_region_weights (effective_from, effective_to);
