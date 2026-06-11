from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.collectors.trade.un_comtrade import (
    UnComtradeCollector,
    UnComtradeParseError,
    assess_un_comtrade_response,
    build_trade_source_record_hash,
    build_un_comtrade_params,
    build_un_comtrade_request,
    parse_un_comtrade_rows,
    validate_period_range,
)
from app.collectors.trade.un_comtrade_config import (
    ENDPOINT,
    FLOW_CODE_BY_DIRECTION,
    HEADERS,
    MAX_MONTHS_PER_RUN,
    REQUEST_TIMEOUT,
    SOURCE_CODE,
    SUPPORTED_HS_CODES,
)
from app.db.models import Base, CollectorRun, DataQualityCheck, RawResponse, TradeFlow
from app.db.seed import seed_database
from app.monitoring.operational_report import build_operational_report
from app.storage.raw_store import RawStore
from scripts.run_collector import build_parser


class FakeComtradeClient:
    def __init__(self, payload: bytes | None = None, status_code: int = 200) -> None:
        self.payload = payload if payload is not None else comtrade_json()
        self.status_code = status_code
        self.calls: list[tuple[str, dict[str, str], dict[str, str], float]] = []

    def get(self, url: str, *, params: dict[str, str], headers: dict[str, str], timeout: float) -> httpx.Response:
        self.calls.append((url, params, headers, timeout))
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(
            self.status_code,
            content=self.payload,
            headers={"content-type": "application/json; charset=utf-8"},
            request=request,
        )


def comtrade_json(*, trade_value: str = "125000.50", include_malformed: bool = False) -> bytes:
    rows: list[dict[str, Any]] = [
        {
            "id": "1507-BRA-WLD-X-202401",
            "cmdCode": "1507",
            "cmdDesc": "Soya-bean oil and its fractions",
            "period": "202401",
            "reporterCode": "76",
            "reporterISO": "BRA",
            "reporterDesc": "Brazil",
            "partnerCode": "0",
            "partnerISO": "WLD",
            "partnerDesc": "World",
            "flowCode": "X",
            "flowDesc": "Export",
            "qty": "1000",
            "qtyUnitAbbr": "t",
            "primaryValue": trade_value,
            "netWgt": "1000000",
            "grossWgt": "1000100",
        },
        {
            "id": "1507-BRA-WLD-X-202402",
            "cmdCode": "1507",
            "period": "202402",
            "reporterDesc": "Brazil",
            "partnerDesc": "World",
            "qty": None,
            "primaryValue": "130000",
            "netWgt": None,
        },
    ]
    if include_malformed:
        rows.append({"period": "bad", "primaryValue": "1"})
    return json.dumps({"data": rows}, separators=(",", ":")).encode("utf-8")


def test_un_comtrade_config_contains_controlled_defaults() -> None:
    assert SOURCE_CODE == "un_comtrade"
    assert ENDPOINT == "https://comtradeapi.un.org/data/v1/get/C/M/HS"
    assert REQUEST_TIMEOUT > 0
    assert MAX_MONTHS_PER_RUN == 3
    assert {"1201", "1507", "2304", "1205", "1514", "2306"} == set(SUPPORTED_HS_CODES)
    assert FLOW_CODE_BY_DIRECTION["export"] == "X"
    assert FLOW_CODE_BY_DIRECTION["import"] == "M"
    assert "commodity-dataset-builder" in HEADERS["User-Agent"]


def test_request_params_include_hs_period_reporter_partner_flow_and_limit() -> None:
    request = build_un_comtrade_request(
        hs_code="1507",
        from_period="2024-01",
        to_period="2024-03",
        reporter="BRA",
        partner="WLD",
        flow="export",
        maxrecords=100,
    )
    params = build_un_comtrade_params(request)

    assert params["cmdCode"] == "1507"
    assert params["period"] == "202401,202402,202403"
    assert params["reporterCode"] == "76"
    assert params["partnerCode"] == "0"
    assert params["flowCode"] == "X"
    assert params["maxRecords"] == "100"
    assert params["format"] == "json"


def test_parser_handles_fixture_json_and_missing_optional_fields() -> None:
    request = _request()
    rows, malformed, rows_array_present, raw_rows_count = parse_un_comtrade_rows(
        comtrade_json(),
        request=request,
        fetched_at=datetime(2026, 6, 11, 12, tzinfo=timezone.utc),
    )

    assert rows_array_present is True
    assert raw_rows_count == 2
    assert malformed == []
    assert rows[0].trade_period == "2024-01"
    assert rows[0].period_start == date(2024, 1, 1)
    assert rows[0].period_end == date(2024, 1, 31)
    assert rows[0].reporter_code == "BRA"
    assert rows[0].partner_code == "WLD"
    assert rows[0].flow_direction == "export"
    assert rows[0].quantity == Decimal("1000")
    assert rows[0].trade_value_usd == Decimal("125000.50")
    assert rows[0].unit_value_usd == Decimal("125.0005")
    assert rows[1].quantity is None
    assert rows[1].trade_value_usd == Decimal("130000")
    assert build_trade_source_record_hash(source_code=SOURCE_CODE, hs_code="1507", row=rows[0])


