from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from importlib import import_module
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db.models import (
    Base,
    CollectorRun,
    DailySupplyDemandFeature,
    Product,
    ProductSupplyDemandWeight,
    RawResponse,
    Source,
    SupplyDemandCommodity,
    SupplyDemandObservation,
    SupplyDemandRevision,
)


supply_demand_schema_migration = import_module("migrations.versions.0018_supply_demand_schema")


def test_metadata_contains_supply_demand_tables() -> None:
    assert "supply_demand_commodities" in Base.metadata.tables
    assert "supply_demand_observations" in Base.metadata.tables
    assert "supply_demand_revisions" in Base.metadata.tables
    assert "product_supply_demand_weights" in Base.metadata.tables
    assert "daily_supply_demand_features" in Base.metadata.tables


def test_supply_demand_commodities_columns_constraints_and_indexes() -> None:
    table = Base.metadata.tables["supply_demand_commodities"]
    expected_columns = {
        "id",
        "source_id",
        "source_commodity_code",
        "source_commodity_name",
        "source_metric_code",
        "source_metric_name",
        "commodity_family",
        "product_code",
        "metric_name",
        "metric_group",
        "unit_hint",
        "frequency",
        "relevance",
        "is_active",
        "metadata_json",
        "created_at",
        "updated_at",
    }
    constraint_names = {constraint.name for constraint in table.constraints}
    index_names = {index.name for index in table.indexes}

    assert expected_columns <= set(table.c.keys())
    assert table.c.source_id.nullable is True
    assert "uq_supply_demand_commodities_source_metric" in constraint_names
    assert "ck_supply_demand_commodities_relevance" in constraint_names
    assert "ck_supply_demand_commodities_metric_group" in constraint_names
    assert {
        "ix_supply_demand_commodities_family",
        "ix_supply_demand_commodities_product_code",
        "ix_supply_demand_commodities_metric_name",
        "ix_supply_demand_commodities_metric_group",
        "ix_supply_demand_commodities_is_active",
    } <= index_names


def test_supply_demand_observations_columns_constraints_indexes_and_foreign_keys() -> None:
    table = Base.metadata.tables["supply_demand_observations"]
    expected_columns = {
        "id",
        "source_id",
        "raw_response_id",
        "collector_run_id",
        "supply_demand_commodity_id",
        "source_record_id",
        "country_code",
        "country_name",
        "region_code",
        "region_name",
        "marketing_year",
        "marketing_year_start",
        "marketing_year_end",
        "report_month",
        "report_year",
        "report_published_at",
        "observed_period_start",
        "observed_period_end",
        "frequency",
        "estimate_type",
        "metric_value",
        "metric_unit",
        "value_usd",
        "is_forecast",
        "is_revision",
        "published_at",
        "fetched_at",
        "source_record_hash",
        "source_payload_hash",
        "metadata_json",
        "created_at",
        "updated_at",
    }
    constraint_names = {constraint.name for constraint in table.constraints}
    index_names = {index.name for index in table.indexes}
    fk_columns = {fk.parent.name for fk in table.foreign_keys}
    unique = next(constraint for constraint in table.constraints if constraint.name == "uq_supply_demand_observations_identity")

    assert expected_columns <= set(table.c.keys())
    assert {"source_id", "raw_response_id", "collector_run_id", "supply_demand_commodity_id"} <= fk_columns
    assert "source_record_hash" not in {column.name for column in unique.columns}
    assert {
        "uq_supply_demand_observations_identity",
        "ck_supply_demand_observations_estimate_type",
        "ck_supply_demand_observations_frequency",
        "ck_supply_demand_observations_report_month",
        "ck_supply_demand_observations_marketing_dates",
        "ck_supply_demand_observations_observed_dates",
    } <= constraint_names
    assert {
        "ix_supply_demand_obs_commodity_year",
        "ix_supply_demand_obs_country_year",
        "ix_supply_demand_obs_report_published",
        "ix_supply_demand_obs_published_at",
        "ix_supply_demand_obs_fetched_at",
        "ix_supply_demand_obs_raw_response_id",
        "ix_supply_demand_obs_collector_run_id",
        "ix_supply_demand_obs_record_hash",
    } <= index_names


