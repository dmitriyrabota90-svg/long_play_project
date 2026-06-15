"""add product supply demand feature columns

Revision ID: 0019_product_supply_demand_features
Revises: 0018_supply_demand_schema
Create Date: 2026-06-14 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0019_product_supply_demand_features"
down_revision = "0018_supply_demand_schema"
branch_labels = None
depends_on = None


SUPPLY_DEMAND_PRODUCT_COLUMNS = (
    ("production_volume", sa.Numeric(18, 8)),
    ("domestic_consumption", sa.Numeric(18, 8)),
    ("food_use", sa.Numeric(18, 8)),
    ("feed_use", sa.Numeric(18, 8)),
    ("crush_volume", sa.Numeric(18, 8)),
    ("exports_volume", sa.Numeric(18, 8)),
    ("imports_volume", sa.Numeric(18, 8)),
    ("beginning_stocks", sa.Numeric(18, 8)),
    ("ending_stocks", sa.Numeric(18, 8)),
    ("stock_to_use_ratio", sa.Numeric(18, 8)),
    ("planted_area", sa.Numeric(18, 8)),
    ("harvested_area", sa.Numeric(18, 8)),
    ("yield_value", sa.Numeric(18, 8)),
    ("production_forecast_revision", sa.Numeric(18, 8)),
    ("ending_stocks_revision", sa.Numeric(18, 8)),
    ("stock_to_use_revision", sa.Numeric(18, 8)),
    ("forecast_month", sa.Integer()),
    ("marketing_year", sa.String(32)),
    ("report_published_at", sa.DateTime(timezone=True)),
    ("supply_demand_as_of_date", sa.Date()),
    ("supply_demand_reporting_lag_days", sa.Integer()),
    ("supply_demand_missing_flags", sa.Text()),
)


def upgrade() -> None:
    for column_name, column_type in SUPPLY_DEMAND_PRODUCT_COLUMNS:
        op.add_column("daily_product_features", sa.Column(column_name, column_type, nullable=True))


def downgrade() -> None:
    for column_name, _column_type in reversed(SUPPLY_DEMAND_PRODUCT_COLUMNS):
        op.drop_column("daily_product_features", column_name)
