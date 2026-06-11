from __future__ import annotations

import os
import subprocess
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.collectors.weather.open_meteo_config import (
    ENDPOINT,
    HEADERS,
    MAX_DAYS_PER_RUN,
    OPEN_METEO_DAILY_VARIABLES,
    OPEN_METEO_VARIABLE_MAPPING,
    REQUEST_TIMEOUT,
    SOURCE_CODE,
    OpenMeteoRequest,
    open_meteo_params,
)
from app.collectors.weather.open_meteo_historical import (
    OpenMeteoHistoricalWeatherCollector,
    OpenMeteoParseError,
    assess_open_meteo_response,
    parse_open_meteo_daily,
    validate_date_range,
)
from app.db.models import Base, CollectorRun, DataQualityCheck, RawResponse, WeatherObservation, WeatherRegion
from app.db.seed import seed_database
from app.monitoring.operational_report import build_operational_report
from app.storage.raw_store import RawStore
from scripts.run_collector import build_parser


def _open_meteo_json(*, temp_mean_day_1: str = "25.5", include_optional: bool = True) -> bytes:
    daily = {
        "time": ["2026-05-01", "2026-05-02"],
        "temperature_2m_mean": [temp_mean_day_1, "26.1"],
        "temperature_2m_min": ["18.3", "18.9"],
        "temperature_2m_max": ["32.2", "33.0"],
        "precipitation_sum": ["1.2", "0"],
        "rain_sum": ["1.2", "0"],
        "snowfall_sum": ["0", "0"],
        "wind_speed_10m_max": ["18.4", "20.1"],
        "shortwave_radiation_sum": ["19.5", "20.0"],
        "et0_fao_evapotranspiration": ["4.1", "4.3"],
    }
    daily_units = {
        "time": "iso8601",
        "temperature_2m_mean": "degC",
        "temperature_2m_min": "degC",
        "temperature_2m_max": "degC",
        "precipitation_sum": "mm",
        "rain_sum": "mm",
        "snowfall_sum": "cm",
        "wind_speed_10m_max": "km/h",
        "shortwave_radiation_sum": "MJ/m2",
        "et0_fao_evapotranspiration": "mm",
    }
    if include_optional:
        daily["relative_humidity_2m_mean"] = ["70", "68"]
        daily["wind_speed_10m_mean"] = ["9.2", "10.4"]
        daily_units["relative_humidity_2m_mean"] = "%"
        daily_units["wind_speed_10m_mean"] = "km/h"
    return (
        "{"
        '"latitude":-12.6,'
        '"longitude":-55.7,'
        f'"daily_units":{_json(daily_units)},'
        f'"daily":{_json(daily)}'
        "}"
    ).encode()


def _json(value: object) -> str:
    import json

    return json.dumps(value, separators=(",", ":"))


class FakeOpenMeteoClient:
    def __init__(self, responses: dict[str, bytes | httpx.Response | Exception] | None = None) -> None:
        self.responses = responses or {"default": _open_meteo_json()}
        self.calls: list[tuple[str, dict[str, str], dict[str, str], float]] = []

    def get(self, url: str, *, params: dict[str, str], headers: dict[str, str], timeout: float) -> httpx.Response:
        self.calls.append((url, params, headers, timeout))
        configured = self.responses.get(params["latitude"], self.responses.get("default", _open_meteo_json()))
        if isinstance(configured, Exception):
            raise configured
        if isinstance(configured, httpx.Response):
            return configured
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(
            200,
            content=configured,
            headers={"content-type": "application/json; charset=utf-8"},
            request=request,
        )


