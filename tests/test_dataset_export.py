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
    assert "calendar_sin_day_of_year" in manifest["columns"]
    assert "energy_wti_delta_7d" in manifest["columns"]
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
