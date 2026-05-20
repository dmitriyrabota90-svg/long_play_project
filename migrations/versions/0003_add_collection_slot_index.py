"""add collection slot index

Revision ID: 0003_add_collection_slot_index
Revises: 0002_add_collection_slot
Create Date: 2026-05-20 00:10:00.000000
"""
from __future__ import annotations

from alembic import op


revision = "0003_add_collection_slot_index"
down_revision = "0002_add_collection_slot"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_price_observations_source_product_collection_slot",
        "price_observations",
        ["source_id", "product_id", "collection_slot"],
    )


def downgrade() -> None:
    op.drop_index("ix_price_observations_source_product_collection_slot", table_name="price_observations")
