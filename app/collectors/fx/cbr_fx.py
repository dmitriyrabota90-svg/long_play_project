from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol
from urllib.parse import urlencode
from xml.etree import ElementTree

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors.base import BaseCollector, CollectorResult
from app.collectors.fx.cbr_fx_config import (
    COLLECTOR_NAME,
    CURRENCIES,
    ENDPOINT,
    HEADERS,
    PARSER_VERSION,
    QUOTE_CURRENCY,
    REQUEST_TIMEOUT,
    SOURCE_CODE,
)
from app.db.models import CollectorRun, DataQualityCheck, FxRate, RawResponse, Source
from app.db.session import session_scope
from app.storage.raw_store import RawStore

logger = logging.getLogger(__name__)


class CbrFxParseError(ValueError):
    """Raised when CBR XML cannot be parsed into expected FX rates."""


class HttpClient(Protocol):
    def get(
        self,
        url: str,
        *,
        params: dict[str, str],
        headers: dict[str, str],
        timeout: float,
    ) -> httpx.Response:
        ...


@dataclass(frozen=True)
class ParsedCbrRate:
    base_currency: str
    quote_currency: str
    rate: Decimal
    observed_at: datetime
    nominal: int


@dataclass(frozen=True)
class ParsedCbrXml:
    observed_at: datetime | None
    rates: dict[str, ParsedCbrRate]
    missing_currencies: list[str]


@dataclass(frozen=True)
class XmlCheck:
    check_name: str
    status: str
    severity: str
    details: dict[str, Any]


