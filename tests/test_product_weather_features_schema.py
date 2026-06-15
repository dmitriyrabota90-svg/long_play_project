from __future__ import annotations

from importlib import import_module

from app.db.models import DailyProductFeature


product_weather_migration = import_module("migrations.versions.0013_weather_features")


PRODUCT_WEATHER_COLUMNS = {
    "weather_temperature_7d_mean_weighted",
    "weather_temperature_30d_mean_weighted",
    "weather_temperature_min_7d_weighted",
    "weather_temperature_max_7d_weighted",
    "weather_precipitation_7d_sum_weighted",
    "weather_precipitation_14d_sum_weighted",
    "weather_precipitation_30d_sum_weighted",
    "weather_heat_stress_days_7d_weighted",
    "weather_heat_stress_days_30d_weighted",
    "weather_frost_days_7d_weighted",
    "weather_frost_days_30d_weighted",
    "weather_drought_proxy_30d_weighted",
    "weather_growing_degree_days_7d_weighted",
    "weather_growing_degree_days_30d_weighted",
    "weather_as_of_date",
    "weather_regions_used",
    "weather_missing_flags",
}


def test_daily_product_feature_metadata_contains_product_weather_columns() -> None:
    assert PRODUCT_WEATHER_COLUMNS <= set(DailyProductFeature.__table__.c.keys())


def test_product_weather_feature_migration_revision_metadata() -> None:
    assert product_weather_migration.revision == "0013_weather_features"
    assert product_weather_migration.down_revision == "0012_weather_schema"


def test_product_weather_feature_migration_column_list_matches_model() -> None:
    migration_columns = {name for name, _column_type in product_weather_migration.PRODUCT_WEATHER_FEATURE_COLUMNS}
    assert migration_columns == PRODUCT_WEATHER_COLUMNS
