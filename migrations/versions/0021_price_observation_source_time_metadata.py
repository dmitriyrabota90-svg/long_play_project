"""add source-time metadata to price observations

Revision ID: 0021_price_source_time
Revises: 0020_daily_slice_provenance
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0021_price_source_time"
down_revision = "0020_daily_slice_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("price_observations", sa.Column("source_time_metadata_json", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("price_observations", "source_time_metadata_json")
