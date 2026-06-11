from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Protocol

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.collectors.base import BaseCollector, CollectorResult
from app.collectors.weather.open_meteo_config import (
    COLLECTOR_NAME,
    CORE_WEATHER_FIELDS,
    ENDPOINT,
    HEADERS,
    HIGH_MEDIUM_PRIORITIES,
    MAX_DAYS_PER_RUN,
    OPEN_METEO_DAILY_VARIABLES,
    OPEN_METEO_VARIABLE_MAPPING,
    PARSER_VERSION,
    REQUEST_TIMEOUT,
    SOURCE_CODE,
    OpenMeteoRequest,
    open_meteo_params,
    open_meteo_url,
)
from app.db.models import CollectorRun, DataQualityCheck, RawResponse, Source, WeatherObservation, WeatherRegion
from app.db.session import session_scope
from app.storage.hashes import stable_json_hash
from app.storage.raw_store import RawStore

logger = logging.getLogger(__name__)


class OpenMeteoParseError(ValueError):
    """Raised when an Open-Meteo daily JSON response cannot be parsed safely."""


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
class ParsedWeatherObservation:
    region_code: str
    source_region_key: str
    observation_date: date
    observed_at: datetime
    values: dict[str, Decimal | None]
    missing_variables: tuple[str, ...]
    units: dict[str, str]
    raw: dict[str, Any]


@dataclass(frozen=True)
class WeatherResponseCheck:
    check_name: str
    status: str
    severity: str
    details: dict[str, Any]


@dataclass(frozen=True)
class OpenMeteoCollectorResult(CollectorResult):
    regions_requested: int = 0
    regions_success: int = 0
    regions_failed: int = 0
    skipped_existing: int = 0
    conflicts_count: int = 0
    regions: tuple[str, ...] = ()
    from_date: str | None = None
    to_date: str | None = None


