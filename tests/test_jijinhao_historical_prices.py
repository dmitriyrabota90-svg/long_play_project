from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import httpx
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.collectors.historical.jijinhao_history_config import HEADERS, historys_params
from app.collectors.historical.jijinhao_historical_prices import (
    JijinhaoHistoricalPricesCollector,
    assess_historys_response,
)
from app.db.models import Base, CollectorRun, DataQualityCheck, HistoricalPriceBar, HistoricalPriceBarRevision, RawResponse
from app.db.seed import seed_database
from app.storage.raw_store import RawStore


def _historys_payload(code: str = "JO_165938", *, close: int = 2990) -> bytes:
    timestamp_ms = int(datetime(2026, 5, 25, tzinfo=timezone.utc).timestamp() * 1000)
    payload = {
        "style": 3,
        "data": {
            f"{code}_productName": "豆粕主力",
            f"{code}_unit": "元/吨",
            code: [
                {
                    "q1": 2998,
                    "q2": close,
                    "q3": 2999,
                    "q4": 2984,
                    "q60": 659103,
                    "time": timestamp_ms,
                }
            ],
        },
    }
    return ("var quote_json = " + json.dumps(payload, ensure_ascii=False)).encode()


class FakeHttpClient:
    def __init__(self, payload: bytes = _historys_payload()) -> None:
        self.payload = payload
        self.calls: list[tuple[str, dict[str, str], dict[str, str], float]] = []

    def get(self, url: str, *, params: dict[str, str], headers: dict[str, str], timeout: float) -> httpx.Response:
        self.calls.append((url, params, headers, timeout))
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(200, content=self.payload, headers={"content-type": "text/html;charset=UTF-8"}, request=request)


def test_historys_response_parser_to_bars() -> None:
    rows, checks = assess_historys_response(
        payload=_historys_payload(),
        content_type="text/html;charset=UTF-8",
        status_code=200,
        external_code="JO_165938",
    )

    assert len(rows) == 1
    assert rows[0].bar_date.isoformat() == "2026-05-25"
    assert rows[0].open_price == 2998
    assert rows[0].high_price == 2999
    assert rows[0].low_price == 2984
    assert rows[0].close_price == 2990
    assert rows[0].price == 2990
    assert rows[0].volume == 659103
    assert {check.check_name: check.status for check in checks}["historical_parser_success"] == "pass"


def test_historys_parser_handles_empty_and_unknown_format() -> None:
    empty_rows, empty_checks = assess_historys_response(
        payload=b"",
        content_type="text/html",
        status_code=200,
        external_code="JO_165938",
    )
    bad_rows, bad_checks = assess_historys_response(
        payload=b"var other = {};",
        content_type="text/html",
        status_code=200,
        external_code="JO_165938",
    )

    assert empty_rows == []
    assert {check.check_name: check.status for check in empty_checks}["historical_parser_success"] == "fail"
    assert bad_rows == []
    assert {check.check_name: check.status for check in bad_checks}["historical_parser_success"] == "fail"


def test_collector_inserts_historical_bars_with_raw_and_run_links(tmp_path: Path) -> None:
    session, cleanup = build_seeded_session()
    client = FakeHttpClient()
    try:
        result = JijinhaoHistoricalPricesCollector(
            http_client=client,
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 5, 28, 12, 0, tzinfo=timezone.utc),
        ).run(session, product_code="soybean_meal", days=30)
        bar = session.scalar(select(HistoricalPriceBar))
        raw_response = session.scalar(select(RawResponse))
        run = session.scalar(select(CollectorRun))
    finally:
        cleanup()

    assert result.status == "success"
    assert result.products_processed == 1
    assert result.records_found == 1
    assert result.records_written == 1
    assert result.skipped_existing == 0
    assert result.conflicts_count == 0
    assert bar is not None
    assert raw_response is not None
    assert run is not None
    assert bar.raw_response_id == raw_response.id
    assert bar.collector_run_id == run.id
    assert bar.price == 2990
    assert bar.close_price == 2990
    assert bar.source_payload_hash == raw_response.sha256
    assert client.calls[0][1] == historys_params("JO_165938", 30)
    assert client.calls[0][2] == HEADERS


