"""add energy features to daily product features

Revision ID: 0009_energy_features
Revises: 0008_energy_prices
Create Date: 2026-06-09 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0009_energy_features"
down_revision = "0008_energy_prices"
branch_labels = None
depends_on = None


ENERGY_COLUMNS = (
    ("energy_brent_usd_per_barrel", sa.Numeric(18, 8)),
    ("energy_wti_usd_per_barrel", sa.Numeric(18, 8)),
    ("energy_henry_hub_usd_mmbtu", sa.Numeric(18, 8)),
    ("energy_diesel_proxy_value", sa.Numeric(18, 8)),
    ("energy_brent_delta_1d", sa.Numeric(18, 8)),
    ("energy_brent_delta_7d", sa.Numeric(18, 8)),
    ("energy_wti_delta_1d", sa.Numeric(18, 8)),
    ("energy_wti_delta_7d", sa.Numeric(18, 8)),
    ("energy_henry_hub_delta_1d", sa.Numeric(18, 8)),
    ("energy_henry_hub_delta_7d", sa.Numeric(18, 8)),
    ("energy_diesel_proxy_delta_7d", sa.Numeric(18, 8)),
    ("energy_as_of_date", sa.Date()),
    ("energy_brent_as_of_date", sa.Date()),
    ("energy_wti_as_of_date", sa.Date()),
    ("energy_henry_hub_as_of_date", sa.Date()),
    ("energy_diesel_as_of_date", sa.Date()),
    ("energy_missing_flags", sa.Text()),
)


def upgrade() -> None:
    for name, column_type in ENERGY_COLUMNS:
        op.add_column("daily_product_features", sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    for name, _column_type in reversed(ENERGY_COLUMNS):
        op.drop_column("daily_product_features", name)
