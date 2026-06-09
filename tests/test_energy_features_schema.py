from __future__ import annotations

from importlib import import_module

from sqlalchemy import create_engine, inspect

from app.db.models import Base


energy_features_migration = import_module("migrations.versions.0009_energy_features")


ENERGY_FEATURE_COLUMNS = {
    "energy_brent_usd_per_barrel",
    "energy_wti_usd_per_barrel",
    "energy_henry_hub_usd_mmbtu",
    "energy_diesel_proxy_value",
    "energy_brent_delta_1d",
    "energy_brent_delta_7d",
    "energy_wti_delta_1d",
    "energy_wti_delta_7d",
    "energy_henry_hub_delta_1d",
    "energy_henry_hub_delta_7d",
    "energy_diesel_proxy_delta_7d",
    "energy_as_of_date",
    "energy_brent_as_of_date",
    "energy_wti_as_of_date",
    "energy_henry_hub_as_of_date",
    "energy_diesel_as_of_date",
    "energy_missing_flags",
}


def test_daily_feature_metadata_contains_energy_columns() -> None:
    table = Base.metadata.tables["daily_product_features"]

    assert ENERGY_FEATURE_COLUMNS <= set(table.c.keys())
    for column_name in ENERGY_FEATURE_COLUMNS:
        assert table.c[column_name].nullable is True


def test_energy_features_migration_revision_metadata() -> None:
    assert energy_features_migration.revision == "0009_energy_features"
    assert energy_features_migration.down_revision == "0008_energy_prices"


def test_create_all_creates_daily_energy_feature_columns() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    inspector = inspect(engine)

    columns = {column["name"] for column in inspector.get_columns("daily_product_features")}
    assert ENERGY_FEATURE_COLUMNS <= columns
