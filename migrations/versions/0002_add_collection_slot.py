"""add collection slot

Revision ID: 0002_add_collection_slot
Revises: 0001_initial_schema
Create Date: 2026-05-20 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0002_add_collection_slot"
down_revision = "0001_initial_schema"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "collector_runs",
        sa.Column("run_type", sa.String(length=50), nullable=False, server_default="manual"),
    )
    op.add_column(
        "collector_runs",
        sa.Column("collection_slot", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "price_observations",
        sa.Column("collection_slot", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("price_observations", "collection_slot")
    op.drop_column("collector_runs", "collection_slot")
    op.drop_column("collector_runs", "run_type")
