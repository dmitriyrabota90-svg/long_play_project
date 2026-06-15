from __future__ import annotations

import os
import subprocess
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from importlib import import_module
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.config.settings import get_settings
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
)
from app.features.supply_demand_daily import build_supply_demand_daily_features


product_supply_demand_migration = import_module("migrations.versions.0019_product_supply_demand_features")


def _session_factory(database_url: str = "sqlite+pysqlite:///:memory:"):
    engine = create_engine(database_url, future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def test_product_supply_demand_feature_columns_and_migration_metadata() -> None:
    table = Base.metadata.tables["daily_product_features"]
    expected_columns = {
        "production_volume",
        "domestic_consumption",
        "food_use",
        "feed_use",
        "crush_volume",
        "exports_volume",
        "imports_volume",
        "beginning_stocks",
        "ending_stocks",
        "stock_to_use_ratio",
        "planted_area",
        "harvested_area",
        "yield_value",
        "production_forecast_revision",
        "ending_stocks_revision",
        "stock_to_use_revision",
        "forecast_month",
        "marketing_year",
        "report_published_at",
        "supply_demand_as_of_date",
        "supply_demand_reporting_lag_days",
        "supply_demand_missing_flags",
    }
    migration_text = Path(product_supply_demand_migration.__file__).read_text(encoding="utf-8")

    assert expected_columns <= set(table.c.keys())
    assert product_supply_demand_migration.revision == "0019_product_supply_demand_features"
    assert product_supply_demand_migration.down_revision == "0018_supply_demand_schema"
    assert "op.add_column(\"daily_product_features\"" in migration_text
    assert "supply_demand_missing_flags" in migration_text


def test_supply_demand_daily_builder_creates_features_and_is_idempotent() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        context = _seed_base(session)
        _add_observation(
            session,
            context=context,
            metric_name="production_volume",
            value="1000",
            report_month=5,
            published_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
        )
        _add_observation(
            session,
            context=context,
            metric_name="production_volume",
            value="1100",
            report_month=6,
            published_at=datetime(2026, 6, 12, tzinfo=timezone.utc),
        )
        _add_observation(session, context=context, metric_name="domestic_consumption", value="500", report_month=6)
        _add_observation(session, context=context, metric_name="crush_volume", value="450", report_month=6)
        _add_observation(session, context=context, metric_name="exports_volume", value="120", report_month=6)
        _add_observation(session, context=context, metric_name="imports_volume", value="30", report_month=6)
        _add_observation(session, context=context, metric_name="beginning_stocks", value="80", report_month=6)
        _add_observation(session, context=context, metric_name="ending_stocks", value="100", report_month=6)
        _add_observation(session, context=context, metric_name="stock_to_use_ratio", value="0.20", report_month=6)
        _add_observation(session, context=context, metric_name="planted_area", value="200", report_month=6)
        _add_observation(session, context=context, metric_name="harvested_area", value="190", report_month=6)
        _add_observation(session, context=context, metric_name="yield", value="5.5", report_month=6)

        first = build_supply_demand_daily_features(
            product_code=context.product.code,
            from_date=date(2026, 6, 15),
            to_date=date(2026, 6, 15),
            session=session,
        )
        second = build_supply_demand_daily_features(
            product_code=context.product.code,
            from_date=date(2026, 6, 15),
            to_date=date(2026, 6, 15),
            session=session,
        )
        feature = session.scalar(select(DailySupplyDemandFeature).where(DailySupplyDemandFeature.product_id == context.product.id))
        rows_count = session.scalar(select(func.count()).select_from(DailySupplyDemandFeature))

    assert first.rows_created == 1
    assert second.rows_skipped == 1
    assert rows_count == 1
    assert feature.production_volume == Decimal("1100.00000000")
    assert feature.domestic_consumption == Decimal("500.00000000")
    assert feature.crush_volume == Decimal("450.00000000")
    assert feature.ending_stocks == Decimal("100.00000000")
    assert feature.stock_to_use_ratio == Decimal("0.20000000")
    assert feature.yield_value == Decimal("5.50000000")
    assert feature.production_forecast_revision == Decimal("100.00000000")
    assert feature.supply_demand_as_of_date == date(2026, 6, 12)
    assert feature.reporting_lag_days == 3
    assert feature.forecast_month == 6
    assert feature.marketing_year == "2025/26"
    assert feature.missing_flags == {"missing_forecast_revision": True}
    assert first.observations_used == 11


def test_supply_demand_daily_builder_excludes_future_published_observations() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        context = _seed_base(session)
        _add_observation(
            session,
            context=context,
            metric_name="production_volume",
            value="100",
            report_month=5,
            published_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
        )
        _add_observation(
            session,
            context=context,
            metric_name="production_volume",
            value="999",
            report_month=6,
            published_at=datetime(2026, 6, 20, tzinfo=timezone.utc),
        )

        build_supply_demand_daily_features(
            product_code=context.product.code,
            from_date=date(2026, 6, 15),
            to_date=date(2026, 6, 15),
            session=session,
        )
        feature = session.scalar(select(DailySupplyDemandFeature).where(DailySupplyDemandFeature.product_id == context.product.id))

    assert feature.production_volume == Decimal("100.00000000")
    assert feature.supply_demand_as_of_date == date(2026, 6, 10)
    assert feature.reporting_lag_days == 5


def test_supply_demand_daily_builder_derives_stock_to_use_when_source_ratio_missing() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        context = _seed_base(session, metrics=("domestic_consumption", "ending_stocks"))
        _add_observation(session, context=context, metric_name="domestic_consumption", value="500", report_month=6)
        _add_observation(session, context=context, metric_name="ending_stocks", value="125", report_month=6)

        build_supply_demand_daily_features(
            product_code=context.product.code,
            from_date=date(2026, 6, 15),
            to_date=date(2026, 6, 15),
            session=session,
        )
        feature = session.scalar(select(DailySupplyDemandFeature).where(DailySupplyDemandFeature.product_id == context.product.id))

    assert feature.stock_to_use_ratio == Decimal("0.25000000")
    assert "missing_stock_to_use_ratio" not in feature.missing_flags


def test_supply_demand_daily_builder_records_missing_flags_without_observations_or_weights() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        product = Product(code="rapeseed_oil", name="Rapeseed oil", category="oil", unit="metric_ton", currency_default="USD")
        session.add(product)
        session.flush()

        result = build_supply_demand_daily_features(
            product_code=product.code,
            from_date=date(2026, 6, 15),
            to_date=date(2026, 6, 15),
            session=session,
        )
        feature = session.scalar(select(DailySupplyDemandFeature).where(DailySupplyDemandFeature.product_id == product.id))

    assert result.rows_created == 1
    assert result.warnings_count == 1
    assert result.missing_products == ["rapeseed_oil"]
    assert feature.supply_demand_as_of_date is None
    assert feature.missing_flags == {"no_product_supply_demand_weights": True}


def test_supply_demand_daily_builder_respects_active_weight_dates() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        context = _seed_base(session)
        for weight in session.scalars(select(ProductSupplyDemandWeight)).all():
            weight.effective_to = date(2026, 6, 1)
        _add_observation(session, context=context, metric_name="production_volume", value="1000", report_month=6)

        build_supply_demand_daily_features(
            product_code=context.product.code,
            from_date=date(2026, 6, 15),
            to_date=date(2026, 6, 15),
            session=session,
        )
        feature = session.scalar(select(DailySupplyDemandFeature).where(DailySupplyDemandFeature.product_id == context.product.id))

    assert feature.production_volume is None
    assert feature.missing_flags == {"no_product_supply_demand_weights": True}


def test_supply_demand_daily_cli(tmp_path: Path) -> None:
    db_path = tmp_path / "features.db"
    database_url = f"sqlite+pysqlite:///{db_path}"
    SessionLocal = _session_factory(database_url)
    with SessionLocal() as session:
        context = _seed_base(session)
        _add_observation(session, context=context, metric_name="production_volume", value="1000", report_month=6)
        session.commit()

    env = {**os.environ, "DATABASE_URL": database_url, "LOG_DIR": str(tmp_path / "logs")}
    get_settings.cache_clear()
    result = subprocess.run(
        [
            sys.executable,
            "scripts/build_features.py",
            "supply_demand_daily",
            "--product",
            "soybean_oil",
            "--from-date",
            "2026-06-15",
            "--to-date",
            "2026-06-15",
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    get_settings.cache_clear()

    assert "products_processed=1" in result.stdout
    assert "rows_created=1" in result.stdout
    assert "observations_used=1" in result.stdout


class _Context:
    def __init__(self, product: Product, source: Source, run: CollectorRun, raw: RawResponse, commodities: dict[str, SupplyDemandCommodity]):
        self.product = product
        self.source = source
        self.run = run
        self.raw = raw
        self.commodities = commodities


def _seed_base(
    session,
    *,
    metrics: tuple[str, ...] = (
        "production_volume",
        "domestic_consumption",
        "crush_volume",
        "exports_volume",
        "imports_volume",
        "beginning_stocks",
        "ending_stocks",
        "stock_to_use_ratio",
        "planted_area",
        "harvested_area",
        "yield",
    ),
) -> _Context:
    product = Product(code="soybean_oil", name="Soybean oil", category="oil", unit="metric_ton", currency_default="USD")
    source = Source(code="usda_psd", name="USDA PSD", source_type="supply_demand", base_url="https://apps.fas.usda.gov/")
    session.add_all([product, source])
    session.flush()
    run = CollectorRun(
        source_id=source.id,
        collector_name="usda_psd",
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
        url="https://apps.fas.usda.gov/psdonline/test",
        method="GET",
        status_code=200,
        content_type="application/json",
        storage_path="data/raw/usda_psd/2026/06/14/1/hash.json",
        sha256="a" * 64,
        bytes_size=2000,
        parser_version="usda_psd_v1",
    )
    session.add(raw)
    session.flush()
    commodities: dict[str, SupplyDemandCommodity] = {}
    for metric_name in metrics:
        commodity = SupplyDemandCommodity(
            source_id=source.id,
            source_commodity_code="psd_needs_verification_soybean_oil",
            source_commodity_name="Soybean oil",
            source_metric_code=f"psd_needs_verification_{metric_name}",
            source_metric_name=metric_name.replace("_", " ").title(),
            commodity_family="soybean",
            product_code="soybean_oil",
            metric_name=metric_name,
            metric_group="area_yield" if metric_name in {"planted_area", "harvested_area", "yield"} else "production",
            unit_hint="metric_ton",
            frequency="monthly_report",
            relevance="direct",
            is_active=True,
            metadata_json={"test": True},
        )
        session.add(commodity)
        session.flush()
        session.add(
            ProductSupplyDemandWeight(
                product_id=product.id,
                supply_demand_commodity_id=commodity.id,
                weight=Decimal("1.00000000"),
                relevance="direct",
                role="direct_supply_demand_proxy",
                effective_from=date(2020, 1, 1),
                effective_to=None,
                is_active=True,
                metadata_json={"test": True},
            )
        )
        commodities[metric_name] = commodity
    session.flush()
    return _Context(product, source, run, raw, commodities)


def _add_observation(
    session,
    *,
    context: _Context,
    metric_name: str,
    value: str,
    report_month: int,
    published_at: datetime | None = datetime(2026, 6, 12, tzinfo=timezone.utc),
) -> None:
    commodity = context.commodities[metric_name]
    session.add(
        SupplyDemandObservation(
            source_id=context.source.id,
            raw_response_id=context.raw.id,
            collector_run_id=context.run.id,
            supply_demand_commodity_id=commodity.id,
            source_record_id=f"{metric_name}-{report_month}-{value}",
            country_code="WLD",
            country_name="World",
            region_code=None,
            region_name=None,
            marketing_year="2025/26",
            marketing_year_start=date(2025, 10, 1),
            marketing_year_end=date(2026, 9, 30),
            report_month=report_month,
            report_year=2026,
            report_published_at=published_at,
            observed_period_start=date(2025, 10, 1),
            observed_period_end=date(2026, 9, 30),
            frequency="monthly_report",
            estimate_type="forecast",
            metric_value=Decimal(value),
            metric_unit="metric_ton",
            value_usd=None,
            is_forecast=True,
            is_revision=False,
            published_at=published_at,
            fetched_at=datetime(2026, 6, 14, tzinfo=timezone.utc),
            source_record_hash=(f"{metric_name}{report_month}{value}" + "a" * 64)[:64],
            source_payload_hash="a" * 64,
            metadata_json={"test": True},
        )
    )
    session.flush()