def test_duplicate_retry_skips_existing_rows(tmp_path: Path) -> None:
    session, cleanup = build_seeded_session()
    try:
        collector = JijinhaoHistoricalPricesCollector(
            http_client=FakeHttpClient(),
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 5, 28, 12, 0, tzinfo=timezone.utc),
        )
        first = collector.run(session, product_code="soybean_meal", days=30)
        second = collector.run(session, product_code="soybean_meal", days=30)
        bars_count = session.scalar(select(func.count()).select_from(HistoricalPriceBar))
    finally:
        cleanup()

    assert first.records_written == 1
    assert second.records_written == 0
    assert second.skipped_existing == 1
    assert bars_count == 1


def test_changed_existing_hash_on_latest_bar_creates_revision_and_updates_main_row(tmp_path: Path) -> None:
    session, cleanup = build_seeded_session()
    try:
        first = JijinhaoHistoricalPricesCollector(
            http_client=FakeHttpClient(_historys_payload(close=2990)),
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 5, 28, 12, 0, tzinfo=timezone.utc),
        ).run(session, product_code="soybean_meal", days=30)
        second = JijinhaoHistoricalPricesCollector(
            http_client=FakeHttpClient(_historys_payload(close=2995)),
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 5, 28, 12, 5, tzinfo=timezone.utc),
        ).run(session, product_code="soybean_meal", days=30)
        bar = session.scalar(select(HistoricalPriceBar))
        revision = session.scalar(select(HistoricalPriceBarRevision))
        update_check = session.scalar(
            select(DataQualityCheck).where(DataQualityCheck.check_name == "historical_latest_bar_updated")
        )
    finally:
        cleanup()

    assert first.records_written == 1
    assert second.records_written == 0
    assert second.updated_existing == 1
    assert second.revisions_written == 1
    assert second.conflicts_count == 0
    assert second.status == "success"
    assert bar.price == 2995
    assert bar.close_price == 2995
    assert revision is not None
    assert revision.revision_reason == "mutable_latest_bar_update"
    assert revision.revision_number == 1
    assert revision.previous_price == Decimal("2990.00000000")
    assert revision.new_price == Decimal("2995.00000000")
    assert "price" in revision.changed_fields
    assert revision.diff_json["price"]["diff_abs"] == "5"
    assert update_check is not None
    assert update_check.status == "pass"
    assert update_check.severity == "warning"
    assert update_check.details_json["policy_decision"] == "updated_latest_bar"
    assert "changed_fields" in update_check.details_json
    assert "diff_json" in update_check.details_json


def test_retry_after_controlled_update_skips_existing_row(tmp_path: Path) -> None:
    session, cleanup = build_seeded_session()
    try:
        collector = JijinhaoHistoricalPricesCollector(
            http_client=FakeHttpClient(_historys_payload(close=2990)),
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 5, 28, 12, 0, tzinfo=timezone.utc),
        )
        collector.run(session, product_code="soybean_meal", days=30)
        JijinhaoHistoricalPricesCollector(
            http_client=FakeHttpClient(_historys_payload(close=2995)),
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 5, 28, 12, 5, tzinfo=timezone.utc),
        ).run(session, product_code="soybean_meal", days=30)
        retry = JijinhaoHistoricalPricesCollector(
            http_client=FakeHttpClient(_historys_payload(close=2995)),
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 5, 28, 12, 10, tzinfo=timezone.utc),
        ).run(session, product_code="soybean_meal", days=30)
        revisions_count = session.scalar(select(func.count()).select_from(HistoricalPriceBarRevision))
    finally:
        cleanup()

    assert retry.records_written == 0
    assert retry.skipped_existing == 1
    assert retry.updated_existing == 0
    assert retry.revisions_written == 0
    assert retry.conflicts_count == 0
    assert revisions_count == 1