@dataclass
class _RegionStats:
    region_code: str
    records_found: int = 0
    records_written: int = 0
    skipped_existing: int = 0
    conflicts_count: int = 0
    raw_response_ids: list[int] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class OpenMeteoHistoricalWeatherCollector(BaseCollector):
    source_code = SOURCE_CODE
    collector_name = COLLECTOR_NAME
    parser_version = PARSER_VERSION

    def __init__(
        self,
        *,
        http_client: HttpClient | None = None,
        raw_store: RawStore | None = None,
        timeout: float = REQUEST_TIMEOUT,
        max_days_per_run: int = MAX_DAYS_PER_RUN,
        clock: Any | None = None,
    ) -> None:
        super().__init__()
        self.http_client = http_client or httpx.Client(follow_redirects=True)
        self.raw_store = raw_store or RawStore()
        self.timeout = timeout
        self.max_days_per_run = max_days_per_run
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def run(
        self,
        session: Session | None = None,
        *,
        region_code: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        run_type: str = "manual",
    ) -> OpenMeteoCollectorResult:
        run_type = _normalize_run_type(run_type)
        if from_date is None or to_date is None:
            raise ValueError("from_date and to_date are required for open_meteo_historical_weather")
        validate_date_range(from_date=from_date, to_date=to_date, max_days=self.max_days_per_run)
        if session is None:
            with session_scope() as scoped_session:
                selected = _select_regions(scoped_session, region_code=region_code, from_date=from_date, to_date=to_date)
                return self._run_with_session(
                    scoped_session,
                    selected_regions=selected,
                    from_date=from_date,
                    to_date=to_date,
                    run_type=run_type,
                )
        selected = _select_regions(session, region_code=region_code, from_date=from_date, to_date=to_date)
        return self._run_with_session(
            session,
            selected_regions=selected,
            from_date=from_date,
            to_date=to_date,
            run_type=run_type,
        )

    def _run_with_session(
        self,
        session: Session,
        *,
        selected_regions: tuple[WeatherRegion, ...],
        from_date: date,
        to_date: date,
        run_type: str,
    ) -> OpenMeteoCollectorResult:
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
                check_name="weather_source_mapping_found",
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
                selected_regions=selected_regions,
                from_date=from_date,
                to_date=to_date,
                regions_success=0,
                regions_failed=len(selected_regions),
                skipped_existing=0,
                conflicts_count=0,
                raw_response_ids=[],
                errors_count=1,
            )

        _write_quality_check(
            session,
            source_id=source.id,
            table_name="sources",
            check_name="weather_source_mapping_found",
            status="pass",
            severity="info",
            details={"source_code": self.source_code, "source_id": source.id},
            checked_at=started_at,
        )
        _write_quality_check(
            session,
            source_id=source.id,
            table_name="weather_regions",
            check_name="weather_request_date_range_valid",
            status="pass",
            severity="info",
            details={
                "from_date": from_date.isoformat(),
                "to_date": to_date.isoformat(),
                "max_days_per_run": self.max_days_per_run,
                "regions_requested": len(selected_regions),
            },
            checked_at=started_at,
        )

        raw_response_ids: list[int] = []
        all_errors: list[str] = []
        records_found = 0
        records_written = 0
        skipped_existing = 0
        conflicts_count = 0
        regions_success = 0
        regions_failed = 0

        for region in selected_regions:
            stats = self._collect_region(
                session,
                source,
                collector_run,
                region,
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
                regions_failed += 1
            else:
                regions_success += 1

        collector_run.finished_at = _to_utc(self.clock())
        collector_run.records_found = records_found
        collector_run.records_written = records_written
        if not all_errors and conflicts_count == 0 and regions_success == len(selected_regions):
            collector_run.status = "success"
        elif records_found > 0 or regions_success > 0:
            collector_run.status = "partial_success"
        else:
            collector_run.status = "error"
        collector_run.error_message = "\n".join(all_errors) if all_errors else None
        session.flush()

        return OpenMeteoCollectorResult(
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
            regions_requested=len(selected_regions),
            regions_success=regions_success,
            regions_failed=regions_failed,
            skipped_existing=skipped_existing,
            conflicts_count=conflicts_count,
            regions=tuple(region.region_code for region in selected_regions),
            from_date=from_date.isoformat(),
            to_date=to_date.isoformat(),
        )

    def _collect_region(
        self,
        session: Session,
        source: Source,
        collector_run: CollectorRun,
        region: WeatherRegion,
        *,
        from_date: date,
        to_date: date,
    ) -> _RegionStats:
        stats = _RegionStats(region_code=region.region_code)
        checked_at = _to_utc(self.clock())
        _write_quality_check(
            session,
            source_id=source.id,
            table_name="weather_regions",
            check_name="weather_region_found",
            status="pass",
            severity="info",
            details={"region_code": region.region_code, "region_id": region.id, "priority": region.priority},
            checked_at=checked_at,
        )
        request = _request_for_region(region, from_date=from_date, to_date=to_date)
        try:
            response = self.http_client.get(
                ENDPOINT,
                params=open_meteo_params(request),
                headers=HEADERS,
                timeout=self.timeout,
            )
            fetched_at = _to_utc(self.clock())
        except (httpx.TimeoutException, httpx.RequestError) as exc:
            message = _request_error_message(region, exc, request=request, timeout=self.timeout)
            logger.warning(message)
            stats.errors.append(message)
            return stats

        raw_response = self._save_raw_response(session, source, collector_run, response, fetched_at)
        stats.raw_response_ids.append(raw_response.id)
        rows, checks = assess_open_meteo_response(
            payload=response.content,
            content_type=response.headers.get("content-type"),
            status_code=response.status_code,
            region=region,
            fetched_at=fetched_at,
        )
        _write_response_checks(
            session,
            source_id=source.id,
            raw_response_id=raw_response.id,
            region=region,
            checks=checks,
            checked_at=fetched_at,
        )
        if response.status_code != 200:
            stats.errors.append(f"{region.region_code}: HTTP status {response.status_code}; url={_response_url(response)}")
            return stats
        if not rows:
            stats.errors.append(f"{region.region_code}: no weather rows parsed")
            return stats

        for row in rows:
            stats.records_found += 1
            source_record_hash = build_weather_source_record_hash(
                source_code=self.source_code,
                region_code=region.region_code,
                row=row,
            )
            _write_row_quality_checks(
                session,
                source_id=source.id,
                raw_response_id=raw_response.id,
                region=region,
                row=row,
                source_record_hash=source_record_hash,
                checked_at=fetched_at,
            )
            existing = _find_existing_observation(
                session,
                source_id=source.id,
                region_id=region.id,
                observation_date=row.observation_date,
                frequency="daily",
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
                    region=region,
                    incoming_hash=source_record_hash,
                    checked_at=fetched_at,
                )
                continue

            session.add(
                WeatherObservation(
                    source_id=source.id,
                    raw_response_id=raw_response.id,
                    collector_run_id=collector_run.id,
                    region_id=region.id,
                    source_region_key=row.source_region_key,
                    observation_date=row.observation_date,
                    observed_at=row.observed_at,
                    fetched_at=fetched_at,
                    frequency="daily",
                    temperature_2m_mean=row.values["temperature_2m_mean"],
                    temperature_2m_min=row.values["temperature_2m_min"],
                    temperature_2m_max=row.values["temperature_2m_max"],
                    precipitation_sum=row.values["precipitation_sum"],
                    snowfall_sum=row.values["snowfall_sum"],
                    relative_humidity_mean=row.values["relative_humidity_mean"],
                    wind_speed_mean=row.values["wind_speed_mean"],
                    wind_speed_max=row.values["wind_speed_max"],
                    evapotranspiration=row.values["evapotranspiration"],
                    shortwave_radiation=row.values["shortwave_radiation"],
                    source_record_hash=source_record_hash,
                    source_payload_hash=raw_response.sha256,
                    metadata_json=_metadata_json(row=row, raw_response=raw_response),
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


def validate_date_range(*, from_date: date, to_date: date, max_days: int = MAX_DAYS_PER_RUN) -> None:
    if from_date > to_date:
        raise ValueError("from_date must be on or before to_date")
    days_count = (to_date - from_date).days + 1
    if days_count > max_days:
        raise ValueError(f"date range exceeds max allowed days: {days_count} > {max_days}")


def assess_open_meteo_response(
    *,
    payload: bytes,
    content_type: str | None,
    status_code: int | None,
    region: WeatherRegion,
    fetched_at: datetime,
) -> tuple[list[ParsedWeatherObservation], list[WeatherResponseCheck]]:
    checks = [
        WeatherResponseCheck(
            check_name="weather_raw_response_present",
            status="pass" if payload is not None else "fail",
            severity="error" if payload is None else "info",
            details={"region_code": region.region_code, "status_code": status_code},
        ),
        WeatherResponseCheck(
            check_name="weather_raw_response_non_empty",
            status="pass" if payload else "fail",
            severity="error" if not payload else "info",
            details={"region_code": region.region_code, "bytes_size": len(payload)},
        ),
        _content_type_check(content_type, region_code=region.region_code),
    ]
    rows: list[ParsedWeatherObservation] = []
    parse_error: str | None = None
    daily_arrays_present = False
    raw_rows_count = 0
    if payload:
        try:
            rows, daily_arrays_present, raw_rows_count = parse_open_meteo_daily(
                payload,
                region=region,
                fetched_at=fetched_at,
            )
        except OpenMeteoParseError as exc:
            parse_error = str(exc)
    else:
        parse_error = "empty response"

    checks.append(
        WeatherResponseCheck(
            check_name="weather_daily_arrays_present",
            status="pass" if daily_arrays_present else "fail",
            severity="error" if not daily_arrays_present else "info",
            details={"region_code": region.region_code, "error": parse_error},
        )
    )
    checks.append(
        WeatherResponseCheck(
            check_name="weather_daily_rows_present",
            status="pass" if rows else "fail",
            severity="error" if not rows else "info",
            details={
                "region_code": region.region_code,
                "raw_rows_count": raw_rows_count,
                "parsed_rows_count": len(rows),
                "error": parse_error,
            },
        )
    )
    return rows, checks


def parse_open_meteo_daily(
    payload: bytes | str | dict[str, Any],
    *,
    region: WeatherRegion,
    fetched_at: datetime,
) -> tuple[list[ParsedWeatherObservation], bool, int]:
    if isinstance(payload, dict):
        data = payload
    else:
        text = payload.decode("utf-8") if isinstance(payload, bytes) else payload
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise OpenMeteoParseError(f"invalid JSON response: {exc}") from exc
    daily = data.get("daily")
    if not isinstance(daily, dict):
        raise OpenMeteoParseError("missing daily object")
    raw_dates = daily.get("time")
    if not isinstance(raw_dates, list):
        raise OpenMeteoParseError("missing daily.time array")
    units = data.get("daily_units") if isinstance(data.get("daily_units"), dict) else {}
    source_region_key = _source_region_key(region)
    rows: list[ParsedWeatherObservation] = []
    for index, raw_date in enumerate(raw_dates):
        if not isinstance(raw_date, str):
            raise OpenMeteoParseError(f"bad daily.time value at index {index}")
        try:
            observation_date = date.fromisoformat(raw_date)
        except ValueError as exc:
            raise OpenMeteoParseError(f"bad daily.time date {raw_date!r}") from exc
        values, missing_variables, raw = _values_for_index(daily, index)
        rows.append(
            ParsedWeatherObservation(
                region_code=region.region_code,
                source_region_key=source_region_key,
                observation_date=observation_date,
                observed_at=datetime.combine(observation_date, time.min, tzinfo=timezone.utc),
                values=values,
                missing_variables=tuple(missing_variables),
                units={str(key): str(value) for key, value in units.items()},
                raw={
                    "source_date": raw_date,
                    "fetched_at": _to_utc(fetched_at).isoformat(),
                    "daily": raw,
                },
            )
        )
    return rows, True, len(raw_dates)


def build_weather_source_record_hash(
    *,
    source_code: str,
    region_code: str,
    row: ParsedWeatherObservation,
) -> str:
    return stable_json_hash(
        {
            "source_code": source_code,
            "region_code": region_code,
            "source_region_key": row.source_region_key,
            "observation_date": row.observation_date.isoformat(),
            "frequency": "daily",
            "values": {key: _canonical_decimal(value) for key, value in sorted(row.values.items())},
            "units": row.units,
        }
    )


def _values_for_index(daily: dict[str, Any], index: int) -> tuple[dict[str, Decimal | None], list[str], dict[str, Any]]:
    values: dict[str, Decimal | None] = {
        "temperature_2m_mean": None,
        "temperature_2m_min": None,
        "temperature_2m_max": None,
        "precipitation_sum": None,
        "snowfall_sum": None,
        "relative_humidity_mean": None,
        "wind_speed_mean": None,
        "wind_speed_max": None,
        "evapotranspiration": None,
        "shortwave_radiation": None,
    }
    missing_variables: list[str] = []
    raw: dict[str, Any] = {}
    for open_meteo_name, model_name in OPEN_METEO_VARIABLE_MAPPING.items():
        raw_values = daily.get(open_meteo_name)
        if not isinstance(raw_values, list) or index >= len(raw_values):
            missing_variables.append(open_meteo_name)
            raw[open_meteo_name] = None
            continue
        raw_value = raw_values[index]
        raw[open_meteo_name] = raw_value
        values[model_name] = _decimal_or_none(raw_value)
    if "rain_sum" in daily and isinstance(daily["rain_sum"], list) and index < len(daily["rain_sum"]):
        raw["rain_sum"] = daily["rain_sum"][index]
    elif "rain_sum" in OPEN_METEO_DAILY_VARIABLES:
        missing_variables.append("rain_sum")
        raw["rain_sum"] = None
    return values, missing_variables, raw


def _write_response_checks(
    session: Session,
    *,
    source_id: int,
    raw_response_id: int,
    region: WeatherRegion,
    checks: list[WeatherResponseCheck],
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
            details={**check.details, "raw_response_id": raw_response_id, "region_code": region.region_code},
            checked_at=checked_at,
        )


def _write_row_quality_checks(
    session: Session,
    *,
    source_id: int,
    raw_response_id: int,
    region: WeatherRegion,
    row: ParsedWeatherObservation,
    source_record_hash: str,
    checked_at: datetime,
) -> None:
    core_values = {field: row.values.get(field) for field in CORE_WEATHER_FIELDS}
    core_present = any(value is not None for value in core_values.values())
    details = {
        "region_code": region.region_code,
        "observation_date": row.observation_date.isoformat(),
        "frequency": "daily",
        "raw_response_id": raw_response_id,
        "missing_variables": list(row.missing_variables),
        "core_values": {key: _canonical_decimal(value) for key, value in core_values.items()},
    }
    checks = [
        (
            "weather_observation_date_valid",
            "pass",
            "info",
            {"observed_at": row.observed_at.isoformat()},
        ),
        (
            "weather_core_values_present",
            "pass" if core_present else "fail",
            "info" if core_present else "warning",
            {},
        ),
        (
            "weather_source_record_hash_present",
            "pass" if source_record_hash else "fail",
            "info" if source_record_hash else "error",
            {"source_record_hash": source_record_hash},
        ),
        (
            "weather_raw_linkage_present",
            "pass" if raw_response_id else "fail",
            "info" if raw_response_id else "error",
            {},
        ),
    ]
    for check_name, status, severity, extra in checks:
        _write_quality_check(
            session,
            source_id=source_id,
            table_name="weather_observations",
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
    existing: WeatherObservation,
    row: ParsedWeatherObservation,
    region: WeatherRegion,
    incoming_hash: str,
    checked_at: datetime,
) -> None:
    changed_fields = _changed_weather_fields(existing, row)
    _write_quality_check(
        session,
        source_id=source_id,
        table_name="weather_observations",
        check_name="weather_existing_observation_hash_changed",
        status="fail",
        severity="warning",
        details={
            "region_code": region.region_code,
            "observation_date": row.observation_date.isoformat(),
            "frequency": "daily",
            "existing_id": existing.id,
            "existing_source_record_hash": existing.source_record_hash,
            "incoming_source_record_hash": incoming_hash,
            "existing_raw_response_id": existing.raw_response_id,
            "incoming_raw_response_id": raw_response_id,
            "changed_fields": changed_fields,
            "existing_values": _weather_values_from_model(existing),
            "incoming_values": {key: _canonical_decimal(value) for key, value in row.values.items()},
            "policy_decision": "rejected_hash_conflict_no_overwrite",
        },
        checked_at=checked_at,
    )


def _changed_weather_fields(existing: WeatherObservation, row: ParsedWeatherObservation) -> list[str]:
    changed: list[str] = []
    existing_values = _weather_values_from_model(existing)
    incoming_values = {key: _canonical_decimal(value) for key, value in row.values.items()}
    for field, incoming in incoming_values.items():
        if existing_values.get(field) != incoming:
            changed.append(field)
    return changed


def _weather_values_from_model(row: WeatherObservation) -> dict[str, str | None]:
    return {
        "temperature_2m_mean": _canonical_decimal(row.temperature_2m_mean),
        "temperature_2m_min": _canonical_decimal(row.temperature_2m_min),
        "temperature_2m_max": _canonical_decimal(row.temperature_2m_max),
        "precipitation_sum": _canonical_decimal(row.precipitation_sum),
        "snowfall_sum": _canonical_decimal(row.snowfall_sum),
        "relative_humidity_mean": _canonical_decimal(row.relative_humidity_mean),
        "wind_speed_mean": _canonical_decimal(row.wind_speed_mean),
        "wind_speed_max": _canonical_decimal(row.wind_speed_max),
        "evapotranspiration": _canonical_decimal(row.evapotranspiration),
        "shortwave_radiation": _canonical_decimal(row.shortwave_radiation),
    }


def _find_existing_observation(
    session: Session,
    *,
    source_id: int,
    region_id: int,
    observation_date: date,
    frequency: str,
) -> WeatherObservation | None:
    return session.scalar(
        select(WeatherObservation)
        .where(
            WeatherObservation.source_id == source_id,
            WeatherObservation.region_id == region_id,
            WeatherObservation.observation_date == observation_date,
            WeatherObservation.frequency == frequency,
        )
        .limit(1)
    )


def _select_regions(
    session: Session,
    *,
    region_code: str | None,
    from_date: date,
    to_date: date,
) -> tuple[WeatherRegion, ...]:
    if region_code:
        region = session.scalar(select(WeatherRegion).where(WeatherRegion.region_code == region_code))
        if region is None:
            raise ValueError(f"unknown weather region: {region_code}")
        if not region.is_active:
            raise ValueError(f"weather region is inactive: {region_code}")
        return (region,)
    days_count = (to_date - from_date).days + 1
    query = select(WeatherRegion).where(WeatherRegion.is_active.is_(True))
    if days_count > 10:
        query = query.where(WeatherRegion.priority.in_(HIGH_MEDIUM_PRIORITIES))
    query = query.order_by(WeatherRegion.priority, WeatherRegion.region_code)
    selected = tuple(session.scalars(query).all())
    if not selected:
        raise ValueError("no active weather regions found")
    return selected


def _request_for_region(region: WeatherRegion, *, from_date: date, to_date: date) -> OpenMeteoRequest:
    return OpenMeteoRequest(
        latitude=_coordinate_str(region.latitude),
        longitude=_coordinate_str(region.longitude),
        from_date=from_date,
        to_date=to_date,
    )


def _metadata_json(*, row: ParsedWeatherObservation, raw_response: RawResponse) -> dict[str, Any]:
    return {
        "source_url": raw_response.url,
        "parser_version": PARSER_VERSION,
        "frequency": "daily",
        "source_frequency": "daily",
        "source_region_key": row.source_region_key,
        "missing_variables": list(row.missing_variables),
        "units": row.units,
        "requested_daily_variables": list(OPEN_METEO_DAILY_VARIABLES),
        "raw_response_id": raw_response.id,
        "raw": row.raw,
    }


def _content_type_check(content_type: str | None, *, region_code: str) -> WeatherResponseCheck:
    if not content_type:
        return WeatherResponseCheck(
            check_name="weather_content_type_expected",
            status="skip",
            severity="info",
            details={"region_code": region_code, "content_type": None},
        )
    normalized = content_type.split(";")[0].strip().lower()
    expected = {"application/json", "text/json"}
    return WeatherResponseCheck(
        check_name="weather_content_type_expected",
        status="pass" if normalized in expected else "fail",
        severity="warning" if normalized not in expected else "info",
        details={"region_code": region_code, "content_type": content_type},
    )


def _response_url(response: httpx.Response) -> str:
    try:
        return str(response.url)
    except RuntimeError:
        return ENDPOINT


def _request_error_message(region: WeatherRegion, exc: Exception, *, request: OpenMeteoRequest, timeout: float) -> str:
    return (
        f"{region.region_code}: Open-Meteo request failed; "
        f"url={open_meteo_url(request)}; "
        f"timeout_seconds={timeout}; "
        f"error_type={type(exc).__name__}; "
        f"error={str(exc)[:300]}"
    )


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip()
    if text in {"", "nan", "NaN", "NA", "N/A", "null", "NULL"}:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError) as exc:
        raise OpenMeteoParseError(f"bad numeric value: {value!r}") from exc


def _coordinate_str(value: Decimal | float | str) -> str:
    return format(Decimal(str(value)).quantize(Decimal("0.000001")), "f")


def _source_region_key(region: WeatherRegion) -> str:
    return f"lat={_coordinate_str(region.latitude)},lon={_coordinate_str(region.longitude)}"


def _canonical_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.normalize(), "f")


def _normalize_run_type(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in {"manual", "backfill"}:
        raise ValueError("run_type must be either 'manual' or 'backfill'")
    return normalized


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
    collector: OpenMeteoHistoricalWeatherCollector,
    collector_run: CollectorRun,
    started_at: datetime,
    *,
    selected_regions: tuple[WeatherRegion, ...],
    from_date: date,
    to_date: date,
    regions_success: int,
    regions_failed: int,
    skipped_existing: int,
    conflicts_count: int,
    raw_response_ids: list[int],
    errors_count: int,
) -> OpenMeteoCollectorResult:
    return OpenMeteoCollectorResult(
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
        regions_requested=len(selected_regions),
        regions_success=regions_success,
        regions_failed=regions_failed,
        skipped_existing=skipped_existing,
        conflicts_count=conflicts_count,
        regions=tuple(region.region_code for region in selected_regions),
        from_date=from_date.isoformat(),
        to_date=to_date.isoformat(),
    )
