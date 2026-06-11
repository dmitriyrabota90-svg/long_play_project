"""add weather schema

Revision ID: 0012_weather_schema
Revises: 0011_benchmark_features
Create Date: 2026-06-11 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "0012_weather_schema"
down_revision = "0011_benchmark_features"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "weather_regions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("region_code", sa.String(length=100), nullable=False),
        sa.Column("region_name", sa.String(length=255), nullable=False),
        sa.Column("country", sa.String(length=100), nullable=False),
        sa.Column("country_code", sa.String(length=2), nullable=True),
        sa.Column("crop", sa.String(length=100), nullable=False),
        sa.Column("commodity_family", sa.String(length=100), nullable=False),
        sa.Column("role", sa.String(length=100), nullable=False),
        sa.Column("priority", sa.String(length=32), nullable=False),
        sa.Column("latitude", sa.Numeric(10, 6), nullable=False),
        sa.Column("longitude", sa.Numeric(10, 6), nullable=False),
        sa.Column("spatial_model", sa.String(length=64), nullable=False),
        sa.Column("aggregation_strategy", sa.String(length=100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("region_code", name="uq_weather_regions_code"),
        sa.CheckConstraint("priority IN ('high', 'medium', 'later')", name="ck_weather_regions_priority"),
        sa.CheckConstraint("latitude >= -90 AND latitude <= 90", name="ck_weather_regions_latitude"),
        sa.CheckConstraint("longitude >= -180 AND longitude <= 180", name="ck_weather_regions_longitude"),
    )
    op.create_index("ix_weather_regions_code", "weather_regions", ["region_code"])
    op.create_index("ix_weather_regions_country_crop", "weather_regions", ["country", "crop"])
    op.create_index("ix_weather_regions_family", "weather_regions", ["commodity_family"])
    op.create_index("ix_weather_regions_active", "weather_regions", ["is_active"])
    op.create_index("ix_weather_regions_priority", "weather_regions", ["priority"])

    op.alter_column("weather_observations", "region_code", existing_type=sa.String(length=100), nullable=True)
    op.alter_column("weather_observations", "lat", existing_type=sa.Float(), nullable=True)
    op.alter_column("weather_observations", "lon", existing_type=sa.Float(), nullable=True)
    op.alter_column("weather_observations", "temperature", existing_type=sa.Float(), nullable=True)
    op.alter_column("weather_observations", "precipitation", existing_type=sa.Float(), nullable=True)
    op.alter_column(
        "weather_observations",
        "soil_moisture",
        existing_type=sa.Float(),
        type_=sa.Numeric(18, 8),
        nullable=True,
    )
    op.alter_column("weather_observations", "weather_metric_json", existing_type=sa.JSON(), nullable=True)
    op.add_column("weather_observations", sa.Column("collector_run_id", sa.Integer(), nullable=False))
    op.add_column("weather_observations", sa.Column("region_id", sa.Integer(), nullable=False))
    op.add_column("weather_observations", sa.Column("source_region_key", sa.String(length=255), nullable=False))
    op.add_column("weather_observations", sa.Column("observation_date", sa.Date(), nullable=False))
    op.add_column("weather_observations", sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False))
    op.add_column("weather_observations", sa.Column("frequency", sa.String(length=32), nullable=False))
    op.add_column("weather_observations", sa.Column("temperature_2m_mean", sa.Numeric(18, 8), nullable=True))
    op.add_column("weather_observations", sa.Column("temperature_2m_min", sa.Numeric(18, 8), nullable=True))
    op.add_column("weather_observations", sa.Column("temperature_2m_max", sa.Numeric(18, 8), nullable=True))
    op.add_column("weather_observations", sa.Column("precipitation_sum", sa.Numeric(18, 8), nullable=True))
    op.add_column("weather_observations", sa.Column("snowfall_sum", sa.Numeric(18, 8), nullable=True))
    op.add_column("weather_observations", sa.Column("relative_humidity_mean", sa.Numeric(18, 8), nullable=True))
    op.add_column("weather_observations", sa.Column("wind_speed_mean", sa.Numeric(18, 8), nullable=True))
    op.add_column("weather_observations", sa.Column("wind_speed_max", sa.Numeric(18, 8), nullable=True))
    op.add_column("weather_observations", sa.Column("evapotranspiration", sa.Numeric(18, 8), nullable=True))
    op.add_column("weather_observations", sa.Column("shortwave_radiation", sa.Numeric(18, 8), nullable=True))
    op.add_column("weather_observations", sa.Column("source_record_hash", sa.String(length=64), nullable=False))
    op.add_column("weather_observations", sa.Column("source_payload_hash", sa.String(length=64), nullable=False))
    op.add_column("weather_observations", sa.Column("metadata_json", sa.JSON(), nullable=True))
    op.add_column(
        "weather_observations",
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_foreign_key(
        "fk_weather_obs_collector_run_id",
        "weather_observations",
        "collector_runs",
        ["collector_run_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_weather_obs_region_id",
        "weather_observations",
        "weather_regions",
        ["region_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_weather_obs_source_region_date_freq",
        "weather_observations",
        ["source_id", "region_id", "observation_date", "frequency"],
    )
    op.create_check_constraint("ck_weather_obs_frequency", "weather_observations", "frequency IN ('daily')")
    op.create_index("ix_weather_obs_region_date", "weather_observations", ["region_id", "observation_date"])
    op.create_index("ix_weather_obs_source_date", "weather_observations", ["source_id", "observation_date"])
    op.create_index("ix_weather_obs_fetched_at", "weather_observations", ["fetched_at"])
    op.create_index("ix_weather_obs_raw_response_id", "weather_observations", ["raw_response_id"])
    op.create_index("ix_weather_obs_collector_run_id", "weather_observations", ["collector_run_id"])
    op.create_index("ix_weather_obs_record_hash", "weather_observations", ["source_record_hash"])

    op.create_table(
        "weather_daily_features",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("region_id", sa.Integer(), nullable=False),
        sa.Column("feature_date", sa.Date(), nullable=False),
        sa.Column("temperature_7d_mean", sa.Numeric(18, 8), nullable=True),
        sa.Column("temperature_30d_mean", sa.Numeric(18, 8), nullable=True),
        sa.Column("temperature_min_7d", sa.Numeric(18, 8), nullable=True),
        sa.Column("temperature_max_7d", sa.Numeric(18, 8), nullable=True),
        sa.Column("precipitation_7d_sum", sa.Numeric(18, 8), nullable=True),
        sa.Column("precipitation_14d_sum", sa.Numeric(18, 8), nullable=True),
        sa.Column("precipitation_30d_sum", sa.Numeric(18, 8), nullable=True),
        sa.Column("heat_stress_days_7d", sa.Integer(), nullable=True),
        sa.Column("heat_stress_days_30d", sa.Integer(), nullable=True),
        sa.Column("frost_days_7d", sa.Integer(), nullable=True),
        sa.Column("frost_days_30d", sa.Integer(), nullable=True),
        sa.Column("drought_proxy_30d", sa.Numeric(18, 8), nullable=True),
        sa.Column("growing_degree_days_7d", sa.Numeric(18, 8), nullable=True),
        sa.Column("growing_degree_days_30d", sa.Numeric(18, 8), nullable=True),
        sa.Column("weather_as_of_date", sa.Date(), nullable=True),
        sa.Column("missing_flags", sa.JSON(), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["region_id"], ["weather_regions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("region_id", "feature_date", name="uq_weather_daily_region_date"),
    )
    op.create_index("ix_weather_daily_region_date", "weather_daily_features", ["region_id", "feature_date"])
    op.create_index("ix_weather_daily_feature_date", "weather_daily_features", ["feature_date"])
    op.create_index("ix_weather_daily_as_of_date", "weather_daily_features", ["weather_as_of_date"])

    op.create_table(
        "product_weather_region_weights",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("region_id", sa.Integer(), nullable=False),
        sa.Column("weight", sa.Numeric(18, 8), nullable=False),
        sa.Column("role", sa.String(length=100), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column("effective_to", sa.Date(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.ForeignKeyConstraint(["region_id"], ["weather_regions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("product_id", "region_id", "role", "effective_from", name="uq_product_weather_region_weight"),
        sa.CheckConstraint("weight >= 0", name="ck_product_weather_weight_nonnegative"),
        sa.CheckConstraint("effective_to IS NULL OR effective_to >= effective_from", name="ck_product_weather_effective_range"),
    )
    op.create_index("ix_product_weather_product_active", "product_weather_region_weights", ["product_id", "is_active"])
    op.create_index("ix_product_weather_region_active", "product_weather_region_weights", ["region_id", "is_active"])
    op.create_index("ix_product_weather_effective", "product_weather_region_weights", ["effective_from", "effective_to"])


def downgrade() -> None:
    op.drop_index("ix_product_weather_effective", table_name="product_weather_region_weights")
    op.drop_index("ix_product_weather_region_active", table_name="product_weather_region_weights")
    op.drop_index("ix_product_weather_product_active", table_name="product_weather_region_weights")
    op.drop_table("product_weather_region_weights")

    op.drop_index("ix_weather_daily_as_of_date", table_name="weather_daily_features")
    op.drop_index("ix_weather_daily_feature_date", table_name="weather_daily_features")
    op.drop_index("ix_weather_daily_region_date", table_name="weather_daily_features")
    op.drop_table("weather_daily_features")

    op.drop_index("ix_weather_obs_record_hash", table_name="weather_observations")
    op.drop_index("ix_weather_obs_collector_run_id", table_name="weather_observations")
    op.drop_index("ix_weather_obs_raw_response_id", table_name="weather_observations")
    op.drop_index("ix_weather_obs_fetched_at", table_name="weather_observations")
    op.drop_index("ix_weather_obs_source_date", table_name="weather_observations")
    op.drop_index("ix_weather_obs_region_date", table_name="weather_observations")
    op.drop_constraint("ck_weather_obs_frequency", "weather_observations", type_="check")
    op.drop_constraint("uq_weather_obs_source_region_date_freq", "weather_observations", type_="unique")
    op.drop_constraint("fk_weather_obs_region_id", "weather_observations", type_="foreignkey")
    op.drop_constraint("fk_weather_obs_collector_run_id", "weather_observations", type_="foreignkey")
    op.drop_column("weather_observations", "updated_at")
    op.drop_column("weather_observations", "metadata_json")
    op.drop_column("weather_observations", "source_payload_hash")
    op.drop_column("weather_observations", "source_record_hash")
    op.drop_column("weather_observations", "shortwave_radiation")
    op.drop_column("weather_observations", "evapotranspiration")
    op.drop_column("weather_observations", "wind_speed_max")
    op.drop_column("weather_observations", "wind_speed_mean")
    op.drop_column("weather_observations", "relative_humidity_mean")
    op.drop_column("weather_observations", "snowfall_sum")
    op.drop_column("weather_observations", "precipitation_sum")
    op.drop_column("weather_observations", "temperature_2m_max")
    op.drop_column("weather_observations", "temperature_2m_min")
    op.drop_column("weather_observations", "temperature_2m_mean")
    op.drop_column("weather_observations", "frequency")
    op.drop_column("weather_observations", "fetched_at")
    op.drop_column("weather_observations", "observation_date")
    op.drop_column("weather_observations", "source_region_key")
    op.drop_column("weather_observations", "region_id")
    op.drop_column("weather_observations", "collector_run_id")
    op.alter_column(
        "weather_observations",
        "soil_moisture",
        existing_type=sa.Numeric(18, 8),
        type_=sa.Float(),
        nullable=True,
    )
    op.alter_column("weather_observations", "weather_metric_json", existing_type=sa.JSON(), nullable=False)
    op.alter_column("weather_observations", "precipitation", existing_type=sa.Float(), nullable=False)
    op.alter_column("weather_observations", "temperature", existing_type=sa.Float(), nullable=False)
    op.alter_column("weather_observations", "lon", existing_type=sa.Float(), nullable=False)
    op.alter_column("weather_observations", "lat", existing_type=sa.Float(), nullable=False)
    op.alter_column("weather_observations", "region_code", existing_type=sa.String(length=100), nullable=False)

    op.drop_index("ix_weather_regions_priority", table_name="weather_regions")
    op.drop_index("ix_weather_regions_active", table_name="weather_regions")
    op.drop_index("ix_weather_regions_family", table_name="weather_regions")
    op.drop_index("ix_weather_regions_country_crop", table_name="weather_regions")
    op.drop_index("ix_weather_regions_code", table_name="weather_regions")
    op.drop_table("weather_regions")
