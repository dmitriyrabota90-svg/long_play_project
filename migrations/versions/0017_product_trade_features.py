"""add product trade feature columns

Revision ID: 0017_product_trade_features
Revises: 0016_trade_schema
Create Date: 2026-06-11 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0017_product_trade_features"
down_revision = "0016_trade_schema"
branch_labels = None
depends_on = None


TRADE_PRODUCT_COLUMNS = (
    ("export_volume_1m", sa.Numeric(18, 8)),
    ("export_volume_3m_avg", sa.Numeric(18, 8)),
    ("export_volume_12m_sum", sa.Numeric(18, 8)),
    ("import_volume_1m", sa.Numeric(18, 8)),
    ("import_volume_3m_avg", sa.Numeric(18, 8)),
    ("import_volume_12m_sum", sa.Numeric(18, 8)),
    ("net_export_volume_1m", sa.Numeric(18, 8)),
    ("export_value_usd_1m", sa.Numeric(18, 8)),
    ("import_value_usd_1m", sa.Numeric(18, 8)),
    ("average_export_unit_value_usd", sa.Numeric(18, 8)),
    ("average_import_unit_value_usd", sa.Numeric(18, 8)),
    ("china_import_volume_1m", sa.Numeric(18, 8)),
    ("major_exporter_volume_1m", sa.Numeric(18, 8)),
    ("major_importer_volume_1m", sa.Numeric(18, 8)),
    ("trade_balance_proxy", sa.Numeric(18, 8)),
    ("trade_yoy_change", sa.Numeric(18, 8)),
    ("trade_as_of_date", sa.Date()),
    ("reporting_lag_days", sa.Integer()),
    ("trade_missing_flags", sa.Text()),
)


def upgrade() -> None:
    for column_name, column_type in TRADE_PRODUCT_COLUMNS:
        op.add_column("daily_product_features", sa.Column(column_name, column_type, nullable=True))


def downgrade() -> None:
    for column_name, _column_type in reversed(TRADE_PRODUCT_COLUMNS):
        op.drop_column("daily_product_features", column_name)

