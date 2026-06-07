from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors.base import BaseCollector, CollectorResult
from app.collectors.energy.fred_energy_config import (
    COLLECTOR_NAME,
    ENDPOINT,
    FRED_ENERGY_SERIES,
    FRED_ENERGY_SERIES_BY_ID,
    HEADERS,
    PARSER_VERSION,
    REQUEST_TIMEOUT,
    SOURCE_CODE,
    FredEnergySeries,
    fred_csv_params,
)
from app.db.models import CollectorRun, DataQualityCheck, EnergyPrice, RawResponse, Source
from app.db.session import session_scope
from app.storage.hashes import stable_json_hash
from app.storage.raw_store import RawStore

logger = logging.getLogger(__name__)

DATE_COLUMNS = ("observation_date", "date", "DATE")
MISSING_VALUE_MARKERS = {"", ".", "nan", "NaN", "NA", "N/A", "null", "NULL"}


class FredEnergyParseError(ValueError):
    """Raised when a FRED CSV response cannot be parsed safely."""


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
class ParsedEnergyPrice:
    series: FredEnergySeries
    period_start: date
    period_end: date
    observed_at: datetime
    value: Decimal
    raw: dict[str, Any]


@dataclass(frozen=True)
class EnergyResponseCheck:
    check_name: str
    status: str
    severity: str
    details: dict[str, Any]


@dataclass(frozen=True)
class FredEnergyCollectorResult(CollectorResult):
    series_requested: int = 0
    series_success: int = 0
    series_failed: int = 0
    skipped_existing: int = 0
    conflicts_count: int = 0
    instruments: tuple[str, ...] = ()
    from_date: str | None = None
    to_date: str | None = None


