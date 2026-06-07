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

from app.collectors.energy.fred_energy_config import (
    ENDPOINT,
    FRED_ENERGY_SERIES,
    HEADERS,
    REQUEST_TIMEOUT,
    fred_csv_params,
    fred_csv_url,
)
from app.collectors.energy.fred_energy_prices import (
    FredEnergyParseError,
    FredEnergyPricesCollector,
    assess_fred_csv_response,
    parse_fred_csv,
)
from app.db.models import Base, CollectorRun, DataQualityCheck, EnergyPrice, RawResponse
from app.db.seed import seed_database
from app.storage.raw_store import RawStore
from scripts.run_collector import build_parser


def _fred_csv(series_id: str = "DCOILBRENTEU", value: str = "64.12") -> bytes:
    return (
        f"observation_date,{series_id}\n"
        "2026-05-20,63.99\n"
        "2026-05-21,.\n"
        f"2026-05-22,{value}\n"
    ).encode()


class FakeHttpClient:
    def __init__(self, responses: dict[str, httpx.Response | bytes] | None = None) -> None:
        self.responses = responses or {"DCOILBRENTEU": _fred_csv()}
        self.calls: list[tuple[str, dict[str, str], dict[str, str], float]] = []

    def get(self, url: str, *, params: dict[str, str], headers: dict[str, str], timeout: float) -> httpx.Response:
        self.calls.append((url, params, headers, timeout))
        series_id = params["id"]
        configured = self.responses[series_id]
        if isinstance(configured, httpx.Response):
            return configured
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(
            200,
            content=configured,
            headers={"content-type": "text/csv; charset=utf-8"},
            request=request,
        )


def test_series_config_contains_four_instruments() -> None:
    ids = {item.external_id for item in FRED_ENERGY_SERIES}

    assert ids == {"DCOILBRENTEU", "DCOILWTICO", "DHHNGSP", "GASDESW"}
    assert {item.instrument_code for item in FRED_ENERGY_SERIES} == ids
    assert next(item for item in FRED_ENERGY_SERIES if item.external_id == "GASDESW").frequency == "weekly"


def test_url_generation_works() -> None:
    assert fred_csv_params("DCOILBRENTEU") == {"id": "DCOILBRENTEU"}
    assert fred_csv_url("DCOILBRENTEU") == f"{ENDPOINT}?id=DCOILBRENTEU"


def test_csv_parser_parses_valid_csv_and_skips_missing_values() -> None:
    series = FRED_ENERGY_SERIES[0]

    rows, header_valid, raw_rows_count = parse_fred_csv(_fred_csv(), series=series)

    assert header_valid is True
    assert raw_rows_count == 3
    assert [row.period_start for row in rows] == [date(2026, 5, 20), date(2026, 5, 22)]
    assert rows[0].value == Decimal("63.99")
    assert rows[1].value == Decimal("64.12")
    assert rows[0].observed_at == datetime(2026, 5, 20, tzinfo=timezone.utc)


def test_csv_parser_filters_dates() -> None:
    series = FRED_ENERGY_SERIES[0]

    rows, _, _ = parse_fred_csv(
        _fred_csv(value="65.50"),
        series=series,
        from_date=date(2026, 5, 22),
        to_date=date(2026, 5, 22),
    )

    assert len(rows) == 1
    assert rows[0].period_start == date(2026, 5, 22)
    assert rows[0].value == Decimal("65.50")


def test_parser_reports_empty_and_unknown_formats() -> None:
    series = FRED_ENERGY_SERIES[0]
    empty_rows, empty_checks = assess_fred_csv_response(
        payload=b"",
        content_type="text/csv",
        status_code=200,
        series=series,
    )

    assert empty_rows == []
    assert {check.check_name: check.status for check in empty_checks}["energy_parsed_rows_gt_zero"] == "fail"

    with pytest.raises(FredEnergyParseError):
        parse_fred_csv(b"not,the,right,header\n1,2,3,4\n", series=series)


def test_collector_inserts_energy_prices_with_raw_and_quality_checks(tmp_path: Path) -> None:
    session, cleanup = build_seeded_session()
    client = FakeHttpClient({"DCOILBRENTEU": _fred_csv(value="64.12")})
    try:
        result = FredEnergyPricesCollector(
            series=(FRED_ENERGY_SERIES[0],),
            http_client=client,
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 6, 5, 12, tzinfo=timezone.utc),
        ).run(
            session,
            series_id="DCOILBRENTEU",
            from_date=date(2026, 5, 20),
            to_date=date(2026, 5, 22),
        )
        rows = session.scalars(select(EnergyPrice).order_by(EnergyPrice.period_start)).all()
        raw_response = session.scalar(select(RawResponse))
        run = session.scalar(select(CollectorRun))
        check_names = set(session.scalars(select(DataQualityCheck.check_name)).all())
    finally:
        cleanup()

    assert result.status == "success"
    assert result.series_requested == 1
    assert result.series_success == 1
    assert result.records_found == 2
    assert result.records_written == 2
    assert result.skipped_existing == 0
    assert result.conflicts_count == 0
    assert len(rows) == 2
    assert raw_response is not None
    assert run is not None
    assert all(row.raw_response_id == raw_response.id for row in rows)
    assert all(row.collector_run_id == run.id for row in rows)
    assert rows[0].instrument_code == "DCOILBRENTEU"
    assert rows[0].currency == "USD"
    assert rows[0].unit == "USD/barrel"
    assert rows[0].normalized_value == rows[0].value
    assert rows[0].source_payload_hash == raw_response.sha256
    assert rows[0].metadata_json["fred_series_id"] == "DCOILBRENTEU"
    assert client.calls[0] == (ENDPOINT, fred_csv_params("DCOILBRENTEU"), HEADERS, REQUEST_TIMEOUT)
    assert "energy_raw_response_non_empty" in check_names
    assert "energy_csv_header_valid" in check_names
    assert "energy_value_positive" in check_names


