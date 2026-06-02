from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.collectors.base import BaseCollector, CollectorResult
from app.collectors.historical.jijinhao_history_config import (
    BAR_TIMEFRAME,
    COLLECTOR_NAME,
    DEFAULT_DAYS,
    ENDPOINT,
    ENDPOINT_ALIAS,
    HEADERS,
    HISTORICAL_PRICE_INSTRUMENTS,
    MAX_DAYS,
    PARSER_VERSION,
    REQUEST_TIMEOUT,
    SOURCE_CODE,
    HistoricalPriceInstrument,
    historys_params,
)
from app.db.models import (
    CollectorRun,
    DataQualityCheck,
    HistoricalPriceBar,
    HistoricalPriceBarRevision,
    Product,
    RawResponse,
    Source,
)
from app.db.session import session_scope
from app.discovery.historical_price_probe import HistoricalRow, parse_historical_response
from app.storage.hashes import stable_json_hash
from app.storage.raw_store import RawStore

logger = logging.getLogger(__name__)


class HistoricalPriceParseError(ValueError):
    """Raised when a historical response cannot be parsed safely."""


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
class HistoricalResponseCheck:
    check_name: str
    status: str
    severity: str
    details: dict[str, Any]


@dataclass(frozen=True)
class ParsedHistoricalBar:
    bar_date: date
    observed_at: datetime
    open_price: Decimal | None
    high_price: Decimal | None
    low_price: Decimal | None
    close_price: Decimal | None
    price: Decimal | None
    volume: Decimal | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class HistoricalCollectorResult(CollectorResult):
    endpoint_alias: str = ENDPOINT_ALIAS
    products_processed: int = 0
    skipped_existing: int = 0
    updated_existing: int = 0
    revisions_written: int = 0
    conflicts_count: int = 0


