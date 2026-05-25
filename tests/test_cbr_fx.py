from __future__ import annotations

import subprocess
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import httpx
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.collectors.fx.cbr_fx import CbrFxCollector, CbrFxParseError, _date_range, assess_cbr_xml_response, parse_cbr_xml
from app.db.models import Base, CollectorRun, DataQualityCheck, FxRate, RawResponse, Source
from app.storage.raw_store import RawStore


CBR_XML = b'''<?xml version="1.0" encoding="windows-1251"?>
<ValCurs Date="25.05.2026" name="Foreign Currency Market">
  <Valute ID="R01235"><NumCode>840</NumCode><CharCode>USD</CharCode><Nominal>1</Nominal><Name>US Dollar</Name><Value>91,1234</Value></Valute>
  <Valute ID="R01239"><NumCode>978</NumCode><CharCode>EUR</CharCode><Nominal>1</Nominal><Name>Euro</Name><Value>99,5000</Value></Valute>
  <Valute ID="R01375"><NumCode>156</NumCode><CharCode>CNY</CharCode><Nominal>10</Nominal><Name>Yuan</Name><Value>125,0000</Value></Valute>
</ValCurs>
'''

MISSING_CNY_XML = b'''<?xml version="1.0" encoding="windows-1251"?>
<ValCurs Date="25.05.2026" name="Foreign Currency Market">
  <Valute ID="R01235"><CharCode>USD</CharCode><Nominal>1</Nominal><Value>91,1234</Value></Valute>
  <Valute ID="R01239"><CharCode>EUR</CharCode><Nominal>1</Nominal><Value>99,5000</Value></Valute>
</ValCurs>
'''


def cbr_xml_for(day: date, *, usd: str = "91,1234", eur: str = "99,5000", cny: str = "125,0000") -> bytes:
    return f'''<?xml version="1.0" encoding="windows-1251"?>
<ValCurs Date="{day:%d.%m.%Y}" name="Foreign Currency Market">
  <Valute ID="R01235"><CharCode>USD</CharCode><Nominal>1</Nominal><Value>{usd}</Value></Valute>
  <Valute ID="R01239"><CharCode>EUR</CharCode><Nominal>1</Nominal><Value>{eur}</Value></Valute>
  <Valute ID="R01375"><CharCode>CNY</CharCode><Nominal>10</Nominal><Value>{cny}</Value></Valute>
</ValCurs>
'''.encode("windows-1251")


class FakeHttpClient:
    def __init__(
        self,
        payload: bytes = CBR_XML,
        status_code: int = 200,
        content_type: str = "application/xml",
        responses_by_date: dict[str, tuple[bytes, int]] | None = None,
    ) -> None:
        self.payload = payload
        self.status_code = status_code
        self.content_type = content_type
        self.responses_by_date = responses_by_date or {}
        self.calls: list[dict[str, object]] = []

    def get(self, url: str, *, params: dict[str, str], headers: dict[str, str], timeout: float) -> httpx.Response:
        self.calls.append({"url": url, "params": params, "headers": headers, "timeout": timeout})
        request_url = url
        payload = self.payload
        status_code = self.status_code
        if params:
            date_req = params["date_req"]
            request_url = f"{url}?date_req={date_req}"
            if date_req in self.responses_by_date:
                payload, status_code = self.responses_by_date[date_req]
        return httpx.Response(
            status_code,
            content=payload,
            headers={"content-type": self.content_type},
            request=httpx.Request("GET", request_url),
        )


def _session_factory():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def _seed_cbr_source(session) -> Source:
    source = Source(code="cbr_fx", name="Central Bank of Russia FX", source_type="fx", base_url="https://www.cbr.ru/")
    session.add(source)
    session.flush()
    return source


def test_parse_cbr_xml_uses_nominal_and_comma_decimal() -> None:
    parsed = parse_cbr_xml(CBR_XML)

    assert parsed.observed_at == datetime(2026, 5, 25, tzinfo=timezone.utc)
    assert parsed.rates["USD"].rate == Decimal("91.1234")
    assert parsed.rates["EUR"].rate == Decimal("99.5000")
    assert parsed.rates["CNY"].rate == Decimal("12.5000")
    assert parsed.missing_currencies == []


