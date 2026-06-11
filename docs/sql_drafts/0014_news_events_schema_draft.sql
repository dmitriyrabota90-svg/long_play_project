-- DRAFT ONLY. DO NOT APPLY.
-- Not an Alembic migration.
-- Phase 6.4B design reference for future news/events tables.
-- Phase 6.4C should implement reviewed schema through Alembic.

CREATE TABLE news_articles (
    id INTEGER PRIMARY KEY,
    source_id INTEGER NOT NULL REFERENCES sources(id),
    raw_response_id INTEGER NOT NULL REFERENCES raw_responses(id),
    collector_run_id INTEGER NOT NULL REFERENCES collector_runs(id),
    external_id VARCHAR(255) NULL,
    url TEXT NOT NULL,
    canonical_url TEXT NULL,
    title TEXT NOT NULL,
    summary TEXT NULL,
    body_text TEXT NULL,
    language VARCHAR(32) NOT NULL,
    source_name VARCHAR(255) NOT NULL,
    country VARCHAR(100) NULL,
    region VARCHAR(100) NULL,
    published_at TIMESTAMP WITH TIME ZONE NOT NULL,
    fetched_at TIMESTAMP WITH TIME ZONE NOT NULL,
    article_hash VARCHAR(64) NOT NULL,
    source_record_hash VARCHAR(64) NOT NULL,
    source_payload_hash VARCHAR(64) NOT NULL,
    metadata_json JSONB NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL
);

CREATE UNIQUE INDEX uq_news_articles_source_external_id
    ON news_articles (source_id, external_id)
    WHERE external_id IS NOT NULL;

CREATE UNIQUE INDEX uq_news_articles_source_article_hash
    ON news_articles (source_id, article_hash);

CREATE INDEX ix_news_articles_source_published
    ON news_articles (source_id, published_at);

CREATE INDEX ix_news_articles_published_at
    ON news_articles (published_at);

CREATE INDEX ix_news_articles_language
    ON news_articles (language);

CREATE INDEX ix_news_articles_country
    ON news_articles (country);

CREATE INDEX ix_news_articles_article_hash
    ON news_articles (article_hash);

CREATE INDEX ix_news_articles_raw_response_id
    ON news_articles (raw_response_id);

CREATE INDEX ix_news_articles_collector_run_id
    ON news_articles (collector_run_id);

CREATE INDEX ix_news_articles_record_hash
    ON news_articles (source_record_hash);

CREATE TABLE commodity_events (
    id INTEGER PRIMARY KEY,
    news_article_id INTEGER NOT NULL REFERENCES news_articles(id),
    source_id INTEGER NOT NULL REFERENCES sources(id),
    event_category VARCHAR(100) NOT NULL,
    commodity_family VARCHAR(100) NOT NULL,
    affected_products JSONB NULL,
    country VARCHAR(100) NULL,
    region VARCHAR(100) NULL,
    event_date DATE NOT NULL,
    published_at TIMESTAMP WITH TIME ZONE NOT NULL,
    direction_hint VARCHAR(32) NOT NULL,
    severity NUMERIC(18, 8) NULL,
    confidence NUMERIC(18, 8) NOT NULL,
    lag_bucket VARCHAR(32) NOT NULL,
    extraction_method VARCHAR(64) NOT NULL,
    extraction_version VARCHAR(64) NOT NULL,
    source_text_hash VARCHAR(64) NOT NULL,
    metadata_json JSONB NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT ck_commodity_events_category
        CHECK (event_category IN (
            'export_restriction',
            'import_policy',
            'war_logistics_disruption',
            'weather_disaster',
            'crop_report',
            'biofuel_policy',
            'energy_shock',
            'currency_macro',
            'demand_shock',
            'supply_chain'
        )),
    CONSTRAINT uq_commodity_events_identity
        UNIQUE (news_article_id, event_category, commodity_family, country, region, event_date, extraction_method),
    CONSTRAINT ck_commodity_events_direction
        CHECK (direction_hint IN ('bullish', 'bearish', 'mixed', 'unknown')),
    CONSTRAINT ck_commodity_events_lag_bucket
        CHECK (lag_bucket IN ('same_day', '1_7d', '7_30d', '30d_plus', 'unknown')),
    CONSTRAINT ck_commodity_events_extraction_method
        CHECK (extraction_method IN ('manual_rule', 'keyword_rule', 'official_report_mapping', 'future_nlp', 'future_llm')),
    CONSTRAINT ck_commodity_events_confidence_range
        CHECK (confidence >= 0 AND confidence <= 1)
);

CREATE INDEX ix_commodity_events_category_date
    ON commodity_events (event_category, event_date);

CREATE INDEX ix_commodity_events_family_date
    ON commodity_events (commodity_family, event_date);

CREATE INDEX ix_commodity_events_country_date
    ON commodity_events (country, event_date);

CREATE INDEX ix_commodity_events_published_at
    ON commodity_events (published_at);

CREATE INDEX ix_commodity_events_direction
    ON commodity_events (direction_hint);

CREATE INDEX ix_commodity_events_confidence
    ON commodity_events (confidence);

CREATE INDEX ix_commodity_events_article_id
    ON commodity_events (news_article_id);

CREATE INDEX ix_commodity_events_source_id
    ON commodity_events (source_id);

CREATE TABLE daily_news_features (
    id INTEGER PRIMARY KEY,
    product_id INTEGER NOT NULL REFERENCES products(id),
    commodity_family VARCHAR(100) NOT NULL,
    feature_date DATE NOT NULL,
    news_count_1d INTEGER NOT NULL,
    news_count_7d INTEGER NOT NULL,
    news_count_30d INTEGER NOT NULL,
    event_count_1d INTEGER NOT NULL,
    event_count_7d INTEGER NOT NULL,
    event_count_30d INTEGER NOT NULL,
    bullish_event_count_7d INTEGER NOT NULL,
    bearish_event_count_7d INTEGER NOT NULL,
    mixed_event_count_7d INTEGER NOT NULL,
    export_restriction_count_30d INTEGER NOT NULL,
    import_policy_count_30d INTEGER NOT NULL,
    war_logistics_count_30d INTEGER NOT NULL,
    weather_disaster_count_30d INTEGER NOT NULL,
    crop_report_count_30d INTEGER NOT NULL,
    biofuel_policy_count_30d INTEGER NOT NULL,
    energy_shock_count_30d INTEGER NOT NULL,
    demand_shock_count_30d INTEGER NOT NULL,
    supply_chain_count_30d INTEGER NOT NULL,
    sentiment_proxy_7d NUMERIC(18, 8) NULL,
    news_as_of_date DATE NULL,
    missing_flags JSONB NULL,
    metadata_json JSONB NULL,
    created_at TIMESTAMP WITH TIME ZONE NOT NULL,
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL,
    CONSTRAINT uq_daily_news_features_product_date
        UNIQUE (product_id, feature_date)
);

CREATE INDEX ix_daily_news_features_product_date
    ON daily_news_features (product_id, feature_date);

CREATE INDEX ix_daily_news_features_family_date
    ON daily_news_features (commodity_family, feature_date);

CREATE INDEX ix_daily_news_features_as_of
    ON daily_news_features (news_as_of_date);