class CbrFxCollector(BaseCollector):
    source_code = SOURCE_CODE
    collector_name = COLLECTOR_NAME
    parser_version = PARSER_VERSION

    def __init__(
        self,
        *,
        http_client: HttpClient | None = None,
        raw_store: RawStore | None = None,
        timeout: float = REQUEST_TIMEOUT,
        clock: Any | None = None,
    ) -> None:
        super().__init__()
        self.http_client = http_client or httpx.Client(follow_redirects=True)
        self.raw_store = raw_store or RawStore()
        self.timeout = timeout
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def run(
        self,
        session: Session | None = None,
        *,
        run_type: str = "manual",
        collection_slot: datetime | None = None,
        requested_date: date | None = None,
    ) -> CollectorResult:
        run_type = _normalize_run_type(run_type)
        collection_slot = _to_utc(collection_slot) if collection_slot is not None else None
        if run_type == "scheduled" and collection_slot is None:
            raise ValueError("collection_slot is required for scheduled cbr_fx runs")
        if session is None:
            with session_scope() as scoped_session:
                return self._run_with_session(
                    scoped_session,
                    run_type=run_type,
                    collection_slot=collection_slot,
                    requested_date=requested_date,
                )
        return self._run_with_session(
            session,
            run_type=run_type,
            collection_slot=collection_slot,
            requested_date=requested_date,
        )

    def _run_with_session(
        self,
        session: Session,
        *,
        run_type: str,
        collection_slot: datetime | None,
        requested_date: date | None,
    ) -> CollectorResult:
        started_at = _to_utc(self.clock())
        source = session.scalar(select(Source).where(Source.code == self.source_code))
        collector_run = CollectorRun(
            source_id=source.id if source else None,
            collector_name=self.collector_name,
            started_at=started_at,
            status="running",
            run_type=run_type,
            collection_slot=collection_slot,
        )
        session.add(collector_run)
        session.flush()

        if source is None:
            message = f"source mapping not found: {self.source_code}"
            collector_run.status = "error"
            collector_run.finished_at = _to_utc(self.clock())
            collector_run.error_message = message
            session.flush()
            return _result_from_run(self, collector_run, started_at, errors_count=1)

        errors: list[str] = []
        raw_response_ids: list[int] = []
        records_found = 0
        records_written = 0

        try:
            response = self._fetch(requested_date=requested_date)
            fetched_at = _to_utc(self.clock())
            raw_response = self._save_raw_response(session, source, collector_run, response, fetched_at)
            raw_response_ids.append(raw_response.id)
            parse_result, checks = assess_cbr_xml_response(
                payload=response.content,
                content_type=response.headers.get("content-type"),
                status_code=response.status_code,
                expected_currencies=CURRENCIES,
            )
            _write_xml_checks(
                session,
                source_id=source.id,
                raw_response_id=raw_response.id,
                checks=checks,
                checked_at=fetched_at,
            )

            if response.status_code != 200:
                errors.append(f"HTTP status {response.status_code}")
            elif parse_result is None:
                errors.append("XML parsing failed")
            else:
                for currency in CURRENCIES:
                    parsed_rate = parse_result.rates.get(currency)
                    if parsed_rate is None:
                        errors.append(f"missing currency {currency}")
                        _write_fx_rate_quality_checks(
                            session,
                            source_id=source.id,
                            raw_response_id=raw_response.id,
                            base_currency=currency,
                            quote_currency=QUOTE_CURRENCY,
                            rate=None,
                            observed_at=parse_result.observed_at or fetched_at,
                            checked_at=fetched_at,
                        )
                        continue

                    records_found += 1
                    _write_fx_rate_quality_checks(
                        session,
                        source_id=source.id,
                        raw_response_id=raw_response.id,
                        base_currency=currency,
                        quote_currency=QUOTE_CURRENCY,
                        rate=parsed_rate.rate,
                        observed_at=parsed_rate.observed_at,
                        checked_at=fetched_at,
                    )
                    _write_fx_rate_jump_check(session, source_id=source.id, current_rate=parsed_rate, checked_at=fetched_at)
                    existing = _find_existing_fx_rate(session, source_id=source.id, rate=parsed_rate)
                    if existing is not None:
                        continue
                    session.add(
                        FxRate(
                            source_id=source.id,
                            raw_response_id=raw_response.id,
                            base_currency=parsed_rate.base_currency,
                            quote_currency=parsed_rate.quote_currency,
                            rate=parsed_rate.rate,
                            observed_at=parsed_rate.observed_at,
                            published_at=None,
                        )
                    )
                    records_written += 1
                    session.flush()
        except httpx.TimeoutException as exc:
            errors.append(f"timeout: {exc}")
        except httpx.RequestError as exc:
            errors.append(f"connection error: {exc}")
        except Exception as exc:
            logger.exception("cbr_fx collector failed")
            errors.append(str(exc))

        collector_run.finished_at = _to_utc(self.clock())
        collector_run.records_found = records_found
        collector_run.records_written = records_written
        if records_found == len(CURRENCIES):
            collector_run.status = "success"
        elif records_found > 0:
            collector_run.status = "partial_success"
        else:
            collector_run.status = "error"
        collector_run.error_message = "\n".join(errors) if errors else None
        session.flush()

        return CollectorResult(
            run_id=collector_run.id,
            source_code=self.source_code,
            collector_name=self.collector_name,
            parser_version=self.parser_version,
            started_at=started_at,
            finished_at=collector_run.finished_at,
            status=collector_run.status,
            records_found=records_found,
            records_written=records_written,
            raw_response_ids=raw_response_ids,
            error_message=collector_run.error_message,
            errors_count=len(errors),
        )

    def _fetch(self, *, requested_date: date | None) -> httpx.Response:
        params = _date_params(requested_date)
        return self.http_client.get(ENDPOINT, params=params, headers=HEADERS, timeout=self.timeout)

    def _save_raw_response(
        self,
        session: Session,
        source: Source,
        collector_run: CollectorRun,
        response: httpx.Response,
        fetched_at: datetime,
    ) -> RawResponse:
        content_type = response.headers.get("content-type")
        raw_result = self.raw_store.save_bytes(
            source_code=self.source_code,
            collector_run_id=collector_run.id,
            payload=response.content,
            fetched_at=fetched_at,
            extension="xml",
            content_type=content_type,
        )
        raw_response = RawResponse(
            source_id=source.id,
            collector_run_id=collector_run.id,
            fetched_at=fetched_at,
            url=str(response.url),
            method="GET",
            status_code=response.status_code,
            content_type=content_type,
            storage_path=raw_result.storage_path,
            sha256=raw_result.sha256,
            bytes_size=raw_result.bytes_size,
            parser_version=self.parser_version,
        )
        session.add(raw_response)
        session.flush()
        return raw_response


def parse_cbr_xml(payload: bytes | str, *, expected_currencies: tuple[str, ...] = CURRENCIES) -> ParsedCbrXml:
    text = payload.decode("windows-1251", errors="replace") if isinstance(payload, bytes) else payload
    try:
        root = ElementTree.fromstring(text)
    except ElementTree.ParseError as exc:
        raise CbrFxParseError(f"XML parsing error: {exc}") from exc

    date_value = root.attrib.get("Date")
    if not date_value:
        raise CbrFxParseError("ValCurs Date attribute is missing")
    try:
        observed_date = datetime.strptime(date_value, "%d.%m.%Y").date()
    except ValueError as exc:
        raise CbrFxParseError(f"ValCurs Date cannot be parsed: {date_value!r}") from exc
    observed_at = datetime.combine(observed_date, time.min, tzinfo=timezone.utc)

    rates: dict[str, ParsedCbrRate] = {}
    expected_set = set(expected_currencies)
    for node in root.findall("Valute"):
        char_code = (node.findtext("CharCode") or "").strip().upper()
        if char_code not in expected_set:
            continue
        nominal = _parse_nominal(node.findtext("Nominal"), char_code)
        value = _parse_cbr_decimal(node.findtext("Value"), char_code)
        rates[char_code] = ParsedCbrRate(
            base_currency=char_code,
            quote_currency=QUOTE_CURRENCY,
            rate=value / Decimal(nominal),
            observed_at=observed_at,
            nominal=nominal,
        )

    missing = [currency for currency in expected_currencies if currency not in rates]
    return ParsedCbrXml(observed_at=observed_at, rates=rates, missing_currencies=missing)


