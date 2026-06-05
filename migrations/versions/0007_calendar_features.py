"""add calendar features

Revision ID: 0007_calendar_features
Revises: 0006_historical_bar_revisions
Create Date: 2026-06-05 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0007_calendar_features"
down_revision = "0006_historical_bar_revisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("daily_product_features", sa.Column("calendar_year", sa.Integer(), nullable=True))
    op.add_column("daily_product_features", sa.Column("calendar_month", sa.Integer(), nullable=True))
    op.add_column("daily_product_features", sa.Column("calendar_quarter", sa.Integer(), nullable=True))
    op.add_column("daily_product_features", sa.Column("calendar_week_of_year", sa.Integer(), nullable=True))
    op.add_column("daily_product_features", sa.Column("calendar_day_of_year", sa.Integer(), nullable=True))
    op.add_column("daily_product_features", sa.Column("calendar_day_of_week", sa.Integer(), nullable=True))
    op.add_column("daily_product_features", sa.Column("calendar_is_month_start", sa.Boolean(), nullable=True))
    op.add_column("daily_product_features", sa.Column("calendar_is_month_end", sa.Boolean(), nullable=True))
    op.add_column("daily_product_features", sa.Column("calendar_is_quarter_start", sa.Boolean(), nullable=True))
    op.add_column("daily_product_features", sa.Column("calendar_is_quarter_end", sa.Boolean(), nullable=True))
    op.add_column("daily_product_features", sa.Column("calendar_sin_day_of_year", sa.Float(), nullable=True))
    op.add_column("daily_product_features", sa.Column("calendar_cos_day_of_year", sa.Float(), nullable=True))
    op.add_column("daily_product_features", sa.Column("calendar_sin_month", sa.Float(), nullable=True))
    op.add_column("daily_product_features", sa.Column("calendar_cos_month", sa.Float(), nullable=True))
    op.add_column("daily_product_features", sa.Column("calendar_season", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("daily_product_features", "calendar_season")
    op.drop_column("daily_product_features", "calendar_cos_month")
    op.drop_column("daily_product_features", "calendar_sin_month")
    op.drop_column("daily_product_features", "calendar_cos_day_of_year")
    op.drop_column("daily_product_features", "calendar_sin_day_of_year")
    op.drop_column("daily_product_features", "calendar_is_quarter_end")
    op.drop_column("daily_product_features", "calendar_is_quarter_start")
    op.drop_column("daily_product_features", "calendar_is_month_end")
    op.drop_column("daily_product_features", "calendar_is_month_start")
    op.drop_column("daily_product_features", "calendar_day_of_week")
    op.drop_column("daily_product_features", "calendar_day_of_year")
    op.drop_column("daily_product_features", "calendar_week_of_year")
    op.drop_column("daily_product_features", "calendar_quarter")
    op.drop_column("daily_product_features", "calendar_month")
    op.drop_column("daily_product_features", "calendar_year")