def test_missing_currency_creates_problem_check() -> None:
    parsed, checks = assess_cbr_xml_response(
        payload=MISSING_CNY_XML,
        content_type="application/xml",
        status_code=200,
    )

    assert parsed is not None
    assert parsed.missing_currencies == ["CNY"]
    cny_check = next(check for check in checks if check.check_name == "currency_present_CNY")
    assert cny_check.status == "fail"
    assert cny_check.severity == "error"


def test_invalid_xml_fails_parse_check() -> None:
    parsed, checks = assess_cbr_xml_response(payload=b"<ValCurs>", content_type="application/xml", status_code=200)

    assert parsed is None
    assert next(check for check in checks if check.check_name == "xml_parse_success").status == "fail"


def test_parse_cbr_xml_raises_on_missing_date() -> None:
    try:
        parse_cbr_xml(b"<ValCurs></ValCurs>")
    except CbrFxParseError as exc:
        assert "Date" in str(exc)
    else:
        raise AssertionError("expected CbrFxParseError")


def test_cbr_fx_collector_writes_rates_and_raw_response(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    http_client = FakeHttpClient()
    with SessionLocal() as session:
        _seed_cbr_source(session)
        collector = CbrFxCollector(
            http_client=http_client,
            raw_store=RawStore(tmp_path / "raw"),
            clock=lambda: datetime(2026, 5, 25, 7, 0, tzinfo=timezone.utc),
        )

        result = collector.run(session=session, requested_date=date(2026, 5, 25))
        session.commit()

        rates = session.scalars(select(FxRate).order_by(FxRate.base_currency)).all()
        raw_count = session.scalar(select(func.count()).select_from(RawResponse))
        run = session.scalar(select(CollectorRun))

    assert result.status == "success"
    assert result.records_found == 3
    assert result.records_written == 3
    assert [(rate.base_currency, rate.quote_currency) for rate in rates] == [("CNY", "RUB"), ("EUR", "RUB"), ("USD", "RUB")]
    assert {rate.base_currency: rate.rate for rate in rates}["CNY"] == Decimal("12.50000000")
    assert raw_count == 1
    assert run.collector_name == "cbr_fx_collector"
    assert http_client.calls[0]["params"] == {"date_req": "25/05/2026"}


def test_cbr_fx_collector_is_idempotent_for_same_observed_date(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_cbr_source(session)
        collector = CbrFxCollector(
            http_client=FakeHttpClient(),
            raw_store=RawStore(tmp_path / "raw"),
            clock=lambda: datetime(2026, 5, 25, 7, 0, tzinfo=timezone.utc),
        )

        first = collector.run(session=session, requested_date=date(2026, 5, 25))
        second = collector.run(session=session, requested_date=date(2026, 5, 25))
        session.commit()

        rate_count = session.scalar(select(func.count()).select_from(FxRate))

    assert first.records_written == 3
    assert second.status == "success"
    assert second.records_found == 3
    assert second.records_written == 0
    assert second.skipped_existing == 3
    assert rate_count == 3


def test_date_range_is_inclusive() -> None:
    assert _date_range(date(2026, 5, 20), date(2026, 5, 22)) == [
        date(2026, 5, 20),
        date(2026, 5, 21),
        date(2026, 5, 22),
    ]


def test_cbr_fx_backfill_writes_inclusive_range_without_duplicates(tmp_path: Path) -> None:
    responses = {
        "20/05/2026": (cbr_xml_for(date(2026, 5, 20), usd="90,0000", eur="98,0000", cny="120,0000"), 200),
        "21/05/2026": (cbr_xml_for(date(2026, 5, 21), usd="91,0000", eur="99,0000", cny="121,0000"), 200),
    }
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_cbr_source(session)
        collector = CbrFxCollector(
            http_client=FakeHttpClient(responses_by_date=responses),
            raw_store=RawStore(tmp_path / "raw"),
            clock=lambda: datetime(2026, 5, 25, 7, 0, tzinfo=timezone.utc),
        )

        first = collector.run_backfill(session=session, from_date=date(2026, 5, 20), to_date=date(2026, 5, 21))
        second = collector.run_backfill(session=session, from_date=date(2026, 5, 20), to_date=date(2026, 5, 21))
        session.commit()

        rate_count = session.scalar(select(func.count()).select_from(FxRate))
        runs = session.scalars(select(CollectorRun).order_by(CollectorRun.id)).all()

    assert first.status == "success"
    assert first.dates_requested == 2
    assert first.dates_success == 2
    assert first.records_found == 6
    assert first.records_written == 6
    assert first.skipped_existing == 0
    assert second.status == "success"
    assert second.records_written == 0
    assert second.skipped_existing == 6
    assert rate_count == 6
    assert [run.run_type for run in runs] == ["backfill", "backfill"]


def test_cbr_fx_backfill_one_date_error_does_not_fail_range(tmp_path: Path) -> None:
    responses = {
        "20/05/2026": (cbr_xml_for(date(2026, 5, 20)), 200),
        "21/05/2026": (b"not xml", 200),
        "22/05/2026": (cbr_xml_for(date(2026, 5, 22)), 200),
    }
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_cbr_source(session)
        collector = CbrFxCollector(
            http_client=FakeHttpClient(responses_by_date=responses),
            raw_store=RawStore(tmp_path / "raw"),
            clock=lambda: datetime(2026, 5, 25, 7, 0, tzinfo=timezone.utc),
        )

        result = collector.run_backfill(session=session, from_date=date(2026, 5, 20), to_date=date(2026, 5, 22))
        session.commit()

        rate_count = session.scalar(select(func.count()).select_from(FxRate))

    assert result.status == "partial_success"
    assert result.dates_requested == 3
    assert result.dates_success == 2
    assert result.dates_failed == 1
    assert result.records_found == 6
    assert result.records_written == 6
    assert result.errors_count == 1
    assert "2026-05-21: XML parsing failed" in result.error_message
    assert rate_count == 6


def test_cbr_fx_manual_date_still_works(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    http_client = FakeHttpClient()
    with SessionLocal() as session:
        _seed_cbr_source(session)
        collector = CbrFxCollector(
            http_client=http_client,
            raw_store=RawStore(tmp_path / "raw"),
            clock=lambda: datetime(2026, 5, 25, 7, 0, tzinfo=timezone.utc),
        )

        result = collector.run(session=session, requested_date=date(2026, 5, 25))
        session.commit()

    assert result.status == "success"
    assert result.observed_at_values == ["2026-05-25T00:00:00+00:00"]
    assert result.currency_pairs == ["CNY/RUB", "EUR/RUB", "USD/RUB"]
    assert http_client.calls[0]["params"] == {"date_req": "25/05/2026"}


def test_cbr_fx_default_manual_run_still_works(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    http_client = FakeHttpClient()
    with SessionLocal() as session:
        _seed_cbr_source(session)
        collector = CbrFxCollector(
            http_client=http_client,
            raw_store=RawStore(tmp_path / "raw"),
            clock=lambda: datetime(2026, 5, 25, 7, 0, tzinfo=timezone.utc),
        )

        result = collector.run(session=session)
        session.commit()

    assert result.status == "success"
    assert http_client.calls[0]["params"] == {}


def test_cbr_fx_missing_currency_is_partial_success(tmp_path: Path) -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _seed_cbr_source(session)
        collector = CbrFxCollector(
            http_client=FakeHttpClient(payload=MISSING_CNY_XML),
            raw_store=RawStore(tmp_path / "raw"),
            clock=lambda: datetime(2026, 5, 25, 7, 0, tzinfo=timezone.utc),
        )

        result = collector.run(session=session, requested_date=date(2026, 5, 25))
        session.commit()

        problematic = session.scalars(select(DataQualityCheck).where(DataQualityCheck.status == "fail")).all()

    assert result.status == "partial_success"
    assert result.records_found == 2
    assert "missing currency CNY" in result.error_message
    assert any(check.check_name == "currency_present_CNY" for check in problematic)


def test_run_collector_help_lists_cbr_fx() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/run_collector.py", "--help"],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "cbr_fx" in result.stdout
    assert "--from-date" in result.stdout
    assert "--to-date" in result.stdout
