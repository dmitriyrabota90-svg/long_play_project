from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config.logging import setup_logging
from app.config.settings import Settings, get_settings
from app.db.models import Base
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
