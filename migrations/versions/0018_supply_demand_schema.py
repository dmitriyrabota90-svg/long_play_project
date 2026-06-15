"""add supply demand schema

Revision ID: 0018_supply_demand_schema
Revises: 0017_trade_features
Create Date: 2026-06-14 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0018_supply_demand_schema"
down_revision = "0017_trade_features"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "supply_demand_commodities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("source_commodity_code", sa.String(length=100), nullable=True),
        sa.Column("source_commodity_name", sa.String(length=255), nullable=False),
        sa.Column("source_metric_code", sa.String(length=100), nullable=True),
        sa.Column("source_metric_name", sa.String(length=255), nullable=False),
        sa.Column("commodity_family", sa.String(length=100), nullable=False),
        sa.Column("product_code", sa.String(length=100), nullable=True),
        sa.Column("metric_name", sa.String(length=100), nullable=False),
        sa.Column("metric_group", sa.String(length=100), nullable=False),
        sa.Column("unit_hint", sa.String(length=100), nullable=True),
        sa.Column("frequency", sa.String(length=64), nullable=False),
        sa.Column("relevance", sa.String(length=32), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("relevance IN ('direct', 'context', 'later')", name="ck_supply_demand_commodities_relevance"),
        sa.CheckConstraint(
            "metric_group IN ("
            "'production', "
            "'consumption_use', "
            "'processing', "
            "'trade', "
            "'stocks', "
            "'area_yield', "
            "'report_metadata', "
            "'quality', "
            "'unknown'"
            ")",
            name="ck_supply_demand_commodities_metric_group",
        ),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id",
            "source_commodity_code",
            "source_metric_code",
            "metric_name",
            name="uq_supply_demand_commodities_source_metric",
        ),
    )
    op.create_index("ix_supply_demand_commodities_family", "supply_demand_commodities", ["commodity_family"])
    op.create_index("ix_supply_demand_commodities_product_code", "supply_demand_commodities", ["product_code"])
    op.create_index("ix_supply_demand_commodities_metric_name", "supply_demand_commodities", ["metric_name"])
    op.create_index("ix_supply_demand_commodities_metric_group", "supply_demand_commodities", ["metric_group"])
    op.create_index("ix_supply_demand_commodities_is_active", "supply_demand_commodities", ["is_active"])

    op.create_table(
        "supply_demand_observations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("raw_response_id", sa.Integer(), nullable=False),
        sa.Column("collector_run_id", sa.Integer(), nullable=False),
        sa.Column("supply_demand_commodity_id", sa.Integer(), nullable=False),
        sa.Column("source_record_id", sa.String(length=255), nullable=True),
        sa.Column("country_code", sa.String(length=32), nullable=False),
        sa.Column("country_name", sa.String(length=255), nullable=False),
        sa.Column("region_code", sa.String(length=64), nullable=True),
        sa.Column("region_name", sa.String(length=255), nullable=True),
        sa.Column("marketing_year", sa.String(length=32), nullable=False),
        sa.Column("marketing_year_start", sa.Date(), nullable=True),
        sa.Column("marketing_year_end", sa.Date(), nullable=True),
        sa.Column("report_month", sa.Integer(), nullable=False),
        sa.Column("report_year", sa.Integer(), nullable=False),
        sa.Column("report_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observed_period_start", sa.Date(), nullable=True),
        sa.Column("observed_period_end", sa.Date(), nullable=True),
        sa.Column("frequency", sa.String(length=32), nullable=False),
        sa.Column("estimate_type", sa.String(length=32), nullable=False),
        sa.Column("metric_value", sa.Numeric(18, 8), nullable=False),
        sa.Column("metric_unit", sa.String(length=100), nullable=False),
        sa.Column("value_usd", sa.Numeric(18, 8), nullable=True),
        sa.Column("is_forecast", sa.Boolean(), nullable=False),
        sa.Column("is_revision", sa.Boolean(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_record_hash", sa.String(length=64), nullable=False),
        sa.Column("source_payload_hash", sa.String(length=64), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "estimate_type IN ('actual', 'estimate', 'forecast', 'projection', 'unknown')",
            name="ck_supply_demand_observations_estimate_type",
        ),
        sa.CheckConstraint(
            "frequency IN ('monthly_report', 'marketing_year', 'annual', 'quarterly', 'unknown')",
            name="ck_supply_demand_observations_frequency",
        ),
        sa.CheckConstraint("report_month BETWEEN 1 AND 12", name="ck_supply_demand_observations_report_month"),
        sa.CheckConstraint(
            "marketing_year_end IS NULL OR marketing_year_start IS NULL OR marketing_year_end >= marketing_year_start",
            name="ck_supply_demand_observations_marketing_dates",
        ),
        sa.CheckConstraint(
            "observed_period_end IS NULL OR observed_period_start IS NULL OR observed_period_end >= observed_period_start",
            name="ck_supply_demand_observations_observed_dates",
        ),
        sa.ForeignKeyConstraint(["collector_run_id"], ["collector_runs.id"]),
        sa.ForeignKeyConstraint(["raw_response_id"], ["raw_responses.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.ForeignKeyConstraint(["supply_demand_commodity_id"], ["supply_demand_commodities.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id",
            "supply_demand_commodity_id",
            "country_code",
            "marketing_year",
            "report_year",
            "report_month",
            "estimate_type",
            name="uq_supply_demand_observations_identity",
        ),
    )
    op.create_index("ix_supply_demand_obs_commodity_year", "supply_demand_observations", ["supply_demand_commodity_id", "marketing_year"])
    op.create_index("ix_supply_demand_obs_country_year", "supply_demand_observations", ["country_code", "marketing_year"])
    op.create_index("ix_supply_demand_obs_report_published", "supply_demand_observations", ["report_published_at"])
    op.create_index("ix_supply_demand_obs_published_at", "supply_demand_observations", ["published_at"])
    op.create_index("ix_supply_demand_obs_fetched_at", "supply_demand_observations", ["fetched_at"])
    op.create_index("ix_supply_demand_obs_raw_response_id", "supply_demand_observations", ["raw_response_id"])
    op.create_index("ix_supply_demand_obs_collector_run_id", "supply_demand_observations", ["collector_run_id"])
    op.create_index("ix_supply_demand_obs_record_hash", "supply_demand_observations", ["source_record_hash"])

    op.create_table(
        "supply_demand_revisions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("supply_demand_observation_id", sa.Integer(), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("old_metric_value", sa.Numeric(18, 8), nullable=True),
        sa.Column("new_metric_value", sa.Numeric(18, 8), nullable=True),
        sa.Column("old_source_record_hash", sa.String(length=64), nullable=False),
        sa.Column("new_source_record_hash", sa.String(length=64), nullable=False),
        sa.Column("revision_reason", sa.String(length=64), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "revision_reason IN ('source_revision', 'report_restatement', 'corrected_estimate', 'parser_change', 'unknown')",
            name="ck_supply_demand_revisions_reason",
        ),
        sa.ForeignKeyConstraint(["supply_demand_observation_id"], ["supply_demand_observations.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("supply_demand_observation_id", "revision_number", name="uq_supply_demand_revisions_obs_number"),
    )
    op.create_index("ix_supply_demand_revisions_observation_id", "supply_demand_revisions", ["supply_demand_observation_id"])
    op.create_index("ix_supply_demand_revisions_detected_at", "supply_demand_revisions", ["detected_at"])
    op.create_index("ix_supply_demand_revisions_reason", "supply_demand_revisions", ["revision_reason"])

    op.create_table(
        "product_supply_demand_weights",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("supply_demand_commodity_id", sa.Integer(), nullable=False),
        sa.Column("weight", sa.Numeric(18, 8), nullable=False),
        sa.Column("relevance", sa.String(length=32), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("relevance IN ('direct', 'context', 'later')", name="ck_product_supply_demand_weights_relevance"),
        sa.CheckConstraint("weight >= 0", name="ck_product_supply_demand_weights_nonnegative"),
        sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="ck_product_supply_demand_weights_dates"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["supply_demand_commodity_id"], ["supply_demand_commodities.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "product_id",
            "supply_demand_commodity_id",
            "role",
            "effective_from",
            name="uq_product_supply_demand_weights_identity",
        ),
    )
    op.create_index("ix_product_supply_demand_weights_product_active", "product_supply_demand_weights", ["product_id", "is_active"])
    op.create_index("ix_product_supply_demand_weights_commodity_active", "product_supply_demand_weights", ["supply_demand_commodity_id", "is_active"])
    op.create_index("ix_product_supply_demand_weights_effective", "product_supply_demand_weights", ["effective_from", "effective_to"])

    op.create_table(
        "daily_supply_demand_features",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("feature_date", sa.Date(), nullable=False),
        sa.Column("production_volume", sa.Numeric(18, 8), nullable=True),
        sa.Column("domestic_consumption", sa.Numeric(18, 8), nullable=True),
        sa.Column("food_use", sa.Numeric(18, 8), nullable=True),
        sa.Column("feed_use", sa.Numeric(18, 8), nullable=True),
        sa.Column("crush_volume", sa.Numeric(18, 8), nullable=True),
        sa.Column("exports_volume", sa.Numeric(18, 8), nullable=True),
        sa.Column("imports_volume", sa.Numeric(18, 8), nullable=True),
        sa.Column("beginning_stocks", sa.Numeric(18, 8), nullable=True),
        sa.Column("ending_stocks", sa.Numeric(18, 8), nullable=True),
        sa.Column("stock_to_use_ratio", sa.Numeric(18, 8), nullable=True),
        sa.Column("planted_area", sa.Numeric(18, 8), nullable=True),
        sa.Column("harvested_area", sa.Numeric(18, 8), nullable=True),
        sa.Column("yield_value", sa.Numeric(18, 8), nullable=True),
        sa.Column("production_forecast_revision", sa.Numeric(18, 8), nullable=True),
        sa.Column("ending_stocks_revision", sa.Numeric(18, 8), nullable=True),
        sa.Column("stock_to_use_revision", sa.Numeric(18, 8), nullable=True),
        sa.Column("forecast_month", sa.Integer(), nullable=True),
        sa.Column("marketing_year", sa.String(length=32), nullable=True),
        sa.Column("report_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("supply_demand_as_of_date", sa.Date(), nullable=True),
        sa.Column("reporting_lag_days", sa.Integer(), nullable=True),
        sa.Column("missing_flags", sa.JSON(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "supply_demand_as_of_date IS NULL OR supply_demand_as_of_date <= feature_date",
            name="ck_daily_supply_demand_features_as_of",
        ),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", "feature_date", name="uq_daily_supply_demand_features_product_date"),
    )
    op.create_index("ix_daily_supply_demand_features_product_date", "daily_supply_demand_features", ["product_id", "feature_date"])
    op.create_index("ix_daily_supply_demand_features_feature_date", "daily_supply_demand_features", ["feature_date"])
    op.create_index("ix_daily_supply_demand_features_as_of", "daily_supply_demand_features", ["supply_demand_as_of_date"])
    op.create_index("ix_daily_supply_demand_features_marketing_year", "daily_supply_demand_features", ["marketing_year"])


def downgrade() -> None:
    op.drop_index("ix_daily_supply_demand_features_marketing_year", table_name="daily_supply_demand_features")
    op.drop_index("ix_daily_supply_demand_features_as_of", table_name="daily_supply_demand_features")
    op.drop_index("ix_daily_supply_demand_features_feature_date", table_name="daily_supply_demand_features")
    op.drop_index("ix_daily_supply_demand_features_product_date", table_name="daily_supply_demand_features")
    op.drop_table("daily_supply_demand_features")

    op.drop_index("ix_product_supply_demand_weights_effective", table_name="product_supply_demand_weights")
    op.drop_index("ix_product_supply_demand_weights_commodity_active", table_name="product_supply_demand_weights")
    op.drop_index("ix_product_supply_demand_weights_product_active", table_name="product_supply_demand_weights")
    op.drop_table("product_supply_demand_weights")

    op.drop_index("ix_supply_demand_revisions_reason", table_name="supply_demand_revisions")
    op.drop_index("ix_supply_demand_revisions_detected_at", table_name="supply_demand_revisions")
    op.drop_index("ix_supply_demand_revisions_observation_id", table_name="supply_demand_revisions")
    op.drop_table("supply_demand_revisions")

    op.drop_index("ix_supply_demand_obs_record_hash", table_name="supply_demand_observations")
    op.drop_index("ix_supply_demand_obs_collector_run_id", table_name="supply_demand_observations")
    op.drop_index("ix_supply_demand_obs_raw_response_id", table_name="supply_demand_observations")
    op.drop_index("ix_supply_demand_obs_fetched_at", table_name="supply_demand_observations")
    op.drop_index("ix_supply_demand_obs_published_at", table_name="supply_demand_observations")
    op.drop_index("ix_supply_demand_obs_report_published", table_name="supply_demand_observations")
    op.drop_index("ix_supply_demand_obs_country_year", table_name="supply_demand_observations")
    op.drop_index("ix_supply_demand_obs_commodity_year", table_name="supply_demand_observations")
    op.drop_table("supply_demand_observations")

    op.drop_index("ix_supply_demand_commodities_is_active", table_name="supply_demand_commodities")
    op.drop_index("ix_supply_demand_commodities_metric_group", table_name="supply_demand_commodities")
    op.drop_index("ix_supply_demand_commodities_metric_name", table_name="supply_demand_commodities")
    op.drop_index("ix_supply_demand_commodities_product_code", table_name="supply_demand_commodities")
    op.drop_index("ix_supply_demand_commodities_family", table_name="supply_demand_commodities")
    op.drop_table("supply_demand_commodities")
