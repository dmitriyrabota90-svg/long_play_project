from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config.logging import setup_logging
from app.config.settings import Settings, get_settings
from app.db.models import (
    Base,
    CollectorRun,
    DailyProductFeature,
    DailySupplyDemandFeature,
    Product,
    ProductSupplyDemandWeight,
    RawResponse,
    Source,
    SupplyDemandCommodity,
    SupplyDemandObservation,
    SupplyDemandRevision,
)
from app.monitoring.operational_report import build_operational_report
from app.operations.backup import build_backup_plan
from app.operations.cleanup import build_cleanup_plan


def test_log_rotation_settings_read_from_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("LOG_DIR", str(tmp_path / "logs"))
    monkeypatch.setenv("LOG_MAX_BYTES", "12345")
    monkeypatch.setenv("LOG_BACKUP_COUNT", "7")
    get_settings.cache_clear()

    settings = get_settings()
    setup_logging(settings)
    rotating_handlers = [handler for handler in logging.getLogger().handlers if isinstance(handler, RotatingFileHandler)]

    assert settings.log_max_bytes == 12345
    assert settings.log_backup_count == 7
    assert rotating_handlers
    assert rotating_handlers[0].maxBytes == 12345
    assert rotating_handlers[0].backupCount == 7
    get_settings.cache_clear()


