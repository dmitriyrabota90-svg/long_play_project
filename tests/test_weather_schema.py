from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from importlib import import_module

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db.models import (
    Base,
    CollectorRun,
    Product,
    ProductWeatherRegionWeight,
    RawResponse,
    Source,
    WeatherDailyFeature,
    WeatherObservation,
    WeatherRegion,
)


weather_schema_migration = import_module("migrations.versions.0012_weather_schema")


def test_metadata_contains_weather_tables() -> None:
    assert "weather_regions" in Base.metadata.tables
    assert "weather_observations" in Base.metadata.tables
    assert "weather_daily_features" in Base.metadata.tables
    assert "product_weather_region_weights" in Base.metadata.tables


def test_weather_region_required_columns_constraints_and_indexes() -> None:
    table = Base.metadata.tables["weather_regions"]
    expected_columns = {
        "id",
        "region_code",
        "region_name",
        "country",
        "country_code",
        "crop",
        "commodity_family",
        "role",
        "priority",
        "latitude",
        "longitude",
        "spatial_model",
        "aggregation_strategy",
        "is_active",
        "metadata_json",
        "created_at",
        "updated_at",
    }
    unique_names = {constraint.name for constraint in table.constraints}
    index_names = {index.name for index in table.indexes}

    assert expected_columns <= set(table.c.keys())
    assert table.c.region_code.nullable is False
    assert table.c.latitude.nullable is False
    assert "uq_weather_regions_code" in unique_names
    assert {
        "ix_weather_regions_code",
        "ix_weather_regions_country_crop",
        "ix_weather_regions_family",
        "ix_weather_regions_active",
        "ix_weather_regions_priority",
    } <= index_names


def test_weather_observation_required_columns_constraints_and_indexes() -> None:
    table = Base.metadata.tables["weather_observations"]
    expected_columns = {
        "id",
        "source_id",
        "raw_response_id",
        "collector_run_id",
        "region_id",
        "source_region_key",
        "observation_date",
        "observed_at",
        "fetched_at",
        "frequency",
        "temperature_2m_mean",
        "temperature_2m_min",
        "temperature_2m_max",
        "precipitation_sum",
        "snowfall_sum",
        "relative_humidity_mean",
        "wind_speed_mean",
        "wind_speed_max",
        "soil_moisture",
        "evapotranspiration",
        "shortwave_radiation",
        "source_record_hash",
        "source_payload_hash",
        "metadata_json",
        "created_at",
        "updated_at",
    }
    unique_names = {constraint.name for constraint in table.constraints}
    index_names = {index.name for index in table.indexes}

    assert expected_columns <= set(table.c.keys())
    assert table.c.source_id.nullable is False
    assert table.c.raw_response_id.nullable is False
    assert table.c.collector_run_id.nullable is False
    assert table.c.region_id.nullable is False
    assert "uq_weather_obs_source_region_date_freq" in unique_names
    assert "ck_weather_obs_frequency" in unique_names
    assert {
        "ix_weather_obs_region_date",
        "ix_weather_obs_source_date",
        "ix_weather_obs_fetched_at",
        "ix_weather_obs_raw_response_id",
        "ix_weather_obs_collector_run_id",
        "ix_weather_obs_record_hash",
    } <= index_names


def test_weather_daily_features_and_weights_constraints() -> None:
    daily_table = Base.metadata.tables["weather_daily_features"]
    weights_table = Base.metadata.tables["product_weather_region_weights"]

    assert "uq_weather_daily_region_date" in {constraint.name for constraint in daily_table.constraints}
    assert {
        "ix_weather_daily_region_date",
        "ix_weather_daily_feature_date",
        "ix_weather_daily_as_of_date",
    } <= {index.name for index in daily_table.indexes}
    assert "uq_product_weather_region_weight" in {constraint.name for constraint in weights_table.constraints}
    assert {
        "ix_product_weather_product_active",
        "ix_product_weather_region_active",
        "ix_product_weather_effective",
    } <= {index.name for index in weights_table.indexes}


def test_weather_schema_migration_revision_metadata() -> None:
    assert weather_schema_migration.revision == "0012_weather_schema"
    assert weather_schema_migration.down_revision == "0011_benchmark_features"


def test_create_all_creates_weather_tables() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    assert "weather_regions" in table_names
    assert "weather_observations" in table_names
    assert "weather_daily_features" in table_names
    assert "product_weather_region_weights" in table_names