@dataclass
class _SeriesStats:
    series_id: str
    records_found: int = 0
    records_written: int = 0
    skipped_existing: int = 0
    conflicts_count: int = 0
    raw_response_ids: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class FredEnergyPricesCollector(BaseCollector):
    source_code = SOURCE_CODE
    collector_name = COLLECTOR_NAME
    parser_version = PARSER_VERSION

    def __init__(
        self,
        *,
        series: tuple[FredEnergySeries, ...] = FRED_ENERGY_SERIES,
        http_client: HttpClient | None = None,
        raw_store: RawStore | None = None,
        timeout: float = REQUEST_TIMEOUT,
        clock: Any | None = None,
    ) -> None:
        super().__init__()
        self.series = series
        self.http_client = http_client or httpx.Client(follow_redirects=True)
        self.raw_store = raw_store or RawStore()
        self.timeout = timeout
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def run(
        self,
        session: Session | None = None,
        *,
        series_id: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        run_type: str = "manual",
    ) -> FredEnergyCollectorResult:
        run_type = _normalize_run_type(run_type)
        if from_date and to_date and from_date > to_date:
            raise ValueError("from_date must be on or before to_date")
        selected = _select_series(self.series, series_id)
        if session is None:
            with session_scope() as scoped_session:
                return self._run_with_session(
                    scoped_session,
                    selected_series=selected,
                    from_date=from_date,
                    to_date=to_date,
                    run_type=run_type,
                )
        return self._run_with_session(
            session,
            selected_series=selected,
            from_date=from_date,
            to_date=to_date,
            run_type=run_type,
        )

    def _run_with_session(
        self,
        session: Session,
        *,
        selected_series: tuple[FredEnergySeries, ...],
        from_date: date | None,
        to_date: date | None,
        run_type: str,
    ) -> FredEnergyCollectorResult:
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
                check_name="energy_source_mapping_found",
                status="fail",
                severity="error",
                details={"source_code": self.source_code},
                checked_at=started_at,
            )
            collector_run.status = "error"
            collector_run.finished_at = _to_utc(self.clock())
            collector_run.error_message = message
            session.flush()
            return _result_from_run(
                self,
                collector_run,
                started_at,
                selected_series=selected_series,
                from_date=from_date,
                to_date=to_date,
                series_success=0,
                series_failed=len(selected_series),
                skipped_existing=0,
                conflicts_count=0,
                raw_response_ids=[],
                errors_count=1,
            )

        _write_quality_check(
            session,
            source_id=source.id,
            table_name="sources",
            check_name="energy_source_mapping_found",
            status="pass",
            severity="info",
            details={"source_code": self.source_code, "source_id": source.id},
            checked_at=started_at,
        )

        raw_response_ids: list[int] = []
        all_errors: list[str] = []
        records_found = 0
        records_written = 0
        skipped_existing = 0
        conflicts_count = 0
        series_success = 0
        series_failed = 0

        for item in selected_series:
            stats = self._collect_series(
                session,
                source,
                collector_run,
                item,
                from_date=from_date,
                to_date=to_date,
            )
            raw_response_ids.extend(stats.raw_response_ids)
            all_errors.extend(stats.errors)
            records_found += stats.records_found
            records_written += stats.records_written
            skipped_existing += stats.skipped_existing
            conflicts_count += stats.conflicts_count
            if stats.errors:
                series_failed += 1
            else:
                series_success += 1

        collector_run.finished_at = _to_utc(self.clock())
        collector_run.records_found = records_found
        collector_run.records_written = records_written
        if not all_errors and conflicts_count == 0 and series_success == len(selected_series):
            collector_run.status = "success"
        elif records_found > 0 or series_success > 0:
            collector_run.status = "partial_success"
        else:
            collector_run.status = "error"
        collector_run.error_message = "\n".join(all_errors) if all_errors else None
        session.flush()

        return FredEnergyCollectorResult(
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
            series_requested=len(selected_series),
            series_success=series_success,
            series_failed=series_failed,
            skipped_existing=skipped_existing,
            conflicts_count=conflicts_count,
            instruments=tuple(item.instrument_code for item in selected_series),
            from_date=from_date.isoformat() if from_date else None,
            to_date=to_date.isoformat() if to_date else None,
        )

    def _collect_series(
        self,
        session: Session,
        source: Source,
        collector_run: CollectorRun,
        series: FredEnergySeries,
        *,
        from_date: date | None,
        to_date: date | None,
    ) -> _SeriesStats:
        stats = _SeriesStats(series_id=series.external_id)
        checked_at = _to_utc(self.clock())
        _write_quality_check(
            session,
            source_id=source.id,
            table_name="energy_prices",
            check_name="energy_date_range_valid",
            status="pass" if not (from_date and to_date and from_date > to_date) else "fail",
            severity="error" if from_date and to_date and from_date > to_date else "info",
            details={
                "series_id": series.external_id,
                "from_date": from_date.isoformat() if from_date else None,
                "to_date": to_date.isoformat() if to_date else None,
            },
            checked_at=checked_at,
        )
        try:
            response = self.http_client.get(
                ENDPOINT,
                params=fred_csv_params(series.external_id),
                headers=HEADERS,
                timeout=self.timeout,
            )
            fetched_at = _to_utc(self.clock())
        except httpx.TimeoutException as exc:
            stats.errors.append(f"{series.external_id}: timeout: {exc}")
            return stats
        except httpx.RequestError as exc:
            stats.errors.append(f"{series.external_id}: connection error: {exc}")
            return stats

        raw_response = self._save_raw_response(session, source, collector_run, response, fetched_at)
        stats.raw_response_ids.append(raw_response.id)

        rows, checks = assess_fred_csv_response(
            payload=response.content,
            content_type=response.headers.get("content-type"),
            status_code=response.status_code,
            series=series,
            from_date=from_date,
            to_date=to_date,
        )
        _write_response_checks(
            session,
            source_id=source.id,
            raw_response_id=raw_response.id,
            series=series,
            checks=checks,
            checked_at=fetched_at,
        )
        if response.status_code != 200:
            stats.errors.append(f"{series.external_id}: HTTP status {response.status_code}")
            return stats
        if not rows:
            stats.errors.append(f"{series.external_id}: no energy rows parsed")
            return stats

        for row in rows:
            stats.records_found += 1
            source_record_hash = build_energy_source_record_hash(source_code=self.source_code, row=row)
            _write_row_quality_checks(
                session,
                source_id=source.id,
                raw_response_id=raw_response.id,
                row=row,
                source_record_hash=source_record_hash,
                checked_at=fetched_at,
            )
            existing = _find_existing_price(
                session,
                source_id=source.id,
                instrument_code=series.instrument_code,
                frequency=series.frequency,
                period_start=row.period_start,
                period_end=row.period_end,
            )
            if existing is not None:
                if existing.source_record_hash == source_record_hash:
                    stats.skipped_existing += 1
                    continue
                stats.conflicts_count += 1
                _write_quality_check(
                    session,
                    source_id=source.id,
                    table_name="energy_prices",
                    check_name="energy_existing_record_hash_changed",
                    status="fail",
                    severity="warning",
                    details={
                        "series_id": series.external_id,
                        "instrument_code": series.instrument_code,
                        "frequency": series.frequency,
                        "period_start": row.period_start.isoformat(),
                        "period_end": row.period_end.isoformat(),
                        "existing_id": existing.id,
                        "existing_value": _canonical_decimal(existing.value),
                        "incoming_value": _canonical_decimal(row.value),
                        "existing_source_record_hash": existing.source_record_hash,
                        "incoming_source_record_hash": source_record_hash,
                        "existing_raw_response_id": existing.raw_response_id,
                        "incoming_raw_response_id": raw_response.id,
                        "policy_decision": "rejected_hash_conflict_no_overwrite",
                    },
                    checked_at=fetched_at,
                )
                continue

            session.add(
                EnergyPrice(
                    source_id=source.id,
                    raw_response_id=raw_response.id,
                    collector_run_id=collector_run.id,
                    instrument_code=series.instrument_code,
                    external_id=series.external_id,
                    instrument_name=series.instrument_name,
                    instrument_category=series.instrument_category,
                    frequency=series.frequency,
                    period_start=row.period_start,
                    period_end=row.period_end,
                    observed_at=row.observed_at,
                    published_at=None,
                    fetched_at=fetched_at,
                    value=row.value,
                    currency=series.currency,
                    unit=series.unit,
                    normalized_value=row.value,
                    normalized_currency=series.currency,
                    normalized_unit=series.unit,
                    source_record_hash=source_record_hash,
                    source_payload_hash=raw_response.sha256,
                    metadata_json=_metadata_json(series=series, raw_response=raw_response),
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
            extension="csv",
            content_type=content_type,
        )
        raw_response = RawResponse(
            source_id=source.id,
            collector_run_id=collector_run.id,
            fetched_at=fetched_at,
            url=_response_url(response),
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


def assess_fred_csv_response(
    *,
    payload: bytes,
    content_type: str | None,
    status_code: int | None,
    series: FredEnergySeries,
    from_date: date | None = None,
    to_date: date | None = None,
) -> tuple[list[ParsedEnergyPrice], list[EnergyResponseCheck]]:
    checks = [
        EnergyResponseCheck(
            check_name="energy_raw_response_present",
            status="pass" if payload is not None else "fail",
            severity="error" if payload is None else "info",
            details={"series_id": series.external_id, "status_code": status_code},
        ),
        EnergyResponseCheck(
            check_name="energy_raw_response_non_empty",
            status="pass" if payload else "fail",
            severity="error" if not payload else "info",
            details={"series_id": series.external_id, "bytes_size": len(payload)},
        ),
        _content_type_check(content_type, series_id=series.external_id),
    ]
    rows: list[ParsedEnergyPrice] = []
    parse_error: str | None = None
    header_valid = False
    raw_rows_count = 0
    if payload:
        try:
            rows, header_valid, raw_rows_count = parse_fred_csv(
                payload,
                series=series,
                from_date=from_date,
                to_date=to_date,
            )
        except FredEnergyParseError as exc:
            parse_error = str(exc)
    else:
        parse_error = "empty response"

    checks.append(
        EnergyResponseCheck(
            check_name="energy_csv_header_valid",
            status="pass" if header_valid else "fail",
            severity="error" if not header_valid else "info",
            details={"series_id": series.external_id, "error": parse_error},
        )
    )
    checks.append(
        EnergyResponseCheck(
            check_name="energy_csv_rows_present",
            status="pass" if raw_rows_count > 0 else "fail",
            severity="error" if raw_rows_count == 0 else "info",
            details={"series_id": series.external_id, "raw_rows_count": raw_rows_count},
        )
    )
    checks.append(
        EnergyResponseCheck(
            check_name="energy_parsed_rows_gt_zero",
            status="pass" if rows else "fail",
            severity="error" if not rows else "info",
            details={
                "series_id": series.external_id,
                "parsed_rows_count": len(rows),
                "from_date": from_date.isoformat() if from_date else None,
                "to_date": to_date.isoformat() if to_date else None,
                "error": parse_error,
            },
        )
    )
    return rows, checks


def parse_fred_csv(
    payload: bytes | str,
    *,
    series: FredEnergySeries,
    from_date: date | None = None,
    to_date: date | None = None,
) -> tuple[list[ParsedEnergyPrice], bool, int]:
    text = payload.decode("utf-8-sig") if isinstance(payload, bytes) else payload
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise FredEnergyParseError("missing CSV header")
    date_column = _find_date_column(reader.fieldnames)
    value_column = _find_value_column(reader.fieldnames, series)
    header_valid = bool(date_column and value_column)
    if not header_valid:
        raise FredEnergyParseError(
            f"missing expected date/value columns for {series.external_id}; columns={reader.fieldnames}"
        )

    rows: list[ParsedEnergyPrice] = []
    raw_rows_count = 0
    for raw_row in reader:
        raw_rows_count += 1
        raw_date = (raw_row.get(date_column) or "").strip()
        if not raw_date:
            raise FredEnergyParseError(f"missing date value on row {raw_rows_count}")
        try:
            period_start = date.fromisoformat(raw_date)
        except ValueError as exc:
            raise FredEnergyParseError(f"bad date value {raw_date!r} for {series.external_id}") from exc
        if from_date and period_start < from_date:
            continue
        if to_date and period_start > to_date:
            continue
        raw_value = (raw_row.get(value_column) or "").strip()
        if raw_value in MISSING_VALUE_MARKERS:
            continue
        try:
            value = Decimal(raw_value)
        except (InvalidOperation, ValueError) as exc:
            raise FredEnergyParseError(
                f"bad numeric value {raw_value!r} for {series.external_id} on {period_start.isoformat()}"
            ) from exc
        rows.append(
            ParsedEnergyPrice(
                series=series,
                period_start=period_start,
                period_end=period_start,
                observed_at=datetime.combine(period_start, time.min, tzinfo=timezone.utc),
                value=value,
                raw=dict(raw_row),
            )
        )
    return rows, header_valid, raw_rows_count


def build_energy_source_record_hash(*, source_code: str, row: ParsedEnergyPrice) -> str:
    return stable_json_hash(
        {
            "source_code": source_code,
            "instrument_code": row.series.instrument_code,
            "frequency": row.series.frequency,
            "period_start": row.period_start.isoformat(),
            "period_end": row.period_end.isoformat(),
            "value": _canonical_decimal(row.value),
            "currency": row.series.currency,
            "unit": row.series.unit,
        }
    )


def _write_response_checks(
    session: Session,
    *,
    source_id: int,
    raw_response_id: int,
    series: FredEnergySeries,
    checks: list[EnergyResponseCheck],
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
            details={**check.details, "raw_response_id": raw_response_id, "instrument_code": series.instrument_code},
            checked_at=checked_at,
        )


def _write_row_quality_checks(
    session: Session,
    *,
    source_id: int,
    raw_response_id: int,
    row: ParsedEnergyPrice,
    source_record_hash: str,
    checked_at: datetime,
) -> None:
    details = {
        "series_id": row.series.external_id,
        "instrument_code": row.series.instrument_code,
        "frequency": row.series.frequency,
        "period_start": row.period_start.isoformat(),
        "period_end": row.period_end.isoformat(),
        "raw_response_id": raw_response_id,
        "value": _canonical_decimal(row.value),
    }
    _write_quality_check(
        session,
        source_id=source_id,
        table_name="energy_prices",
        check_name="energy_value_is_not_null",
        status="pass",
        severity="info",
        details=details,
        checked_at=checked_at,
    )
    _write_quality_check(
        session,
        source_id=source_id,
        table_name="energy_prices",
        check_name="energy_value_positive",
        status="pass" if row.value > 0 else "fail",
        severity="error" if row.value <= 0 else "info",
        details=details,
        checked_at=checked_at,
    )
    _write_quality_check(
        session,
        source_id=source_id,
        table_name="energy_prices",
        check_name="energy_source_record_hash_present",
        status="pass" if source_record_hash else "fail",
        severity="error" if not source_record_hash else "info",
        details={**details, "source_record_hash": source_record_hash},
        checked_at=checked_at,
    )


def _find_existing_price(
    session: Session,
    *,
    source_id: int,
    instrument_code: str,
    frequency: str,
    period_start: date,
    period_end: date,
) -> EnergyPrice | None:
    return session.scalar(
        select(EnergyPrice)
        .where(
            EnergyPrice.source_id == source_id,
            EnergyPrice.instrument_code == instrument_code,
            EnergyPrice.frequency == frequency,
            EnergyPrice.period_start == period_start,
            EnergyPrice.period_end == period_end,
        )
        .limit(1)
    )


def _metadata_json(*, series: FredEnergySeries, raw_response: RawResponse) -> dict[str, Any]:
    return {
        "fred_series_id": series.external_id,
        "source_url": raw_response.url,
        "frequency": series.frequency,
        "source_frequency": series.frequency,
        "unit_note": series.unit_note,
        "frequency_note": series.frequency_note,
        "parser_version": PARSER_VERSION,
        "missing_value_marker": ".",
    }


def _content_type_check(content_type: str | None, *, series_id: str) -> EnergyResponseCheck:
    if not content_type:
        return EnergyResponseCheck(
            check_name="energy_content_type_expected",
            status="skip",
            severity="info",
            details={"series_id": series_id, "content_type": None},
        )
    normalized = content_type.split(";")[0].strip().lower()
    expected = {"application/csv", "application/vnd.ms-excel", "text/csv", "text/plain"}
    return EnergyResponseCheck(
        check_name="energy_content_type_expected",
        status="pass" if normalized in expected else "fail",
        severity="warning" if normalized not in expected else "info",
        details={"series_id": series_id, "content_type": content_type},
    )


def _find_date_column(fieldnames: list[str]) -> str | None:
    lowered = {item.lower(): item for item in fieldnames}
    for candidate in DATE_COLUMNS:
        if candidate.lower() in lowered:
            return lowered[candidate.lower()]
    return None


def _find_value_column(fieldnames: list[str], series: FredEnergySeries) -> str | None:
    if series.external_id in fieldnames:
        return series.external_id
    if series.instrument_code in fieldnames:
        return series.instrument_code
    date_column = _find_date_column(fieldnames)
    candidates = [item for item in fieldnames if item != date_column]
    return candidates[0] if len(candidates) == 1 else None


def _select_series(series: tuple[FredEnergySeries, ...], series_id: str | None) -> tuple[FredEnergySeries, ...]:
    if series_id is None:
        return series
    normalized = series_id.strip().upper()
    selected = tuple(item for item in series if item.external_id == normalized or item.instrument_code == normalized)
    if not selected:
        raise ValueError(f"unknown FRED energy series: {series_id}")
    return selected


def is_known_series(series_id: str) -> bool:
    return series_id.strip().upper() in FRED_ENERGY_SERIES_BY_ID


def _normalize_run_type(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"manual", "backfill"}:
        raise ValueError("run_type must be either 'manual' or 'backfill'")
    return normalized


def _response_url(response: httpx.Response) -> str:
    try:
        return str(response.url)
    except RuntimeError:
        return ENDPOINT


def _canonical_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.normalize(), "f")


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


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
    collector: FredEnergyPricesCollector,
    collector_run: CollectorRun,
    started_at: datetime,
    *,
    selected_series: tuple[FredEnergySeries, ...],
    from_date: date | None,
    to_date: date | None,
    series_success: int,
    series_failed: int,
    skipped_existing: int,
    conflicts_count: int,
    raw_response_ids: list[int],
    errors_count: int,
) -> FredEnergyCollectorResult:
    return FredEnergyCollectorResult(
        run_id=collector_run.id,
        source_code=collector.source_code,
        collector_name=collector.collector_name,
        parser_version=collector.parser_version,
        started_at=started_at,
        finished_at=collector_run.finished_at or _to_utc(datetime.now(timezone.utc)),
        status=collector_run.status,
        records_found=collector_run.records_found,
        records_written=collector_run.records_written,
        raw_response_ids=raw_response_ids,
        error_message=collector_run.error_message,
        errors_count=errors_count,
        series_requested=len(selected_series),
        series_success=series_success,
        series_failed=series_failed,
        skipped_existing=skipped_existing,
        conflicts_count=conflicts_count,
        instruments=tuple(item.instrument_code for item in selected_series),
        from_date=from_date.isoformat() if from_date else None,
        to_date=to_date.isoformat() if to_date else None,
    )