def test_parser_reports_empty_and_unknown_formats() -> None:
    request = _request()
    rows, malformed, checks = assess_un_comtrade_response(
        payload=b"",
        content_type="application/json",
        status_code=200,
        request=request,
        fetched_at=datetime(2026, 6, 11, 12, tzinfo=timezone.utc),
    )

    assert rows == []
    assert malformed == []
    assert {check.check_name: check.status for check in checks}["trade_rows_present"] == "fail"
    with pytest.raises(UnComtradeParseError):
        parse_un_comtrade_rows(b'{"not_data":[]}', request=request, fetched_at=datetime.now(timezone.utc))


def test_validation_rejects_bad_hs_period_flow_and_range() -> None:
    validate_period_range(from_period="2024-01", to_period="2024-03")
    with pytest.raises(ValueError, match="unsupported HS code"):
        build_un_comtrade_request(
            hs_code="9999",
            from_period="2024-01",
            to_period="2024-01",
            reporter="BRA",
            partner="WLD",
            flow="export",
            maxrecords=100,
        )
    with pytest.raises(ValueError, match="from_period"):
        validate_period_range(from_period="2024-02", to_period="2024-01")
    with pytest.raises(ValueError, match="max allowed months"):
        validate_period_range(from_period="2024-01", to_period="2024-04")
    with pytest.raises(ValueError, match="unsupported flow"):
        build_un_comtrade_request(
            hs_code="1507",
            from_period="2024-01",
            to_period="2024-01",
            reporter="BRA",
            partner="WLD",
            flow="transit",
            maxrecords=100,
        )
    with pytest.raises(ValueError, match="WLD/world is not supported as reporter"):
        build_un_comtrade_request(
            hs_code="1507",
            from_period="2024-01",
            to_period="2024-01",
            reporter="WLD",
            partner="BRA",
            flow="export",
            maxrecords=100,
        )


def test_collector_inserts_trade_flows_with_raw_and_quality_checks(tmp_path: Path) -> None:
    session, cleanup = build_seeded_session()
    client = FakeComtradeClient()
    try:
        result = UnComtradeCollector(
            http_client=client,
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 6, 11, 12, tzinfo=timezone.utc),
        ).run(
            session,
            hs_code="1507",
            from_period="2024-01",
            to_period="2024-02",
            reporter="BRA",
            partner="WLD",
            flow="export",
            maxrecords=100,
        )
        rows = session.scalars(select(TradeFlow).order_by(TradeFlow.period_start)).all()
        raw_response = session.scalar(select(RawResponse))
        run = session.scalar(select(CollectorRun))
        check_names = set(session.scalars(select(DataQualityCheck.check_name)).all())
    finally:
        cleanup()

    assert result.status == "success"
    assert result.hs_code == "1507"
    assert result.reporter == "BRA"
    assert result.partner == "WLD"
    assert result.records_found == 2
    assert result.records_written == 2
    assert result.skipped_existing == 0
    assert result.conflicts_count == 0
    assert len(rows) == 2
    assert raw_response is not None
    assert run is not None
    assert all(row.raw_response_id == raw_response.id for row in rows)
    assert all(row.collector_run_id == run.id for row in rows)
    assert rows[0].trade_value_usd == Decimal("125000.50000000")
    assert rows[0].quantity == Decimal("1000.00000000")
    assert rows[0].source_payload_hash == raw_response.sha256
    assert rows[0].metadata_json["request_params"]["cmdCode"] == "1507"
    assert client.calls[0][0] == ENDPOINT
    assert client.calls[0][1]["reporterCode"] == "76"
    assert client.calls[0][2] == HEADERS
    assert client.calls[0][3] == REQUEST_TIMEOUT
    assert "trade_raw_response_non_empty" in check_names
    assert "trade_hs_code_found" in check_names
    assert "trade_raw_linkage_present" in check_names


def test_duplicate_retry_skips_existing_trade_flows(tmp_path: Path) -> None:
    session, cleanup = build_seeded_session()
    try:
        collector = UnComtradeCollector(
            http_client=FakeComtradeClient(),
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 6, 11, 12, tzinfo=timezone.utc),
        )
        first = collector.run(session, hs_code="1507", from_period="2024-01", to_period="2024-02", reporter="BRA", partner="WLD")
        second = collector.run(session, hs_code="1507", from_period="2024-01", to_period="2024-02", reporter="BRA", partner="WLD")
        rows_count = session.scalar(select(func.count()).select_from(TradeFlow))
    finally:
        cleanup()

    assert first.records_written == 2
    assert second.records_written == 0
    assert second.skipped_existing == 2
    assert second.conflicts_count == 0
    assert rows_count == 2