def test_open_meteo_config_contains_expected_defaults() -> None:
    assert SOURCE_CODE == "open_meteo_historical_weather"
    assert ENDPOINT == "https://archive-api.open-meteo.com/v1/archive"
    assert REQUEST_TIMEOUT > 0
    assert MAX_DAYS_PER_RUN == 45
    assert {
        "temperature_2m_mean",
        "temperature_2m_min",
        "temperature_2m_max",
        "precipitation_sum",
        "snowfall_sum",
        "relative_humidity_2m_mean",
        "wind_speed_10m_mean",
        "wind_speed_10m_max",
        "shortwave_radiation_sum",
        "et0_fao_evapotranspiration",
    } <= set(OPEN_METEO_DAILY_VARIABLES)
    assert OPEN_METEO_VARIABLE_MAPPING["relative_humidity_2m_mean"] == "relative_humidity_mean"
    assert "commodity-dataset-builder" in HEADERS["User-Agent"]


def test_open_meteo_params_include_coordinates_dates_and_daily_variables() -> None:
    params = open_meteo_params(
        OpenMeteoRequest(
            latitude="-12.600000",
            longitude="-55.700000",
            from_date=date(2026, 5, 1),
            to_date=date(2026, 5, 10),
        )
    )

    assert params["latitude"] == "-12.600000"
    assert params["longitude"] == "-55.700000"
    assert params["start_date"] == "2026-05-01"
    assert params["end_date"] == "2026-05-10"
    assert "temperature_2m_mean" in params["daily"]
    assert "et0_fao_evapotranspiration" in params["daily"]
    assert params["timezone"] == "UTC"


def test_parser_handles_fixture_json() -> None:
    region = _weather_region()

    rows, daily_arrays_present, raw_rows_count = parse_open_meteo_daily(
        _open_meteo_json(),
        region=region,
        fetched_at=datetime(2026, 6, 11, 12, tzinfo=timezone.utc),
    )

    assert daily_arrays_present is True
    assert raw_rows_count == 2
    assert rows[0].observation_date == date(2026, 5, 1)
    assert rows[0].observed_at == datetime(2026, 5, 1, tzinfo=timezone.utc)
    assert rows[0].values["temperature_2m_mean"] == Decimal("25.5")
    assert rows[0].values["relative_humidity_mean"] == Decimal("70")
    assert rows[0].source_region_key == "lat=-12.600000,lon=-55.700000"


def test_parser_handles_missing_optional_variables() -> None:
    region = _weather_region()

    rows, _, _ = parse_open_meteo_daily(
        _open_meteo_json(include_optional=False),
        region=region,
        fetched_at=datetime(2026, 6, 11, 12, tzinfo=timezone.utc),
    )

    assert rows[0].values["relative_humidity_mean"] is None
    assert rows[0].values["wind_speed_mean"] is None
    assert "relative_humidity_2m_mean" in rows[0].missing_variables
    assert "wind_speed_10m_mean" in rows[0].missing_variables


def test_parser_reports_empty_and_unknown_formats() -> None:
    region = _weather_region()
    rows, checks = assess_open_meteo_response(
        payload=b"",
        content_type="application/json",
        status_code=200,
        region=region,
        fetched_at=datetime(2026, 6, 11, 12, tzinfo=timezone.utc),
    )

    assert rows == []
    assert {check.check_name: check.status for check in checks}["weather_daily_rows_present"] == "fail"
    with pytest.raises(OpenMeteoParseError):
        parse_open_meteo_daily(b'{"not_daily":{}}', region=region, fetched_at=datetime.now(timezone.utc))


def test_date_range_validation() -> None:
    validate_date_range(from_date=date(2026, 5, 1), to_date=date(2026, 5, 10), max_days=10)
    with pytest.raises(ValueError, match="from_date"):
        validate_date_range(from_date=date(2026, 5, 2), to_date=date(2026, 5, 1), max_days=10)
    with pytest.raises(ValueError, match="max allowed days"):
        validate_date_range(from_date=date(2026, 5, 1), to_date=date(2026, 5, 11), max_days=10)