def assess_cbr_xml_response(
    *,
    payload: bytes,
    content_type: str | None,
    status_code: int | None,
    expected_currencies: tuple[str, ...] = CURRENCIES,
) -> tuple[ParsedCbrXml | None, list[XmlCheck]]:
    checks: list[XmlCheck] = []
    checks.append(
        XmlCheck(
            check_name="raw_response_non_empty",
            status="pass" if payload else "fail",
            severity="error" if not payload else "info",
            details={"bytes_size": len(payload), "status_code": status_code},
        )
    )
    checks.append(_content_type_check(content_type))

    parse_result: ParsedCbrXml | None = None
    parse_error: str | None = None
    if payload:
        try:
            parse_result = parse_cbr_xml(payload, expected_currencies=expected_currencies)
        except CbrFxParseError as exc:
            parse_error = str(exc)
    else:
        parse_error = "empty response"

    checks.append(
        XmlCheck(
            check_name="xml_parse_success",
            status="pass" if parse_result is not None else "fail",
            severity="error" if parse_result is None else "info",
            details={"error": parse_error},
        )
    )
    checks.append(
        XmlCheck(
            check_name="cbr_valcurs_date_present",
            status="pass" if parse_result is not None and parse_result.observed_at is not None else "fail",
            severity="error" if parse_result is None or parse_result.observed_at is None else "info",
            details={
                "observed_at": parse_result.observed_at.isoformat() if parse_result and parse_result.observed_at else None,
                "error": parse_error,
            },
        )
    )
    for currency in expected_currencies:
        present = parse_result is not None and currency in parse_result.rates
        checks.append(
            XmlCheck(
                check_name=f"currency_present_{currency}",
                status="pass" if present else "fail",
                severity="error" if not present else "info",
                details={"currency": currency},
            )
        )
    return parse_result, checks


def _content_type_check(content_type: str | None) -> XmlCheck:
    if not content_type:
        return XmlCheck(
            check_name="content_type_expected",
            status="skip",
            severity="info",
            details={"content_type": None},
        )
    normalized = content_type.split(";")[0].strip().lower()
    expected = {"application/xml", "text/xml", "application/octet-stream"}
    is_expected = normalized in expected or normalized.endswith("+xml")
    return XmlCheck(
        check_name="content_type_expected",
        status="pass" if is_expected else "fail",
        severity="warning" if not is_expected else "info",
        details={"content_type": content_type},
    )


def _parse_nominal(value: str | None, char_code: str) -> int:
    try:
        nominal = int((value or "").strip())
    except ValueError as exc:
        raise CbrFxParseError(f"{char_code}: nominal cannot be parsed: {value!r}") from exc
    if nominal <= 0:
        raise CbrFxParseError(f"{char_code}: nominal must be positive")
    return nominal


def _parse_cbr_decimal(value: str | None, char_code: str) -> Decimal:
    cleaned = (value or "").strip().replace(" ", "").replace(",", ".")
    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise CbrFxParseError(f"{char_code}: value cannot be parsed: {value!r}") from exc


def _date_params(requested_date: date | None) -> dict[str, str]:
    if requested_date is None:
        return {}
    return {"date_req": requested_date.strftime("%d/%m/%Y")}


def build_cbr_url(requested_date: date | None) -> str:
    params = _date_params(requested_date)
    if not params:
        return ENDPOINT
    return f"{ENDPOINT}?{urlencode(params)}"


def _find_existing_fx_rate(session: Session, *, source_id: int, rate: ParsedCbrRate) -> FxRate | None:
    return session.scalar(
        select(FxRate)
        .where(
            FxRate.source_id == source_id,
            FxRate.base_currency == rate.base_currency,
            FxRate.quote_currency == rate.quote_currency,
            FxRate.observed_at == rate.observed_at,
        )
        .limit(1)
    )