def test_operational_report_handles_empty_database(tmp_path: Path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)

    with SessionLocal() as session:
        report = build_operational_report(freshness_hours=24, session=session)

    assert report["database"]["ok"] is True
    assert report["status"] == "degraded"
    assert report["last_24h"]["collector_runs"] == 0
    assert report["historical_price_bars"]["count"] == 0
    assert report["historical_price_bars"]["last_date"] is None
    assert report["historical_price_bars"]["last_bar_date"] is None
    assert report["historical_price_bars"]["last_created_at"] is None
    assert report["historical_price_bars"]["last_successful_run"] is None
    assert report["historical_price_bars"]["last_partial_run"] is None
    assert report["historical_price_bar_revisions"]["count"] == 0
    assert report["historical_price_bar_revisions"]["last_created_at"] is None
    assert report["daily_product_features"]["energy_coverage"]["rows_with_brent"] == 0
    assert report["daily_product_features"]["energy_coverage"]["rows_with_wti"] == 0
    assert report["daily_product_features"]["energy_coverage"]["rows_with_henry_hub"] == 0
    assert report["daily_product_features"]["energy_coverage"]["rows_with_diesel"] == 0
    assert report["daily_product_features"]["energy_coverage"]["latest_energy_feature_date"] is None
    assert report["daily_product_features"]["benchmark_coverage"]["rows_with_soybean_oil_benchmark"] == 0
    assert report["daily_product_features"]["benchmark_coverage"]["rows_with_soybeans_benchmark"] == 0
    assert report["daily_product_features"]["benchmark_coverage"]["rows_with_palm_oil_benchmark"] == 0
    assert report["daily_product_features"]["benchmark_coverage"]["rows_with_maize_benchmark"] == 0
    assert report["daily_product_features"]["benchmark_coverage"]["rows_with_wheat_benchmark"] == 0
    assert report["daily_product_features"]["benchmark_coverage"]["rows_with_fertilizer_benchmark"] == 0
    assert report["daily_product_features"]["benchmark_coverage"]["latest_benchmark_feature_date"] is None
    assert report["daily_product_features"]["weather_coverage"]["rows_with_weather_temperature_30d"] == 0
    assert report["daily_product_features"]["weather_coverage"]["rows_with_weather_precipitation_30d"] == 0
    assert report["daily_product_features"]["weather_coverage"]["rows_with_weather_gdd_30d"] == 0
    assert report["daily_product_features"]["weather_coverage"]["latest_product_weather_feature_date"] is None
    assert report["daily_product_features"]["news_coverage"]["rows_with_news_count_7d"] == 0
    assert report["daily_product_features"]["news_coverage"]["rows_with_event_count_7d"] == 0
    assert report["daily_product_features"]["news_coverage"]["rows_with_news_as_of_date"] == 0
    assert report["daily_product_features"]["news_coverage"]["latest_product_news_feature_date"] is None
    assert report["daily_product_features"]["trade_coverage"]["rows_with_export_volume_1m"] == 0
    assert report["daily_product_features"]["trade_coverage"]["rows_with_import_volume_1m"] == 0
    assert report["daily_product_features"]["trade_coverage"]["rows_with_trade_as_of_date"] == 0
    assert report["daily_product_features"]["trade_coverage"]["latest_product_trade_feature_date"] is None
    assert report["energy_prices"]["count"] == 0
    assert report["energy_prices"]["instruments_count"] == 0
    assert report["energy_prices"]["first_period_start"] is None
    assert report["energy_prices"]["last_period_start"] is None
    assert report["energy_prices"]["last_observed_at"] is None
    assert report["energy_prices"]["last_fetched_at"] is None
    assert report["commodity_benchmarks"]["count"] == 0
    assert report["commodity_benchmarks"]["benchmarks_count"] == 0
    assert report["commodity_benchmarks"]["first_period_start"] is None
    assert report["commodity_benchmarks"]["last_period_start"] is None
    assert report["commodity_benchmarks"]["last_observed_at"] is None
    assert report["commodity_benchmarks"]["last_fetched_at"] is None
    assert report["weather_regions"]["count"] == 0
    assert report["weather_regions"]["active_count"] == 0
    assert report["weather_regions"]["high_priority_count"] == 0
    assert report["weather_regions"]["countries_count"] == 0
    assert report["weather_regions"]["commodity_families_count"] == 0
    assert report["weather_observations"]["count"] == 0
    assert report["weather_observations"]["regions_count"] == 0
    assert report["weather_observations"]["first_observation_date"] is None
    assert report["weather_observations"]["last_observation_date"] is None
    assert report["weather_observations"]["last_fetched_at"] is None
    assert report["weather_daily_features"]["count"] == 0
    assert report["weather_daily_features"]["regions_count"] == 0
    assert report["weather_daily_features"]["first_feature_date"] is None
    assert report["weather_daily_features"]["last_feature_date"] is None
    assert report["weather_daily_features"]["latest_weather_as_of_date"] is None
    assert report["product_weather_region_weights"]["count"] == 0
    assert report["product_weather_region_weights"]["active_count"] == 0
    assert report["product_weather_region_weights"]["products_count"] == 0
    assert report["product_weather_region_weights"]["regions_count"] == 0
    assert report["news_articles"]["count"] == 0
    assert report["news_articles"]["sources_count"] == 0
    assert report["news_articles"]["first_published_at"] is None
    assert report["news_articles"]["last_published_at"] is None
    assert report["news_articles"]["last_fetched_at"] is None
    assert report["news_articles"]["languages_count"] == 0
    assert report["commodity_events"]["count"] == 0
    assert report["commodity_events"]["categories_count"] == 0
    assert report["commodity_events"]["commodity_families_count"] == 0
    assert report["commodity_events"]["first_event_date"] is None
    assert report["commodity_events"]["last_event_date"] is None
    assert report["commodity_events"]["latest_published_at"] is None
    assert report["daily_news_features"]["count"] == 0
    assert report["daily_news_features"]["products_count"] == 0
    assert report["daily_news_features"]["first_feature_date"] is None
    assert report["daily_news_features"]["last_feature_date"] is None
    assert report["daily_news_features"]["latest_news_as_of_date"] is None
    assert report["trade_commodity_codes"]["count"] == 0
    assert report["trade_commodity_codes"]["active_count"] == 0
    assert report["trade_commodity_codes"]["code_systems_count"] == 0
    assert report["trade_commodity_codes"]["direct_mappings_count"] == 0
    assert report["trade_commodity_codes"]["context_mappings_count"] == 0
    assert report["trade_flows"]["count"] == 0
    assert report["trade_flows"]["commodities_count"] == 0
    assert report["trade_flows"]["reporters_count"] == 0
    assert report["trade_flows"]["partners_count"] == 0
    assert report["trade_flows"]["first_period_start"] is None
    assert report["trade_flows"]["last_period_start"] is None
    assert report["trade_flows"]["last_fetched_at"] is None
    assert report["product_trade_code_weights"]["count"] == 0
    assert report["product_trade_code_weights"]["active_count"] == 0
    assert report["product_trade_code_weights"]["products_count"] == 0
    assert report["product_trade_code_weights"]["commodity_codes_count"] == 0
    assert report["daily_trade_features"]["count"] == 0
    assert report["daily_trade_features"]["products_count"] == 0
    assert report["daily_trade_features"]["first_feature_date"] is None
    assert report["daily_trade_features"]["last_feature_date"] is None
    assert report["daily_trade_features"]["latest_trade_as_of_date"] is None
    assert report["supply_demand_commodities"]["count"] == 0
    assert report["supply_demand_commodities"]["active_count"] == 0
    assert report["supply_demand_commodities"]["metrics_count"] == 0
    assert report["supply_demand_observations"]["count"] == 0
    assert report["supply_demand_revisions"]["count"] == 0
    assert report["product_supply_demand_weights"]["count"] == 0
    assert report["daily_supply_demand_features"]["count"] == 0


