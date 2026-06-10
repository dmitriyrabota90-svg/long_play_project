from __future__ import annotations

from importlib import import_module

from sqlalchemy import create_engine, inspect

from app.db.models import Base


benchmark_features_migration = import_module("migrations.versions.0011_benchmark_features")

BENCHMARK_FEATURE_COLUMNS = {
    "benchmark_soybean_oil_value",
    "benchmark_soybeans_value",
    "benchmark_palm_oil_value",
    "benchmark_maize_value",
    "benchmark_wheat_value",
    "benchmark_fertilizer_index_value",
    "benchmark_soybean_oil_delta_1m",
    "benchmark_soybean_oil_delta_3m",
    "benchmark_soybeans_delta_1m",
    "benchmark_soybeans_delta_3m",
    "benchmark_palm_oil_delta_1m",
    "benchmark_palm_oil_delta_3m",
    "benchmark_maize_delta_1m",
    "benchmark_maize_delta_3m",
    "benchmark_wheat_delta_1m",
    "benchmark_wheat_delta_3m",
    "benchmark_fertilizer_index_delta_1m",
    "benchmark_fertilizer_index_delta_3m",
    "benchmark_as_of_date",
    "benchmark_soybean_oil_as_of_date",
    "benchmark_soybeans_as_of_date",
    "benchmark_palm_oil_as_of_date",
    "benchmark_maize_as_of_date",
    "benchmark_wheat_as_of_date",
    "benchmark_fertilizer_index_as_of_date",
    "benchmark_missing_flags",
}


def test_daily_feature_metadata_contains_benchmark_columns() -> None:
    table = Base.metadata.tables["daily_product_features"]

    assert BENCHMARK_FEATURE_COLUMNS <= set(table.c.keys())
    for column_name in BENCHMARK_FEATURE_COLUMNS:
        assert table.c[column_name].nullable is True


def test_benchmark_features_migration_revision_metadata() -> None:
    assert benchmark_features_migration.revision == "0011_benchmark_features"
    assert benchmark_features_migration.down_revision == "0010_commodity_benchmarks"


def test_create_all_creates_daily_benchmark_feature_columns() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    inspector = inspect(engine)

    columns = {column["name"] for column in inspector.get_columns("daily_product_features")}

    assert BENCHMARK_FEATURE_COLUMNS <= columns