def test_unknown_region_rejected() -> None:
    session, cleanup = build_seeded_session()
    try:
        with pytest.raises(ValueError, match="unknown weather region"):
            OpenMeteoHistoricalWeatherCollector(http_client=FakeOpenMeteoClient()).run(
                session,
                region_code="not_real",
                from_date=date(2026, 5, 1),
                to_date=date(2026, 5, 2),
            )
    finally:
        cleanup()


def test_collector_inserts_weather_observations_with_raw_and_quality_checks(tmp_path: Path) -> None:
    session, cleanup = build_seeded_session()
    client = FakeOpenMeteoClient()
    try:
        result = OpenMeteoHistoricalWeatherCollector(
            http_client=client,
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 6, 11, 12, tzinfo=timezone.utc),
        ).run(
            session,
            region_code="br_mato_grosso_soybean",
            from_date=date(2026, 5, 1),
            to_date=date(2026, 5, 2),
        )
        rows = session.scalars(select(WeatherObservation).order_by(WeatherObservation.observation_date)).all()
        raw_response = session.scalar(select(RawResponse))
        run = session.scalar(select(CollectorRun))
        check_names = set(session.scalars(select(DataQualityCheck.check_name)).all())
    finally:
        cleanup()

    assert result.status == "success"
    assert result.regions_requested == 1
    assert result.regions_success == 1
    assert result.records_found == 2
    assert result.records_written == 2
    assert result.skipped_existing == 0
    assert result.conflicts_count == 0
    assert len(rows) == 2
    assert raw_response is not None
    assert run is not None
    assert all(row.raw_response_id == raw_response.id for row in rows)
    assert all(row.collector_run_id == run.id for row in rows)
    assert rows[0].temperature_2m_mean == Decimal("25.50000000")
    assert rows[0].precipitation_sum == Decimal("1.20000000")
    assert rows[0].metadata_json["source_region_key"] == "lat=-12.600000,lon=-55.700000"
    assert rows[0].source_payload_hash == raw_response.sha256
    assert client.calls[0][0] == ENDPOINT
    assert client.calls[0][1]["start_date"] == "2026-05-01"
    assert client.calls[0][2] == HEADERS
    assert client.calls[0][3] == REQUEST_TIMEOUT
    assert "weather_raw_response_non_empty" in check_names
    assert "weather_daily_arrays_present" in check_names
    assert "weather_core_values_present" in check_names
    assert "weather_raw_linkage_present" in check_names


def test_duplicate_retry_skips_existing_weather_rows(tmp_path: Path) -> None:
    session, cleanup = build_seeded_session()
    try:
        collector = OpenMeteoHistoricalWeatherCollector(
            http_client=FakeOpenMeteoClient(),
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 6, 11, 12, tzinfo=timezone.utc),
        )
        first = collector.run(
            session,
            region_code="br_mato_grosso_soybean",
            from_date=date(2026, 5, 1),
            to_date=date(2026, 5, 2),
        )
        second = collector.run(
            session,
            region_code="br_mato_grosso_soybean",
            from_date=date(2026, 5, 1),
            to_date=date(2026, 5, 2),
        )
        rows_count = session.scalar(select(func.count()).select_from(WeatherObservation))
    finally:
        cleanup()

    assert first.records_written == 2
    assert second.records_written == 0
    assert second.skipped_existing == 2
    assert second.conflicts_count == 0
    assert rows_count == 2