@dataclass
class _ProductStats:
    product_code: str
    records_found: int = 0
    records_written: int = 0
    skipped_existing: int = 0
    updated_existing: int = 0
    revisions_written: int = 0
    conflicts_count: int = 0
    raw_response_ids: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class JijinhaoHistoricalPricesCollector(BaseCollector):
    source_code = SOURCE_CODE
    collector_name = COLLECTOR_NAME
    parser_version = PARSER_VERSION

    def __init__(
        self,
        *,
        instruments: tuple[HistoricalPriceInstrument, ...] = HISTORICAL_PRICE_INSTRUMENTS,
        http_client: HttpClient | None = None,
        raw_store: RawStore | None = None,
        timeout: float = REQUEST_TIMEOUT,
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
        product_code: str | None = None,
        days: int = DEFAULT_DAYS,
        run_type: str = "manual",
        endpoint_alias: str = ENDPOINT_ALIAS,
    ) -> HistoricalCollectorResult:
        run_type = _normalize_run_type(run_type)
        days = _normalize_days(days)
        if endpoint_alias != ENDPOINT_ALIAS:
            raise ValueError(f"{endpoint_alias} is not supported for production historical collector in Phase 4.6")
        selected = _select_instruments(self.instruments, product_code)
        if session is None:
            with session_scope() as scoped_session:
                return self._run_with_session(scoped_session, instruments=selected, days=days, run_type=run_type)
        return self._run_with_session(session, instruments=selected, days=days, run_type=run_type)

    def _run_with_session(
        self,
        session: Session,
        *,
        instruments: tuple[HistoricalPriceInstrument, ...],
        days: int,
        run_type: str,
    ) -> HistoricalCollectorResult:
        started_at = _to_utc(self.clock())
        source = session.scalar(select(Source).where(Source.code == self.source_code))
        collector_run = CollectorRun(
            source_id=source.id if source else None,
            collector_name=self.collector_name,
            started_at=started_at,
            status="running",
            run_type=run_type,
            collection_slot=None,
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

        all_errors: list[str] = []
        raw_response_ids: list[int] = []
        records_found = 0
        records_written = 0
        skipped_existing = 0
        updated_existing = 0
        revisions_written = 0
        conflicts_count = 0
        products_processed = 0

        for instrument in instruments:
            stats = self._collect_product(session, source, collector_run, instrument, days=days)
            products_processed += 1
            records_found += stats.records_found
            records_written += stats.records_written
            skipped_existing += stats.skipped_existing
            updated_existing += stats.updated_existing
            revisions_written += stats.revisions_written
            conflicts_count += stats.conflicts_count
            raw_response_ids.extend(stats.raw_response_ids)
            all_errors.extend(stats.errors)

        collector_run.finished_at = _to_utc(self.clock())
        collector_run.records_found = records_found
        collector_run.records_written = records_written
        if not all_errors and conflicts_count == 0 and products_processed == len(instruments):
            collector_run.status = "success"
        elif records_found > 0:
            collector_run.status = "partial_success"
        else:
            collector_run.status = "error"
        collector_run.error_message = "\n".join(all_errors) if all_errors else None
        session.flush()

        return HistoricalCollectorResult(
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
            errors_count=len(all_errors),
            endpoint_alias=ENDPOINT_ALIAS,
            products_processed=products_processed,
            skipped_existing=skipped_existing,
            updated_existing=updated_existing,
            revisions_written=revisions_written,
            conflicts_count=conflicts_count,
        )

    def _collect_product(
        self,
        session: Session,
        source: Source,
        collector_run: CollectorRun,
        instrument: HistoricalPriceInstrument,
        *,
        days: int,
    ) -> _ProductStats:
        stats = _ProductStats(product_code=instrument.product_code)
        product = session.scalar(select(Product).where(Product.code == instrument.product_code))
        checked_at = _to_utc(self.clock())
        if product is None:
            _write_quality_check(
                session,
                source_id=source.id,
                table_name="historical_price_bars",
                check_name="historical_product_mapping_found",
                status="fail",
                severity="error",
                details={"product_code": instrument.product_code, "external_code": instrument.external_code},
                checked_at=checked_at,
            )
            stats.errors.append(f"product mapping not found: {instrument.product_code}")
            return stats
        _write_quality_check(
            session,
            source_id=source.id,
            table_name="products",
            check_name="historical_product_mapping_found",
            status="pass",
            severity="info",
            details={"product_code": instrument.product_code, "product_id": product.id},
            checked_at=checked_at,
        )

        try:
            response = self.http_client.get(
                ENDPOINT,
                params=historys_params(instrument.external_code, days),
                headers=HEADERS,
                timeout=self.timeout,
            )
            fetched_at = _to_utc(self.clock())
        except httpx.TimeoutException as exc:
            stats.errors.append(f"{instrument.product_code}: timeout: {exc}")
            return stats
        except httpx.RequestError as exc:
            stats.errors.append(f"{instrument.product_code}: connection error: {exc}")
            return stats

        raw_response = self._save_raw_response(session, source, collector_run, response, fetched_at)
        stats.raw_response_ids.append(raw_response.id)

        rows, response_checks = assess_historys_response(
            payload=response.content,
            content_type=response.headers.get("content-type"),
            status_code=response.status_code,
            external_code=instrument.external_code,
            days=days,
        )
        _write_response_checks(
            session,
            source_id=source.id,
            raw_response_id=raw_response.id,
            instrument=instrument,
            checks=response_checks,
            checked_at=fetched_at,
        )

        if response.status_code != 200:
            stats.errors.append(f"{instrument.product_code}: HTTP status {response.status_code}")
            return stats
        if not rows:
            stats.errors.append(f"{instrument.product_code}: no historical rows parsed")
            return stats

        for row in rows:
            stats.records_found += 1
            source_record_hash = build_historical_source_record_hash(
                source_code=self.source_code,
                product_code=instrument.product_code,
                external_code=instrument.external_code,
                endpoint_alias=ENDPOINT_ALIAS,
                bar_timeframe=BAR_TIMEFRAME,
                bar_date=row.bar_date,
                open_price=row.open_price,
                high_price=row.high_price,
                low_price=row.low_price,
                close_price=row.close_price,
                price=row.price,
                volume=row.volume,
                currency=instrument.currency,
                unit=instrument.unit,
            )
            _write_bar_quality_checks(
                session,
                source_id=source.id,
                product_id=product.id,
                raw_response_id=raw_response.id,
                bar=row,
                source_record_hash=source_record_hash,
                checked_at=fetched_at,
            )
            existing = _find_existing_bar(
                session,
                product_id=product.id,
                source_id=source.id,
                endpoint_alias=ENDPOINT_ALIAS,
                bar_timeframe=BAR_TIMEFRAME,
                bar_date=row.bar_date,
            )
            if existing is not None:
                if existing.source_record_hash == source_record_hash:
                    stats.skipped_existing += 1
                    continue
                changed_fields, diff_json = build_historical_bar_diff(existing, row, raw_response, source_record_hash)
                details = _revision_quality_details(
                    product=product,
                    product_code=instrument.product_code,
                    existing=existing,
                    incoming_bar=row,
                    incoming_raw_response=raw_response,
                    collector_run=collector_run,
                    incoming_source_record_hash=source_record_hash,
                    changed_fields=changed_fields,
                    diff_json=diff_json,
                )
                max_bar_date = _max_bar_date(
                    session,
                    product_id=product.id,
                    source_id=source.id,
                    endpoint_alias=ENDPOINT_ALIAS,
                    bar_timeframe=BAR_TIMEFRAME,
                )
                if existing.bar_date == max_bar_date:
                    _write_revision(
                        session,
                        existing=existing,
                        incoming_bar=row,
                        incoming_raw_response=raw_response,
                        collector_run=collector_run,
                        revision_reason="mutable_latest_bar_update",
                        incoming_source_record_hash=source_record_hash,
                        changed_fields=changed_fields,
                        diff_json=diff_json,
                    )
                    _apply_incoming_bar_update(
                        existing,
                        incoming_bar=row,
                        incoming_raw_response=raw_response,
                        collector_run=collector_run,
                        incoming_source_record_hash=source_record_hash,
                    )
                    stats.updated_existing += 1
                    stats.revisions_written += 1
                    _write_quality_check(
                        session,
                        source_id=source.id,
                        table_name="historical_price_bars",
                        check_name="historical_latest_bar_updated",
                        status="pass",
                        severity="warning",
                        details={**details, "policy_decision": "updated_latest_bar"},
                        checked_at=fetched_at,
                    )
                    session.flush()
                    continue
                _write_revision(
                    session,
                    existing=existing,
                    incoming_bar=row,
                    incoming_raw_response=raw_response,
                    collector_run=collector_run,
                    revision_reason="immutable_old_bar_conflict",
                    incoming_source_record_hash=source_record_hash,
                    changed_fields=changed_fields,
                    diff_json=diff_json,
                )
                stats.conflicts_count += 1
                stats.revisions_written += 1
                _write_quality_check(
                    session,
                    source_id=source.id,
                    table_name="historical_price_bars",
                    check_name="historical_old_bar_hash_changed",
                    status="fail",
                    severity="warning",
                    details={**details, "policy_decision": "rejected_old_bar_conflict"},
                    checked_at=fetched_at,
                )
                session.flush()
                continue

            session.add(
                HistoricalPriceBar(
                    product_id=product.id,
                    source_id=source.id,
                    raw_response_id=raw_response.id,
                    collector_run_id=collector_run.id,
                    external_code=instrument.external_code,
                    endpoint_alias=ENDPOINT_ALIAS,
                    bar_date=row.bar_date,
                    bar_timeframe=BAR_TIMEFRAME,
                    open_price=row.open_price,
                    high_price=row.high_price,
                    low_price=row.low_price,
                    close_price=row.close_price,
                    price=row.price,
                    volume=row.volume,
                    currency=instrument.currency,
                    unit=instrument.unit,
                    observed_at=row.observed_at,
                    published_at=None,
                    fetched_at=fetched_at,
                    source_record_hash=source_record_hash,
                    source_payload_hash=raw_response.sha256,
                )
            )
            stats.records_written += 1
            session.flush()
        return stats

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
        return raw_response


def assess_historys_response(
    *,
    payload: bytes,
    content_type: str | None,
    status_code: int | None,
    external_code: str,
    days: int = DEFAULT_DAYS,
) -> tuple[list[ParsedHistoricalBar], list[HistoricalResponseCheck]]:
    checks: list[HistoricalResponseCheck] = []
    checks.append(
        HistoricalResponseCheck(
            check_name="historical_raw_response_non_empty",
            status="pass" if payload else "fail",
            severity="error" if not payload else "info",
            details={"bytes_size": len(payload), "status_code": status_code, "external_code": external_code},
        )
    )
    checks.append(_content_type_check(content_type, external_code=external_code))
    checks.append(
        HistoricalResponseCheck(
            check_name="historical_response_size_within_limit",
            status="pass" if len(payload) <= 100_000 else "fail",
            severity="warning" if len(payload) > 100_000 else "info",
            details={"bytes_size": len(payload), "limit_bytes": 100_000, "external_code": external_code},
        )
    )

    parsed_rows: list[ParsedHistoricalBar] = []
    parse_error: str | None = None
    if payload:
        rows, _, notes = parse_historical_response(
            endpoint_alias=ENDPOINT_ALIAS,
            external_code=external_code,
            content=payload,
            days=days,
        )
        try:
            parsed_rows = [_normalize_history_row(item) for item in rows]
        except HistoricalPriceParseError as exc:
            parse_error = str(exc)
        if not parsed_rows and parse_error is None:
            parse_error = notes or "no rows parsed"
    else:
        parse_error = "empty response"

    checks.append(
        HistoricalResponseCheck(
            check_name="historical_parser_success",
            status="pass" if parsed_rows else "fail",
            severity="error" if not parsed_rows else "info",
            details={"external_code": external_code, "rows_count": len(parsed_rows), "error": parse_error},
        )
    )
    return parsed_rows, checks


def build_historical_source_record_hash(
    *,
    source_code: str,
    product_code: str,
    external_code: str,
    endpoint_alias: str,
    bar_timeframe: str,
    bar_date: date,
    open_price: Decimal | None,
    high_price: Decimal | None,
    low_price: Decimal | None,
    close_price: Decimal | None,
    price: Decimal | None,
    volume: Decimal | None,
    currency: str,
    unit: str,
) -> str:
    return stable_json_hash(
        {
            "source_code": source_code,
            "product_code": product_code,
            "external_code": external_code,
            "endpoint_alias": endpoint_alias,
            "bar_timeframe": bar_timeframe,
            "bar_date": bar_date.isoformat(),
            "open_price": _canonical_decimal(open_price),
            "high_price": _canonical_decimal(high_price),
            "low_price": _canonical_decimal(low_price),
            "close_price": _canonical_decimal(close_price),
            "price": _canonical_decimal(price),
            "volume": _canonical_decimal(volume),
            "currency": currency,
            "unit": unit,
        }
    )


def _normalize_history_row(row: HistoricalRow) -> ParsedHistoricalBar:
    if not row.observed_at:
        raise HistoricalPriceParseError("historical row has no observed_at")
    try:
        bar_date = date.fromisoformat(row.observed_at[:10])
    except ValueError as exc:
        raise HistoricalPriceParseError(f"historical row date cannot be parsed: {row.observed_at!r}") from exc
    return ParsedHistoricalBar(
        bar_date=bar_date,
        observed_at=datetime.combine(bar_date, time.min, tzinfo=timezone.utc),
        open_price=_to_decimal(row.open),
        high_price=_to_decimal(row.high),
        low_price=_to_decimal(row.low),
        close_price=_to_decimal(row.close),
        price=_to_decimal(row.price),
        volume=_to_decimal(row.volume),
        raw=row.raw,
    )


def _find_existing_bar(
    session: Session,
    *,
    product_id: int,
    source_id: int,
    endpoint_alias: str,
    bar_timeframe: str,
    bar_date: date,
) -> HistoricalPriceBar | None:
    return session.scalar(
        select(HistoricalPriceBar)
        .where(
            HistoricalPriceBar.product_id == product_id,
            HistoricalPriceBar.source_id == source_id,
            HistoricalPriceBar.endpoint_alias == endpoint_alias,
            HistoricalPriceBar.bar_timeframe == bar_timeframe,
            HistoricalPriceBar.bar_date == bar_date,
        )
        .limit(1)
    )


def _max_bar_date(
    session: Session,
    *,
    product_id: int,
    source_id: int,
    endpoint_alias: str,
    bar_timeframe: str,
) -> date | None:
    return session.scalar(
        select(func.max(HistoricalPriceBar.bar_date)).where(
            HistoricalPriceBar.product_id == product_id,
            HistoricalPriceBar.source_id == source_id,
            HistoricalPriceBar.endpoint_alias == endpoint_alias,
            HistoricalPriceBar.bar_timeframe == bar_timeframe,
        )
    )


def build_historical_bar_diff(
    existing: HistoricalPriceBar,
    incoming_bar: ParsedHistoricalBar,
    incoming_raw_response: RawResponse,
    incoming_source_record_hash: str,
) -> tuple[list[str], dict[str, Any]]:
    pairs: dict[str, tuple[Decimal | str | int | None, Decimal | str | int | None]] = {
        "open_price": (existing.open_price, incoming_bar.open_price),
        "high_price": (existing.high_price, incoming_bar.high_price),
        "low_price": (existing.low_price, incoming_bar.low_price),
        "close_price": (existing.close_price, incoming_bar.close_price),
        "price": (existing.price, incoming_bar.price),
        "volume": (existing.volume, incoming_bar.volume),
        "source_record_hash": (existing.source_record_hash, incoming_source_record_hash),
        "source_payload_hash": (existing.source_payload_hash, incoming_raw_response.sha256),
    }
    changed_fields: list[str] = []
    diff_json: dict[str, Any] = {}
    for field, (old_value, new_value) in pairs.items():
        if _json_value(old_value) == _json_value(new_value):
            continue
        changed_fields.append(field)
        diff_json[field] = {"old": _json_value(old_value), "new": _json_value(new_value)}
        if isinstance(old_value, Decimal) and isinstance(new_value, Decimal):
            diff_abs = new_value - old_value
            diff_pct = diff_abs / old_value if old_value != 0 else None
            diff_json[field]["diff_abs"] = _canonical_decimal(diff_abs)
            diff_json[field]["diff_pct"] = _canonical_decimal(diff_pct)
    return changed_fields, diff_json


def _revision_quality_details(
    *,
    product: Product,
    product_code: str,
    existing: HistoricalPriceBar,
    incoming_bar: ParsedHistoricalBar,
    incoming_raw_response: RawResponse,
    collector_run: CollectorRun,
    incoming_source_record_hash: str,
    changed_fields: list[str],
    diff_json: dict[str, Any],
) -> dict[str, Any]:
    return {
        "product_id": product.id,
        "product_code": product_code,
        "bar_date": existing.bar_date.isoformat(),
        "endpoint_alias": existing.endpoint_alias,
        "bar_timeframe": existing.bar_timeframe,
        "existing_id": existing.id,
        "existing_source_record_hash": existing.source_record_hash,
        "incoming_source_record_hash": incoming_source_record_hash,
        "existing_raw_response_id": existing.raw_response_id,
        "incoming_raw_response_id": incoming_raw_response.id,
        "existing_collector_run_id": existing.collector_run_id,
        "incoming_collector_run_id": collector_run.id,
        "existing_values": _bar_values(existing),
        "incoming_values": _incoming_values(incoming_bar),
        "changed_fields": changed_fields,
        "diff_json": diff_json,
    }


def _write_revision(
    session: Session,
    *,
    existing: HistoricalPriceBar,
    incoming_bar: ParsedHistoricalBar,
    incoming_raw_response: RawResponse,
    collector_run: CollectorRun,
    revision_reason: str,
    incoming_source_record_hash: str,
    changed_fields: list[str],
    diff_json: dict[str, Any],
) -> None:
    revision_number = _next_revision_number(session, existing.id)
    session.add(
        HistoricalPriceBarRevision(
            historical_price_bar_id=existing.id,
            product_id=existing.product_id,
            source_id=existing.source_id,
            raw_response_id=existing.raw_response_id,
            collector_run_id=existing.collector_run_id,
            revision_reason=revision_reason,
            revision_number=revision_number,
            previous_open=existing.open_price,
            previous_high=existing.high_price,
            previous_low=existing.low_price,
            previous_close=existing.close_price,
            previous_price=existing.price,
            previous_volume=existing.volume,
            previous_currency=existing.currency,
            previous_unit=existing.unit,
            previous_observed_at=existing.observed_at,
            previous_published_at=existing.published_at,
            previous_fetched_at=existing.fetched_at,
            previous_source_record_hash=existing.source_record_hash,
            previous_source_payload_hash=existing.source_payload_hash,
            new_raw_response_id=incoming_raw_response.id,
            new_collector_run_id=collector_run.id,
            new_open=incoming_bar.open_price,
            new_high=incoming_bar.high_price,
            new_low=incoming_bar.low_price,
            new_close=incoming_bar.close_price,
            new_price=incoming_bar.price,
            new_volume=incoming_bar.volume,
            new_observed_at=incoming_bar.observed_at,
            new_fetched_at=incoming_raw_response.fetched_at,
            new_source_record_hash=incoming_source_record_hash,
            new_source_payload_hash=incoming_raw_response.sha256,
            changed_fields=changed_fields,
            diff_json=diff_json,
        )
    )


def _next_revision_number(session: Session, historical_price_bar_id: int) -> int:
    current = session.scalar(
        select(func.max(HistoricalPriceBarRevision.revision_number)).where(
            HistoricalPriceBarRevision.historical_price_bar_id == historical_price_bar_id
        )
    )
    return (current or 0) + 1


def _apply_incoming_bar_update(
    existing: HistoricalPriceBar,
    *,
    incoming_bar: ParsedHistoricalBar,
    incoming_raw_response: RawResponse,
    collector_run: CollectorRun,
    incoming_source_record_hash: str,
) -> None:
    existing.raw_response_id = incoming_raw_response.id
    existing.collector_run_id = collector_run.id
    existing.open_price = incoming_bar.open_price
    existing.high_price = incoming_bar.high_price
    existing.low_price = incoming_bar.low_price
    existing.close_price = incoming_bar.close_price
    existing.price = incoming_bar.price
    existing.volume = incoming_bar.volume
    existing.observed_at = incoming_bar.observed_at
    existing.published_at = None
    existing.fetched_at = incoming_raw_response.fetched_at
    existing.source_record_hash = incoming_source_record_hash
    existing.source_payload_hash = incoming_raw_response.sha256
    existing.updated_at = _to_utc(datetime.now(timezone.utc))


def _bar_values(existing: HistoricalPriceBar) -> dict[str, Any]:
    return {
        "open_price": _json_value(existing.open_price),
        "high_price": _json_value(existing.high_price),
        "low_price": _json_value(existing.low_price),
        "close_price": _json_value(existing.close_price),
        "price": _json_value(existing.price),
        "volume": _json_value(existing.volume),
    }


def _incoming_values(incoming_bar: ParsedHistoricalBar) -> dict[str, Any]:
    return {
        "open_price": _json_value(incoming_bar.open_price),
        "high_price": _json_value(incoming_bar.high_price),
        "low_price": _json_value(incoming_bar.low_price),
        "close_price": _json_value(incoming_bar.close_price),
        "price": _json_value(incoming_bar.price),
        "volume": _json_value(incoming_bar.volume),
    }


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return _canonical_decimal(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _write_response_checks(
    session: Session,
    *,
    source_id: int,
    raw_response_id: int,
    instrument: HistoricalPriceInstrument,
    checks: list[HistoricalResponseCheck],
    checked_at: datetime,
) -> None:
    for check in checks:
        details = dict(check.details)
        details.update({"raw_response_id": raw_response_id, "product_code": instrument.product_code})
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


def _write_bar_quality_checks(
    session: Session,
    *,
    source_id: int,
    product_id: int,
    raw_response_id: int | None,
    bar: ParsedHistoricalBar,
    source_record_hash: str | None,
    checked_at: datetime,
) -> None:
    has_price = bar.price is not None or bar.close_price is not None
    positive_price = any(value is not None and value > 0 for value in (bar.price, bar.close_price))
    details = {
        "product_id": product_id,
        "raw_response_id": raw_response_id,
        "bar_date": bar.bar_date.isoformat(),
        "observed_at": bar.observed_at.isoformat(),
    }
    _write_quality_check(session, source_id=source_id, table_name="historical_price_bars", check_name="historical_bar_date_present", status="pass", severity="info", details=details, checked_at=checked_at)
    _write_quality_check(session, source_id=source_id, table_name="historical_price_bars", check_name="historical_price_present", status="pass" if has_price else "fail", severity="error" if not has_price else "info", details={**details, "price": _canonical_decimal(bar.price), "close": _canonical_decimal(bar.close_price)}, checked_at=checked_at)
    _write_quality_check(session, source_id=source_id, table_name="historical_price_bars", check_name="historical_price_positive", status="pass" if positive_price else "fail", severity="error" if not positive_price else "info", details={**details, "price": _canonical_decimal(bar.price), "close": _canonical_decimal(bar.close_price)}, checked_at=checked_at)
    _write_quality_check(session, source_id=source_id, table_name="historical_price_bars", check_name="historical_no_duplicate_product_date", status="pass", severity="info", details=details, checked_at=checked_at)
    future_observed = bar.observed_at > checked_at
    _write_quality_check(session, source_id=source_id, table_name="historical_price_bars", check_name="historical_no_future_observed_at", status="fail" if future_observed else "pass", severity="error" if future_observed else "info", details=details, checked_at=checked_at)
    _write_quality_check(session, source_id=source_id, table_name="historical_price_bars", check_name="historical_fetched_at_present", status="pass", severity="info", details={**details, "fetched_at": checked_at.isoformat()}, checked_at=checked_at)
    _write_quality_check(session, source_id=source_id, table_name="historical_price_bars", check_name="historical_source_record_hash_present", status="pass" if source_record_hash else "fail", severity="error" if not source_record_hash else "info", details={**details, "source_record_hash": source_record_hash}, checked_at=checked_at)
    ohlc_values = (bar.open_price, bar.high_price, bar.low_price, bar.close_price)
    if all(value is None for value in ohlc_values):
        _write_quality_check(session, source_id=source_id, table_name="historical_price_bars", check_name="historical_ohlc_consistent", status="skip", severity="info", details={**details, "reason": "OHLC fields absent"}, checked_at=checked_at)
        return
    consistent = _ohlc_consistent(bar)
    _write_quality_check(
        session,
        source_id=source_id,
        table_name="historical_price_bars",
        check_name="historical_ohlc_consistent",
        status="pass" if consistent else "fail",
        severity="error" if not consistent else "info",
        details={**details, "open": _canonical_decimal(bar.open_price), "high": _canonical_decimal(bar.high_price), "low": _canonical_decimal(bar.low_price), "close": _canonical_decimal(bar.close_price)},
        checked_at=checked_at,
    )


def _content_type_check(content_type: str | None, *, external_code: str) -> HistoricalResponseCheck:
    if not content_type:
        return HistoricalResponseCheck(check_name="historical_content_type_expected", status="skip", severity="info", details={"content_type": None, "external_code": external_code})
    normalized = content_type.split(";")[0].strip().lower()
    expected = {"application/javascript", "application/json", "application/x-javascript", "text/javascript", "text/plain", "text/html"}
    return HistoricalResponseCheck(check_name="historical_content_type_expected", status="pass" if normalized in expected else "fail", severity="warning" if normalized not in expected else "info", details={"content_type": content_type, "external_code": external_code})


def _ohlc_consistent(bar: ParsedHistoricalBar) -> bool:
    open_price, high_price, low_price, close_price = bar.open_price, bar.high_price, bar.low_price, bar.close_price
    if any(value is None for value in (open_price, high_price, low_price, close_price)):
        return False
    return high_price >= low_price and high_price >= open_price and high_price >= close_price and low_price <= open_price and low_price <= close_price


def _write_quality_check(session: Session, *, source_id: int | None, table_name: str, check_name: str, status: str, severity: str, details: dict[str, Any], checked_at: datetime) -> None:
    session.add(DataQualityCheck(source_id=source_id, table_name=table_name, check_name=check_name, checked_at=checked_at, status=status, severity=severity, details_json=details))


def _select_instruments(instruments: tuple[HistoricalPriceInstrument, ...], product_code: str | None) -> tuple[HistoricalPriceInstrument, ...]:
    if product_code is None:
        return instruments
    selected = tuple(item for item in instruments if item.product_code == product_code)
    if not selected:
        raise ValueError(f"unknown product_code: {product_code}")
    return selected


def _normalize_run_type(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"manual", "backfill"}:
        raise ValueError("run_type must be either 'manual' or 'backfill'")
    return normalized


def _normalize_days(value: int) -> int:
    if value <= 0:
        raise ValueError("days must be positive")
    if value > MAX_DAYS:
        raise ValueError(f"days must be <= {MAX_DAYS} for Phase 4.6 historys collector")
    return value


def _to_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value).strip().replace(",", "."))
    except (InvalidOperation, ValueError) as exc:
        raise HistoricalPriceParseError(f"decimal value cannot be parsed: {value!r}") from exc


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _canonical_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.normalize(), "f")


def _result_from_run(collector: JijinhaoHistoricalPricesCollector, collector_run: CollectorRun, started_at: datetime, *, errors_count: int) -> HistoricalCollectorResult:
    return HistoricalCollectorResult(
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
