"""add product news feature columns

Revision ID: 0015_news_features
Revises: 0014_news_events_schema
Create Date: 2026-06-11 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0015_news_features"
down_revision = "0014_news_events_schema"
branch_labels = None
depends_on = None


NEWS_PRODUCT_COLUMNS = (
    ("news_count_1d", sa.Integer()),
    ("news_count_7d", sa.Integer()),
    ("news_count_30d", sa.Integer()),
    ("event_count_1d", sa.Integer()),
    ("event_count_7d", sa.Integer()),
    ("event_count_30d", sa.Integer()),
    ("bullish_event_count_7d", sa.Integer()),
    ("bearish_event_count_7d", sa.Integer()),
    ("mixed_event_count_7d", sa.Integer()),
    ("export_restriction_count_30d", sa.Integer()),
    ("import_policy_count_30d", sa.Integer()),
    ("war_logistics_count_30d", sa.Integer()),
    ("weather_disaster_count_30d", sa.Integer()),
    ("crop_report_count_30d", sa.Integer()),
    ("biofuel_policy_count_30d", sa.Integer()),
    ("energy_shock_count_30d", sa.Integer()),
    ("demand_shock_count_30d", sa.Integer()),
    ("supply_chain_count_30d", sa.Integer()),
    ("sentiment_proxy_7d", sa.Numeric(18, 8)),
    ("news_as_of_date", sa.Date()),
    ("news_missing_flags", sa.Text()),
)


def upgrade() -> None:
    for column_name, column_type in NEWS_PRODUCT_COLUMNS:
        op.add_column("daily_product_features", sa.Column(column_name, column_type, nullable=True))


def downgrade() -> None:
    for column_name, _column_type in reversed(NEWS_PRODUCT_COLUMNS):
        op.drop_column("daily_product_features", column_name)
