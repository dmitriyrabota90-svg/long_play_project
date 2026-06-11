"""add product weather features to daily product features

Revision ID: 0013_product_weather_features
Revises: 0012_weather_schema
Create Date: 2026-06-11 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0013_product_weather_features"
down_revision = "0012_weather_schema"
branch_labels = None
depends_on = None


PRODUCT_WEATHER_FEATURE_COLUMNS = (
    ("weather_temperature_7d_mean_weighted", sa.Numeric(18, 8)),
    ("weather_temperature_30d_mean_weighted", sa.Numeric(18, 8)),
    ("weather_temperature_min_7d_weighted", sa.Numeric(18, 8)),
    ("weather_temperature_max_7d_weighted", sa.Numeric(18, 8)),
    ("weather_precipitation_7d_sum_weighted", sa.Numeric(18, 8)),
    ("weather_precipitation_14d_sum_weighted", sa.Numeric(18, 8)),
    ("weather_precipitation_30d_sum_weighted", sa.Numeric(18, 8)),
    ("weather_heat_stress_days_7d_weighted", sa.Numeric(18, 8)),
    ("weather_heat_stress_days_30d_weighted", sa.Numeric(18, 8)),
    ("weather_frost_days_7d_weighted", sa.Numeric(18, 8)),
    ("weather_frost_days_30d_weighted", sa.Numeric(18, 8)),
    ("weather_drought_proxy_30d_weighted", sa.Numeric(18, 8)),
    ("weather_growing_degree_days_7d_weighted", sa.Numeric(18, 8)),
    ("weather_growing_degree_days_30d_weighted", sa.Numeric(18, 8)),
    ("weather_as_of_date", sa.Date()),
    ("weather_regions_used", sa.Text()),
    ("weather_missing_flags", sa.Text()),
)


def upgrade() -> None:
    for name, column_type in PRODUCT_WEATHER_FEATURE_COLUMNS:
        op.add_column("daily_product_features", sa.Column(name, column_type, nullable=True))


def downgrade() -> None:
    for name, _column_type in reversed(PRODUCT_WEATHER_FEATURE_COLUMNS):
        op.drop_column("daily_product_features", name)