def test_changed_existing_flow_creates_conflict_warning_without_overwrite(tmp_path: Path) -> None:
    session, cleanup = build_seeded_session()
    try:
        UnComtradeCollector(
            http_client=FakeComtradeClient(comtrade_json(trade_value="125000.50")),
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 6, 11, 12, tzinfo=timezone.utc),
        ).run(session, hs_code="1507", from_period="2024-01", to_period="2024-02", reporter="BRA", partner="WLD")
        second = UnComtradeCollector(
            http_client=FakeComtradeClient(comtrade_json(trade_value="126000.50")),
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 6, 11, 12, 5, tzinfo=timezone.utc),
        ).run(session, hs_code="1507", from_period="2024-01", to_period="2024-02", reporter="BRA", partner="WLD")
        first_row = session.scalar(select(TradeFlow).where(TradeFlow.period_start == date(2024, 1, 1)))
        warning = session.scalar(select(DataQualityCheck).where(DataQualityCheck.check_name == "trade_existing_flow_hash_changed"))
    finally:
        cleanup()

    assert second.records_written == 0
    assert second.skipped_existing == 1
    assert second.conflicts_count == 1
    assert second.status == "partial_success"
    assert first_row.trade_value_usd == Decimal("125000.50000000")
    assert warning is not None
    assert warning.status == "fail"
    assert warning.severity == "warning"
    assert "trade_value_usd" in warning.details_json["changed_fields"]
    assert warning.details_json["policy_decision"] == "rejected_hash_conflict_no_overwrite"


def test_malformed_row_is_skipped_without_failing_entire_run(tmp_path: Path) -> None:
    session, cleanup = build_seeded_session()
    try:
        result = UnComtradeCollector(
            http_client=FakeComtradeClient(comtrade_json(include_malformed=True)),
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 6, 11, 12, tzinfo=timezone.utc),
        ).run(session, hs_code="1507", from_period="2024-01", to_period="2024-02", reporter="BRA", partner="WLD")
        rows_count = session.scalar(select(func.count()).select_from(TradeFlow))
        malformed_check = session.scalar(select(DataQualityCheck).where(DataQualityCheck.check_name == "trade_malformed_row_skipped"))
    finally:
        cleanup()

    assert result.status == "success"
    assert result.records_written == 2
    assert result.skipped_malformed == 1
    assert rows_count == 2
    assert malformed_check is not None
    assert malformed_check.severity == "warning"


def test_cli_argument_parsing_supports_un_comtrade() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "un_comtrade",
            "--hs-code",
            "1507",
            "--from-period",
            "2024-01",
            "--to-period",
            "2024-03",
            "--reporter",
            "BRA",
            "--partner",
            "WLD",
            "--flow",
            "export",
            "--maxrecords",
            "100",
        ]
    )

    assert args.collector_name == "un_comtrade"
    assert args.hs_code == "1507"
    assert args.from_period == "2024-01"
    assert args.to_period == "2024-03"
    assert args.reporter == "BRA"
    assert args.partner == "WLD"
    assert args.flow == "export"
    assert args.maxrecords == 100


def test_cli_rejects_missing_un_comtrade_required_args_without_db_access(tmp_path: Path) -> None:
    result = subprocess.run(
        [sys.executable, "scripts/run_collector.py", "un_comtrade", "--hs-code", "1507"],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "LOG_DIR": str(tmp_path / "logs")},
    )

    assert result.returncode != 0
    assert "--from-period" in result.stderr
    assert "--reporter" in result.stderr


def test_operational_report_sees_trade_flows(tmp_path: Path) -> None:
    session, cleanup = build_seeded_session()
    try:
        UnComtradeCollector(
            http_client=FakeComtradeClient(),
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 6, 11, 12, tzinfo=timezone.utc),
        ).run(session, hs_code="1507", from_period="2024-01", to_period="2024-02", reporter="BRA", partner="WLD")
        report = build_operational_report(session=session)
    finally:
        cleanup()

    assert report["trade_flows"]["count"] == 2
    assert report["trade_flows"]["commodities_count"] == 1
    assert report["trade_flows"]["reporters_count"] == 1
    assert report["trade_flows"]["partners_count"] == 1
    assert report["trade_flows"]["first_period_start"] == "2024-01-01"
    assert report["trade_flows"]["last_period_start"] == "2024-02-01"
    assert report["trade_flows"]["last_fetched_at"] == "2026-06-11T12:00:00+00:00"


def _request():
    return build_un_comtrade_request(
        hs_code="1507",
        from_period="2024-01",
        to_period="2024-02",
        reporter="BRA",
        partner="WLD",
        flow="export",
        maxrecords=100,
    )


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

