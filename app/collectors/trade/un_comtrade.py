from __future__ import annotations

import json
import logging
from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors.base import BaseCollector, CollectorResult
from app.collectors.trade.un_comtrade_config import (
    COLLECTOR_NAME,
    DEFAULT_MAXRECORDS,
    ENDPOINT,
    FLOW_CODE_BY_DIRECTION,
    HEADERS,
    MAX_MAXRECORDS,
    MAX_MONTHS_PER_RUN,
    PARSER_VERSION,
    REQUEST_TIMEOUT,
    SOURCE_CODE,
    SUPPORTED_HS_CODES,
    TradePartner,
    is_supported_hs_code,
    resolve_trade_partner,
    un_comtrade_params,
)
from app.db.models import CollectorRun, DataQualityCheck, RawResponse, Source, TradeCommodityCode, TradeFlow
from app.db.session import session_scope
from app.storage.hashes import stable_json_hash
from app.storage.raw_store import RawStore

logger = logging.getLogger(__name__)


class UnComtradeParseError(ValueError):
    """Raised when a UN Comtrade response cannot be parsed safely."""


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
class UnComtradeRequest:
    hs_code: str
    from_period: str
    to_period: str
    reporter: TradePartner
    partner: TradePartner
    flow_direction: str
    maxrecords: int


@dataclass(frozen=True)
class ParsedTradeFlow:
    source_record_id: str | None
    reporter_code: str
    reporter_name: str
    partner_code: str
    partner_name: str
    flow_direction: str
    trade_period: str
    period_start: date
    period_end: date
    frequency: str
    quantity: Decimal | None
    quantity_unit: str | None
    trade_value_usd: Decimal | None
    trade_value_local: Decimal | None
    currency: str | None
    unit_value_usd: Decimal | None
    net_weight_kg: Decimal | None
    gross_weight_kg: Decimal | None
    published_at: datetime | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class TradeResponseCheck:
    check_name: str
    status: str
    severity: str
    details: dict[str, Any]


@dataclass(frozen=True)
class UnComtradeCollectorResult(CollectorResult):
    hs_code: str | None = None
    from_period: str | None = None
    to_period: str | None = None
    reporter: str | None = None
    partner: str | None = None
    flow: str | None = None
    maxrecords: int = DEFAULT_MAXRECORDS
    skipped_existing: int = 0
    conflicts_count: int = 0
    skipped_malformed: int = 0


