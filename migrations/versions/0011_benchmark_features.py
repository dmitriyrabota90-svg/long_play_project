"""add benchmark features to daily product features

Revision ID: 0011_benchmark_features
Revises: 0010_commodity_benchmarks
Create Date: 2026-06-10 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0011_benchmark_features"
down_revision = "0010_commodity_benchmarks"
branch_labels = None
depends_on = None


BENCHMARK_FEATURE_COLUMNS = (
    ("benchmark_soybean_oil_value", sa.Numeric(18, 8)),
    ("benchmark_soybeans_value", sa.Numeric(18, 8)),
    ("benchmark_palm_oil_value", sa.Numeric(18, 8)),
    ("benchmark_maize_value", sa.Numeric(18, 8)),
    ("benchmark_wheat_value", sa.Numeric(18, 8)),
    ("benchmark_fertilizer_index_value", sa.Numeric(18, 8)),
    ("benchmark_soybean_oil_delta_1m", sa.Numeric(18, 8)),
    ("benchmark_soybean_oil_delta_3m", sa.Numeric(18, 8)),
    ("benchmark_soybeans_delta_1m", sa.Numeric(18, 8)),
    ("benchmark_soybeans_delta_3m", sa.Numeric(18, 8)),
    ("benchmark_palm_oil_delta_1m", sa.Numeric(18, 8)),
    ("benchmark_palm_oil_delta_3m", sa.Numeric(18, 8)),
    ("benchmark_maize_delta_1m", sa.Numeric(18, 8)),
    ("benchmark_maize_delta_3m", sa.Numeric(18, 8)),
    ("benchmark_wheat_delta_1m", sa.Numeric(18, 8)),
    ("benchmark_wheat_delta_3m", sa.Numeric(18, 8)),
    ("benchmark_fertilizer_index_delta_1m", sa.Numeric(18, 8)),
    ("benchmark_fertilizer_index_delta_3m", sa.Numeric(18, 8)),
    ("benchmark_as_of_date", sa.Date()),
    ("benchmark_soybean_oil_as_of_date", sa.Date()),
    ("benchmark_soybeans_as_of_date", sa.Date()),
    ("benchmark_palm_oil_as_of_date", sa.Date()),
    ("benchmark_maize_as_of_date", sa.Date()),
    ("benchmark_wheat_as_of_date", sa.Date()),
    ("benchmark_fertilizer_index_as_of_date", sa.Date()),
    ("benchmark_missing_flags", sa.Text()),
)


def upgrade() -> None:
    for name, column_type in BENCHMARK_FEATURE_COLUMNS:
        op.add_column("daily_product_features", sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    for name, _column_type in reversed(BENCHMARK_FEATURE_COLUMNS):
        op.drop_column("daily_product_features", name)
