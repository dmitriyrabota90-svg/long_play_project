from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors.base import BaseCollector, CollectorResult
from app.collectors.prices.current_price_config import (
    CURRENT_PRICE_HEADERS,
    CURRENT_PRICE_INSTRUMENTS,
    CurrentPriceInstrument,
)
from app.db.models import (
    CollectorRun,
    DataQualityCheck,
    PriceObservation,
    Product,
    RawResponse,
    Source,
)
from app.db.session import session_scope
from app.storage.hashes import stable_json_hash
from app.storage.raw_store import RawStore

logger = logging.getLogger(__name__)


class PriceParseError(ValueError):
    """Raised when a current-price response cannot be parsed."""


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
class InstrumentResult:
    records_found: int = 0
    records_written: int = 0
    error: str | None = None


@dataclass(frozen=True)
class SchemaCheck:
    check_name: str
    status: str
    severity: str
    details: dict[str, Any]


class CurrentPriceSourceCollector(BaseCollector):
    source_code = "current_price_source"
    collector_name = "current_price_source_collector"
    parser_version = "current_price_source_v1"

    def __init__(
        self,
        *,
        instruments: tuple[CurrentPriceInstrument, ...] = CURRENT_PRICE_INSTRUMENTS,
        http_client: HttpClient | None = None,
        raw_store: RawStore | None = None,
        timeout: float = 20.0,
        clock: Any | None = None,
    ) -> None:
        super().__init__()
        self.instruments = instruments
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
    ) -> CollectorResult:
        run_type = _normalize_run_type(run_type)
        collection_slot = _to_utc(collection_slot) if collection_slot is not None else None
        if run_type == "scheduled" and collection_slot is None:
            raise ValueError("collection_slot is required for scheduled current_price_source runs")
        if session is None:
            with session_scope() as scoped_session:
                return self._run_with_session(scoped_session, run_type=run_type, collection_slot=collection_slot)
        return self._run_with_session(session, run_type=run_type, collection_slot=collection_slot)

    def _run_with_session(
        self,
        session: Session,
        *,
        run_type: str,
        collection_slot: datetime | None,
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
            logger.error(message)
            return _result_from_run(self, collector_run, started_at, errors_count=1)

        errors: list[str] = []
        records_found = 0
        records_written = 0
        raw_response_ids: list[int] = []

        for instrument in self.instruments:
            result = self._collect_instrument(
                session,
                source,
                collector_run,
                instrument,
                raw_response_ids,
                run_type=run_type,
                collection_slot=collection_slot,
            )
            records_found += result.records_found
            records_written += result.records_written
            if result.error:
                errors.append(result.error)

        collector_run.finished_at = _to_utc(self.clock())
        collector_run.records_found = records_found
        collector_run.records_written = records_written
        if not errors and records_found == len(self.instruments):
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

    def _collect_instrument(
        self,
        session: Session,
        source: Source,
        collector_run: CollectorRun,
        instrument: CurrentPriceInstrument,
        raw_response_ids: list[int],
        run_type: str,
        collection_slot: datetime | None,
    ) -> InstrumentResult:
        product = session.scalar(select(Product).where(Product.code == instrument.product_code))
        if product is None:
            _write_quality_check(
                session,
                source_id=source.id,
                table_name="price_observations",
                check_name="product_mapping_found",
                status="fail",
                severity="error",
                details={
                    "product_code": instrument.product_code,
                    "external_code": instrument.external_code,
                },
                checked_at=_to_utc(self.clock()),
            )
            message = f"product mapping not found: {instrument.product_code}"
            logger.error(message)
            return InstrumentResult(error=message)
        _write_quality_check(
            session,
            source_id=source.id,
            table_name="products",
            check_name="product_mapping_found",
            status="pass",
            severity="info",
            details={"product_code": instrument.product_code, "product_id": product.id},
            checked_at=_to_utc(self.clock()),
        )

        try:
            response = self.http_client.get(
                instrument.endpoint,
                params=instrument.params,
                headers=CURRENT_PRICE_HEADERS,
                timeout=self.timeout,
            )
            fetched_at = _to_utc(self.clock())
        except httpx.TimeoutException as exc:
            _write_price_quality_checks(
                session,
                source_id=source.id,
                product_id=product.id,
                raw_response_id=None,
                price=None,
                checked_at=_to_utc(self.clock()),
            )
            return self._instrument_error(instrument, "timeout", exc)
        except httpx.RequestError as exc:
            _write_price_quality_checks(
                session,
                source_id=source.id,
                product_id=product.id,
                raw_response_id=None,
                price=None,
                checked_at=_to_utc(self.clock()),
            )
            return self._instrument_error(instrument, "connection error", exc)

        raw_response = self._save_raw_response(session, source, collector_run, instrument, response, fetched_at)
        raw_response_ids.append(raw_response.id)
        observed_at = collection_slot if run_type == "scheduled" else fetched_at

        _write_schema_checks(
            session,
            source_id=source.id,
            raw_response_id=raw_response.id,
            instrument=instrument,
            checks=assess_response_schema(
                instrument=instrument,
                payload=response.content,
                content_type=response.headers.get("content-type"),
                previous_sizes=_previous_raw_response_sizes(session, source.id, instrument.external_code, raw_response.id),
            ),
            checked_at=fetched_at,
        )

        if response.status_code != 200:
            _write_price_quality_checks(
                session,
                source_id=source.id,
                product_id=product.id,
                raw_response_id=raw_response.id,
                price=None,
                checked_at=fetched_at,
            )
            message = f"{instrument.product_code}: HTTP status {response.status_code}"
            logger.error(message)
            return InstrumentResult(error=message)
        if not response.content:
            _write_price_quality_checks(
                session,
                source_id=source.id,
                product_id=product.id,
                raw_response_id=raw_response.id,
                price=None,
                checked_at=fetched_at,
            )
            message = f"{instrument.product_code}: empty response"
            logger.error(message)
            return InstrumentResult(error=message)

        try:
            price = parse_price_response(instrument, response.content)
        except PriceParseError as exc:
            _write_price_quality_checks(
                session,
                source_id=source.id,
                product_id=product.id,
                raw_response_id=raw_response.id,
                price=None,
                checked_at=fetched_at,
            )
            message = f"{instrument.product_code}: {exc}"
            logger.error(message)
            return InstrumentResult(error=message)

        source_record_hash = build_source_record_hash(
            source_code=self.source_code,
            product_code=instrument.product_code,
            external_code=instrument.external_code,
            observed_at=observed_at,
            collection_slot=collection_slot if run_type == "scheduled" else None,
            price=price,
            currency=instrument.currency,
            unit=instrument.unit,
        )
        existing = _find_existing_price_observation(
            session,
            product_id=product.id,
            source_id=source.id,
            observed_at=observed_at,
            source_record_hash=source_record_hash,
            collection_slot=collection_slot if run_type == "scheduled" else None,
        )

        _write_price_quality_checks(
            session,
            source_id=source.id,
            product_id=product.id,
            raw_response_id=raw_response.id,
            price=price,
            checked_at=fetched_at,
        )
        _write_price_jump_check(
            session,
            source_id=source.id,
            product_id=product.id,
            current_price=price,
            observed_at=observed_at,
        )

        if existing is not None:
            logger.info(
                "price observation already exists product_code=%s observed_at=%s",
                instrument.product_code,
                observed_at.isoformat(),
            )
            return InstrumentResult(records_found=1, records_written=0)

        session.add(
            PriceObservation(
                product_id=product.id,
                source_id=source.id,
                raw_response_id=raw_response.id,
                observed_at=observed_at,
                collection_slot=collection_slot if run_type == "scheduled" else None,
                published_at=None,
                price=price,
                currency=instrument.currency,
                unit=instrument.unit,
                basis=None,
                delivery_period=None,
                source_record_hash=source_record_hash,
            )
        )
        session.flush()
        return InstrumentResult(records_found=1, records_written=1)

    def _save_raw_response(
        self,
        session: Session,
        source: Source,
        collector_run: CollectorRun,
        instrument: CurrentPriceInstrument,
        response: httpx.Response,
        fetched_at: datetime,
    ) -> RawResponse:
        content_type = response.headers.get("content-type")
        raw_result = self.raw_store.save_bytes(
            source_code=self.source_code,
            collector_run_id=collector_run.id,
            payload=response.content,
            fetched_at=fetched_at,
            extension="txt",
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
        logger.info(
            "raw response saved product_code=%s raw_response_id=%s sha256=%s",
            instrument.product_code,
            raw_response.id,
            raw_response.sha256,
        )
        return raw_response

    def _instrument_error(self, instrument: CurrentPriceInstrument, error_type: str, exc: Exception) -> InstrumentResult:
        message = f"{instrument.product_code}: {error_type}: {exc}"
        logger.exception(message)
        return InstrumentResult(error=message)


def parse_price_response(instrument: CurrentPriceInstrument, payload: bytes | str) -> Decimal:
    text = payload.decode("utf-8", errors="replace") if isinstance(payload, bytes) else payload
    body = _strip_response_prefix(text, instrument.response_prefix)

    if instrument.parser_type == "json":
        return _parse_json_price(instrument, body)
    if instrument.parser_type == "csv":
        return _parse_csv_price(instrument, body)
    raise PriceParseError(f"unsupported parser_type: {instrument.parser_type}")


def build_source_record_hash(
    *,
    source_code: str,
    product_code: str,
    external_code: str,
    observed_at: datetime,
    collection_slot: datetime | None = None,
    price: Decimal,
    currency: str,
    unit: str,
) -> str:
    collection_slot = _to_utc(collection_slot) if collection_slot is not None else None
    observed_at = _to_utc(observed_at)
    return stable_json_hash(
        {
            "source_code": source_code,
            "product_code": product_code,
            "external_code": external_code,
            "observed_at": observed_at.isoformat() if collection_slot is None else None,
            "collection_slot": collection_slot.isoformat() if collection_slot is not None else None,
            "price": _canonical_decimal(price),
            "currency": currency,
            "unit": unit,
        }
    )


def assess_response_schema(
    *,
    instrument: CurrentPriceInstrument,
    payload: bytes,
    content_type: str | None,
    previous_sizes: list[int] | None = None,
) -> list[SchemaCheck]:
    previous_sizes = previous_sizes or []
    text = payload.decode("utf-8", errors="replace") if payload else ""
    checks: list[SchemaCheck] = []

    checks.append(
        SchemaCheck(
            check_name="raw_response_non_empty",
            status="pass" if len(payload) > 0 else "fail",
            severity="error" if len(payload) == 0 else "info",
            details=_schema_details(instrument, bytes_size=len(payload)),
        )
    )
    checks.append(_content_type_check(instrument, content_type))
    checks.append(_raw_size_anomaly_check(instrument, len(payload), previous_sizes))

    prefix_found = bool(text.strip().startswith(instrument.response_prefix))
    checks.append(
        SchemaCheck(
            check_name="response_prefix_found",
            status="pass" if prefix_found else "fail",
            severity="error" if not prefix_found else "info",
            details=_schema_details(instrument, response_prefix=instrument.response_prefix),
        )
    )
    if not prefix_found:
        return checks

    try:
        body = _strip_response_prefix(text, instrument.response_prefix)
    except PriceParseError:
        return checks

    if instrument.parser_type == "json":
        checks.extend(_json_schema_checks(instrument, body))
    elif instrument.parser_type == "csv":
        checks.extend(_csv_schema_checks(instrument, body))

    return checks


def _strip_response_prefix(text: str, prefix: str) -> str:
    stripped = text.strip()
    if not stripped.startswith(prefix):
        raise PriceParseError(f"missing response_prefix: {prefix!r}")
    body = stripped[len(prefix) :].strip()
    if body.endswith(";"):
        body = body[:-1].strip()
    return body


def _json_schema_checks(instrument: CurrentPriceInstrument, body: str) -> list[SchemaCheck]:
    checks: list[SchemaCheck] = []
    try:
        root: Any = json.loads(body)
    except json.JSONDecodeError as exc:
        return [
            SchemaCheck(
                check_name="json_parseable",
                status="fail",
                severity="error",
                details=_schema_details(instrument, error=str(exc)),
            ),
            SchemaCheck(
                check_name="json_root_contains_external_code",
                status="fail",
                severity="error",
                details=_schema_details(instrument),
            ),
            SchemaCheck(
                check_name="json_price_path_exists",
                status="fail",
                severity="error",
                details=_schema_details(instrument, price_path=".".join(instrument.price_path or ())),
            ),
            SchemaCheck(
                check_name="price_convertible",
                status="fail",
                severity="error",
                details=_schema_details(instrument, error="JSON parsing failed"),
            ),
        ]

    root_has_code = isinstance(root, dict) and instrument.external_code in root
    checks.append(
        SchemaCheck(
            check_name="json_root_contains_external_code",
            status="pass" if root_has_code else "fail",
            severity="error" if not root_has_code else "info",
            details=_schema_details(instrument),
        )
    )

    price_path_exists = True
    value = root
    for key in instrument.price_path or ():
        if not isinstance(value, dict) or key not in value:
            price_path_exists = False
            break
        value = value[key]
    checks.append(
        SchemaCheck(
            check_name="json_price_path_exists",
            status="pass" if price_path_exists else "fail",
            severity="error" if not price_path_exists else "info",
            details=_schema_details(instrument, price_path=".".join(instrument.price_path or ())),
        )
    )
    checks.append(_price_convertible_check(instrument, value if price_path_exists else None))
    return checks


def _csv_schema_checks(instrument: CurrentPriceInstrument, body: str) -> list[SchemaCheck]:
    if (body.startswith('"') and body.endswith('"')) or (body.startswith("'") and body.endswith("'")):
        body = body[1:-1]
    parts = [part.strip() for part in next(csv.reader([body]))]
    price_index = instrument.price_index
    has_enough_columns = price_index is not None and len(parts) > price_index
    checks = [
        SchemaCheck(
            check_name="csv_column_count_gt_price_index",
            status="pass" if has_enough_columns else "fail",
            severity="error" if not has_enough_columns else "info",
            details=_schema_details(
                instrument,
                columns=len(parts),
                price_index=price_index,
            ),
        )
    ]
    checks.append(_price_convertible_check(instrument, parts[price_index] if has_enough_columns else None))
    return checks


def _content_type_check(instrument: CurrentPriceInstrument, content_type: str | None) -> SchemaCheck:
    if not content_type:
        return SchemaCheck(
            check_name="content_type_expected",
            status="skip",
            severity="info",
            details=_schema_details(instrument, content_type=None),
        )
    normalized = content_type.split(";")[0].strip().lower()
    expected = {
        "application/javascript",
        "application/json",
        "application/x-javascript",
        "text/javascript",
        "text/plain",
        "text/html",
    }
    is_expected = normalized in expected
    return SchemaCheck(
        check_name="content_type_expected",
        status="pass" if is_expected else "fail",
        severity="warning" if not is_expected else "info",
        details=_schema_details(instrument, content_type=content_type),
    )


def _raw_size_anomaly_check(
    instrument: CurrentPriceInstrument,
    bytes_size: int,
    previous_sizes: list[int],
) -> SchemaCheck:
    if not previous_sizes:
        return SchemaCheck(
            check_name="raw_response_size_anomaly",
            status="skip",
            severity="info",
            details=_schema_details(instrument, bytes_size=bytes_size, previous_sizes_count=0),
        )
    average = sum(previous_sizes) / len(previous_sizes)
    is_anomaly = average > 0 and (bytes_size > average * 3 or bytes_size < average / 3)
    return SchemaCheck(
        check_name="raw_response_size_anomaly",
        status="fail" if is_anomaly else "pass",
        severity="warning" if is_anomaly else "info",
        details=_schema_details(
            instrument,
            bytes_size=bytes_size,
            previous_average_size=round(average, 2),
            previous_sizes_count=len(previous_sizes),
        ),
    )


def _price_convertible_check(instrument: CurrentPriceInstrument, value: Any) -> SchemaCheck:
    try:
        _to_decimal(value)
    except PriceParseError as exc:
        return SchemaCheck(
            check_name="price_convertible",
            status="fail",
            severity="error",
            details=_schema_details(instrument, value=value, error=str(exc)),
        )
    return SchemaCheck(
        check_name="price_convertible",
        status="pass",
        severity="info",
        details=_schema_details(instrument, value=str(value)),
    )


def _schema_details(instrument: CurrentPriceInstrument, **extra: Any) -> dict[str, Any]:
    details = {
        "product_code": instrument.product_code,
        "external_code": instrument.external_code,
        "parser_type": instrument.parser_type,
    }
    details.update(extra)
    return details


def _parse_json_price(instrument: CurrentPriceInstrument, body: str) -> Decimal:
    if not instrument.price_path:
        raise PriceParseError("missing price_path")
    try:
        value: Any = json.loads(body)
    except json.JSONDecodeError as exc:
        raise PriceParseError(f"JSON parsing error: {exc}") from exc

    for key in instrument.price_path:
        if not isinstance(value, dict) or key not in value:
            raise PriceParseError(f"missing price_path: {'.'.join(instrument.price_path)}")
        value = value[key]
    return _to_decimal(value)


def _parse_csv_price(instrument: CurrentPriceInstrument, body: str) -> Decimal:
    if instrument.price_index is None:
        raise PriceParseError("missing price_index")
    if (body.startswith('"') and body.endswith('"')) or (body.startswith("'") and body.endswith("'")):
        body = body[1:-1]
    parts = [part.strip() for part in next(csv.reader([body]))]
    if instrument.price_index >= len(parts):
        raise PriceParseError(
            f"price_index out of range: index={instrument.price_index} columns={len(parts)}"
        )
    return _to_decimal(parts[instrument.price_index])


def _to_decimal(value: Any) -> Decimal:
    if value is None:
        raise PriceParseError("price is NULL")
    cleaned = str(value).strip().strip('"').strip("'").replace(" ", "")
    if not cleaned:
        raise PriceParseError("price is NULL")
    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise PriceParseError(f"price cannot be converted to float: {value!r}") from exc


def _write_price_quality_checks(
    session: Session,
    *,
    source_id: int,
    product_id: int,
    raw_response_id: int | None,
    price: Decimal | None,
    checked_at: datetime,
) -> None:
    _write_quality_check(
        session,
        source_id=source_id,
        table_name="price_observations",
        check_name="raw_response_present",
        status="pass" if raw_response_id is not None else "fail",
        severity="error" if raw_response_id is None else "info",
        details={"product_id": product_id, "raw_response_id": raw_response_id},
        checked_at=checked_at,
    )
    _write_quality_check(
        session,
        source_id=source_id,
        table_name="price_observations",
        check_name="price_is_not_null",
        status="pass" if price is not None else "fail",
        severity="error" if price is None else "info",
        details={"product_id": product_id, "raw_response_id": raw_response_id},
        checked_at=checked_at,
    )
    _write_quality_check(
        session,
        source_id=source_id,
        table_name="price_observations",
        check_name="price_positive",
        status="pass" if price is not None and price > 0 else "fail",
        severity="error" if price is None or price <= 0 else "info",
        details={
            "product_id": product_id,
            "raw_response_id": raw_response_id,
            "price": _canonical_decimal(price) if price is not None else None,
        },
        checked_at=checked_at,
    )


def _find_existing_price_observation(
    session: Session,
    *,
    product_id: int,
    source_id: int,
    observed_at: datetime,
    source_record_hash: str,
    collection_slot: datetime | None,
) -> PriceObservation | None:
    if collection_slot is not None:
        return session.scalar(
            select(PriceObservation)
            .where(
                PriceObservation.product_id == product_id,
                PriceObservation.source_id == source_id,
                PriceObservation.collection_slot == collection_slot,
            )
            .limit(1)
        )
    return session.scalar(
        select(PriceObservation).where(
            PriceObservation.product_id == product_id,
            PriceObservation.source_id == source_id,
            PriceObservation.observed_at == observed_at,
            PriceObservation.source_record_hash == source_record_hash,
        )
    )


def _write_schema_checks(
    session: Session,
    *,
    source_id: int,
    raw_response_id: int,
    instrument: CurrentPriceInstrument,
    checks: list[SchemaCheck],
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


def _previous_raw_response_sizes(
    session: Session,
    source_id: int,
    external_code: str,
    current_raw_response_id: int,
    *,
    limit: int = 20,
) -> list[int]:
    rows = session.execute(
        select(RawResponse.bytes_size)
        .where(
            RawResponse.source_id == source_id,
            RawResponse.id != current_raw_response_id,
            RawResponse.url.like(f"%{external_code}%"),
            RawResponse.bytes_size > 0,
        )
        .order_by(RawResponse.fetched_at.desc())
        .limit(limit)
    ).all()
    return [row[0] for row in rows]


def _write_price_jump_check(
    session: Session,
    *,
    source_id: int,
    product_id: int,
    current_price: Decimal,
    observed_at: datetime,
) -> None:
    previous = session.scalar(
        select(PriceObservation)
        .where(
            PriceObservation.product_id == product_id,
            PriceObservation.source_id == source_id,
            PriceObservation.observed_at < observed_at,
        )
        .order_by(PriceObservation.observed_at.desc())
        .limit(1)
    )
    if previous is None or previous.price <= 0:
        status = "skip"
        severity = "info"
        jump_ratio = None
    else:
        jump_ratio = abs(current_price - previous.price) / previous.price
        status = "fail" if jump_ratio > Decimal("0.20") else "pass"
        severity = "warning" if status == "fail" else "info"

    _write_quality_check(
        session,
        source_id=source_id,
        table_name="price_observations",
        check_name="price_jump_gt_20pct",
        status=status,
        severity=severity,
        details={
            "product_id": product_id,
            "observed_at": observed_at.isoformat(),
            "current_price": _canonical_decimal(current_price),
            "previous_price": _canonical_decimal(previous.price) if previous is not None else None,
            "jump_ratio": _canonical_decimal(jump_ratio) if jump_ratio is not None else None,
        },
        checked_at=observed_at,
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
    collector: CurrentPriceSourceCollector,
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
