from __future__ import annotations

import os
import subprocess
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.config.settings import get_settings
from app.db.models import (
    Base,
    CollectorRun,
    DataQualityCheck,
    RawResponse,
    Source,
    WeatherDailyFeature,
    WeatherObservation,
    WeatherRegion,
)
from app.db.seed import seed_database
from app.features.weather_daily import build_weather_daily_features
from app.monitoring.operational_report import build_operational_report


def test_weather_daily_aggregation_creates_features_and_windows() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_weather_observations(session, "br_mato_grosso_soybean", days=10)

        result = build_weather_daily_features(
            session=session,
            region_code="br_mato_grosso_soybean",
            from_date=date(2026, 5, 7),
            to_date=date(2026, 5, 10),
        )
        session.commit()
        feature_7 = _feature(session, "br_mato_grosso_soybean", date(2026, 5, 7))
        feature_10 = _feature(session, "br_mato_grosso_soybean", date(2026, 5, 10))

    assert result.regions_processed == 1
    assert result.dates_processed == 4
    assert result.rows_created == 4
    assert feature_7.temperature_7d_mean == Decimal("14.00000000")
    assert feature_7.temperature_30d_mean == Decimal("14.00000000")
    assert feature_7.temperature_min_7d == Decimal("-1.00000000")
    assert feature_7.temperature_max_7d == Decimal("32.00000000")
    assert feature_7.precipitation_7d_sum == Decimal("28.00000000")
    assert feature_7.precipitation_14d_sum == Decimal("28.00000000")
    assert feature_7.precipitation_30d_sum == Decimal("28.00000000")
    assert feature_7.heat_stress_days_7d == 3
    assert feature_7.heat_stress_days_30d == 3
    assert feature_7.frost_days_7d == 2
    assert feature_7.frost_days_30d == 2
    assert feature_7.growing_degree_days_7d == Decimal("28.00000000")
    assert feature_7.growing_degree_days_30d == Decimal("28.00000000")
    assert feature_7.drought_proxy_30d == Decimal("28.00000000")
    assert feature_7.weather_as_of_date == date(2026, 5, 7)
    assert feature_7.missing_flags["incomplete_14d_window"] is True
    assert feature_7.missing_flags["incomplete_30d_window"] is True
    assert feature_10.temperature_7d_mean == Decimal("17.00000000")
    assert feature_10.precipitation_7d_sum == Decimal("49.00000000")
    assert feature_10.precipitation_14d_sum == Decimal("55.00000000")
    assert feature_10.precipitation_30d_sum == Decimal("55.00000000")
    assert feature_10.growing_degree_days_7d == Decimal("49.00000000")
    assert feature_10.growing_degree_days_30d == Decimal("55.00000000")
    assert feature_10.metadata_json["gdd_base_temperature"] == "10"
    assert feature_10.metadata_json["observation_count_7d"] == 7


def test_weather_daily_gdd_uses_rapeseed_base_temperature() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_weather_observations(session, "ca_saskatchewan_canola", days=7)

        build_weather_daily_features(
            session=session,
            region_code="ca_saskatchewan_canola",
            from_date=date(2026, 5, 7),
            to_date=date(2026, 5, 7),
        )
        session.commit()
        feature = _feature(session, "ca_saskatchewan_canola", date(2026, 5, 7))

    assert feature.growing_degree_days_7d == Decimal("63.00000000")
    assert feature.growing_degree_days_30d == Decimal("63.00000000")
    assert feature.metadata_json["gdd_base_temperature"] == "5"


def test_weather_daily_missing_flags_for_incomplete_and_missing_values() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_weather_observations(session, "br_mato_grosso_soybean", days=2, precipitation_none=True)

        result = build_weather_daily_features(session=session, region_code="br_mato_grosso_soybean")
        session.commit()
        feature = _feature(session, "br_mato_grosso_soybean", date(2026, 5, 2))

    assert result.warnings_count == 2
    assert feature.precipitation_7d_sum is None
    assert feature.missing_flags["missing_precipitation"] is True
    assert feature.missing_flags["incomplete_7d_window"] is True
    assert feature.missing_flags["incomplete_14d_window"] is True
    assert feature.missing_flags["incomplete_30d_window"] is True


