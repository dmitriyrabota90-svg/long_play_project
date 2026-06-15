"""add trade schema

Revision ID: 0016_trade_schema
Revises: 0015_news_features
Create Date: 2026-06-11 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0016_trade_schema"
down_revision = "0015_news_features"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "trade_commodity_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("code_system", sa.String(length=64), nullable=False),
        sa.Column("commodity_code", sa.String(length=64), nullable=False),
        sa.Column("commodity_name", sa.String(length=255), nullable=False),
        sa.Column("hs_code", sa.String(length=64), nullable=True),
        sa.Column("hs_revision", sa.String(length=32), nullable=False),
        sa.Column("commodity_family", sa.String(length=100), nullable=False),
        sa.Column("product_code", sa.String(length=100), nullable=True),
        sa.Column("relevance", sa.String(length=32), nullable=False),
        sa.Column("unit_hint", sa.String(length=100), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("relevance IN ('direct', 'context', 'later')", name="ck_trade_codes_relevance"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code_system", "commodity_code", "hs_revision", name="uq_trade_codes_system_code_rev"),
    )
    op.create_index("ix_trade_codes_family", "trade_commodity_codes", ["commodity_family"])
    op.create_index("ix_trade_codes_product_code", "trade_commodity_codes", ["product_code"])
    op.create_index("ix_trade_codes_hs_code", "trade_commodity_codes", ["hs_code"])
    op.create_index("ix_trade_codes_is_active", "trade_commodity_codes", ["is_active"])

    op.create_table(
        "trade_flows",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("raw_response_id", sa.Integer(), nullable=False),
        sa.Column("collector_run_id", sa.Integer(), nullable=False),
        sa.Column("trade_commodity_code_id", sa.Integer(), nullable=False),
        sa.Column("source_record_id", sa.String(length=255), nullable=True),
        sa.Column("reporter_code", sa.String(length=32), nullable=False),
        sa.Column("reporter_name", sa.String(length=255), nullable=False),
        sa.Column("partner_code", sa.String(length=32), nullable=False),
        sa.Column("partner_name", sa.String(length=255), nullable=False),
        sa.Column("flow_direction", sa.String(length=32), nullable=False),
        sa.Column("trade_period", sa.String(length=32), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("frequency", sa.String(length=32), nullable=False),
        sa.Column("quantity", sa.Numeric(18, 8), nullable=True),
        sa.Column("quantity_unit", sa.String(length=100), nullable=True),
        sa.Column("trade_value_usd", sa.Numeric(18, 8), nullable=True),
        sa.Column("trade_value_local", sa.Numeric(18, 8), nullable=True),
        sa.Column("currency", sa.String(length=16), nullable=True),
        sa.Column("unit_value_usd", sa.Numeric(18, 8), nullable=True),
        sa.Column("net_weight_kg", sa.Numeric(18, 8), nullable=True),
        sa.Column("gross_weight_kg", sa.Numeric(18, 8), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_record_hash", sa.String(length=64), nullable=False),
        sa.Column("source_payload_hash", sa.String(length=64), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "flow_direction IN ('export', 'import', 're_export', 're_import', 'unknown')",
            name="ck_trade_flows_direction",
        ),
        sa.CheckConstraint("frequency IN ('monthly', 'annual', 'quarterly', 'unknown')", name="ck_trade_flows_frequency"),
        sa.CheckConstraint("period_end >= period_start", name="ck_trade_flows_period_order"),
        sa.ForeignKeyConstraint(["collector_run_id"], ["collector_runs.id"]),
        sa.ForeignKeyConstraint(["raw_response_id"], ["raw_responses.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.ForeignKeyConstraint(["trade_commodity_code_id"], ["trade_commodity_codes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_id",
            "trade_commodity_code_id",
            "reporter_code",
            "partner_code",
            "flow_direction",
            "frequency",
            "period_start",
            "period_end",
            name="uq_trade_flows_identity",
        ),
    )
    op.create_index("ix_trade_flows_code_period", "trade_flows", ["trade_commodity_code_id", "period_start"])
    op.create_index("ix_trade_flows_reporter_period", "trade_flows", ["reporter_code", "period_start"])
    op.create_index("ix_trade_flows_partner_period", "trade_flows", ["partner_code", "period_start"])
    op.create_index("ix_trade_flows_direction_period", "trade_flows", ["flow_direction", "period_start"])
    op.create_index("ix_trade_flows_source_fetched", "trade_flows", ["source_id", "fetched_at"])
    op.create_index("ix_trade_flows_raw_response_id", "trade_flows", ["raw_response_id"])
    op.create_index("ix_trade_flows_collector_run_id", "trade_flows", ["collector_run_id"])
    op.create_index("ix_trade_flows_record_hash", "trade_flows", ["source_record_hash"])

    op.create_table(
        "product_trade_code_weights",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("trade_commodity_code_id", sa.Integer(), nullable=False),
        sa.Column("weight", sa.Numeric(18, 8), nullable=False),
        sa.Column("relevance", sa.String(length=32), nullable=False),
        sa.Column("role", sa.String(length=64), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("relevance IN ('direct', 'context', 'later')", name="ck_product_trade_weight_relevance"),
        sa.CheckConstraint("weight >= 0", name="ck_product_trade_weight_nonnegative"),
        sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="ck_product_trade_weight_dates"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["trade_commodity_code_id"], ["trade_commodity_codes.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", "trade_commodity_code_id", "role", "effective_from", name="uq_product_trade_code_weight"),
    )
    op.create_index("ix_product_trade_weight_product_active", "product_trade_code_weights", ["product_id", "is_active"])
    op.create_index("ix_product_trade_weight_code_active", "product_trade_code_weights", ["trade_commodity_code_id", "is_active"])
    op.create_index("ix_product_trade_weight_effective", "product_trade_code_weights", ["effective_from", "effective_to"])

    op.create_table(
        "daily_trade_features",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("feature_date", sa.Date(), nullable=False),
        sa.Column("export_volume_1m", sa.Numeric(18, 8), nullable=True),
        sa.Column("export_volume_3m_avg", sa.Numeric(18, 8), nullable=True),
        sa.Column("export_volume_12m_sum", sa.Numeric(18, 8), nullable=True),
        sa.Column("import_volume_1m", sa.Numeric(18, 8), nullable=True),
        sa.Column("import_volume_3m_avg", sa.Numeric(18, 8), nullable=True),
        sa.Column("import_volume_12m_sum", sa.Numeric(18, 8), nullable=True),
        sa.Column("net_export_volume_1m", sa.Numeric(18, 8), nullable=True),
        sa.Column("export_value_usd_1m", sa.Numeric(18, 8), nullable=True),
        sa.Column("import_value_usd_1m", sa.Numeric(18, 8), nullable=True),
        sa.Column("average_export_unit_value_usd", sa.Numeric(18, 8), nullable=True),
        sa.Column("average_import_unit_value_usd", sa.Numeric(18, 8), nullable=True),
        sa.Column("china_import_volume_1m", sa.Numeric(18, 8), nullable=True),
        sa.Column("major_exporter_volume_1m", sa.Numeric(18, 8), nullable=True),
        sa.Column("major_importer_volume_1m", sa.Numeric(18, 8), nullable=True),
        sa.Column("trade_balance_proxy", sa.Numeric(18, 8), nullable=True),
        sa.Column("trade_yoy_change", sa.Numeric(18, 8), nullable=True),
        sa.Column("trade_as_of_date", sa.Date(), nullable=True),
        sa.Column("reporting_lag_days", sa.Integer(), nullable=True),
        sa.Column("missing_flags", sa.JSON(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("trade_as_of_date IS NULL OR trade_as_of_date <= feature_date", name="ck_daily_trade_features_as_of"),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", "feature_date", name="uq_daily_trade_features_product_date"),
    )
    op.create_index("ix_daily_trade_features_product_date", "daily_trade_features", ["product_id", "feature_date"])
    op.create_index("ix_daily_trade_features_feature_date", "daily_trade_features", ["feature_date"])
    op.create_index("ix_daily_trade_features_as_of", "daily_trade_features", ["trade_as_of_date"])


def downgrade() -> None:
    op.drop_index("ix_daily_trade_features_as_of", table_name="daily_trade_features")
    op.drop_index("ix_daily_trade_features_feature_date", table_name="daily_trade_features")
    op.drop_index("ix_daily_trade_features_product_date", table_name="daily_trade_features")
    op.drop_table("daily_trade_features")

    op.drop_index("ix_product_trade_weight_effective", table_name="product_trade_code_weights")
    op.drop_index("ix_product_trade_weight_code_active", table_name="product_trade_code_weights")
    op.drop_index("ix_product_trade_weight_product_active", table_name="product_trade_code_weights")
    op.drop_table("product_trade_code_weights")

    op.drop_index("ix_trade_flows_record_hash", table_name="trade_flows")
    op.drop_index("ix_trade_flows_collector_run_id", table_name="trade_flows")
    op.drop_index("ix_trade_flows_raw_response_id", table_name="trade_flows")
    op.drop_index("ix_trade_flows_source_fetched", table_name="trade_flows")
    op.drop_index("ix_trade_flows_direction_period", table_name="trade_flows")
    op.drop_index("ix_trade_flows_partner_period", table_name="trade_flows")
    op.drop_index("ix_trade_flows_reporter_period", table_name="trade_flows")
    op.drop_index("ix_trade_flows_code_period", table_name="trade_flows")
    op.drop_table("trade_flows")

    op.drop_index("ix_trade_codes_is_active", table_name="trade_commodity_codes")
    op.drop_index("ix_trade_codes_hs_code", table_name="trade_commodity_codes")
    op.drop_index("ix_trade_codes_product_code", table_name="trade_commodity_codes")
    op.drop_index("ix_trade_codes_family", table_name="trade_commodity_codes")
    op.drop_table("trade_commodity_codes")
