"""add energy prices

Revision ID: 0008_energy_prices
Revises: 0007_calendar_features
Create Date: 2026-06-05 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0008_energy_prices"
down_revision = "0007_calendar_features"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "energy_prices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("raw_response_id", sa.Integer(), sa.ForeignKey("raw_responses.id"), nullable=False),
        sa.Column("collector_run_id", sa.Integer(), sa.ForeignKey("collector_runs.id"), nullable=False),
        sa.Column("instrument_code", sa.String(length=100), nullable=False),
        sa.Column("external_id", sa.String(length=100), nullable=False),
        sa.Column("instrument_name", sa.String(length=255), nullable=False),
        sa.Column("instrument_category", sa.String(length=100), nullable=False),
        sa.Column("frequency", sa.String(length=32), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("value", sa.Numeric(18, 8), nullable=False),
        sa.Column("currency", sa.String(length=16), nullable=True),
        sa.Column("unit", sa.String(length=100), nullable=False),
        sa.Column("normalized_value", sa.Numeric(18, 8), nullable=True),
        sa.Column("normalized_currency", sa.String(length=16), nullable=True),
        sa.Column("normalized_unit", sa.String(length=100), nullable=True),
        sa.Column("source_record_hash", sa.String(length=64), nullable=False),
        sa.Column("source_payload_hash", sa.String(length=64), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint(
            "source_id",
            "instrument_code",
            "frequency",
            "period_start",
            "period_end",
            name="uq_energy_source_instr_freq_period",
        ),
        sa.CheckConstraint("period_end >= period_start", name="ck_energy_prices_period_order"),
        sa.CheckConstraint("frequency IN ('daily', 'weekly', 'monthly')", name="ck_energy_prices_frequency"),
    )
    op.create_index(
        "ix_energy_source_instr_period",
        "energy_prices",
        ["source_id", "instrument_code", "period_start", "period_end"],
    )
    op.create_index("ix_energy_instr_observed", "energy_prices", ["instrument_code", "observed_at"])
    op.create_index("ix_energy_category_observed", "energy_prices", ["instrument_category", "observed_at"])
    op.create_index("ix_energy_fetched_at", "energy_prices", ["fetched_at"])
    op.create_index("ix_energy_raw_response_id", "energy_prices", ["raw_response_id"])
    op.create_index("ix_energy_collector_run_id", "energy_prices", ["collector_run_id"])
    op.create_index("ix_energy_source_record_hash", "energy_prices", ["source_record_hash"])


def downgrade() -> None:
    op.drop_index("ix_energy_source_record_hash", table_name="energy_prices")
    op.drop_index("ix_energy_collector_run_id", table_name="energy_prices")
    op.drop_index("ix_energy_raw_response_id", table_name="energy_prices")
    op.drop_index("ix_energy_fetched_at", table_name="energy_prices")
    op.drop_index("ix_energy_category_observed", table_name="energy_prices")
    op.drop_index("ix_energy_instr_observed", table_name="energy_prices")
    op.drop_index("ix_energy_source_instr_period", table_name="energy_prices")
    op.drop_table("energy_prices")
