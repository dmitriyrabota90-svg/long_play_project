from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors.base import BaseCollector, CollectorResult
from app.collectors.supply_demand.usda_psd_config import (
    COLLECTOR_NAME,
    DEFAULT_MAXRECORDS,
    HEADERS,
    LIVE_PROBE_ENDPOINT_CANDIDATE,
    MAX_MARKETING_YEARS_PER_RUN,
    MAX_MAXRECORDS,
    PARSER_VERSION,
    REQUEST_TIMEOUT,
    SOURCE_CODE,
    SOURCE_SCHEMA_STATUS,
    SUPPORTED_METRICS,
    PsdCommodityFamily,
    PsdCountry,
    is_supported_metric,
    resolve_commodity_family,
    resolve_country,
    usda_psd_live_probe_params,
)
from app.db.models import CollectorRun, DataQualityCheck, RawResponse, Source, SupplyDemandCommodity, SupplyDemandObservation
from app.db.session import session_scope
from app.storage.hashes import stable_json_hash
from app.storage.raw_store import RawStore

logger = logging.getLogger(__name__)


class UsdaPsdParseError(ValueError):
    """Raised when a USDA PSD response cannot be parsed safely."""


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
class UsdaPsdRequest:
    commodity_family: PsdCommodityFamily
    from_marketing_year: int
    to_marketing_year: int
    country: PsdCountry
    maxrecords: int
    dry_run: bool = False
    fixture_file: Path | None = None
    live_probe: bool = False


@dataclass(frozen=True)
class ParsedSupplyDemandRow:
    source_record_id: str
    commodity_family: str
    product_code: str | None
    metric_name: str
    country_code: str
    country_name: str
    region_code: str | None
    region_name: str | None
    marketing_year: str
    marketing_year_start: date | None
    marketing_year_end: date | None
    report_month: int
    report_year: int
    report_published_at: datetime | None
    observed_period_start: date | None
    observed_period_end: date | None
    frequency: str
    estimate_type: str
    metric_value: Decimal
    metric_unit: str
    value_usd: Decimal | None
    is_forecast: bool
    is_revision: bool
    published_at: datetime | None
    raw: dict[str, Any]


@dataclass(frozen=True)
class PsdResponseCheck:
    check_name: str
    status: str
    severity: str
    details: dict[str, Any]


@dataclass(frozen=True)
class UsdaPsdCollectorResult(CollectorResult):
    commodity_family: str | None = None
    from_marketing_year: int | None = None
    to_marketing_year: int | None = None
    country: str | None = None
    maxrecords: int = DEFAULT_MAXRECORDS
    dry_run: bool = False
    fixture_file: str | None = None
    live_probe: bool = False
    skipped_existing: int = 0
    skipped_unmapped: int = 0
    skipped_malformed: int = 0
    conflicts_count: int = 0