def _write_xml_checks(
    session: Session,
    *,
    source_id: int,
    raw_response_id: int,
    checks: list[XmlCheck],
    checked_at: datetime,
) -> None:
    for check in checks:
        details = dict(check.details)
        details["raw_response_id"] = raw_response_id
        _write_quality_check(
            session,
            source_id=source_id,
            table_name="raw_responses",
            check_name=check.check_name,
            status=check.status,
            severity=check.severity,
            details=details,
            checked_at=checked_at,
        )


def _write_fx_rate_quality_checks(
    session: Session,
    *,
    source_id: int,
    raw_response_id: int | None,
    base_currency: str,
    quote_currency: str,
    rate: Decimal | None,
    observed_at: datetime,
    checked_at: datetime,
) -> None:
    details = {
        "base_currency": base_currency,
        "quote_currency": quote_currency,
        "raw_response_id": raw_response_id,
        "observed_at": observed_at.isoformat(),
    }
    _write_quality_check(
        session,
        source_id=source_id,
        table_name="fx_rates",
        check_name="raw_response_present",
        status="pass" if raw_response_id is not None else "fail",
        severity="error" if raw_response_id is None else "info",
        details=details,
        checked_at=checked_at,
    )
    _write_quality_check(
        session,
        source_id=source_id,
        table_name="fx_rates",
        check_name="fx_rate_is_not_null",
        status="pass" if rate is not None else "fail",
        severity="error" if rate is None else "info",
        details={**details, "rate": _canonical_decimal(rate)},
        checked_at=checked_at,
    )
    _write_quality_check(
        session,
        source_id=source_id,
        table_name="fx_rates",
        check_name="fx_rate_positive",
        status="pass" if rate is not None and rate > 0 else "fail",
        severity="error" if rate is None or rate <= 0 else "info",
        details={**details, "rate": _canonical_decimal(rate)},
        checked_at=checked_at,
    )


def _write_fx_rate_jump_check(
    session: Session,
    *,
    source_id: int,
    current_rate: ParsedCbrRate,
    checked_at: datetime,
) -> None:
    previous = session.scalar(
        select(FxRate)
        .where(
            FxRate.source_id == source_id,
            FxRate.base_currency == current_rate.base_currency,
            FxRate.quote_currency == current_rate.quote_currency,
            FxRate.observed_at < current_rate.observed_at,
        )
        .order_by(FxRate.observed_at.desc())
        .limit(1)
    )
    if previous is None or previous.rate <= 0:
        status = "skip"
        severity = "info"
        jump_ratio = None
    else:
        jump_ratio = abs(current_rate.rate - previous.rate) / previous.rate
        status = "fail" if jump_ratio > Decimal("0.20") else "pass"
        severity = "warning" if status == "fail" else "info"

    _write_quality_check(
        session,
        source_id=source_id,
        table_name="fx_rates",
        check_name="fx_rate_jump_gt_20pct",
        status=status,
        severity=severity,
        details={
            "base_currency": current_rate.base_currency,
            "quote_currency": current_rate.quote_currency,
            "observed_at": current_rate.observed_at.isoformat(),
            "current_rate": _canonical_decimal(current_rate.rate),
            "previous_rate": _canonical_decimal(previous.rate) if previous is not None else None,
            "jump_ratio": _canonical_decimal(jump_ratio),
        },
        checked_at=checked_at,
    )


def _write_quality_check(
    session: Session,
    *,
    source_id: int | None,
    table_name: str,
    check_name: str,
    status: str,
    severity: str,
    details: dict[str, Any],
    checked_at: datetime,
) -> None:
    session.add(
        DataQualityCheck(
            source_id=source_id,
            table_name=table_name,
            check_name=check_name,
            checked_at=checked_at,
            status=status,
            severity=severity,
            details_json=details,
        )
    )


def _result_from_run(
    collector: CbrFxCollector,
    collector_run: CollectorRun,
    started_at: datetime,
    *,
    errors_count: int,
) -> CollectorResult:
    return CollectorResult(
        run_id=collector_run.id,
        source_code=collector.source_code,
        collector_name=collector.collector_name,
        parser_version=collector.parser_version,
        started_at=started_at,
        finished_at=collector_run.finished_at or _to_utc(datetime.now(timezone.utc)),
        status=collector_run.status,
        records_found=collector_run.records_found,
        records_written=collector_run.records_written,
        error_message=collector_run.error_message,
        errors_count=errors_count,
    )


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _normalize_run_type(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"manual", "scheduled"}:
        raise ValueError("run_type must be either 'manual' or 'scheduled'")
    return normalized


def _canonical_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.normalize(), "f")