def test_changed_weather_value_creates_conflict_warning_without_overwrite(tmp_path: Path) -> None:
    session, cleanup = build_seeded_session()
    try:
        OpenMeteoHistoricalWeatherCollector(
            http_client=FakeOpenMeteoClient({"default": _open_meteo_json(temp_mean_day_1="25.5")}),
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 6, 11, 12, tzinfo=timezone.utc),
        ).run(
            session,
            region_code="br_mato_grosso_soybean",
            from_date=date(2026, 5, 1),
            to_date=date(2026, 5, 1),
        )
        second = OpenMeteoHistoricalWeatherCollector(
            http_client=FakeOpenMeteoClient({"default": _open_meteo_json(temp_mean_day_1="27.0")}),
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 6, 11, 12, 5, tzinfo=timezone.utc),
        ).run(
            session,
            region_code="br_mato_grosso_soybean",
            from_date=date(2026, 5, 1),
            to_date=date(2026, 5, 1),
        )
        row = session.scalar(select(WeatherObservation))
        warning = session.scalar(
            select(DataQualityCheck).where(DataQualityCheck.check_name == "weather_existing_observation_hash_changed")
        )
    finally:
        cleanup()

    assert second.status == "partial_success"
    assert second.records_written == 0
    assert second.conflicts_count == 1
    assert row.temperature_2m_mean == Decimal("25.50000000")
    assert warning is not None
    assert warning.status == "fail"
    assert warning.severity == "warning"
    assert warning.details_json["incoming_values"]["temperature_2m_mean"] == "27"
    assert warning.details_json["policy_decision"] == "rejected_hash_conflict_no_overwrite"


def test_one_failed_region_produces_partial_success(tmp_path: Path) -> None:
    session, cleanup = build_seeded_session()
    client = FakeOpenMeteoClient(
        {
            "-12.600000": _open_meteo_json(),
            "-24.900000": httpx.ReadTimeout("synthetic timeout"),
        }
    )
    try:
        for region in session.scalars(select(WeatherRegion)).all():
            region.is_active = region.region_code in {"br_mato_grosso_soybean", "br_parana_soybean"}
        session.flush()
        result = OpenMeteoHistoricalWeatherCollector(
            http_client=client,
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 6, 11, 12, tzinfo=timezone.utc),
        ).run(session, from_date=date(2026, 5, 1), to_date=date(2026, 5, 2))
        rows_count = session.scalar(select(func.count()).select_from(WeatherObservation))
    finally:
        cleanup()

    assert result.status == "partial_success"
    assert result.regions_requested == 2
    assert result.regions_success == 1
    assert result.regions_failed == 1
    assert result.records_written == 2
    assert result.errors_count == 1
    assert rows_count == 2


def test_cli_argument_parsing_supports_open_meteo_weather() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "open_meteo_historical_weather",
            "--region",
            "br_mato_grosso_soybean",
            "--from-date",
            "2026-05-01",
            "--to-date",
            "2026-05-10",
        ]
    )

    assert args.collector_name == "open_meteo_historical_weather"
    assert args.region == "br_mato_grosso_soybean"
    assert args.from_date == "2026-05-01"
    assert args.to_date == "2026-05-10"


def test_cli_rejects_missing_weather_dates_without_db_access(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_collector.py",
            "open_meteo_historical_weather",
            "--region",
            "br_mato_grosso_soybean",
        ],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "LOG_DIR": str(tmp_path / "logs")},
    )

    assert result.returncode != 0
    assert "--from-date and --to-date are required" in result.stderr


def test_operational_report_sees_weather_observations(tmp_path: Path) -> None:
    session, cleanup = build_seeded_session()
    try:
        OpenMeteoHistoricalWeatherCollector(
            http_client=FakeOpenMeteoClient(),
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 6, 11, 12, tzinfo=timezone.utc),
        ).run(
            session,
            region_code="br_mato_grosso_soybean",
            from_date=date(2026, 5, 1),
            to_date=date(2026, 5, 2),
        )
        report = build_operational_report(session=session)
    finally:
        cleanup()

    assert report["weather_observations"]["count"] == 2
    assert report["weather_observations"]["regions_count"] == 1
    assert report["weather_observations"]["first_observation_date"] == "2026-05-01"
    assert report["weather_observations"]["last_observation_date"] == "2026-05-02"


def build_seeded_session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)
    session = SessionLocal()
    seed_database(session)

    def cleanup() -> None:
        session.close()
        engine.dispose()

    return session, cleanup


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