@dataclass
class _TradeStats:
    records_found: int = 0
    records_written: int = 0
    skipped_existing: int = 0
    conflicts_count: int = 0
    skipped_malformed: int = 0
    raw_response_ids: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class UnComtradeCollector(BaseCollector):
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
        hs_code: str,
        from_period: str,
        to_period: str,
        reporter: str,
        partner: str,
        flow: str = "export",
        maxrecords: int = DEFAULT_MAXRECORDS,
        run_type: str = "manual",
    ) -> UnComtradeCollectorResult:
        run_type = _normalize_run_type(run_type)
        request = build_un_comtrade_request(
            hs_code=hs_code,
            from_period=from_period,
            to_period=to_period,
            reporter=reporter,
            partner=partner,
            flow=flow,
            maxrecords=maxrecords,
        )
        if session is None:
            with session_scope() as scoped_session:
                return self._run_with_session(scoped_session, request=request, run_type=run_type)
        return self._run_with_session(session, request=request, run_type=run_type)

    def _run_with_session(
        self,
        session: Session,
        *,
        request: UnComtradeRequest,
        run_type: str,
    ) -> UnComtradeCollectorResult:
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
            _write_quality_check(
                session,
                source_id=None,
                table_name="sources",
                check_name="trade_source_mapping_found",
                status="fail",
                severity="error",
                details={"source_code": self.source_code},
                checked_at=started_at,
            )
            collector_run.status = "error"
            collector_run.finished_at = _to_utc(self.clock())
            collector_run.error_message = message
            session.flush()
            return _result_from_run(self, collector_run, started_at, request=request, errors_count=1)

        commodity_code = _find_trade_commodity_code(session, hs_code=request.hs_code)
        _write_request_quality_checks(
            session,
            source_id=source.id,
            request=request,
            commodity_code_id=commodity_code.id if commodity_code else None,
            checked_at=started_at,
        )
        if commodity_code is None:
            message = f"trade commodity code not found or inactive: {request.hs_code}"
            collector_run.status = "error"
            collector_run.finished_at = _to_utc(self.clock())
            collector_run.error_message = message
            session.flush()
            return _result_from_run(self, collector_run, started_at, request=request, errors_count=1)

        stats = self._collect_request(session, source, collector_run, commodity_code, request)

        collector_run.finished_at = _to_utc(self.clock())
        collector_run.records_found = stats.records_found
        collector_run.records_written = stats.records_written
        if not stats.errors and stats.conflicts_count == 0:
            collector_run.status = "success"
        elif stats.records_found > 0 or stats.records_written > 0:
            collector_run.status = "partial_success"
        else:
            collector_run.status = "error"
        collector_run.error_message = "\n".join(stats.errors) if stats.errors else None
        session.flush()

        return UnComtradeCollectorResult(
            run_id=collector_run.id,
            source_code=self.source_code,
            collector_name=self.collector_name,
            parser_version=self.parser_version,
            started_at=started_at,
            finished_at=collector_run.finished_at,
            status=collector_run.status,
            records_found=stats.records_found,
            records_written=stats.records_written,
            raw_response_ids=stats.raw_response_ids,
            error_message=collector_run.error_message,
            errors_count=len(stats.errors),
            hs_code=request.hs_code,
            from_period=request.from_period,
            to_period=request.to_period,
            reporter=request.reporter.code,
            partner=request.partner.code,
            flow=request.flow_direction,
            maxrecords=request.maxrecords,
            skipped_existing=stats.skipped_existing,
            conflicts_count=stats.conflicts_count,
            skipped_malformed=stats.skipped_malformed,
        )

    def _collect_request(
        self,
        session: Session,
        source: Source,
        collector_run: CollectorRun,
        commodity_code: TradeCommodityCode,
        request: UnComtradeRequest,
    ) -> _TradeStats:
        stats = _TradeStats()
        params = build_un_comtrade_params(request)
        try:
            response = self.http_client.get(ENDPOINT, params=params, headers=HEADERS, timeout=self.timeout)
            fetched_at = _to_utc(self.clock())
        except httpx.TimeoutException as exc:
            stats.errors.append(f"UN Comtrade request timeout: {exc}")
            return stats
        except httpx.RequestError as exc:
            stats.errors.append(f"UN Comtrade connection error: {exc}")
            return stats

        raw_response = self._save_raw_response(session, source, collector_run, response, fetched_at)
        stats.raw_response_ids.append(raw_response.id)

        rows, malformed, response_checks = assess_un_comtrade_response(
            payload=response.content,
            content_type=response.headers.get("content-type"),
            status_code=response.status_code,
            request=request,
            fetched_at=fetched_at,
        )
        stats.skipped_malformed = len(malformed)
        _write_response_checks(
            session,
            source_id=source.id,
            raw_response_id=raw_response.id,
            request=request,
            checks=response_checks,
            checked_at=fetched_at,
        )
        _write_malformed_row_checks(
            session,
            source_id=source.id,
            raw_response_id=raw_response.id,
            request=request,
            malformed=malformed,
            checked_at=fetched_at,
        )

        if response.status_code != 200:
            stats.errors.append(f"UN Comtrade HTTP status {response.status_code}; url={response.url}")
            return stats
        if not rows and _has_parser_error(response_checks):
            stats.errors.append("UN Comtrade response parser produced no trade rows")
            return stats

        for row in rows:
            stats.records_found += 1
            source_record_hash = build_trade_source_record_hash(
                source_code=self.source_code,
                hs_code=request.hs_code,
                row=row,
            )
            _write_row_quality_checks(
                session,
                source_id=source.id,
                raw_response_id=raw_response.id,
                trade_commodity_code_id=commodity_code.id,
                row=row,
                source_record_hash=source_record_hash,
                checked_at=fetched_at,
            )
            existing = _find_existing_trade_flow(
                session,
                source_id=source.id,
                trade_commodity_code_id=commodity_code.id,
                row=row,
            )
            if existing is not None:
                if existing.source_record_hash == source_record_hash:
                    stats.skipped_existing += 1
                    continue
                stats.conflicts_count += 1
                _write_conflict_quality_check(
                    session,
                    source_id=source.id,
                    raw_response_id=raw_response.id,
                    existing=existing,
                    row=row,
                    incoming_source_record_hash=source_record_hash,
                    checked_at=fetched_at,
                )
                continue

            session.add(
                TradeFlow(
                    source_id=source.id,
                    raw_response_id=raw_response.id,
                    collector_run_id=collector_run.id,
                    trade_commodity_code_id=commodity_code.id,
                    source_record_id=row.source_record_id,
                    reporter_code=row.reporter_code,
                    reporter_name=row.reporter_name,
                    partner_code=row.partner_code,
                    partner_name=row.partner_name,
                    flow_direction=row.flow_direction,
                    trade_period=row.trade_period,
                    period_start=row.period_start,
                    period_end=row.period_end,
                    frequency=row.frequency,
                    quantity=row.quantity,
                    quantity_unit=row.quantity_unit,
                    trade_value_usd=row.trade_value_usd,
                    trade_value_local=row.trade_value_local,
                    currency=row.currency,
                    unit_value_usd=row.unit_value_usd,
                    net_weight_kg=row.net_weight_kg,
                    gross_weight_kg=row.gross_weight_kg,
                    published_at=row.published_at,
                    fetched_at=fetched_at,
                    source_record_hash=source_record_hash,
                    source_payload_hash=raw_response.sha256,
                    metadata_json={
                        "source": self.source_code,
                        "endpoint": ENDPOINT,
                        "request_params": build_un_comtrade_params(request),
                        "raw": row.raw,
                    },
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
            extension="json",
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


def build_un_comtrade_request(
    *,
    hs_code: str,
    from_period: str,
    to_period: str,
    reporter: str,
    partner: str,
    flow: str,
    maxrecords: int | None,
) -> UnComtradeRequest:
    hs_code = hs_code.strip()
    if not is_supported_hs_code(hs_code):
        supported = ", ".join(SUPPORTED_HS_CODES)
        raise ValueError(f"unsupported HS code: {hs_code}; supported codes: {supported}")
    from_period = _normalize_period(from_period)
    to_period = _normalize_period(to_period)
    validate_period_range(from_period=from_period, to_period=to_period)
    flow_direction = _normalize_flow(flow)
    resolved_maxrecords = maxrecords if maxrecords is not None else DEFAULT_MAXRECORDS
    validate_maxrecords(resolved_maxrecords)
    return UnComtradeRequest(
        hs_code=hs_code,
        from_period=from_period,
        to_period=to_period,
        reporter=resolve_trade_partner(reporter, allow_world=False),
        partner=resolve_trade_partner(partner, allow_world=True),
        flow_direction=flow_direction,
        maxrecords=resolved_maxrecords,
    )


def build_un_comtrade_params(request: UnComtradeRequest) -> dict[str, str]:
    periods = ",".join(period.replace("-", "") for period in month_periods(request.from_period, request.to_period))
    return un_comtrade_params(
        hs_code=request.hs_code,
        period=periods,
        reporter=request.reporter,
        partner=request.partner,
        flow_direction=request.flow_direction,
        maxrecords=request.maxrecords,
    )


def validate_period_range(*, from_period: str, to_period: str, max_months: int = MAX_MONTHS_PER_RUN) -> None:
    if from_period > to_period:
        raise ValueError("from_period must be on or before to_period")
    months_count = len(tuple(month_periods(from_period, to_period)))
    if months_count > max_months:
        raise ValueError(f"period range exceeds max allowed months: {months_count} > {max_months}")


def validate_maxrecords(value: int, *, maximum: int = MAX_MAXRECORDS) -> None:
    if value <= 0:
        raise ValueError("maxrecords must be positive")
    if value > maximum:
        raise ValueError(f"maxrecords must be <= {maximum}")


def month_periods(from_period: str, to_period: str) -> tuple[str, ...]:
    start_year, start_month = _period_parts(from_period)
    end_year, end_month = _period_parts(to_period)
    periods: list[str] = []
    year = start_year
    month = start_month
    while (year, month) <= (end_year, end_month):
        periods.append(f"{year:04d}-{month:02d}")
        month += 1
        if month == 13:
            year += 1
            month = 1
    return tuple(periods)


def assess_un_comtrade_response(
    *,
    payload: bytes,
    content_type: str | None,
    status_code: int | None,
    request: UnComtradeRequest,
    fetched_at: datetime,
) -> tuple[list[ParsedTradeFlow], list[dict[str, Any]], list[TradeResponseCheck]]:
    checks = [
        TradeResponseCheck(
            "trade_raw_response_present",
            "pass" if payload is not None else "fail",
            "error" if payload is None else "info",
            {"status_code": status_code, "hs_code": request.hs_code},
        ),
        TradeResponseCheck(
            "trade_raw_response_non_empty",
            "pass" if payload else "fail",
            "error" if not payload else "info",
            {"bytes_size": len(payload), "status_code": status_code, "hs_code": request.hs_code},
        ),
        _content_type_check(content_type, hs_code=request.hs_code),
    ]
    rows: list[ParsedTradeFlow] = []
    malformed: list[dict[str, Any]] = []
    rows_array_present = False
    raw_rows_count = 0
    parse_error: str | None = None
    if payload:
        try:
            rows, malformed, rows_array_present, raw_rows_count = parse_un_comtrade_rows(
                payload,
                request=request,
                fetched_at=fetched_at,
            )
        except UnComtradeParseError as exc:
            parse_error = str(exc)
    else:
        parse_error = "empty response"
    checks.append(
        TradeResponseCheck(
            "trade_rows_present",
            "pass" if rows else "fail",
            "warning" if rows_array_present and not rows else "error" if not rows else "info",
            {
                "hs_code": request.hs_code,
                "rows_array_present": rows_array_present,
                "raw_rows_count": raw_rows_count,
                "parsed_rows_count": len(rows),
                "malformed_rows_count": len(malformed),
                "error": parse_error,
            },
        )
    )
    return rows, malformed, checks


def parse_un_comtrade_rows(
    payload: bytes | str | dict[str, Any],
    *,
    request: UnComtradeRequest,
    fetched_at: datetime,
) -> tuple[list[ParsedTradeFlow], list[dict[str, Any]], bool, int]:
    data = _json_payload(payload)
    raw_rows = _raw_data_rows(data)
    rows_array_present = isinstance(raw_rows, list)
    if raw_rows is None:
        raise UnComtradeParseError("missing data array")
    rows: list[ParsedTradeFlow] = []
    malformed: list[dict[str, Any]] = []
    for index, raw_row in enumerate(raw_rows):
        if not isinstance(raw_row, dict):
            malformed.append({"index": index, "error": "trade row is not an object", "raw_type": type(raw_row).__name__})
            continue
        try:
            rows.append(_parse_trade_row(raw_row, request=request, fetched_at=fetched_at))
        except UnComtradeParseError as exc:
            malformed.append({"index": index, "error": str(exc), "raw_keys": sorted(str(key) for key in raw_row.keys())})
    return rows, malformed, rows_array_present, len(raw_rows)


def build_trade_source_record_hash(*, source_code: str, hs_code: str, row: ParsedTradeFlow) -> str:
    return stable_json_hash(
        {
            "source_code": source_code,
            "hs_code": hs_code,
            "source_record_id": row.source_record_id,
            "reporter_code": row.reporter_code,
            "partner_code": row.partner_code,
            "flow_direction": row.flow_direction,
            "trade_period": row.trade_period,
            "period_start": row.period_start.isoformat(),
            "period_end": row.period_end.isoformat(),
            "frequency": row.frequency,
            "quantity": _canonical_decimal(row.quantity),
            "quantity_unit": row.quantity_unit,
            "trade_value_usd": _canonical_decimal(row.trade_value_usd),
            "trade_value_local": _canonical_decimal(row.trade_value_local),
            "currency": row.currency,
            "unit_value_usd": _canonical_decimal(row.unit_value_usd),
            "net_weight_kg": _canonical_decimal(row.net_weight_kg),
            "gross_weight_kg": _canonical_decimal(row.gross_weight_kg),
        }
    )


def _parse_trade_row(raw: dict[str, Any], *, request: UnComtradeRequest, fetched_at: datetime) -> ParsedTradeFlow:
    period = _string_value(raw, "period", "periodDesc", "refPeriodId") or request.from_period.replace("-", "")
    normalized_period = _period_from_raw(period)
    period_start, period_end = period_bounds(normalized_period)
    quantity = _decimal_or_none(_first_present(raw, "qty", "quantity", "primaryQuantity", "qtyValue"))
    trade_value_usd = _decimal_or_none(_first_present(raw, "primaryValue", "tradeValue", "tradeValueUsd", "fobvalue", "cifvalue"))
    net_weight_kg = _decimal_or_none(_first_present(raw, "netWgt", "netWeight", "netWeightKg"))
    gross_weight_kg = _decimal_or_none(_first_present(raw, "grossWgt", "grossWeight", "grossWeightKg"))
    unit_value_usd = _decimal_or_none(_first_present(raw, "unitValue", "unitValueUsd"))
    if unit_value_usd is None and trade_value_usd is not None and quantity is not None and quantity != 0:
        unit_value_usd = trade_value_usd / quantity
    reporter_code = request.reporter.code
    partner_code = request.partner.code
    return ParsedTradeFlow(
        source_record_id=_source_record_id(raw, request=request, period=normalized_period),
        reporter_code=reporter_code,
        reporter_name=_string_value(raw, "reporterDesc", "reporterName") or request.reporter.name,
        partner_code=partner_code,
        partner_name=_string_value(raw, "partnerDesc", "partnerName") or request.partner.name,
        flow_direction=request.flow_direction,
        trade_period=normalized_period,
        period_start=period_start,
        period_end=period_end,
        frequency="monthly",
        quantity=quantity,
        quantity_unit=_string_value(raw, "qtyUnitAbbr", "qtyUnit", "unit") or None,
        trade_value_usd=trade_value_usd,
        trade_value_local=_decimal_or_none(_first_present(raw, "tradeValueLocal")),
        currency=_string_value(raw, "currency") or "USD",
        unit_value_usd=unit_value_usd,
        net_weight_kg=net_weight_kg,
        gross_weight_kg=gross_weight_kg,
        published_at=_parse_datetime(_first_present(raw, "publicationDate", "publishedAt", "updatedAt")),
        raw={
            "source_row": raw,
            "fetched_at": _to_utc(fetched_at).isoformat(),
            "request_reporter_code": request.reporter.request_code,
            "request_partner_code": request.partner.request_code,
            "request_flow_code": FLOW_CODE_BY_DIRECTION[request.flow_direction],
        },
    )


def period_bounds(period: str) -> tuple[date, date]:
    year, month = _period_parts(period)
    last_day = monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def _find_trade_commodity_code(session: Session, *, hs_code: str) -> TradeCommodityCode | None:
    return session.scalar(
        select(TradeCommodityCode)
        .where(
            TradeCommodityCode.code_system == "HS",
            TradeCommodityCode.commodity_code == hs_code,
            TradeCommodityCode.is_active.is_(True),
        )
        .limit(1)
    )


def _find_existing_trade_flow(
    session: Session,
    *,
    source_id: int,
    trade_commodity_code_id: int,
    row: ParsedTradeFlow,
) -> TradeFlow | None:
    return session.scalar(
        select(TradeFlow)
        .where(
            TradeFlow.source_id == source_id,
            TradeFlow.trade_commodity_code_id == trade_commodity_code_id,
            TradeFlow.reporter_code == row.reporter_code,
            TradeFlow.partner_code == row.partner_code,
            TradeFlow.flow_direction == row.flow_direction,
            TradeFlow.frequency == row.frequency,
            TradeFlow.period_start == row.period_start,
            TradeFlow.period_end == row.period_end,
        )
        .limit(1)
    )


def _write_request_quality_checks(
    session: Session,
    *,
    source_id: int,
    request: UnComtradeRequest,
    commodity_code_id: int | None,
    checked_at: datetime,
) -> None:
    _write_quality_check(
        session,
        source_id=source_id,
        table_name="trade_commodity_codes",
        check_name="trade_hs_code_found",
        status="pass" if commodity_code_id is not None else "fail",
        severity="info" if commodity_code_id is not None else "error",
        details={"hs_code": request.hs_code, "trade_commodity_code_id": commodity_code_id},
        checked_at=checked_at,
    )
    _write_quality_check(
        session,
        source_id=source_id,
        table_name="trade_flows",
        check_name="trade_request_period_range_valid",
        status="pass",
        severity="info",
        details={
            "from_period": request.from_period,
            "to_period": request.to_period,
            "max_months_per_run": MAX_MONTHS_PER_RUN,
            "reporter": request.reporter.code,
            "partner": request.partner.code,
            "flow": request.flow_direction,
            "maxrecords": request.maxrecords,
        },
        checked_at=checked_at,
    )


def _write_response_checks(
    session: Session,
    *,
    source_id: int,
    raw_response_id: int,
    request: UnComtradeRequest,
    checks: list[TradeResponseCheck],
    checked_at: datetime,
) -> None:
    for check in checks:
        _write_quality_check(
            session,
            source_id=source_id,
            table_name="raw_responses",
            check_name=check.check_name,
            status=check.status,
            severity=check.severity,
            details={**check.details, "raw_response_id": raw_response_id, "hs_code": request.hs_code},
            checked_at=checked_at,
        )


def _write_malformed_row_checks(
    session: Session,
    *,
    source_id: int,
    raw_response_id: int,
    request: UnComtradeRequest,
    malformed: list[dict[str, Any]],
    checked_at: datetime,
) -> None:
    for item in malformed:
        _write_quality_check(
            session,
            source_id=source_id,
            table_name="trade_flows",
            check_name="trade_malformed_row_skipped",
            status="fail",
            severity="warning",
            details={**item, "raw_response_id": raw_response_id, "hs_code": request.hs_code},
            checked_at=checked_at,
        )


def _write_row_quality_checks(
    session: Session,
    *,
    source_id: int,
    raw_response_id: int,
    trade_commodity_code_id: int,
    row: ParsedTradeFlow,
    source_record_hash: str,
    checked_at: datetime,
) -> None:
    quantity_or_value = row.quantity is not None or row.trade_value_usd is not None
    checks = [
        ("trade_flow_period_valid", "pass", "info", {"trade_period": row.trade_period}),
        ("trade_flow_direction_valid", "pass", "info", {"flow_direction": row.flow_direction}),
        ("trade_reporter_present", "pass" if row.reporter_code else "fail", "info" if row.reporter_code else "error", {}),
        ("trade_partner_present", "pass" if row.partner_code else "fail", "info" if row.partner_code else "error", {}),
        (
            "trade_quantity_or_value_present",
            "pass" if quantity_or_value else "fail",
            "info" if quantity_or_value else "warning",
            {"quantity": _canonical_decimal(row.quantity), "trade_value_usd": _canonical_decimal(row.trade_value_usd)},
        ),
        (
            "trade_source_record_hash_present",
            "pass" if source_record_hash else "fail",
            "info" if source_record_hash else "error",
            {"source_record_hash": source_record_hash},
        ),
        ("trade_raw_linkage_present", "pass" if raw_response_id else "fail", "info" if raw_response_id else "error", {}),
    ]
    details = {
        "raw_response_id": raw_response_id,
        "trade_commodity_code_id": trade_commodity_code_id,
        "reporter_code": row.reporter_code,
        "partner_code": row.partner_code,
        "flow_direction": row.flow_direction,
        "period_start": row.period_start.isoformat(),
        "period_end": row.period_end.isoformat(),
    }
    for check_name, status, severity, extra in checks:
        _write_quality_check(
            session,
            source_id=source_id,
            table_name="trade_flows",
            check_name=check_name,
            status=status,
            severity=severity,
            details={**details, **extra},
            checked_at=checked_at,
        )


def _write_conflict_quality_check(
    session: Session,
    *,
    source_id: int,
    raw_response_id: int,
    existing: TradeFlow,
    row: ParsedTradeFlow,
    incoming_source_record_hash: str,
    checked_at: datetime,
) -> None:
    changed_fields = _changed_trade_fields(existing, row)
    _write_quality_check(
        session,
        source_id=source_id,
        table_name="trade_flows",
        check_name="trade_existing_flow_hash_changed",
        status="fail",
        severity="warning",
        details={
            "existing_id": existing.id,
            "raw_response_id": raw_response_id,
            "reporter_code": row.reporter_code,
            "partner_code": row.partner_code,
            "flow_direction": row.flow_direction,
            "period_start": row.period_start.isoformat(),
            "period_end": row.period_end.isoformat(),
            "existing_source_record_hash": existing.source_record_hash,
            "incoming_source_record_hash": incoming_source_record_hash,
            "changed_fields": changed_fields,
            "existing_values": _trade_values_from_model(existing),
            "incoming_values": _trade_values_from_row(row),
            "policy_decision": "rejected_hash_conflict_no_overwrite",
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
    collector: UnComtradeCollector,
    collector_run: CollectorRun,
    started_at: datetime,
    *,
    request: UnComtradeRequest,
    errors_count: int,
) -> UnComtradeCollectorResult:
    return UnComtradeCollectorResult(
        run_id=collector_run.id,
        source_code=collector.source_code,
        collector_name=collector.collector_name,
        parser_version=collector.parser_version,
        started_at=started_at,
        finished_at=collector_run.finished_at or started_at,
        status=collector_run.status,
        records_found=collector_run.records_found,
        records_written=collector_run.records_written,
        raw_response_ids=[],
        error_message=collector_run.error_message,
        errors_count=errors_count,
        hs_code=request.hs_code,
        from_period=request.from_period,
        to_period=request.to_period,
        reporter=request.reporter.code,
        partner=request.partner.code,
        flow=request.flow_direction,
        maxrecords=request.maxrecords,
    )


def _json_payload(payload: bytes | str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    text = payload.decode("utf-8-sig") if isinstance(payload, bytes) else payload
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise UnComtradeParseError(f"invalid JSON response: {exc}") from exc
    if not isinstance(data, dict):
        raise UnComtradeParseError("JSON response root is not an object")
    return data


def _raw_data_rows(data: dict[str, Any]) -> list[Any] | None:
    for key in ("data", "dataset", "results", "items"):
        value = data.get(key)
        if isinstance(value, list):
            return value
    return None


def _content_type_check(content_type: str | None, *, hs_code: str) -> TradeResponseCheck:
    normalized = (content_type or "").split(";")[0].strip().lower()
    ok = normalized in {"application/json", "text/json", "text/plain"} or normalized.endswith("+json")
    return TradeResponseCheck(
        "trade_content_type_expected",
        "pass" if ok else "fail",
        "info" if ok else "warning",
        {"content_type": content_type, "hs_code": hs_code},
    )


def _has_parser_error(checks: list[TradeResponseCheck]) -> bool:
    return any(check.check_name == "trade_rows_present" and check.status == "fail" and check.severity == "error" for check in checks)


def _normalize_period(value: str) -> str:
    cleaned = value.strip()
    if len(cleaned) == 6 and cleaned.isdigit():
        cleaned = f"{cleaned[:4]}-{cleaned[4:]}"
    try:
        year, month = _period_parts(cleaned)
    except ValueError as exc:
        raise ValueError("period must use YYYY-MM format") from exc
    return f"{year:04d}-{month:02d}"


def _period_from_raw(value: str) -> str:
    try:
        return _normalize_period(str(value))
    except ValueError as exc:
        raise UnComtradeParseError("trade row period must use YYYY-MM or YYYYMM format") from exc


def _period_parts(period: str) -> tuple[int, int]:
    if len(period) != 7 or period[4] != "-":
        raise ValueError("bad period")
    year = int(period[:4])
    month = int(period[5:])
    if month < 1 or month > 12:
        raise ValueError("bad month")
    return year, month


def _normalize_flow(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_")
    aliases = {"imports": "import", "exports": "export", "reexports": "re_export", "reimports": "re_import"}
    normalized = aliases.get(normalized, normalized)
    if normalized not in FLOW_CODE_BY_DIRECTION:
        supported = ", ".join(FLOW_CODE_BY_DIRECTION)
        raise ValueError(f"unsupported flow: {value}; supported flows: {supported}")
    return normalized


def _first_present(raw: dict[str, Any], *keys: str) -> Any | None:
    for key in keys:
        value = raw.get(key)
        if value not in (None, ""):
            return value
    return None


def _string_value(raw: dict[str, Any], *keys: str) -> str | None:
    value = _first_present(raw, *keys)
    if value is None:
        return None
    return str(value).strip() or None


def _decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None


def _parse_datetime(value: Any | None) -> datetime | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return _to_utc(parsed)


def _source_record_id(raw: dict[str, Any], *, request: UnComtradeRequest, period: str) -> str:
    explicit = _string_value(raw, "id", "sourceRecordId", "datasetCode")
    if explicit:
        return explicit
    return "|".join(
        [
            request.hs_code,
            request.reporter.code,
            request.partner.code,
            request.flow_direction,
            period,
        ]
    )


def _changed_trade_fields(existing: TradeFlow, row: ParsedTradeFlow) -> list[str]:
    existing_values = _trade_values_from_model(existing)
    incoming_values = _trade_values_from_row(row)
    return [field for field, incoming in incoming_values.items() if existing_values.get(field) != incoming]


def _trade_values_from_model(row: TradeFlow) -> dict[str, Any]:
    return {
        "quantity": _canonical_decimal(row.quantity),
        "quantity_unit": row.quantity_unit,
        "trade_value_usd": _canonical_decimal(row.trade_value_usd),
        "trade_value_local": _canonical_decimal(row.trade_value_local),
        "currency": row.currency,
        "unit_value_usd": _canonical_decimal(row.unit_value_usd),
        "net_weight_kg": _canonical_decimal(row.net_weight_kg),
        "gross_weight_kg": _canonical_decimal(row.gross_weight_kg),
    }


def _trade_values_from_row(row: ParsedTradeFlow) -> dict[str, Any]:
    return {
        "quantity": _canonical_decimal(row.quantity),
        "quantity_unit": row.quantity_unit,
        "trade_value_usd": _canonical_decimal(row.trade_value_usd),
        "trade_value_local": _canonical_decimal(row.trade_value_local),
        "currency": row.currency,
        "unit_value_usd": _canonical_decimal(row.unit_value_usd),
        "net_weight_kg": _canonical_decimal(row.net_weight_kg),
        "gross_weight_kg": _canonical_decimal(row.gross_weight_kg),
    }


def _canonical_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.normalize(), "f")


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _normalize_run_type(value: str) -> str:
    if value == "scheduled":
        raise ValueError("scheduled runs are not supported for un_comtrade")
    if value not in {"manual", "backfill"}:
        raise ValueError("run_type must be manual or backfill")
    return value
