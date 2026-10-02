"""add immutable daily-slice provenance revisions

Revision ID: 0020_daily_slice_provenance
Revises: 0019_supply_demand_features
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0020_daily_slice_provenance"
down_revision = "0019_supply_demand_features"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "daily_slice_build_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("build_mode", sa.String(length=32), nullable=False),
        sa.Column("feature_builder_version", sa.String(length=100), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_table(
        "daily_slice_revisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("build_run_id", sa.Integer(), sa.ForeignKey("daily_slice_build_runs.id"), nullable=False),
        sa.Column("daily_product_feature_id", sa.Integer(), sa.ForeignKey("daily_product_features.id"), nullable=False),
        sa.Column("product_id", sa.Integer(), sa.ForeignKey("products.id"), nullable=False),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("feature_date", sa.Date(), nullable=False),
        sa.Column("schema_version", sa.String(length=32), nullable=False),
        sa.Column("content_sha256", sa.String(length=64), nullable=False),
        sa.Column("slice_content_json", sa.JSON(), nullable=False),
        sa.Column("logical_data_cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("readiness_confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("selected_price_observation_id", sa.Integer(), sa.ForeignKey("price_observations.id"), nullable=False),
        sa.Column("selected_raw_response_id", sa.Integer(), sa.ForeignKey("raw_responses.id"), nullable=True),
        sa.Column("product_code", sa.String(length=100), nullable=False),
        sa.Column("source_code", sa.String(length=100), nullable=False),
        sa.Column("external_code", sa.String(length=100), nullable=True),
        sa.Column("price_value", sa.Numeric(18, 6), nullable=False),
        sa.Column("price_currency", sa.String(length=16), nullable=False),
        sa.Column("price_unit", sa.String(length=100), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observation_created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("collection_slot", sa.DateTime(timezone=True), nullable=True),
        sa.Column("provider_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_sha256", sa.String(length=64), nullable=True),
        sa.Column("source_record_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("build_run_id", "daily_product_feature_id", name="uq_daily_slice_revision_run_feature"),
    )
    op.create_index("ix_daily_slice_revision_product_date", "daily_slice_revisions", ["product_id", "feature_date"])
    op.create_index("ix_daily_slice_revision_ready", "daily_slice_revisions", ["readiness_confirmed_at"])


def downgrade() -> None:
    op.drop_index("ix_daily_slice_revision_ready", table_name="daily_slice_revisions")
    op.drop_index("ix_daily_slice_revision_product_date", table_name="daily_slice_revisions")
    op.drop_table("daily_slice_revisions")
    op.drop_table("daily_slice_build_runs")
