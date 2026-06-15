"""add news events schema

Revision ID: 0014_news_events_schema
Revises: 0013_weather_features
Create Date: 2026-06-11 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0014_news_events_schema"
down_revision = "0013_weather_features"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "news_articles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("raw_response_id", sa.Integer(), nullable=False),
        sa.Column("collector_run_id", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("body_text", sa.Text(), nullable=True),
        sa.Column("language", sa.String(length=32), nullable=False),
        sa.Column("source_name", sa.String(length=255), nullable=False),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("region", sa.String(length=100), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("article_hash", sa.String(length=64), nullable=False),
        sa.Column("source_record_hash", sa.String(length=64), nullable=False),
        sa.Column("source_payload_hash", sa.String(length=64), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["collector_run_id"], ["collector_runs.id"]),
        sa.ForeignKeyConstraint(["raw_response_id"], ["raw_responses.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_news_articles_source_external_id",
        "news_articles",
        ["source_id", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL"),
    )
    op.create_index("uq_news_articles_source_article_hash", "news_articles", ["source_id", "article_hash"], unique=True)
    op.create_index("ix_news_articles_source_published", "news_articles", ["source_id", "published_at"])
    op.create_index("ix_news_articles_published_at", "news_articles", ["published_at"])
    op.create_index("ix_news_articles_language", "news_articles", ["language"])
    op.create_index("ix_news_articles_country", "news_articles", ["country"])
    op.create_index("ix_news_articles_article_hash", "news_articles", ["article_hash"])
    op.create_index("ix_news_articles_raw_response_id", "news_articles", ["raw_response_id"])
    op.create_index("ix_news_articles_collector_run_id", "news_articles", ["collector_run_id"])
    op.create_index("ix_news_articles_record_hash", "news_articles", ["source_record_hash"])

    op.create_table(
        "commodity_events",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("news_article_id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("event_category", sa.String(length=100), nullable=False),
        sa.Column("commodity_family", sa.String(length=100), nullable=False),
        sa.Column("affected_products", sa.JSON(), nullable=True),
        sa.Column("country", sa.String(length=100), nullable=True),
        sa.Column("region", sa.String(length=100), nullable=True),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("direction_hint", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.Numeric(18, 8), nullable=True),
        sa.Column("confidence", sa.Numeric(18, 8), nullable=False),
        sa.Column("lag_bucket", sa.String(length=32), nullable=False),
        sa.Column("extraction_method", sa.String(length=64), nullable=False),
        sa.Column("extraction_version", sa.String(length=64), nullable=False),
        sa.Column("source_text_hash", sa.String(length=64), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "event_category IN ("
            "'export_restriction', 'import_policy', 'war_logistics_disruption', "
            "'weather_disaster', 'crop_report', 'biofuel_policy', 'energy_shock', "
            "'currency_macro', 'demand_shock', 'supply_chain'"
            ")",
            name="ck_commodity_events_category",
        ),
        sa.CheckConstraint("direction_hint IN ('bullish', 'bearish', 'mixed', 'unknown')", name="ck_commodity_events_direction"),
        sa.CheckConstraint("lag_bucket IN ('same_day', '1_7d', '7_30d', '30d_plus', 'unknown')", name="ck_commodity_events_lag_bucket"),
        sa.CheckConstraint(
            "extraction_method IN ('manual_rule', 'keyword_rule', 'official_report_mapping', 'future_nlp', 'future_llm')",
            name="ck_commodity_events_method",
        ),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name="ck_commodity_events_confidence"),
        sa.ForeignKeyConstraint(["news_article_id"], ["news_articles.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "news_article_id",
            "event_category",
            "commodity_family",
            "country",
            "region",
            "event_date",
            "extraction_method",
            name="uq_commodity_events_identity",
        ),
    )
    op.create_index("ix_commodity_events_category_date", "commodity_events", ["event_category", "event_date"])
    op.create_index("ix_commodity_events_family_date", "commodity_events", ["commodity_family", "event_date"])
    op.create_index("ix_commodity_events_country_date", "commodity_events", ["country", "event_date"])
    op.create_index("ix_commodity_events_published_at", "commodity_events", ["published_at"])
    op.create_index("ix_commodity_events_direction", "commodity_events", ["direction_hint"])
    op.create_index("ix_commodity_events_confidence", "commodity_events", ["confidence"])
    op.create_index("ix_commodity_events_article_id", "commodity_events", ["news_article_id"])
    op.create_index("ix_commodity_events_source_id", "commodity_events", ["source_id"])

    op.create_table(
        "daily_news_features",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("commodity_family", sa.String(length=100), nullable=False),
        sa.Column("feature_date", sa.Date(), nullable=False),
        sa.Column("news_count_1d", sa.Integer(), nullable=False),
        sa.Column("news_count_7d", sa.Integer(), nullable=False),
        sa.Column("news_count_30d", sa.Integer(), nullable=False),
        sa.Column("event_count_1d", sa.Integer(), nullable=False),
        sa.Column("event_count_7d", sa.Integer(), nullable=False),
        sa.Column("event_count_30d", sa.Integer(), nullable=False),
        sa.Column("bullish_event_count_7d", sa.Integer(), nullable=False),
        sa.Column("bearish_event_count_7d", sa.Integer(), nullable=False),
        sa.Column("mixed_event_count_7d", sa.Integer(), nullable=False),
        sa.Column("export_restriction_count_30d", sa.Integer(), nullable=False),
        sa.Column("import_policy_count_30d", sa.Integer(), nullable=False),
        sa.Column("war_logistics_count_30d", sa.Integer(), nullable=False),
        sa.Column("weather_disaster_count_30d", sa.Integer(), nullable=False),
        sa.Column("crop_report_count_30d", sa.Integer(), nullable=False),
        sa.Column("biofuel_policy_count_30d", sa.Integer(), nullable=False),
        sa.Column("energy_shock_count_30d", sa.Integer(), nullable=False),
        sa.Column("demand_shock_count_30d", sa.Integer(), nullable=False),
        sa.Column("supply_chain_count_30d", sa.Integer(), nullable=False),
        sa.Column("sentiment_proxy_7d", sa.Numeric(18, 8), nullable=True),
        sa.Column("news_as_of_date", sa.Date(), nullable=True),
        sa.Column("missing_flags", sa.JSON(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", "feature_date", name="uq_daily_news_features_product_date"),
    )
    op.create_index("ix_daily_news_features_product_date", "daily_news_features", ["product_id", "feature_date"])
    op.create_index("ix_daily_news_features_family_date", "daily_news_features", ["commodity_family", "feature_date"])
    op.create_index("ix_daily_news_features_feature_date", "daily_news_features", ["feature_date"])
    op.create_index("ix_daily_news_features_as_of", "daily_news_features", ["news_as_of_date"])


def downgrade() -> None:
    op.drop_index("ix_daily_news_features_as_of", table_name="daily_news_features")
    op.drop_index("ix_daily_news_features_feature_date", table_name="daily_news_features")
    op.drop_index("ix_daily_news_features_family_date", table_name="daily_news_features")
    op.drop_index("ix_daily_news_features_product_date", table_name="daily_news_features")
    op.drop_table("daily_news_features")

    op.drop_index("ix_commodity_events_source_id", table_name="commodity_events")
    op.drop_index("ix_commodity_events_article_id", table_name="commodity_events")
    op.drop_index("ix_commodity_events_confidence", table_name="commodity_events")
    op.drop_index("ix_commodity_events_direction", table_name="commodity_events")
    op.drop_index("ix_commodity_events_published_at", table_name="commodity_events")
    op.drop_index("ix_commodity_events_country_date", table_name="commodity_events")
    op.drop_index("ix_commodity_events_family_date", table_name="commodity_events")
    op.drop_index("ix_commodity_events_category_date", table_name="commodity_events")
    op.drop_table("commodity_events")

    op.drop_index("ix_news_articles_record_hash", table_name="news_articles")
    op.drop_index("ix_news_articles_collector_run_id", table_name="news_articles")
    op.drop_index("ix_news_articles_raw_response_id", table_name="news_articles")
    op.drop_index("ix_news_articles_article_hash", table_name="news_articles")
    op.drop_index("ix_news_articles_country", table_name="news_articles")
    op.drop_index("ix_news_articles_language", table_name="news_articles")
    op.drop_index("ix_news_articles_published_at", table_name="news_articles")
    op.drop_index("ix_news_articles_source_published", table_name="news_articles")
    op.drop_index("uq_news_articles_source_article_hash", table_name="news_articles")
    op.drop_index("uq_news_articles_source_external_id", table_name="news_articles")
    op.drop_table("news_articles")
