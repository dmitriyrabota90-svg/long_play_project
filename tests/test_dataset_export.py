from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config.settings import get_settings
from app.db.models import Base, DailyProductFeature, Product
from app.exports.daily_features_export import (
    DAILY_FEATURE_COLUMNS,
    DatasetExportValidationError,
    _ensure_parquet_available,
    _git_commit,
    export_daily_features,
    load_daily_feature_rows,
    validate_daily_feature_rows,
)
from app.features.daily import build_calendar_features


def _session_factory(database_url: str = "sqlite+pysqlite:///:memory:"):
    engine = create_engine(database_url, future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def _seed_product(session, *, code: str = "rapeseed_oil", name: str = "Rapeseed Oil") -> Product:
    product = Product(code=code, name=name, category="oil", unit="metric_ton", currency_default="CNY")
    session.add(product)
    session.flush()
    return product


def _seed_feature(
    session,
    *,
    product: Product,
    feature_date: date,
    price: str = "100.00",
) -> DailyProductFeature:
    now = datetime(2026, 6, 4, 10, tzinfo=timezone.utc)
    calendar_values = build_calendar_features(feature_date)
    feature = DailyProductFeature(
        product_id=product.id,
        feature_date=feature_date,
        as_of_at=now,
        features_json={"price_last": price},
        feature_version="daily_features_v1",
        price_last=Decimal(price),
        price_first=Decimal(price),
        price_min=Decimal(price),
        price_max=Decimal(price),
        price_observations_count=2,
        cny_rub=Decimal("10.00000000"),
        usd_rub=Decimal("90.00000000"),
        eur_rub=Decimal("100.00000000"),
        fx_as_of_date=feature_date,
        benchmark_soybean_oil_value=Decimal("1000.00000000"),
        benchmark_soybean_oil_as_of_date=feature_date,
        benchmark_as_of_date=feature_date,
        benchmark_missing_flags="missing_benchmark_soybeans",
        weather_temperature_30d_mean_weighted=Decimal("21.50000000"),
        weather_precipitation_30d_sum_weighted=Decimal("42.00000000"),
        weather_growing_degree_days_30d_weighted=Decimal("88.00000000"),
        weather_as_of_date=feature_date,
        weather_regions_used="br_mato_grosso_soybean,br_parana_soybean",
        weather_missing_flags="partial_weather_regions",
        news_count_1d=1,
        news_count_7d=2,
        news_count_30d=3,
        event_count_1d=1,
        event_count_7d=2,
        event_count_30d=4,
        bullish_event_count_7d=1,
        bearish_event_count_7d=0,
        mixed_event_count_7d=1,
        export_restriction_count_30d=1,
        import_policy_count_30d=0,
        war_logistics_count_30d=0,
        weather_disaster_count_30d=0,
        crop_report_count_30d=1,
        biofuel_policy_count_30d=0,
        energy_shock_count_30d=1,
        demand_shock_count_30d=0,
        supply_chain_count_30d=0,
        sentiment_proxy_7d=Decimal("0.50000000"),
        news_as_of_date=feature_date,
        news_missing_flags="partial_source_coverage",
        export_volume_1m=Decimal("1000.00000000"),
        export_volume_3m_avg=Decimal("900.00000000"),
        export_volume_12m_sum=None,
        import_volume_1m=Decimal("100.00000000"),
        import_volume_3m_avg=None,
        import_volume_12m_sum=None,
        net_export_volume_1m=Decimal("900.00000000"),
        export_value_usd_1m=Decimal("850000.00000000"),
        import_value_usd_1m=Decimal("85000.00000000"),
        average_export_unit_value_usd=Decimal("850.00000000"),
        average_import_unit_value_usd=Decimal("850.00000000"),
        china_import_volume_1m=Decimal("100.00000000"),
        major_exporter_volume_1m=Decimal("1000.00000000"),
        major_importer_volume_1m=Decimal("100.00000000"),
        trade_balance_proxy=Decimal("900.00000000"),
        trade_yoy_change=None,
        trade_as_of_date=feature_date,
        reporting_lag_days=7,
        trade_missing_flags="missing_yoy_history",
        **calendar_values,
        created_at=now,
        updated_at=now,
    )
    session.add(feature)
    session.flush()
    return feature


def test_export_query_returns_rows_from_sample_db() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        product = _seed_product(session)
        _seed_feature(session, product=product, feature_date=date(2026, 6, 1))
        rows = load_daily_feature_rows(session=session)

    assert rows[0]["product_code"] == "rapeseed_oil"
    assert rows[0]["product_name"] == "Rapeseed Oil"
    assert rows[0]["feature_date"] == "2026-06-01"
    assert rows[0]["calendar_year"] == 2026
    assert rows[0]["calendar_month"] == 6
    assert rows[0]["calendar_day_of_week"] == 1
    assert rows[0]["calendar_season"] == "summer"
    assert rows[0]["benchmark_soybean_oil_value"] == "1000.00000000"
    assert rows[0]["benchmark_soybean_oil_as_of_date"] == "2026-06-01"
    assert rows[0]["weather_temperature_30d_mean_weighted"] == "21.50000000"
    assert rows[0]["weather_precipitation_30d_sum_weighted"] == "42.00000000"
    assert rows[0]["weather_growing_degree_days_30d_weighted"] == "88.00000000"
    assert rows[0]["weather_regions_used"] == "br_mato_grosso_soybean,br_parana_soybean"
    assert rows[0]["weather_missing_flags"] == "partial_weather_regions"
    assert rows[0]["news_count_7d"] == 2
    assert rows[0]["event_count_7d"] == 2
    assert rows[0]["sentiment_proxy_7d"] == "0.50000000"
    assert rows[0]["news_as_of_date"] == "2026-06-01"
    assert rows[0]["news_missing_flags"] == "partial_source_coverage"
    assert rows[0]["export_volume_1m"] == "1000.00000000"
    assert rows[0]["import_volume_1m"] == "100.00000000"
    assert rows[0]["net_export_volume_1m"] == "900.00000000"
    assert rows[0]["trade_as_of_date"] == "2026-06-01"
    assert rows[0]["reporting_lag_days"] == 7
    assert rows[0]["trade_missing_flags"] == "missing_yoy_history"
    assert "historical_price_bars" not in rows[0]


def test_daily_features_export_creates_csv_manifest_and_sha256(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    export_dir = tmp_path / "exports"
    with SessionLocal() as session:
        first = _seed_product(session, code="rapeseed_oil", name="Rapeseed Oil")
        second = _seed_product(session, code="soybean_oil", name="Soybean Oil")
        _seed_feature(session, product=first, feature_date=date(2026, 6, 1), price="100.00")
        _seed_feature(session, product=second, feature_date=date(2026, 6, 1), price="200.00")
        result = export_daily_features(session=session, output_dir=export_dir, settings=_settings(export_dir))

    csv_file = Path(result.files[0]["path"])
    manifest_file = Path(result.manifest_path)
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    with csv_file.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader)
        rows = list(reader)

    assert result.row_count == 2
    assert manifest["row_count"] == len(rows) == 2
    assert manifest["column_count"] == len(header)
    assert result.column_count == len(DAILY_FEATURE_COLUMNS)
    assert result.column_count > 44
    assert "calendar_year" in header
    assert "calendar_season" in header
    assert "energy_brent_usd_per_barrel" in header
    assert "energy_diesel_proxy_delta_7d" in header
    assert "benchmark_soybean_oil_value" in header
    assert "benchmark_fertilizer_index_delta_3m" in header
    assert "weather_temperature_30d_mean_weighted" in header
    assert "weather_precipitation_30d_sum_weighted" in header
    assert "weather_growing_degree_days_30d_weighted" in header
    assert "weather_regions_used" in header
    assert "news_count_7d" in header
    assert "event_count_7d" in header
    assert "sentiment_proxy_7d" in header
    assert "news_as_of_date" in header
    assert "news_missing_flags" in header
    assert "export_volume_1m" in header
    assert "import_volume_1m" in header
    assert "trade_as_of_date" in header
    assert "trade_missing_flags" in header
    assert "calendar_sin_day_of_year" in manifest["columns"]
    assert "energy_wti_delta_7d" in manifest["columns"]
    assert "benchmark_as_of_date" in manifest["columns"]
    assert "weather_as_of_date" in manifest["columns"]
    assert "news_count_7d" in manifest["columns"]
    assert "sentiment_proxy_7d" in manifest["columns"]
    assert "export_volume_1m" in manifest["columns"]
    assert "trade_as_of_date" in manifest["columns"]
    assert "commodity_benchmarks" in manifest["source_tables"]
    assert "weather_daily_features" in manifest["source_tables"]
    assert "product_weather_region_weights" in manifest["source_tables"]
    assert "daily_news_features" in manifest["source_tables"]
    assert "commodity_events" in manifest["source_tables"]
    assert "news_articles" in manifest["source_tables"]
    assert "daily_trade_features" in manifest["source_tables"]
    assert "trade_flows" in manifest["source_tables"]
    assert "product_trade_code_weights" in manifest["source_tables"]
    assert "trade_commodity_codes" in manifest["source_tables"]
    assert "World Bank Pink Sheet commodity benchmarks through the feature builder" in manifest["included_sources"]
    assert "Open-Meteo region weather aggregates through product_weather_region_weights" in manifest["included_sources"]
    assert "Rule-based commodity events and daily news aggregates through the feature builder" in manifest["included_sources"]
    assert "UN Comtrade trade flows through daily_trade_features and product_trade_code_weights" in manifest["included_sources"]
    assert "commodity_benchmarks" not in manifest["excluded_sources"]
    assert "weather_observations" not in manifest["excluded_sources"]
    assert "news_articles" not in manifest["excluded_sources"]
    assert "trade_flows" not in manifest["excluded_sources"]
    assert manifest["sha256"]["csv"] == result.sha256["csv"]
    assert len(result.sha256["csv"]) == 64
    assert manifest["products"] == ["rapeseed_oil", "soybean_oil"]
    assert manifest["feature_date_min"] == "2026-06-01"
    assert manifest["feature_date_max"] == "2026-06-01"
    assert "historical_price_bars" in manifest["excluded_sources"]


def test_date_filters_work(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    export_dir = tmp_path / "exports"
    with SessionLocal() as session:
        product = _seed_product(session)
        _seed_feature(session, product=product, feature_date=date(2026, 6, 1))
        _seed_feature(session, product=product, feature_date=date(2026, 6, 2))
        result = export_daily_features(
            session=session,
            from_date=date(2026, 6, 2),
            to_date=date(2026, 6, 2),
            output_dir=export_dir,
            settings=_settings(export_dir),
        )

    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert result.row_count == 1
    assert manifest["feature_date_min"] == "2026-06-02"
    assert manifest["feature_date_max"] == "2026-06-02"


def test_empty_dataset_fails_clearly(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session, pytest.raises(DatasetExportValidationError, match="no rows"):
        export_daily_features(session=session, output_dir=tmp_path / "exports", settings=_settings(tmp_path / "exports"))


def test_duplicate_product_date_detection() -> None:
    rows = [
        {"product_code": "rapeseed_oil", "feature_date": "2026-06-01"},
        {"product_code": "rapeseed_oil", "feature_date": "2026-06-01"},
    ]
    with pytest.raises(DatasetExportValidationError, match="duplicate"):
        validate_daily_feature_rows(rows)


def test_output_path_must_stay_under_export_dir(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        product = _seed_product(session)
        _seed_feature(session, product=product, feature_date=date(2026, 6, 1))
        with pytest.raises(DatasetExportValidationError, match="output-dir"):
            export_daily_features(
                session=session,
                output_dir=tmp_path / "outside",
                settings=_settings(tmp_path / "exports"),
            )


def test_manifest_does_not_contain_database_url_or_secrets(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    export_dir = tmp_path / "exports"
    with SessionLocal() as session:
        product = _seed_product(session)
        _seed_feature(session, product=product, feature_date=date(2026, 6, 1))
        result = export_daily_features(session=session, output_dir=export_dir, settings=_settings(export_dir))

    text = Path(result.manifest_path).read_text(encoding="utf-8")
    assert "DATABASE_URL" not in text
    assert "postgresql+psycopg2://" not in text
    assert "TELEGRAM_TOKEN" not in text


def test_manifest_uses_app_git_commit_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("APP_GIT_COMMIT", "abc123")
    SessionLocal = _session_factory()
    export_dir = tmp_path / "exports"
    with SessionLocal() as session:
        product = _seed_product(session)
        _seed_feature(session, product=product, feature_date=date(2026, 6, 1))
        result = export_daily_features(session=session, output_dir=export_dir, settings=_settings(export_dir))

    manifest = json.loads(Path(result.manifest_path).read_text(encoding="utf-8"))
    assert manifest["git_commit"] == "abc123"
    assert _git_commit() == "abc123"


def test_parquet_unavailable_path_is_clear(monkeypatch) -> None:
    monkeypatch.setattr("app.exports.daily_features_export.importlib.util.find_spec", lambda _name: None)
    with pytest.raises(DatasetExportValidationError, match="Parquet export is not available"):
        _ensure_parquet_available()


def test_export_dataset_cli_daily_features(tmp_path: Path) -> None:
    db_path = tmp_path / "export.db"
    database_url = f"sqlite+pysqlite:///{db_path}"
    export_dir = tmp_path / "exports"
    SessionLocal = _session_factory(database_url)
    with SessionLocal() as session:
        product = _seed_product(session)
        _seed_feature(session, product=product, feature_date=date(2026, 6, 1))
        session.commit()

    env = {
        **os.environ,
        "DATABASE_URL": database_url,
        "EXPORT_DATA_DIR": str(export_dir),
        "LOG_DIR": str(tmp_path / "logs"),
    }
    get_settings.cache_clear()
    result = subprocess.run(
        [
            sys.executable,
            "scripts/export_dataset.py",
            "daily_features",
            "--from-date",
            "2026-06-01",
            "--to-date",
            "2026-06-01",
            "--format",
            "csv",
            "--output-dir",
            str(export_dir),
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    get_settings.cache_clear()

    assert "row_count=1" in result.stdout
    assert "csv_sha256=" in result.stdout
    assert "manifest_path=" in result.stdout
    assert list(export_dir.glob("daily_features_v1_*_manifest.json"))


def test_export_dataset_cli_list() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/export_dataset.py", "--list"],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.strip() == "daily_features"


def _settings(export_dir: Path):
    from app.config.settings import Settings

    return Settings(EXPORT_DATA_DIR=export_dir)
