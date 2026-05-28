"""add historical price bars

Revision ID: 0005_historical_price_bars
Revises: 0004_daily_features
Create Date: 2026-05-28 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0005_historical_price_bars"
down_revision = "0004_daily_features"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "historical_price_bars",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("raw_response_id", sa.Integer(), sa.ForeignKey("raw_responses.id"), nullable=False),
        sa.Column("collector_run_id", sa.Integer(), sa.ForeignKey("collector_runs.id"), nullable=False),
        sa.Column("external_code", sa.String(length=100), nullable=False),
        sa.Column("endpoint_alias", sa.String(length=50), nullable=False),
        sa.Column("bar_date", sa.Date(), nullable=False),
        sa.Column("bar_timeframe", sa.String(length=50), nullable=False),
        sa.Column("open_price", sa.Numeric(18, 8), nullable=True),
        sa.Column("high_price", sa.Numeric(18, 8), nullable=True),
        sa.Column("low_price", sa.Numeric(18, 8), nullable=True),
        sa.Column("close_price", sa.Numeric(18, 8), nullable=True),
        sa.Column("price", sa.Numeric(18, 8), nullable=True),
        sa.Column("volume", sa.Numeric(24, 8), nullable=True),
        sa.Column("currency", sa.String(length=16), nullable=False),
        sa.Column("unit", sa.String(length=100), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_record_hash", sa.String(length=64), nullable=False),
        sa.Column("source_payload_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "product_id",
            "source_id",
            "endpoint_alias",
            "bar_timeframe",
            "bar_date",
            name="uq_hist_bars_product_source_endpoint_timeframe_date",
        ),
    )
    op.create_index("ix_hist_bars_product_bar_date", "historical_price_bars", ["product_id", "bar_date"])
    op.create_index("ix_hist_bars_source_fetched_at", "historical_price_bars", ["source_id", "fetched_at"])
    op.create_index(
        "ix_hist_bars_product_source_timeframe_date",
        "historical_price_bars",
        ["product_id", "source_id", "bar_timeframe", "bar_date"],
    )
    op.create_index("ix_hist_bars_raw_response_id", "historical_price_bars", ["raw_response_id"])
    op.create_index("ix_hist_bars_collector_run_id", "historical_price_bars", ["collector_run_id"])
    op.create_index("ix_hist_bars_source_record_hash", "historical_price_bars", ["source_record_hash"])


def downgrade() -> None:
    op.drop_index("ix_hist_bars_source_record_hash", table_name="historical_price_bars")
    op.drop_index("ix_hist_bars_collector_run_id", table_name="historical_price_bars")
    op.drop_index("ix_hist_bars_raw_response_id", table_name="historical_price_bars")
    op.drop_index("ix_hist_bars_product_source_timeframe_date", table_name="historical_price_bars")
    op.drop_index("ix_hist_bars_source_fetched_at", table_name="historical_price_bars")
    op.drop_index("ix_hist_bars_product_bar_date", table_name="historical_price_bars")
    op.drop_table("historical_price_bars")
