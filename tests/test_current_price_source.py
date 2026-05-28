from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.collectors.prices.current_price_config import CURRENT_PRICE_HEADERS, CURRENT_PRICE_INSTRUMENTS
from app.collectors.prices.current_price_source import (
    CurrentPriceSourceCollector,
    PriceParseError,
    build_source_record_hash,
    parse_price_response,
)
from app.db.models import Base, CollectorRun, DataQualityCheck, PriceObservation
from app.db.seed import seed_database
from app.storage.raw_store import RawStore


def instrument(product_code: str):
    return next(item for item in CURRENT_PRICE_INSTRUMENTS if item.product_code == product_code)


def test_parse_json_response_for_rapeseed_oil() -> None:
    payload = 'var quote_json = {"JO_166042":{"q5":"7654.25"}};'

    assert parse_price_response(instrument("rapeseed_oil"), payload) == Decimal("7654.25")


def test_parse_csv_response_for_soybean_oil() -> None:
    payload = 'var hq_str_JO_165951 = "name,open,high,8123.50,low";'

    assert parse_price_response(instrument("soybean_oil"), payload) == Decimal("8123.50")


def test_parse_csv_response_for_rapeseed_meal() -> None:
    payload = 'var hq_str_JO_166106 = "name,open,high,3210,low";'

    assert parse_price_response(instrument("rapeseed_meal"), payload) == Decimal("3210")


def test_parse_json_response_for_soybean_meal() -> None:
    payload = 'var quote_json = {"JO_165938":{"showName":"豆粕主力","q5":"2977.00"}};'

    assert parse_price_response(instrument("soybean_meal"), payload) == Decimal("2977.00")


def test_current_price_instruments_include_confirmed_soybean_meal_without_removing_existing_products() -> None:
    instruments_by_product = {item.product_code: item for item in CURRENT_PRICE_INSTRUMENTS}

    assert set(instruments_by_product) == {
        "rapeseed_oil",
        "soybean_oil",
        "rapeseed_meal",
        "soybean_meal",
    }
    soybean_meal = instruments_by_product["soybean_meal"]
    assert soybean_meal.external_code == "JO_165938"
    assert soybean_meal.endpoint == "https://api.jijinhao.com/quoteCenter/realTime.htm"
    assert soybean_meal.parser_type == "json"
    assert soybean_meal.price_path == ("JO_165938", "q5")
    assert soybean_meal.params == {"codes": "JO_165938"}


def test_parse_error_missing_response_prefix() -> None:
    with pytest.raises(PriceParseError, match="missing response_prefix"):
        parse_price_response(instrument("rapeseed_oil"), '{"JO_166042":{"q5":"7654.25"}}')


def test_parse_error_missing_price_path() -> None:
    payload = 'var quote_json = {"JO_166042":{"other":"7654.25"}};'

    with pytest.raises(PriceParseError, match="missing price_path"):
        parse_price_response(instrument("rapeseed_oil"), payload)


def test_parse_error_price_index_out_of_range() -> None:
    payload = 'var hq_str_JO_165951 = "name,open";'

    with pytest.raises(PriceParseError, match="price_index out of range"):
        parse_price_response(instrument("soybean_oil"), payload)


def test_source_record_hash_is_stable() -> None:
    observed_at = datetime(2026, 5, 20, 6, 0, tzinfo=timezone.utc)

    first = build_source_record_hash(
        source_code="current_price_source",
        product_code="rapeseed_oil",
        external_code="JO_166042",
        observed_at=observed_at,
        price=Decimal("7654.2500"),
        currency="CNY",
        unit="metric_ton",
    )
    second = build_source_record_hash(
        source_code="current_price_source",
        product_code="rapeseed_oil",
        external_code="JO_166042",
        observed_at=observed_at,
        price=Decimal("7654.25"),
        currency="CNY",
        unit="metric_ton",
    )

    assert first == second


class FakeHttpClient:
    def __init__(self, payload: bytes, *, content_type: str = "text/plain") -> None:
        self.payload = payload
        self.content_type = content_type

    def get(
        self,
        url: str,
        *,
        params: dict[str, str],
        headers: dict[str, str],
        timeout: float,
    ) -> httpx.Response:
        assert headers == CURRENT_PRICE_HEADERS
        request = httpx.Request("GET", url, params=params)
        return httpx.Response(200, content=self.payload, headers={"content-type": self.content_type}, request=request)


def test_collector_idempotency_does_not_insert_duplicate_price_observations(tmp_path: Path) -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)
    fixed_at = datetime(2026, 5, 20, 6, 0, tzinfo=timezone.utc)
    payload = b'var quote_json = {"JO_166042":{"q5":"7654.25"}};'

    with SessionLocal() as session:
        seed_database(session)
        collector = CurrentPriceSourceCollector(
            instruments=(instrument("rapeseed_oil"),),
            http_client=FakeHttpClient(payload),
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: fixed_at,
        )

        first = collector.run(session)
        second = collector.run(session)
        observation_count = session.scalar(select(func.count()).select_from(PriceObservation))

    assert first.records_written == 1
    assert second.records_written == 0
    assert observation_count == 1