def test_duplicate_retry_skips_existing_rows(tmp_path: Path) -> None:
    session, cleanup = build_seeded_session()
    try:
        collector = FredEnergyPricesCollector(
            series=(FRED_ENERGY_SERIES[0],),
            http_client=FakeHttpClient({"DCOILBRENTEU": _fred_csv(value="64.12")}),
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 6, 5, 12, tzinfo=timezone.utc),
        )
        first = collector.run(session, from_date=date(2026, 5, 20), to_date=date(2026, 5, 22))
        second = collector.run(session, from_date=date(2026, 5, 20), to_date=date(2026, 5, 22))
        rows_count = session.scalar(select(func.count()).select_from(EnergyPrice))
    finally:
        cleanup()

    assert first.records_written == 2
    assert second.records_written == 0
    assert second.skipped_existing == 2
    assert second.conflicts_count == 0
    assert rows_count == 2


def test_changed_existing_value_creates_conflict_warning_without_overwrite(tmp_path: Path) -> None:
    session, cleanup = build_seeded_session()
    try:
        FredEnergyPricesCollector(
            series=(FRED_ENERGY_SERIES[0],),
            http_client=FakeHttpClient({"DCOILBRENTEU": b"observation_date,DCOILBRENTEU\n2026-05-20,64.12\n"}),
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 6, 5, 12, tzinfo=timezone.utc),
        ).run(session, from_date=date(2026, 5, 20), to_date=date(2026, 5, 20))
        second = FredEnergyPricesCollector(
            series=(FRED_ENERGY_SERIES[0],),
            http_client=FakeHttpClient({"DCOILBRENTEU": b"observation_date,DCOILBRENTEU\n2026-05-20,65.00\n"}),
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 6, 5, 12, 5, tzinfo=timezone.utc),
        ).run(session, from_date=date(2026, 5, 20), to_date=date(2026, 5, 20))
        row = session.scalar(select(EnergyPrice))
        warning = session.scalar(
            select(DataQualityCheck).where(DataQualityCheck.check_name == "energy_existing_record_hash_changed")
        )
    finally:
        cleanup()

    assert second.status == "partial_success"
    assert second.records_written == 0
    assert second.conflicts_count == 1
    assert row.value == Decimal("64.12000000")
    assert warning is not None
    assert warning.status == "fail"
    assert warning.severity == "warning"
    assert warning.details_json["incoming_value"] == "65"
    assert warning.details_json["policy_decision"] == "rejected_hash_conflict_no_overwrite"


def test_unknown_series_rejected() -> None:
    collector = FredEnergyPricesCollector(series=(FRED_ENERGY_SERIES[0],))

    with pytest.raises(ValueError, match="unknown FRED energy series"):
        collector.run(series_id="BAD_SERIES")


def test_one_bad_series_does_not_fail_whole_run(tmp_path: Path) -> None:
    session, cleanup = build_seeded_session()
    good, bad = FRED_ENERGY_SERIES[0], FRED_ENERGY_SERIES[1]
    bad_response = httpx.Response(
        500,
        content=b"error",
        headers={"content-type": "text/plain"},
        request=httpx.Request("GET", ENDPOINT, params={"id": bad.external_id}),
    )
    try:
        result = FredEnergyPricesCollector(
            series=(good, bad),
            http_client=FakeHttpClient({good.external_id: _fred_csv(good.external_id), bad.external_id: bad_response}),
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 6, 5, 12, tzinfo=timezone.utc),
        ).run(session, from_date=date(2026, 5, 20), to_date=date(2026, 5, 22))
        rows_count = session.scalar(select(func.count()).select_from(EnergyPrice))
    finally:
        cleanup()

    assert result.status == "partial_success"
    assert result.series_success == 1
    assert result.series_failed == 1
    assert result.errors_count == 1
    assert result.records_written == 2
    assert rows_count == 2


def test_cli_argument_parsing_supports_fred_energy_prices() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "fred_energy_prices",
            "--series",
            "DCOILBRENTEU",
            "--from-date",
            "2026-05-20",
            "--to-date",
            "2026-06-05",
        ]
    )

    assert args.collector_name == "fred_energy_prices"
    assert args.series == "DCOILBRENTEU"
    assert args.from_date == "2026-05-20"
    assert args.to_date == "2026-06-05"


def test_cli_rejects_unknown_fred_series_without_db_access(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_collector.py",
            "fred_energy_prices",
            "--series",
            "BAD_SERIES",
        ],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "LOG_DIR": str(tmp_path / "logs")},
    )

    assert result.returncode != 0
    assert "unknown FRED energy series: BAD_SERIES" in result.stderr


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