def test_operational_report_includes_product_trade_coverage() -> None:
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
        session.add(product)
        session.flush()
        session.add(
            DailyProductFeature(
                product_id=product.id,
                feature_date=date(2026, 6, 10),
                as_of_at=datetime(2026, 6, 10, 12, tzinfo=timezone.utc),
                features_json={"export_volume_1m": "1000.00000000"},
                feature_version="daily_features_v1",
                price_last=Decimal("100.000000"),
                export_volume_1m=Decimal("1000.00000000"),
                import_volume_1m=Decimal("100.00000000"),
                trade_as_of_date=date(2026, 6, 9),
            )
        )
        session.commit()
        report = build_operational_report(freshness_hours=24, session=session)

    coverage = report["daily_product_features"]["trade_coverage"]
    assert coverage["rows_with_export_volume_1m"] == 1
    assert coverage["rows_with_import_volume_1m"] == 1
    assert coverage["rows_with_trade_as_of_date"] == 1
    assert coverage["latest_product_trade_feature_date"] == "2026-06-10"


def test_operational_report_includes_supply_demand_counts() -> None:
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
        commodity = SupplyDemandCommodity(
            source_id=source.id,
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
            metadata_json={"design_phase": "6.7C"},
        )
        session.add_all([raw, commodity])
        session.flush()
        observation = SupplyDemandObservation(
            source_id=source.id,
            raw_response_id=raw.id,
            collector_run_id=run.id,
            supply_demand_commodity_id=commodity.id,
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
            source_record_hash="record" + "a" * 58,
            source_payload_hash="a" * 64,
            metadata_json={"source": "test"},
        )
        session.add(observation)
        session.flush()
        session.add_all(
            [
                ProductSupplyDemandWeight(
                    product_id=product.id,
                    supply_demand_commodity_id=commodity.id,
                    weight=Decimal("1.00000000"),
                    relevance="direct",
                    role="direct_supply_demand_proxy",
                    effective_from=date(2020, 1, 1),
                    effective_to=None,
                    is_active=True,
                    metadata_json={"design_phase": "6.7C"},
                ),
                DailySupplyDemandFeature(
                    product_id=product.id,
                    feature_date=date(2026, 6, 14),
                    production_volume=Decimal("1000.00000000"),
                    domestic_consumption=None,
                    food_use=None,
                    feed_use=None,
                    crush_volume=None,
                    exports_volume=None,
                    imports_volume=None,
                    beginning_stocks=None,
                    ending_stocks=None,
                    stock_to_use_ratio=None,
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
                    missing_flags=None,
                    metadata_json={"source": "test"},
                ),
                SupplyDemandRevision(
                    supply_demand_observation_id=observation.id,
                    revision_number=1,
                    old_metric_value=Decimal("999.00000000"),
                    new_metric_value=Decimal("1000.00000000"),
                    old_source_record_hash="record" + "b" * 58,
                    new_source_record_hash="record" + "a" * 58,
                    revision_reason="source_revision",
                    detected_at=datetime(2026, 6, 15, tzinfo=timezone.utc),
                    metadata_json={"source": "test"},
                ),
            ]
        )
        session.commit()
        report = build_operational_report(freshness_hours=24, session=session)

    assert report["supply_demand_commodities"]["count"] == 1
    assert report["supply_demand_commodities"]["active_count"] == 1
    assert report["supply_demand_commodities"]["metrics_count"] == 1
    assert report["supply_demand_observations"]["count"] == 1
    assert report["supply_demand_revisions"]["count"] == 1
    assert report["product_supply_demand_weights"]["count"] == 1
    assert report["daily_supply_demand_features"]["count"] == 1


def test_cleanup_operational_dry_run_does_not_delete_files(tmp_path: Path) -> None:
    log_dir = tmp_path / "logs"
    raw_dir = tmp_path / "raw"
    export_dir = tmp_path / "exports"
    log_dir.mkdir()
    raw_dir.mkdir()
    export_dir.mkdir()
    rotated_log = log_dir / "app.log.1"
    raw_file = raw_dir / "raw.txt"
    export_file = export_dir / "dataset_manifest.json"
    rotated_log.write_text("old log", encoding="utf-8")
    raw_file.write_text("raw", encoding="utf-8")
    export_file.write_text("{}", encoding="utf-8")
    settings = Settings(LOG_DIR=log_dir, RAW_DATA_DIR=raw_dir, EXPORT_DATA_DIR=export_dir)

    plan = build_cleanup_plan(settings=settings, dry_run=True)

    assert plan["dry_run"] is True
    assert plan["actions_executed"] == []
    assert rotated_log.exists()
    assert raw_file.exists()
    assert export_file.exists()


def test_backup_plan_defaults_to_dry_run(tmp_path: Path) -> None:
    settings = Settings(RAW_DATA_DIR=tmp_path / "raw", EXPORT_DATA_DIR=tmp_path / "exports")

    plan = build_backup_plan(settings=settings)

    assert plan["dry_run"] is True
    assert plan["actions_executed"] == []
    assert "pg_dump" in plan["postgres"]["command"]
