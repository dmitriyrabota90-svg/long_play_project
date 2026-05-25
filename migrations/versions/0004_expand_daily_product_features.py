"""expand daily product features

Revision ID: 0004_expand_daily_product_features
Revises: 0003_add_collection_slot_index
Create Date: 2026-05-25 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0004_expand_daily_product_features"
down_revision = "0003_add_collection_slot_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("daily_product_features", sa.Column("price_last", sa.Numeric(18, 6), nullable=True))
    op.add_column("daily_product_features", sa.Column("price_first", sa.Numeric(18, 6), nullable=True))
    op.add_column("daily_product_features", sa.Column("price_min", sa.Numeric(18, 6), nullable=True))
    op.add_column("daily_product_features", sa.Column("price_max", sa.Numeric(18, 6), nullable=True))
    op.add_column("daily_product_features", sa.Column("price_observations_count", sa.Integer(), nullable=True))
    op.add_column("daily_product_features", sa.Column("price_delta_abs_1d", sa.Numeric(18, 6), nullable=True))
    op.add_column("daily_product_features", sa.Column("price_delta_pct_1d", sa.Numeric(18, 8), nullable=True))
    op.add_column("daily_product_features", sa.Column("price_intraday_delta_abs", sa.Numeric(18, 6), nullable=True))
    op.add_column("daily_product_features", sa.Column("price_intraday_delta_pct", sa.Numeric(18, 8), nullable=True))
    op.add_column("daily_product_features", sa.Column("price_rolling_mean_3d", sa.Numeric(18, 6), nullable=True))
    op.add_column("daily_product_features", sa.Column("price_rolling_mean_7d", sa.Numeric(18, 6), nullable=True))
    op.add_column("daily_product_features", sa.Column("price_rolling_std_7d", sa.Numeric(18, 6), nullable=True))
    op.add_column("daily_product_features", sa.Column("cny_rub", sa.Numeric(18, 8), nullable=True))
    op.add_column("daily_product_features", sa.Column("usd_rub", sa.Numeric(18, 8), nullable=True))
    op.add_column("daily_product_features", sa.Column("eur_rub", sa.Numeric(18, 8), nullable=True))
    op.add_column("daily_product_features", sa.Column("cny_rub_delta_abs_1d", sa.Numeric(18, 8), nullable=True))
    op.add_column("daily_product_features", sa.Column("cny_rub_delta_pct_1d", sa.Numeric(18, 8), nullable=True))
    op.add_column("daily_product_features", sa.Column("usd_rub_delta_abs_1d", sa.Numeric(18, 8), nullable=True))
    op.add_column("daily_product_features", sa.Column("usd_rub_delta_pct_1d", sa.Numeric(18, 8), nullable=True))
    op.add_column("daily_product_features", sa.Column("eur_rub_delta_abs_1d", sa.Numeric(18, 8), nullable=True))
    op.add_column("daily_product_features", sa.Column("eur_rub_delta_pct_1d", sa.Numeric(18, 8), nullable=True))
    op.add_column("daily_product_features", sa.Column("fx_as_of_date", sa.Date(), nullable=True))
    op.add_column(
        "daily_product_features",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_unique_constraint(
        "uq_daily_product_features_product_date",
        "daily_product_features",
        ["product_id", "feature_date"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_daily_product_features_product_date", "daily_product_features", type_="unique")
    op.drop_column("daily_product_features", "updated_at")
    op.drop_column("daily_product_features", "fx_as_of_date")
    op.drop_column("daily_product_features", "eur_rub_delta_pct_1d")
    op.drop_column("daily_product_features", "eur_rub_delta_abs_1d")
    op.drop_column("daily_product_features", "usd_rub_delta_pct_1d")
    op.drop_column("daily_product_features", "usd_rub_delta_abs_1d")
    op.drop_column("daily_product_features", "cny_rub_delta_pct_1d")
    op.drop_column("daily_product_features", "cny_rub_delta_abs_1d")
    op.drop_column("daily_product_features", "eur_rub")
    op.drop_column("daily_product_features", "usd_rub")
    op.drop_column("daily_product_features", "cny_rub")
    op.drop_column("daily_product_features", "price_rolling_std_7d")
    op.drop_column("daily_product_features", "price_rolling_mean_7d")
    op.drop_column("daily_product_features", "price_rolling_mean_3d")
    op.drop_column("daily_product_features", "price_intraday_delta_pct")
    op.drop_column("daily_product_features", "price_intraday_delta_abs")
    op.drop_column("daily_product_features", "price_delta_pct_1d")
    op.drop_column("daily_product_features", "price_delta_abs_1d")
    op.drop_column("daily_product_features", "price_observations_count")
    op.drop_column("daily_product_features", "price_max")
    op.drop_column("daily_product_features", "price_min")
    op.drop_column("daily_product_features", "price_first")
    op.drop_column("daily_product_features", "price_last")