def test_supply_demand_revision_weights_and_daily_features_constraints() -> None:
    revision_table = Base.metadata.tables["supply_demand_revisions"]
    weights_table = Base.metadata.tables["product_supply_demand_weights"]
    daily_table = Base.metadata.tables["daily_supply_demand_features"]

    assert "uq_supply_demand_revisions_obs_number" in {constraint.name for constraint in revision_table.constraints}
    assert "ck_supply_demand_revisions_reason" in {constraint.name for constraint in revision_table.constraints}
    assert {
        "ix_supply_demand_revisions_observation_id",
        "ix_supply_demand_revisions_detected_at",
        "ix_supply_demand_revisions_reason",
    } <= {index.name for index in revision_table.indexes}
    assert "uq_product_supply_demand_weights_identity" in {constraint.name for constraint in weights_table.constraints}
    assert "ck_product_supply_demand_weights_relevance" in {constraint.name for constraint in weights_table.constraints}
    assert "ck_product_supply_demand_weights_nonnegative" in {constraint.name for constraint in weights_table.constraints}
    assert "ck_product_supply_demand_weights_dates" in {constraint.name for constraint in weights_table.constraints}
    assert "uq_daily_supply_demand_features_product_date" in {constraint.name for constraint in daily_table.constraints}
    assert "ck_daily_supply_demand_features_as_of" in {constraint.name for constraint in daily_table.constraints}


def test_supply_demand_schema_migration_revision_metadata() -> None:
    migration_text = Path(supply_demand_schema_migration.__file__).read_text(encoding="utf-8")

    assert supply_demand_schema_migration.revision == "0018_supply_demand_schema"
    assert supply_demand_schema_migration.down_revision == "0017_trade_features"
    assert "op.create_table(\n        \"supply_demand_commodities\"" in migration_text
    assert "op.create_table(\n        \"supply_demand_observations\"" in migration_text
    assert "op.create_table(\n        \"supply_demand_revisions\"" in migration_text
    assert "op.create_table(\n        \"product_supply_demand_weights\"" in migration_text
    assert "op.create_table(\n        \"daily_supply_demand_features\"" in migration_text


def test_create_all_creates_supply_demand_tables() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    assert "supply_demand_commodities" in table_names
    assert "supply_demand_observations" in table_names
    assert "supply_demand_revisions" in table_names
    assert "product_supply_demand_weights" in table_names
    assert "daily_supply_demand_features" in table_names