def test_weather_daily_no_future_leakage() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_weather_observations(session, "br_mato_grosso_soybean", days=11, day_11_mean="100")

        build_weather_daily_features(
            session=session,
            region_code="br_mato_grosso_soybean",
            from_date=date(2026, 5, 10),
            to_date=date(2026, 5, 10),
        )
        session.commit()
        feature = _feature(session, "br_mato_grosso_soybean", date(2026, 5, 10))
        future_checks = session.scalars(
            select(DataQualityCheck).where(DataQualityCheck.check_name == "weather_daily_no_future_observations")
        ).all()

    assert feature.temperature_7d_mean == Decimal("17.00000000")
    assert feature.weather_as_of_date == date(2026, 5, 10)
    assert all(check.status == "pass" for check in future_checks)


def test_weather_daily_idempotent_rerun_skips_and_updates_without_duplicates() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_weather_observations(session, "br_mato_grosso_soybean", days=7)

        first = build_weather_daily_features(session=session, region_code="br_mato_grosso_soybean")
        second = build_weather_daily_features(session=session, region_code="br_mato_grosso_soybean")
        observation = session.scalar(
            select(WeatherObservation).where(WeatherObservation.observation_date == date(2026, 5, 7)).limit(1)
        )
        observation.precipitation_sum = Decimal("99")
        third = build_weather_daily_features(
            session=session,
            region_code="br_mato_grosso_soybean",
            from_date=date(2026, 5, 7),
            to_date=date(2026, 5, 7),
        )
        session.commit()
        count = session.scalar(select(func.count()).select_from(WeatherDailyFeature))
        duplicate_count = session.scalar(
            select(func.count()).select_from(
                select(WeatherDailyFeature.region_id, WeatherDailyFeature.feature_date)
                .group_by(WeatherDailyFeature.region_id, WeatherDailyFeature.feature_date)
                .having(func.count() > 1)
                .subquery()
            )
        )
        feature = _feature(session, "br_mato_grosso_soybean", date(2026, 5, 7))

    assert first.rows_created == 7
    assert second.rows_skipped == 7
    assert third.rows_updated == 1
    assert count == 7
    assert duplicate_count == 0
    assert feature.precipitation_7d_sum == Decimal("120.00000000")


def test_weather_daily_quality_checks_are_created() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_weather_observations(session, "br_mato_grosso_soybean", days=7)

        build_weather_daily_features(session=session, region_code="br_mato_grosso_soybean")
        session.commit()
        check_names = set(session.scalars(select(DataQualityCheck.check_name)).all())

    assert "weather_daily_region_present" in check_names
    assert "weather_daily_feature_date_valid" in check_names
    assert "weather_daily_observations_present" in check_names
    assert "weather_daily_no_future_observations" in check_names
    assert "weather_daily_as_of_not_future" in check_names
    assert "weather_daily_temperature_reasonable" in check_names
    assert "weather_daily_precipitation_non_negative" in check_names
    assert "weather_daily_gdd_non_negative" in check_names
    assert "weather_daily_missing_flags_recorded" in check_names


def test_weather_daily_operational_report_sees_features() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_weather_observations(session, "br_mato_grosso_soybean", days=3)

        build_weather_daily_features(session=session, region_code="br_mato_grosso_soybean")
        session.commit()
        report = build_operational_report(session=session)

    assert report["weather_daily_features"]["count"] == 3
    assert report["weather_daily_features"]["regions_count"] == 1
    assert report["weather_daily_features"]["first_feature_date"] == "2026-05-01"
    assert report["weather_daily_features"]["last_feature_date"] == "2026-05-03"
    assert report["weather_daily_features"]["latest_weather_as_of_date"] == "2026-05-03"


