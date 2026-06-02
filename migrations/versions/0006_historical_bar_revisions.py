"""add historical bar revisions

Revision ID: 0006_historical_bar_revisions
Revises: 0005_historical_price_bars
Create Date: 2026-05-29 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0006_historical_bar_revisions"
down_revision = "0005_historical_price_bars"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "historical_price_bar_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("historical_price_bar_id", sa.Integer(), sa.ForeignKey("historical_price_bars.id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("raw_response_id", sa.Integer(), sa.ForeignKey("raw_responses.id"), nullable=False),
        sa.Column("collector_run_id", sa.Integer(), sa.ForeignKey("collector_runs.id"), nullable=False),
        sa.Column("revision_reason", sa.String(length=100), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("previous_open", sa.Numeric(18, 8), nullable=True),
        sa.Column("previous_high", sa.Numeric(18, 8), nullable=True),
        sa.Column("previous_low", sa.Numeric(18, 8), nullable=True),
        sa.Column("previous_close", sa.Numeric(18, 8), nullable=True),
        sa.Column("previous_price", sa.Numeric(18, 8), nullable=True),
        sa.Column("previous_volume", sa.Numeric(24, 8), nullable=True),
        sa.Column("previous_currency", sa.String(length=16), nullable=False),
        sa.Column("previous_unit", sa.String(length=100), nullable=False),
        sa.Column("previous_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("previous_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("previous_fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("previous_source_record_hash", sa.String(length=64), nullable=False),
        sa.Column("previous_source_payload_hash", sa.String(length=64), nullable=False),
        sa.Column("new_raw_response_id", sa.Integer(), sa.ForeignKey("raw_responses.id"), nullable=False),
        sa.Column("new_collector_run_id", sa.Integer(), sa.ForeignKey("collector_runs.id"), nullable=False),
        sa.Column("new_open", sa.Numeric(18, 8), nullable=True),
        sa.Column("new_high", sa.Numeric(18, 8), nullable=True),
        sa.Column("new_low", sa.Numeric(18, 8), nullable=True),
        sa.Column("new_close", sa.Numeric(18, 8), nullable=True),
        sa.Column("new_price", sa.Numeric(18, 8), nullable=True),
        sa.Column("new_volume", sa.Numeric(24, 8), nullable=True),
        sa.Column("new_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("new_fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("new_source_record_hash", sa.String(length=64), nullable=False),
        sa.Column("new_source_payload_hash", sa.String(length=64), nullable=False),
        sa.Column("changed_fields", sa.JSON(), nullable=False),
        sa.Column("diff_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_hist_bar_revisions_bar_id", "historical_price_bar_revisions", ["historical_price_bar_id"])
    op.create_index("ix_hist_bar_revisions_product_created", "historical_price_bar_revisions", ["product_id", "created_at"])
    op.create_index("ix_hist_bar_revisions_source_created", "historical_price_bar_revisions", ["source_id", "created_at"])
    op.create_index("ix_hist_bar_revisions_created_at", "historical_price_bar_revisions", ["created_at"])
    op.create_index("ix_hist_bar_revisions_reason", "historical_price_bar_revisions", ["revision_reason"])


def downgrade() -> None:
    op.drop_index("ix_hist_bar_revisions_reason", table_name="historical_price_bar_revisions")
    op.drop_index("ix_hist_bar_revisions_created_at", table_name="historical_price_bar_revisions")
    op.drop_index("ix_hist_bar_revisions_source_created", table_name="historical_price_bar_revisions")
    op.drop_index("ix_hist_bar_revisions_product_created", table_name="historical_price_bar_revisions")
    op.drop_index("ix_hist_bar_revisions_bar_id", table_name="historical_price_bar_revisions")
    op.drop_table("historical_price_bar_revisions")