def test_supply_demand_rows_insert_and_unique_constraints() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)

    with SessionLocal() as session:
        source = Source(
            code="usda_psd",
            name="USDA PSD / FAS PSD Online",
            source_type="supply_demand",
            base_url="https://apps.fas.usda.gov/psdonline/",
        )
        product = Product(
            code="soybean_oil",
            name="Soybean oil",
            category="oil",
            unit="metric_ton",
            currency_default="USD",
        )
        session.add_all([source, product])
        session.flush()
        run = CollectorRun(
            source_id=source.id,
            collector_name="usda_psd_collector",
            started_at=datetime(2026, 6, 14, tzinfo=timezone.utc),
            status="success",
            run_type="manual",
        )
        session.add(run)
        session.flush()
        raw = RawResponse(
            source_id=source.id,
            collector_run_id=run.id,
            fetched_at=datetime(2026, 6, 14, tzinfo=timezone.utc),
            url="https://apps.fas.usda.gov/psdonline/",
            method="GET",
            status_code=200,
            content_type="application/json",
            storage_path="data/raw/usda_psd/2026/06/14/1/hash.json",
            sha256="a" * 64,
            bytes_size=2000,
            parser_version="usda_psd_v1",
        )
        commodity = _supply_demand_commodity(source.id)
        session.add_all([raw, commodity])
        session.flush()

        session.add(_supply_demand_observation(source.id, raw.id, run.id, commodity.id))
        session.add(_product_supply_demand_weight(product.id, commodity.id))
        session.add(_daily_supply_demand_feature(product.id))
        session.commit()

        loaded_observation = session.scalar(
            select(SupplyDemandObservation).where(SupplyDemandObservation.source_record_hash == "record" + "a" * 58)
        )
        assert loaded_observation is not None
        assert loaded_observation.raw_response_id == raw.id
        assert loaded_observation.collector_run_id == run.id
        assert loaded_observation.supply_demand_commodity_id == commodity.id

        session.add(
            SupplyDemandRevision(
                supply_demand_observation_id=loaded_observation.id,
                revision_number=1,
                old_metric_value=Decimal("1000.00000000"),
                new_metric_value=Decimal("1001.00000000"),
                old_source_record_hash="record" + "a" * 58,
                new_source_record_hash="record" + "b" * 58,
                revision_reason="source_revision",
                detected_at=datetime(2026, 6, 15, tzinfo=timezone.utc),
                metadata_json={"source": "test"},
            )
        )
        session.commit()

        session.add(
            _supply_demand_observation(
                source.id,
                raw.id,
                run.id,
                commodity.id,
                source_record_hash="record" + "c" * 58,
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def _supply_demand_commodity(source_id: int) -> SupplyDemandCommodity:
    return SupplyDemandCommodity(
        source_id=source_id,
        source_commodity_code="psd_needs_verification_soybean_oil",
        source_commodity_name="Soybean oil",
        source_metric_code="psd_needs_verification_production_volume",
        source_metric_name="Production Volume",
        commodity_family="soybean",
        product_code="soybean_oil",
        metric_name="production_volume",
        metric_group="production",
        unit_hint="metric_ton",
        frequency="monthly_report",
        relevance="direct",
        is_active=True,
        metadata_json={"design_phase": "6.7C", "exact_psd_code_status": "needs_verification"},
    )


def _supply_demand_observation(
    source_id: int,
    raw_response_id: int,
    collector_run_id: int,
    supply_demand_commodity_id: int,
    *,
    source_record_hash: str = "record" + "a" * 58,
) -> SupplyDemandObservation:
    return SupplyDemandObservation(
        source_id=source_id,
        raw_response_id=raw_response_id,
        collector_run_id=collector_run_id,
        supply_demand_commodity_id=supply_demand_commodity_id,
        source_record_id="row-1",
        country_code="US",
        country_name="United States",
        region_code=None,
        region_name=None,
        marketing_year="2025/26",
        marketing_year_start=date(2025, 10, 1),
        marketing_year_end=date(2026, 9, 30),
        report_month=6,
        report_year=2026,
        report_published_at=datetime(2026, 6, 12, tzinfo=timezone.utc),
        observed_period_start=date(2025, 10, 1),
        observed_period_end=date(2026, 9, 30),
        frequency="monthly_report",
        estimate_type="forecast",
        metric_value=Decimal("1000.00000000"),
        metric_unit="metric_ton",
        value_usd=None,
        is_forecast=True,
        is_revision=False,
        published_at=datetime(2026, 6, 12, tzinfo=timezone.utc),
        fetched_at=datetime(2026, 6, 14, tzinfo=timezone.utc),
        source_record_hash=source_record_hash,
        source_payload_hash="a" * 64,
        metadata_json={"source": "test"},
    )


def _product_supply_demand_weight(product_id: int, supply_demand_commodity_id: int) -> ProductSupplyDemandWeight:
    return ProductSupplyDemandWeight(
        product_id=product_id,
        supply_demand_commodity_id=supply_demand_commodity_id,
        weight=Decimal("1.00000000"),
        relevance="direct",
        role="direct_supply_demand_proxy",
        effective_from=date(2020, 1, 1),
        effective_to=None,
        is_active=True,
        metadata_json={"design_phase": "6.7C"},
    )


def _daily_supply_demand_feature(product_id: int) -> DailySupplyDemandFeature:
    return DailySupplyDemandFeature(
        product_id=product_id,
        feature_date=date(2026, 6, 14),
        production_volume=Decimal("1000.00000000"),
        domestic_consumption=Decimal("900.00000000"),
        food_use=None,
        feed_use=None,
        crush_volume=None,
        exports_volume=Decimal("50.00000000"),
        imports_volume=Decimal("10.00000000"),
        beginning_stocks=Decimal("100.00000000"),
        ending_stocks=Decimal("110.00000000"),
        stock_to_use_ratio=Decimal("0.12000000"),
        planted_area=None,
        harvested_area=None,
        yield_value=None,
        production_forecast_revision=None,
        ending_stocks_revision=None,
        stock_to_use_revision=None,
        forecast_month=6,
        marketing_year="2025/26",
        report_published_at=datetime(2026, 6, 12, tzinfo=timezone.utc),
        supply_demand_as_of_date=date(2026, 6, 12),
        reporting_lag_days=2,
        missing_flags={"missing_area": True},
        metadata_json={"source": "test"},
    )