@dataclass
class _PsdStats:
    records_found: int = 0
    records_written: int = 0
    skipped_existing: int = 0
    skipped_unmapped: int = 0
    skipped_malformed: int = 0
    conflicts_count: int = 0
    raw_response_ids: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class UsdaPsdCollector(BaseCollector):
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
        commodity_family: str,
        from_marketing_year: int,
        to_marketing_year: int,
        country: str,
        maxrecords: int | None = None,
        dry_run: bool = False,
        fixture_file: str | Path | None = None,
        live_probe: bool = False,
        run_type: str = "manual",
    ) -> UsdaPsdCollectorResult:
        run_type = _normalize_run_type(run_type)
        request = build_usda_psd_request(
            commodity_family=commodity_family,
            from_marketing_year=from_marketing_year,
            to_marketing_year=to_marketing_year,
            country=country,
            maxrecords=maxrecords,
            dry_run=dry_run,
            fixture_file=fixture_file,
            live_probe=live_probe,
        )
        if session is None:
            with session_scope() as scoped_session:
                return self._run_with_session(scoped_session, request=request, run_type=run_type)
        return self._run_with_session(session, request=request, run_type=run_type)

    def _run_with_session(self, session: Session, *, request: UsdaPsdRequest, run_type: str) -> UsdaPsdCollectorResult:
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
                check_name="supply_demand_source_mapping_found",
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

        _write_request_quality_checks(session, source_id=source.id, request=request, checked_at=started_at)
        stats = self._collect_request(session, source, collector_run, request)

        collector_run.finished_at = _to_utc(self.clock())
        collector_run.records_found = stats.records_found
        collector_run.records_written = stats.records_written
        if not stats.errors and stats.conflicts_count == 0 and stats.skipped_unmapped == 0 and stats.skipped_malformed == 0:
            collector_run.status = "success"
        elif stats.records_found > 0 or stats.records_written > 0:
            collector_run.status = "partial_success"
        else:
            collector_run.status = "error"
        collector_run.error_message = "\n".join(stats.errors) if stats.errors else None
        session.flush()

        return UsdaPsdCollectorResult(
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
            commodity_family=request.commodity_family.code,
            from_marketing_year=request.from_marketing_year,
            to_marketing_year=request.to_marketing_year,
            country=request.country.code,
            maxrecords=request.maxrecords,
            dry_run=request.dry_run,
            fixture_file=str(request.fixture_file) if request.fixture_file else None,
            live_probe=request.live_probe,
            skipped_existing=stats.skipped_existing,
            skipped_unmapped=stats.skipped_unmapped,
            skipped_malformed=stats.skipped_malformed,
            conflicts_count=stats.conflicts_count,
        )

    def _collect_request(
        self,
        session: Session,
        source: Source,
        collector_run: CollectorRun,
        request: UsdaPsdRequest,
    ) -> _PsdStats:
        stats = _PsdStats()
        try:
            response = self._fetch_response(request)
            fetched_at = _to_utc(self.clock())
        except (OSError, httpx.TimeoutException, httpx.RequestError, ValueError) as exc:
            stats.errors.append(f"USDA PSD request error: {exc}")
            return stats

        raw_response = self._save_raw_response(session, source, collector_run, response, fetched_at)
        stats.raw_response_ids.append(raw_response.id)

        rows, malformed, checks = assess_usda_psd_response(
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
            checks=checks,
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
            stats.errors.append(f"USDA PSD HTTP status {response.status_code}; url={response.url}")
            return stats
        if not rows and _has_parser_error(checks):
            stats.errors.append("USDA PSD response parser produced no supply-demand rows")
            return stats

        for row in rows[: request.maxrecords]:
            stats.records_found += 1
            mapping = _find_supply_demand_mapping(session, source_id=source.id, row=row)
            if mapping is None:
                stats.skipped_unmapped += 1
                _write_mapping_missing_quality_check(
                    session,
                    source_id=source.id,
                    raw_response_id=raw_response.id,
                    request=request,
                    row=row,
                    checked_at=fetched_at,
                )
                continue
            source_record_hash = build_supply_demand_source_record_hash(
                source_code=self.source_code,
                row=row,
                supply_demand_commodity_id=mapping.id,
            )
            _write_row_quality_checks(
                session,
                source_id=source.id,
                raw_response_id=raw_response.id,
                supply_demand_commodity_id=mapping.id,
                row=row,
                source_record_hash=source_record_hash,
                checked_at=fetched_at,
            )
            existing = _find_existing_supply_demand_observation(
                session,
                source_id=source.id,
                supply_demand_commodity_id=mapping.id,
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
            if request.dry_run:
                continue
            session.add(
                SupplyDemandObservation(
                    source_id=source.id,
                    raw_response_id=raw_response.id,
                    collector_run_id=collector_run.id,
                    supply_demand_commodity_id=mapping.id,
                    source_record_id=row.source_record_id,
                    country_code=row.country_code,
                    country_name=row.country_name,
                    region_code=row.region_code,
                    region_name=row.region_name,
                    marketing_year=row.marketing_year,
                    marketing_year_start=row.marketing_year_start,
                    marketing_year_end=row.marketing_year_end,
                    report_month=row.report_month,
                    report_year=row.report_year,
                    report_published_at=row.report_published_at,
                    observed_period_start=row.observed_period_start,
                    observed_period_end=row.observed_period_end,
                    frequency=row.frequency,
                    estimate_type=row.estimate_type,
                    metric_value=row.metric_value,
                    metric_unit=row.metric_unit,
                    value_usd=row.value_usd,
                    is_forecast=row.is_forecast,
                    is_revision=row.is_revision,
                    published_at=row.published_at,
                    fetched_at=fetched_at,
                    source_record_hash=source_record_hash,
                    source_payload_hash=raw_response.sha256,
                    metadata_json={
                        "source": self.source_code,
                        "source_schema_status": SOURCE_SCHEMA_STATUS,
                        "request": _request_metadata(request),
                        "publication_date_available": row.published_at is not None,
                        "raw": row.raw,
                    },
                )
            )
            stats.records_written += 1
            session.flush()
        return stats

    def _fetch_response(self, request: UsdaPsdRequest) -> httpx.Response:
        if request.fixture_file is not None:
            payload = request.fixture_file.read_bytes()
            http_request = httpx.Request("GET", f"file://{request.fixture_file}")
            return httpx.Response(
                200,
                content=payload,
                headers={"content-type": "application/json; charset=utf-8"},
                request=http_request,
            )
        if not request.live_probe:
            raise ValueError("provide --fixture-file or explicitly opt in with --live-probe")
        params = build_usda_psd_live_probe_params(request)
        return self.http_client.get(
            LIVE_PROBE_ENDPOINT_CANDIDATE,
            params=params,
            headers=HEADERS,
            timeout=self.timeout,
        )

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


def build_usda_psd_request(
    *,
    commodity_family: str,
    from_marketing_year: int,
    to_marketing_year: int,
    country: str,
    maxrecords: int | None,
    dry_run: bool = False,
    fixture_file: str | Path | None = None,
    live_probe: bool = False,
) -> UsdaPsdRequest:
    resolved_family = resolve_commodity_family(commodity_family)
    resolved_country = resolve_country(country)
    validate_marketing_year_range(from_marketing_year=from_marketing_year, to_marketing_year=to_marketing_year)
    resolved_maxrecords = maxrecords if maxrecords is not None else DEFAULT_MAXRECORDS
    validate_maxrecords(resolved_maxrecords)
    fixture_path = Path(fixture_file) if fixture_file is not None else None
    if fixture_path is not None and live_probe:
        raise ValueError("--fixture-file and --live-probe cannot be combined")
    if fixture_path is not None and not fixture_path.exists():
        raise ValueError(f"fixture file not found: {fixture_path}")
    return UsdaPsdRequest(
        commodity_family=resolved_family,
        from_marketing_year=from_marketing_year,
        to_marketing_year=to_marketing_year,
        country=resolved_country,
        maxrecords=resolved_maxrecords,
        dry_run=dry_run,
        fixture_file=fixture_path,
        live_probe=live_probe,
    )


def build_usda_psd_live_probe_params(request: UsdaPsdRequest) -> dict[str, str]:
    return usda_psd_live_probe_params(
        commodity_family=request.commodity_family,
        country=request.country,
        from_marketing_year=request.from_marketing_year,
        to_marketing_year=request.to_marketing_year,
        maxrecords=request.maxrecords,
    )


def validate_marketing_year_range(
    *,
    from_marketing_year: int,
    to_marketing_year: int,
    max_years: int = MAX_MARKETING_YEARS_PER_RUN,
) -> None:
    if from_marketing_year > to_marketing_year:
        raise ValueError("from_marketing_year must be on or before to_marketing_year")
    years_count = to_marketing_year - from_marketing_year + 1
    if years_count > max_years:
        raise ValueError(f"marketing year range exceeds max allowed years: {years_count} > {max_years}")


def validate_maxrecords(value: int, *, maximum: int = MAX_MAXRECORDS) -> None:
    if value <= 0:
        raise ValueError("maxrecords must be positive")
    if value > maximum:
        raise ValueError(f"maxrecords must be <= {maximum}")


def assess_usda_psd_response(
    *,
    payload: bytes,
    content_type: str | None,
    status_code: int | None,
    request: UsdaPsdRequest,
    fetched_at: datetime,
) -> tuple[list[ParsedSupplyDemandRow], list[dict[str, Any]], list[PsdResponseCheck]]:
    checks = [
        PsdResponseCheck(
            "supply_demand_raw_response_non_empty",
            "pass" if payload else "fail",
            "error" if not payload else "info",
            {"bytes_size": len(payload), "status_code": status_code, "commodity_family": request.commodity_family.code},
        ),
        _content_type_check(content_type, commodity_family=request.commodity_family.code),
        PsdResponseCheck(
            "supply_demand_live_probe_skipped_fixture_mode",
            "skip" if request.fixture_file is not None else "pass",
            "warning" if request.fixture_file is not None else "info",
            {"fixture_file": str(request.fixture_file) if request.fixture_file else None, "live_probe": request.live_probe},
        ),
        PsdResponseCheck(
            "supply_demand_dry_run_no_normalized_writes",
            "skip" if request.dry_run else "pass",
            "info",
            {"dry_run": request.dry_run},
        ),
    ]
    rows: list[ParsedSupplyDemandRow] = []
    malformed: list[dict[str, Any]] = []
    rows_array_present = False
    raw_rows_count = 0
    parse_error: str | None = None
    if payload:
        try:
            rows, malformed, rows_array_present, raw_rows_count = parse_usda_psd_rows(
                payload,
                request=request,
                fetched_at=fetched_at,
            )
        except UsdaPsdParseError as exc:
            parse_error = str(exc)
    else:
        parse_error = "empty response"
    checks.append(
        PsdResponseCheck(
            "supply_demand_normalized_rows_found",
            "pass" if rows else "fail",
            "warning" if rows_array_present and not rows else "error" if not rows else "info",
            {
                "commodity_family": request.commodity_family.code,
                "rows_array_present": rows_array_present,
                "raw_rows_count": raw_rows_count,
                "parsed_rows_count": len(rows),
                "malformed_rows_count": len(malformed),
                "error": parse_error,
                "source_schema_status": SOURCE_SCHEMA_STATUS,
            },
        )
    )
    return rows, malformed, checks


def parse_usda_psd_rows(
    payload: bytes | str | dict[str, Any],
    *,
    request: UsdaPsdRequest,
    fetched_at: datetime,
) -> tuple[list[ParsedSupplyDemandRow], list[dict[str, Any]], bool, int]:
    data = _json_payload(payload)
    raw_rows = _raw_data_rows(data)
    rows_array_present = isinstance(raw_rows, list)
    if raw_rows is None:
        raise UsdaPsdParseError("missing data/rows array")
    rows: list[ParsedSupplyDemandRow] = []
    malformed: list[dict[str, Any]] = []
    for index, raw_row in enumerate(raw_rows):
        if not isinstance(raw_row, dict):
            malformed.append({"index": index, "error": "supply-demand row is not an object", "raw_type": type(raw_row).__name__})
            continue
        try:
            rows.append(_parse_supply_demand_row(raw_row, request=request, fetched_at=fetched_at))
        except UsdaPsdParseError as exc:
            malformed.append({"index": index, "error": str(exc), "raw_keys": sorted(str(key) for key in raw_row.keys())})
    return rows, malformed, rows_array_present, len(raw_rows)


def build_supply_demand_source_record_hash(
    *,
    source_code: str,
    row: ParsedSupplyDemandRow,
    supply_demand_commodity_id: int,
) -> str:
    return stable_json_hash(
        {
            "source_code": source_code,
            "supply_demand_commodity_id": supply_demand_commodity_id,
            "source_record_id": row.source_record_id,
            "country_code": row.country_code,
            "marketing_year": row.marketing_year,
            "report_year": row.report_year,
            "report_month": row.report_month,
            "estimate_type": row.estimate_type,
            "metric_value": _canonical_decimal(row.metric_value),
            "metric_unit": row.metric_unit,
            "value_usd": _canonical_decimal(row.value_usd),
            "published_at": row.published_at.isoformat() if row.published_at else None,
            "report_published_at": row.report_published_at.isoformat() if row.report_published_at else None,
        }
    )


def _parse_supply_demand_row(raw: dict[str, Any], *, request: UsdaPsdRequest, fetched_at: datetime) -> ParsedSupplyDemandRow:
    metric_name = _normalize_metric(_string_value(raw, "metric_name", "metric", "attribute", "attributeName", "psdAttributeName"))
    if metric_name is None or not is_supported_metric(metric_name):
        raise UsdaPsdParseError(f"unsupported or missing metric: {metric_name}")
    metric_value = _decimal_or_none(_first_present(raw, "metric_value", "value", "Value", "amount"))
    if metric_value is None:
        raise UsdaPsdParseError("metric value is missing or invalid")

    country_code = _country_code(raw, request)
    country = resolve_country(country_code)
    country_name = _string_value(raw, "country_name", "countryName", "country") or country.name
    marketing_year = _marketing_year(raw)
    report_published_at = _parse_datetime(_first_present(raw, "report_published_at", "reportPublishedAt", "publicationDate"))
    published_at = _parse_datetime(_first_present(raw, "published_at", "publishedAt")) or report_published_at
    report_month = _integer_or_none(_first_present(raw, "report_month", "reportMonth", "forecast_month", "forecastMonth"))
    if report_month is None:
        report_month = (published_at or fetched_at).month
    report_year = _integer_or_none(_first_present(raw, "report_year", "reportYear"))
    if report_year is None:
        report_year = (published_at or fetched_at).year

    observed_period_start = _parse_date(_first_present(raw, "observed_period_start", "observedPeriodStart"))
    observed_period_end = _parse_date(_first_present(raw, "observed_period_end", "observedPeriodEnd"))
    marketing_year_start = _parse_date(_first_present(raw, "marketing_year_start", "marketingYearStart"))
    marketing_year_end = _parse_date(_first_present(raw, "marketing_year_end", "marketingYearEnd"))
    if observed_period_start is None or observed_period_end is None:
        inferred_start, inferred_end = _marketing_year_bounds(marketing_year)
        observed_period_start = observed_period_start or inferred_start
        observed_period_end = observed_period_end or inferred_end
    marketing_year_start = marketing_year_start or observed_period_start
    marketing_year_end = marketing_year_end or observed_period_end

    estimate_type = _normalize_estimate_type(_string_value(raw, "estimate_type", "estimateType", "forecastType", "status"))
    product_code = _string_value(raw, "product_code", "productCode") or request.commodity_family.product_code
    return ParsedSupplyDemandRow(
        source_record_id=_source_record_id(raw, request=request, metric_name=metric_name, marketing_year=marketing_year),
        commodity_family=_string_value(raw, "commodity_family", "commodityFamily") or request.commodity_family.commodity_family,
        product_code=product_code,
        metric_name=metric_name,
        country_code=country.code,
        country_name=country_name,
        region_code=_string_value(raw, "region_code", "regionCode"),
        region_name=_string_value(raw, "region_name", "regionName"),
        marketing_year=marketing_year,
        marketing_year_start=marketing_year_start,
        marketing_year_end=marketing_year_end,
        report_month=report_month,
        report_year=report_year,
        report_published_at=report_published_at,
        observed_period_start=observed_period_start,
        observed_period_end=observed_period_end,
        frequency=_normalize_frequency(_string_value(raw, "frequency")),
        estimate_type=estimate_type,
        metric_value=metric_value,
        metric_unit=_string_value(raw, "metric_unit", "unit", "unitDescription") or "unknown",
        value_usd=_decimal_or_none(_first_present(raw, "value_usd", "valueUsd")),
        is_forecast=_bool_or_default(_first_present(raw, "is_forecast", "isForecast"), estimate_type in {"forecast", "projection"}),
        is_revision=_bool_or_default(_first_present(raw, "is_revision", "isRevision"), False),
        published_at=published_at,
        raw={
            "source_row": raw,
            "fetched_at": _to_utc(fetched_at).isoformat(),
            "source_schema_status": SOURCE_SCHEMA_STATUS,
        },
    )


def _find_supply_demand_mapping(
    session: Session,
    *,
    source_id: int,
    row: ParsedSupplyDemandRow,
) -> SupplyDemandCommodity | None:
    statement = select(SupplyDemandCommodity).where(
        SupplyDemandCommodity.source_id == source_id,
        SupplyDemandCommodity.commodity_family == row.commodity_family,
        SupplyDemandCommodity.metric_name == row.metric_name,
        SupplyDemandCommodity.is_active.is_(True),
    )
    if row.product_code is None:
        statement = statement.where(SupplyDemandCommodity.product_code.is_(None))
    else:
        statement = statement.where(SupplyDemandCommodity.product_code == row.product_code)
    return session.scalar(statement.limit(1))


def _find_existing_supply_demand_observation(
    session: Session,
    *,
    source_id: int,
    supply_demand_commodity_id: int,
    row: ParsedSupplyDemandRow,
) -> SupplyDemandObservation | None:
    return session.scalar(
        select(SupplyDemandObservation)
        .where(
            SupplyDemandObservation.source_id == source_id,
            SupplyDemandObservation.supply_demand_commodity_id == supply_demand_commodity_id,
            SupplyDemandObservation.country_code == row.country_code,
            SupplyDemandObservation.marketing_year == row.marketing_year,
            SupplyDemandObservation.report_year == row.report_year,
            SupplyDemandObservation.report_month == row.report_month,
            SupplyDemandObservation.estimate_type == row.estimate_type,
        )
        .limit(1)
    )


def _write_request_quality_checks(
    session: Session,
    *,
    source_id: int,
    request: UsdaPsdRequest,
    checked_at: datetime,
) -> None:
    checks = [
        (
            "supply_demand_source_mapping_found",
            "pass",
            "info",
            {"source_code": SOURCE_CODE},
        ),
        (
            "supply_demand_commodity_family_supported",
            "pass",
            "info",
            {"commodity_family": request.commodity_family.code},
        ),
        (
            "supply_demand_marketing_year_range_valid",
            "pass",
            "info",
            {
                "from_marketing_year": request.from_marketing_year,
                "to_marketing_year": request.to_marketing_year,
                "max_marketing_years_per_run": MAX_MARKETING_YEARS_PER_RUN,
            },
        ),
        (
            "supply_demand_country_supported",
            "pass",
            "info",
            {"country": request.country.code},
        ),
    ]
    for check_name, status, severity, details in checks:
        _write_quality_check(
            session,
            source_id=source_id,
            table_name="supply_demand_observations",
            check_name=check_name,
            status=status,
            severity=severity,
            details={**details, "source_schema_status": SOURCE_SCHEMA_STATUS, "request": _request_metadata(request)},
            checked_at=checked_at,
        )


def _write_response_checks(
    session: Session,
    *,
    source_id: int,
    raw_response_id: int,
    request: UsdaPsdRequest,
    checks: list[PsdResponseCheck],
    checked_at: datetime,
) -> None:
    _write_quality_check(
        session,
        source_id=source_id,
        table_name="raw_responses",
        check_name="supply_demand_raw_response_persisted",
        status="pass",
        severity="info",
        details={"raw_response_id": raw_response_id, "request": _request_metadata(request)},
        checked_at=checked_at,
    )
    for check in checks:
        _write_quality_check(
            session,
            source_id=source_id,
            table_name="raw_responses",
            check_name=check.check_name,
            status=check.status,
            severity=check.severity,
            details={**check.details, "raw_response_id": raw_response_id, "request": _request_metadata(request)},
            checked_at=checked_at,
        )


def _write_malformed_row_checks(
    session: Session,
    *,
    source_id: int,
    raw_response_id: int,
    request: UsdaPsdRequest,
    malformed: list[dict[str, Any]],
    checked_at: datetime,
) -> None:
    for item in malformed:
        _write_quality_check(
            session,
            source_id=source_id,
            table_name="supply_demand_observations",
            check_name="supply_demand_malformed_row_skipped",
            status="fail",
            severity="warning",
            details={**item, "raw_response_id": raw_response_id, "request": _request_metadata(request)},
            checked_at=checked_at,
        )


def _write_mapping_missing_quality_check(
    session: Session,
    *,
    source_id: int,
    raw_response_id: int,
    request: UsdaPsdRequest,
    row: ParsedSupplyDemandRow,
    checked_at: datetime,
) -> None:
    _write_quality_check(
        session,
        source_id=source_id,
        table_name="supply_demand_commodities",
        check_name="supply_demand_mapping_found",
        status="fail",
        severity="warning",
        details={
            "raw_response_id": raw_response_id,
            "commodity_family": row.commodity_family,
            "product_code": row.product_code,
            "metric_name": row.metric_name,
            "country_code": row.country_code,
            "marketing_year": row.marketing_year,
            "request": _request_metadata(request),
        },
        checked_at=checked_at,
    )


def _write_row_quality_checks(
    session: Session,
    *,
    source_id: int,
    raw_response_id: int,
    supply_demand_commodity_id: int,
    row: ParsedSupplyDemandRow,
    source_record_hash: str,
    checked_at: datetime,
) -> None:
    checks = [
        ("supply_demand_mapping_found", "pass", "info", {"supply_demand_commodity_id": supply_demand_commodity_id}),
        ("supply_demand_metric_value_present", "pass", "info", {"metric_value": _canonical_decimal(row.metric_value)}),
        (
            "supply_demand_metric_unit_present",
            "skip" if row.metric_unit == "unknown" else "pass",
            "warning" if row.metric_unit == "unknown" else "info",
            {"metric_unit": row.metric_unit},
        ),
        ("supply_demand_country_code_present", "pass" if row.country_code else "fail", "info" if row.country_code else "error", {}),
        (
            "supply_demand_source_record_hash_present",
            "pass" if source_record_hash else "fail",
            "info" if source_record_hash else "error",
            {"source_record_hash": source_record_hash},
        ),
        ("supply_demand_raw_response_id_linked", "pass" if raw_response_id else "fail", "info" if raw_response_id else "error", {}),
        (
            "supply_demand_publication_date_missing",
            "skip" if row.published_at is None else "pass",
            "warning" if row.published_at is None else "info",
            {"published_at": row.published_at.isoformat() if row.published_at else None},
        ),
    ]
    details = {
        "raw_response_id": raw_response_id,
        "supply_demand_commodity_id": supply_demand_commodity_id,
        "country_code": row.country_code,
        "marketing_year": row.marketing_year,
        "report_year": row.report_year,
        "report_month": row.report_month,
        "estimate_type": row.estimate_type,
        "metric_name": row.metric_name,
    }
    for check_name, status, severity, extra in checks:
        _write_quality_check(
            session,
            source_id=source_id,
            table_name="supply_demand_observations",
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
    existing: SupplyDemandObservation,
    row: ParsedSupplyDemandRow,
    incoming_source_record_hash: str,
    checked_at: datetime,
) -> None:
    _write_quality_check(
        session,
        source_id=source_id,
        table_name="supply_demand_observations",
        check_name="supply_demand_existing_observation_hash_changed",
        status="fail",
        severity="warning",
        details={
            "existing_id": existing.id,
            "raw_response_id": raw_response_id,
            "country_code": row.country_code,
            "marketing_year": row.marketing_year,
            "report_year": row.report_year,
            "report_month": row.report_month,
            "estimate_type": row.estimate_type,
            "existing_source_record_hash": existing.source_record_hash,
            "incoming_source_record_hash": incoming_source_record_hash,
            "changed_fields": _changed_supply_demand_fields(existing, row),
            "existing_values": _supply_demand_values_from_model(existing),
            "incoming_values": _supply_demand_values_from_row(row),
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
    collector: UsdaPsdCollector,
    collector_run: CollectorRun,
    started_at: datetime,
    *,
    request: UsdaPsdRequest,
    errors_count: int,
) -> UsdaPsdCollectorResult:
    return UsdaPsdCollectorResult(
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
        commodity_family=request.commodity_family.code,
        from_marketing_year=request.from_marketing_year,
        to_marketing_year=request.to_marketing_year,
        country=request.country.code,
        maxrecords=request.maxrecords,
        dry_run=request.dry_run,
        fixture_file=str(request.fixture_file) if request.fixture_file else None,
        live_probe=request.live_probe,
    )


def _json_payload(payload: bytes | str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    text = payload.decode("utf-8-sig") if isinstance(payload, bytes) else payload
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise UsdaPsdParseError(f"invalid JSON response: {exc}") from exc
    if not isinstance(data, dict):
        raise UsdaPsdParseError("JSON response root is not an object")
    return data


def _raw_data_rows(data: dict[str, Any]) -> list[Any] | None:
    for key in ("data", "rows", "dataset", "results", "items"):
        value = data.get(key)
        if isinstance(value, list):
            return value
    return None


def _content_type_check(content_type: str | None, *, commodity_family: str) -> PsdResponseCheck:
    normalized = (content_type or "").split(";")[0].strip().lower()
    ok = normalized in {"application/json", "text/json", "text/plain"} or normalized.endswith("+json")
    return PsdResponseCheck(
        "supply_demand_content_type_expected",
        "pass" if ok else "fail",
        "info" if ok else "warning",
        {"content_type": content_type, "commodity_family": commodity_family},
    )


def _has_parser_error(checks: list[PsdResponseCheck]) -> bool:
    return any(
        check.check_name == "supply_demand_normalized_rows_found" and check.status == "fail" and check.severity == "error"
        for check in checks
    )


def _normalize_metric(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "production": "production_volume",
        "production_volume": "production_volume",
        "domestic_consumption": "domestic_consumption",
        "domestic_use": "domestic_consumption",
        "total_domestic_consumption": "domestic_consumption",
        "feed_use": "feed_use",
        "feed": "feed_use",
        "crush": "crush_volume",
        "crush_volume": "crush_volume",
        "exports": "exports_volume",
        "ty_exports": "exports_volume",
        "exports_volume": "exports_volume",
        "imports": "imports_volume",
        "ty_imports": "imports_volume",
        "imports_volume": "imports_volume",
        "beginning_stocks": "beginning_stocks",
        "ending_stocks": "ending_stocks",
        "ending_stock": "ending_stocks",
        "stock_to_use": "stock_to_use_ratio",
        "stock_to_use_ratio": "stock_to_use_ratio",
        "planted_area": "planted_area",
        "harvested_area": "harvested_area",
        "yield": "yield",
        "yield_value": "yield",
    }
    return aliases.get(normalized, normalized)


def _normalize_estimate_type(value: str | None) -> str:
    normalized = (value or "unknown").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "actual": "actual",
        "estimate": "estimate",
        "estimated": "estimate",
        "forecast": "forecast",
        "projection": "projection",
        "projected": "projection",
    }
    return aliases.get(normalized, "unknown")


def _normalize_frequency(value: str | None) -> str:
    normalized = (value or "monthly_report").strip().lower().replace("-", "_").replace(" ", "_")
    if normalized in {"monthly_report", "marketing_year", "annual", "quarterly", "unknown"}:
        return normalized
    return "unknown"


def _country_code(raw: dict[str, Any], request: UsdaPsdRequest) -> str:
    return (_string_value(raw, "country_code", "countryCode", "country") or request.country.code).upper()


def _marketing_year(raw: dict[str, Any]) -> str:
    value = _first_present(raw, "marketing_year", "marketingYear", "marketYear", "year")
    if value in (None, ""):
        raise UsdaPsdParseError("marketing year is missing")
    return str(value).strip()


def _marketing_year_bounds(marketing_year: str) -> tuple[date | None, date | None]:
    year = _integer_or_none(marketing_year[:4])
    if year is None:
        return None, None
    return date(year, 1, 1), date(year, 12, 31)


def _source_record_id(raw: dict[str, Any], *, request: UsdaPsdRequest, metric_name: str, marketing_year: str) -> str:
    explicit = _string_value(raw, "id", "source_record_id", "sourceRecordId", "recordId")
    if explicit:
        return explicit
    return "|".join(
        [
            request.commodity_family.code,
            request.country.code,
            marketing_year,
            metric_name,
        ]
    )


def _changed_supply_demand_fields(existing: SupplyDemandObservation, row: ParsedSupplyDemandRow) -> list[str]:
    existing_values = _supply_demand_values_from_model(existing)
    incoming_values = _supply_demand_values_from_row(row)
    return [field for field, incoming in incoming_values.items() if existing_values.get(field) != incoming]


def _supply_demand_values_from_model(row: SupplyDemandObservation) -> dict[str, Any]:
    return {
        "metric_value": _canonical_decimal(row.metric_value),
        "metric_unit": row.metric_unit,
        "value_usd": _canonical_decimal(row.value_usd),
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "report_published_at": row.report_published_at.isoformat() if row.report_published_at else None,
        "observed_period_start": row.observed_period_start.isoformat() if row.observed_period_start else None,
        "observed_period_end": row.observed_period_end.isoformat() if row.observed_period_end else None,
    }


def _supply_demand_values_from_row(row: ParsedSupplyDemandRow) -> dict[str, Any]:
    return {
        "metric_value": _canonical_decimal(row.metric_value),
        "metric_unit": row.metric_unit,
        "value_usd": _canonical_decimal(row.value_usd),
        "published_at": row.published_at.isoformat() if row.published_at else None,
        "report_published_at": row.report_published_at.isoformat() if row.report_published_at else None,
        "observed_period_start": row.observed_period_start.isoformat() if row.observed_period_start else None,
        "observed_period_end": row.observed_period_end.isoformat() if row.observed_period_end else None,
    }


def _request_metadata(request: UsdaPsdRequest) -> dict[str, Any]:
    return {
        "commodity_family": request.commodity_family.code,
        "country": request.country.code,
        "from_marketing_year": request.from_marketing_year,
        "to_marketing_year": request.to_marketing_year,
        "maxrecords": request.maxrecords,
        "dry_run": request.dry_run,
        "fixture_file": str(request.fixture_file) if request.fixture_file else None,
        "live_probe": request.live_probe,
        "source_schema_status": SOURCE_SCHEMA_STATUS,
    }


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


def _integer_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value).strip())
    except ValueError:
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


def _parse_date(value: Any | None) -> date | None:
    if value in (None, ""):
        return None
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


def _bool_or_default(value: Any, default: bool) -> bool:
    if value in (None, ""):
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


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
        raise ValueError("scheduled runs are not supported for usda_psd")
    if value not in {"manual", "backfill"}:
        raise ValueError("run_type must be manual or backfill")
    return value