def test_build_features_cli_supports_weather_daily(tmp_path: Path) -> None:
    db_path = tmp_path / "weather_features.db"
    database_url = f"sqlite+pysqlite:///{db_path}"
    SessionLocal = _session_factory(database_url)
    with SessionLocal() as session:
        _seed_weather_observations(session, "br_mato_grosso_soybean", days=3)
        session.commit()

    env = {**os.environ, "DATABASE_URL": database_url, "LOG_DIR": str(tmp_path / "logs")}
    get_settings.cache_clear()
    first = subprocess.run(
        [
            sys.executable,
            "scripts/build_features.py",
            "weather_daily",
            "--region",
            "br_mato_grosso_soybean",
            "--from-date",
            "2026-05-01",
            "--to-date",
            "2026-05-03",
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    second = subprocess.run(
        [
            sys.executable,
            "scripts/build_features.py",
            "weather_daily",
            "--region",
            "br_mato_grosso_soybean",
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    get_settings.cache_clear()

    assert "regions_processed=1" in first.stdout
    assert "rows_created=3" in first.stdout
    assert "rows_skipped=3" in second.stdout


def _session_factory(database_url: str = "sqlite+pysqlite:///:memory:"):
    engine = create_engine(database_url, future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def _seed_weather_observations(
    session,
    region_code: str,
    *,
    days: int,
    precipitation_none: bool = False,
    day_11_mean: str | None = None,
) -> None:
    seed_database(session)
    source = session.scalar(select(Source).where(Source.code == "open_meteo_historical_weather"))
    region = session.scalar(select(WeatherRegion).where(WeatherRegion.region_code == region_code))
    run = CollectorRun(
        source_id=source.id,
        collector_name="open_meteo_historical_weather",
        started_at=datetime(2026, 6, 11, 12, tzinfo=timezone.utc),
        finished_at=datetime(2026, 6, 11, 12, 1, tzinfo=timezone.utc),
        status="success",
        run_type="manual",
    )
    session.add(run)
    session.flush()
    raw = RawResponse(
        source_id=source.id,
        collector_run_id=run.id,
        fetched_at=datetime(2026, 6, 11, 12, tzinfo=timezone.utc),
        url="https://archive-api.open-meteo.com/v1/archive",
        method="GET",
        status_code=200,
        content_type="application/json",
        storage_path="data/raw/open_meteo_historical_weather/2026/06/11/1/hash.json",
        sha256="a" * 64,
        bytes_size=1200,
        parser_version="open_meteo_weather_v1",
    )
    session.add(raw)
    session.flush()

    for day in range(1, days + 1):
        observation_date = date(2026, 5, day)
        mean = Decimal(day_11_mean) if day == 11 and day_11_mean is not None else Decimal(10 + day)
        precipitation = None if precipitation_none else Decimal(day)
        session.add(
            WeatherObservation(
                source_id=source.id,
                raw_response_id=raw.id,
                collector_run_id=run.id,
                region_id=region.id,
                source_region_key=f"test:{region.region_code}",
                observation_date=observation_date,
                observed_at=datetime.combine(observation_date, datetime.min.time(), tzinfo=timezone.utc),
                fetched_at=datetime(2026, 6, 11, 12, tzinfo=timezone.utc),
                frequency="daily",
                temperature_2m_mean=mean,
                temperature_2m_min=Decimal(day - 2),
                temperature_2m_max=Decimal(25 + day),
                precipitation_sum=precipitation,
                snowfall_sum=Decimal("0"),
                relative_humidity_mean=Decimal("70"),
                wind_speed_mean=Decimal("10"),
                wind_speed_max=Decimal("20"),
                evapotranspiration=Decimal("4"),
                shortwave_radiation=Decimal("18"),
                source_record_hash=f"{day:064d}"[-64:],
                source_payload_hash=raw.sha256,
                metadata_json={"fixture": True},
            )
        )
    session.flush()


def _feature(session, region_code: str, feature_date: date) -> WeatherDailyFeature:
    region = session.scalar(select(WeatherRegion).where(WeatherRegion.region_code == region_code))
    feature = session.scalar(
        select(WeatherDailyFeature)
        .where(WeatherDailyFeature.region_id == region.id, WeatherDailyFeature.feature_date == feature_date)
        .limit(1)
    )
    assert feature is not None
    return feature