def test_weather_rows_insert_and_unique_constraints() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)

    with SessionLocal() as session:
        product = Product(
            code="soybean_oil",
            name="Soybean oil",
            category="oil",
            unit="metric_ton",
            currency_default="USD",
        )
        source = Source(
            code="open_meteo_historical_weather",
            name="Open-Meteo Historical Weather API",
            source_type="weather",
            base_url="https://open-meteo.com/",
        )
        session.add_all([product, source])
        session.flush()
        run = CollectorRun(
            source_id=source.id,
            collector_name="open_meteo_weather_collector",
            started_at=datetime(2026, 6, 11, tzinfo=timezone.utc),
            status="success",
            run_type="manual",
        )
        session.add(run)
        session.flush()
        raw = RawResponse(
            source_id=source.id,
            collector_run_id=run.id,
            fetched_at=datetime(2026, 6, 11, tzinfo=timezone.utc),
            url="https://archive-api.open-meteo.com/v1/archive",
            method="GET",
            status_code=200,
            content_type="application/json",
            storage_path="data/raw/open_meteo_historical_weather/2026/06/11/1/hash.json",
            sha256="a" * 64,
            bytes_size=1200,
            parser_version="open_meteo_weather_v1",
        )
        region = _weather_region()
        session.add_all([raw, region])
        session.flush()

        session.add(_weather_observation(source.id, raw.id, run.id, region.id))
        session.add(_weather_daily_feature(region.id))
        session.add(_product_weather_weight(product.id, region.id))
        session.commit()

        loaded_observation = session.scalar(select(WeatherObservation).where(WeatherObservation.region_id == region.id))
        assert loaded_observation is not None
        assert loaded_observation.temperature_2m_mean == Decimal("24.50000000")
        assert loaded_observation.raw_response_id == raw.id
        assert loaded_observation.collector_run_id == run.id

        session.add(_weather_observation(source.id, raw.id, run.id, region.id, source_record_hash="b" * 64))
        with pytest.raises(IntegrityError):
            session.commit()


def _weather_region() -> WeatherRegion:
    return WeatherRegion(
        region_code="br_mato_grosso_soybean",
        region_name="Mato Grosso soybean belt",
        country="Brazil",
        country_code="BR",
        crop="soybean",
        commodity_family="soybean",
        role="production_export",
        priority="high",
        latitude=Decimal("-12.600000"),
        longitude=Decimal("-55.700000"),
        spatial_model="centroid",
        aggregation_strategy="single_point",
        is_active=True,
        metadata_json={"reason_for_ml": "soybean supply weather"},
    )


def _weather_observation(
    source_id: int,
    raw_response_id: int,
    collector_run_id: int,
    region_id: int,
    *,
    source_record_hash: str = "a" * 64,
) -> WeatherObservation:
    return WeatherObservation(
        source_id=source_id,
        raw_response_id=raw_response_id,
        collector_run_id=collector_run_id,
        region_id=region_id,
        source_region_key="lat=-12.600000,lon=-55.700000",
        observation_date=date(2026, 6, 1),
        observed_at=datetime(2026, 6, 1, tzinfo=timezone.utc),
        fetched_at=datetime(2026, 6, 11, tzinfo=timezone.utc),
        frequency="daily",
        temperature_2m_mean=Decimal("24.50000000"),
        temperature_2m_min=Decimal("19.00000000"),
        temperature_2m_max=Decimal("31.00000000"),
        precipitation_sum=Decimal("2.20000000"),
        snowfall_sum=None,
        relative_humidity_mean=Decimal("70.00000000"),
        wind_speed_mean=Decimal("3.10000000"),
        wind_speed_max=Decimal("7.20000000"),
        soil_moisture=None,
        evapotranspiration=Decimal("4.00000000"),
        shortwave_radiation=Decimal("18.00000000"),
        source_record_hash=source_record_hash,
        source_payload_hash="a" * 64,
        metadata_json={"source": "open_meteo"},
    )


def _weather_daily_feature(region_id: int) -> WeatherDailyFeature:
    return WeatherDailyFeature(
        region_id=region_id,
        feature_date=date(2026, 6, 1),
        temperature_7d_mean=Decimal("24.00000000"),
        temperature_30d_mean=Decimal("23.50000000"),
        precipitation_7d_sum=Decimal("10.00000000"),
        precipitation_14d_sum=Decimal("20.00000000"),
        precipitation_30d_sum=Decimal("35.00000000"),
        weather_as_of_date=date(2026, 6, 1),
        missing_flags={"soil_moisture": "missing"},
        metadata_json={"window_policy": "past_only"},
    )


def _product_weather_weight(product_id: int, region_id: int) -> ProductWeatherRegionWeight:
    return ProductWeatherRegionWeight(
        product_id=product_id,
        region_id=region_id,
        weight=Decimal("1.00000000"),
        role="production",
        effective_from=date(2026, 1, 1),
        effective_to=None,
        is_active=True,
        metadata_json={"weight_policy": "equal_first_version"},
    )