def test_manual_run_saves_observed_at_as_fetched_at(tmp_path: Path) -> None:
    session, cleanup = build_seeded_session()
    fixed_at = datetime(2026, 5, 20, 6, 30, tzinfo=timezone.utc)
    try:
        collector = CurrentPriceSourceCollector(
            instruments=(instrument("rapeseed_oil"),),
            http_client=FakeHttpClient(b'var quote_json = {"JO_166042":{"q5":"7654.25"}};'),
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: fixed_at,
        )
        result = collector.run(session, run_type="manual")
        observation = session.scalar(select(PriceObservation))
        run = session.scalar(select(CollectorRun))
    finally:
        cleanup()

    assert result.records_written == 1
    assert as_utc(observation.observed_at) == fixed_at
    assert observation.collection_slot is None
    assert run.run_type == "manual"
    assert run.collection_slot is None


def test_scheduled_run_saves_observed_at_and_collection_slot(tmp_path: Path) -> None:
    session, cleanup = build_seeded_session()
    fetched_at = datetime(2026, 5, 20, 6, 30, tzinfo=timezone.utc)
    collection_slot = datetime(2026, 5, 20, 6, 0, tzinfo=timezone.utc)
    try:
        collector = CurrentPriceSourceCollector(
            instruments=(instrument("rapeseed_oil"),),
            http_client=FakeHttpClient(b'var quote_json = {"JO_166042":{"q5":"7654.25"}};'),
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: fetched_at,
        )
        result = collector.run(session, run_type="scheduled", collection_slot=collection_slot)
        observation = session.scalar(select(PriceObservation))
        run = session.scalar(select(CollectorRun))
    finally:
        cleanup()

    assert result.records_written == 1
    assert as_utc(observation.observed_at) == collection_slot
    assert as_utc(observation.collection_slot) == collection_slot
    assert run.run_type == "scheduled"
    assert as_utc(run.collection_slot) == collection_slot


def test_scheduled_collection_slot_does_not_insert_duplicate_on_retry(tmp_path: Path) -> None:
    session, cleanup = build_seeded_session()
    collection_slot = datetime(2026, 5, 20, 6, 0, tzinfo=timezone.utc)
    payload = b'var quote_json = {"JO_166042":{"q5":"7654.25"}};'
    retry_payload = b'var quote_json = {"JO_166042":{"q5":"7655.00"}};'
    try:
        first = CurrentPriceSourceCollector(
            instruments=(instrument("rapeseed_oil"),),
            http_client=FakeHttpClient(payload),
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 5, 20, 6, 2, tzinfo=timezone.utc),
        ).run(session, run_type="scheduled", collection_slot=collection_slot)
        second = CurrentPriceSourceCollector(
            instruments=(instrument("rapeseed_oil"),),
            http_client=FakeHttpClient(retry_payload),
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 5, 20, 6, 8, tzinfo=timezone.utc),
        ).run(session, run_type="scheduled", collection_slot=collection_slot)
        observation_count = session.scalar(select(func.count()).select_from(PriceObservation))
    finally:
        cleanup()

    assert first.records_written == 1
    assert second.records_written == 0
    assert observation_count == 1


def test_schema_check_catches_missing_prefix(tmp_path: Path) -> None:
    assert_schema_failure(
        tmp_path,
        product_code="rapeseed_oil",
        payload=b'{"JO_166042":{"q5":"7654.25"}}',
        check_name="response_prefix_found",
    )


def test_schema_check_catches_missing_json_key(tmp_path: Path) -> None:
    assert_schema_failure(
        tmp_path,
        product_code="rapeseed_oil",
        payload=b'var quote_json = {"OTHER":{"q5":"7654.25"}};',
        check_name="json_root_contains_external_code",
    )


def test_schema_check_catches_short_csv(tmp_path: Path) -> None:
    assert_schema_failure(
        tmp_path,
        product_code="soybean_oil",
        payload=b'var hq_str_JO_165951 = "name,open";',
        check_name="csv_column_count_gt_price_index",
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


def assert_schema_failure(tmp_path: Path, *, product_code: str, payload: bytes, check_name: str) -> None:
    session, cleanup = build_seeded_session()
    try:
        collector = CurrentPriceSourceCollector(
            instruments=(instrument(product_code),),
            http_client=FakeHttpClient(payload),
            raw_store=RawStore(base_dir=tmp_path / "raw"),
            clock=lambda: datetime(2026, 5, 20, 6, 0, tzinfo=timezone.utc),
        )
        collector.run(session)
        check = session.scalar(
            select(DataQualityCheck).where(
                DataQualityCheck.check_name == check_name,
                DataQualityCheck.status == "fail",
            )
        )
    finally:
        cleanup()

    assert check is not None


def as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