def test_changed_existing_hash_on_old_bar_creates_warning_without_update(tmp_path: Path) -> None:
    session, cleanup = build_seeded_session()
    try:
        first = JijinhaoHistoricalPricesCollector(
            http_client=FakeHttpClient(_historys_payload(close=2990)),
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 5, 28, 12, 0, tzinfo=timezone.utc),
        ).run(session, product_code="soybean_meal", days=30)
        existing = session.scalar(select(HistoricalPriceBar))
        session.add(
            HistoricalPriceBar(
                product_id=existing.product_id,
                source_id=existing.source_id,
                raw_response_id=existing.raw_response_id,
                collector_run_id=existing.collector_run_id,
                external_code=existing.external_code,
                endpoint_alias=existing.endpoint_alias,
                bar_date=date(2026, 5, 26),
                bar_timeframe=existing.bar_timeframe,
                open_price=existing.open_price,
                high_price=existing.high_price,
                low_price=existing.low_price,
                close_price=existing.close_price,
                price=existing.price,
                volume=existing.volume,
                currency=existing.currency,
                unit=existing.unit,
                observed_at=datetime(2026, 5, 26, tzinfo=timezone.utc),
                published_at=None,
                fetched_at=existing.fetched_at,
                source_record_hash="f" * 64,
                source_payload_hash=existing.source_payload_hash,
            )
        )
        session.flush()
        second = JijinhaoHistoricalPricesCollector(
            http_client=FakeHttpClient(_historys_payload(close=2995)),
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 5, 28, 12, 5, tzinfo=timezone.utc),
        ).run(session, product_code="soybean_meal", days=30)
        old_bar = session.scalar(select(HistoricalPriceBar).where(HistoricalPriceBar.bar_date == date(2026, 5, 25)))
        revision = session.scalar(
            select(HistoricalPriceBarRevision).where(
                HistoricalPriceBarRevision.revision_reason == "immutable_old_bar_conflict"
            )
        )
        warning = session.scalar(select(DataQualityCheck).where(DataQualityCheck.check_name == "historical_old_bar_hash_changed"))
    finally:
        cleanup()

    assert first.records_written == 1
    assert second.records_written == 0
    assert second.updated_existing == 0
    assert second.conflicts_count == 1
    assert second.revisions_written == 1
    assert second.status == "partial_success"
    assert old_bar.price == 2990
    assert revision is not None
    assert revision.revision_reason == "immutable_old_bar_conflict"
    assert warning is not None
    assert warning.status == "fail"
    assert warning.severity == "warning"
    assert warning.details_json["policy_decision"] == "rejected_old_bar_conflict"
    assert "diff_json" in warning.details_json


def test_quality_checks_are_written(tmp_path: Path) -> None:
    session, cleanup = build_seeded_session()
    try:
        JijinhaoHistoricalPricesCollector(
            http_client=FakeHttpClient(),
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 5, 28, 12, 0, tzinfo=timezone.utc),
        ).run(session, product_code="soybean_meal", days=30)
        check_names = set(session.scalars(select(DataQualityCheck.check_name)).all())
    finally:
        cleanup()

    assert "historical_raw_response_non_empty" in check_names
    assert "historical_parser_success" in check_names
    assert "historical_price_present" in check_names
    assert "historical_ohlc_consistent" in check_names


def test_cli_rejects_kdata_for_production_historical_collector(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_collector.py",
            "jijinhao_historical_prices",
            "--endpoint",
            "kdata",
            "--product-code",
            "soybean_meal",
        ],
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "LOG_DIR": str(tmp_path / "logs")},
    )

    assert result.returncode != 0
    assert "kdata is not supported for production historical collector in Phase 4.6" in result.stderr


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
