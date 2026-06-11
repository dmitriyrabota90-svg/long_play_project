from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import DataQualityCheck, WeatherDailyFeature, WeatherObservation, WeatherRegion
from app.db.session import session_scope


WEATHER_DAILY_FEATURE_VERSION = "weather_daily_features_v1"
HEAT_STRESS_THRESHOLD_C = Decimal("30")
FROST_THRESHOLD_C = Decimal("0")
SOYBEAN_GDD_BASE_C = Decimal("10")
RAPESEED_GDD_BASE_C = Decimal("5")
DEFAULT_GDD_BASE_C = Decimal("10")


@dataclass(frozen=True)
class WeatherDailyBuildResult:
    regions_processed: int = 0
    dates_processed: int = 0
    rows_created: int = 0
    rows_updated: int = 0
    rows_skipped: int = 0
    warnings_count: int = 0
    missing_observation_regions: list[str] = field(default_factory=list)


def build_weather_daily_features(
    *,
    region_code: str | None = None,
    from_date: date | None = None,
    to_date: date | None = None,
    session: Session | None = None,
) -> WeatherDailyBuildResult:
    if session is None:
        with session_scope() as scoped_session:
            return _build_weather_daily_features_with_session(
                scoped_session,
                region_code=region_code,
                from_date=from_date,
                to_date=to_date,
            )
    return _build_weather_daily_features_with_session(
        session,
        region_code=region_code,
        from_date=from_date,
        to_date=to_date,
    )


def _build_weather_daily_features_with_session(
    session: Session,
    *,
    region_code: str | None,
    from_date: date | None,
    to_date: date | None,
) -> WeatherDailyBuildResult:
    checked_at = datetime.now(timezone.utc)
    regions = _select_regions(session, region_code=region_code)
    if not regions:
        return WeatherDailyBuildResult()

    bounds = _observation_date_bounds(session, regions=regions)
    if bounds is None:
        for region in regions:
            _write_missing_region_check(session, region=region, checked_at=checked_at)
        return WeatherDailyBuildResult(
            regions_processed=len(regions),
            dates_processed=0,
            rows_skipped=len(regions),
            warnings_count=len(regions),
            missing_observation_regions=[region.region_code for region in regions],
        )

    start = from_date or bounds[0]
    end = to_date or bounds[1]
    if start > end:
        raise ValueError("from_date must be on or before to_date")
    feature_dates = tuple(_date_range(start, end))
    observations = _load_observations(session, regions=regions, to_date=end)

    rows_created = 0
    rows_updated = 0
    rows_skipped = 0
    warnings_count = 0
    missing_regions: list[str] = []

    for region in regions:
        region_observations = observations.get(region.id, [])
        if not region_observations:
            missing_regions.append(region.region_code)
            rows_skipped += len(feature_dates) or 1
            warnings_count += 1
            _write_missing_region_check(session, region=region, checked_at=checked_at)
            continue
        for feature_date in feature_dates:
            values = _feature_values(region=region, observations=region_observations, feature_date=feature_date)
            if values is None:
                rows_skipped += 1
                warnings_count += 1
                _write_quality_checks(
                    session,
                    region=region,
                    feature_date=feature_date,
                    values=None,
                    checked_at=checked_at,
                )
                continue
            if values["missing_flags"]:
                warnings_count += 1
            existing = session.scalar(
                select(WeatherDailyFeature)
                .where(WeatherDailyFeature.region_id == region.id, WeatherDailyFeature.feature_date == feature_date)
                .limit(1)
            )
            if existing is None:
                session.add(WeatherDailyFeature(region_id=region.id, feature_date=feature_date, **values))
                rows_created += 1
            elif _feature_row_needs_update(existing, values):
                for key, value in values.items():
                    setattr(existing, key, value)
                existing.updated_at = checked_at
                rows_updated += 1
            else:
                rows_skipped += 1
            session.flush()
            _write_quality_checks(
                session,
                region=region,
                feature_date=feature_date,
                values=values,
                checked_at=checked_at,
            )

    return WeatherDailyBuildResult(
        regions_processed=len(regions),
        dates_processed=len(feature_dates),
        rows_created=rows_created,
        rows_updated=rows_updated,
        rows_skipped=rows_skipped,
        warnings_count=warnings_count,
        missing_observation_regions=missing_regions,
    )


def _feature_values(
    *,
    region: WeatherRegion,
    observations: list[WeatherObservation],
    feature_date: date,
) -> dict[str, Any] | None:
    eligible = [item for item in observations if item.observation_date <= feature_date]
    if not eligible:
        return None
    windows = {
        7: _window(eligible, feature_date=feature_date, days=7),
        14: _window(eligible, feature_date=feature_date, days=14),
        30: _window(eligible, feature_date=feature_date, days=30),
    }
    base_temperature = _gdd_base_temperature(region)
    precipitation_30d = _sum_decimal([item.precipitation_sum for item in windows[30]])
    values: dict[str, Any] = {
        "temperature_7d_mean": _mean_decimal([item.temperature_2m_mean for item in windows[7]]),
        "temperature_30d_mean": _mean_decimal([item.temperature_2m_mean for item in windows[30]]),
        "temperature_min_7d": _min_decimal([item.temperature_2m_min for item in windows[7]]),
        "temperature_max_7d": _max_decimal([item.temperature_2m_max for item in windows[7]]),
        "precipitation_7d_sum": _sum_decimal([item.precipitation_sum for item in windows[7]]),
        "precipitation_14d_sum": _sum_decimal([item.precipitation_sum for item in windows[14]]),
        "precipitation_30d_sum": precipitation_30d,
        "heat_stress_days_7d": _threshold_count([item.temperature_2m_max for item in windows[7]], HEAT_STRESS_THRESHOLD_C, "gte"),
        "heat_stress_days_30d": _threshold_count([item.temperature_2m_max for item in windows[30]], HEAT_STRESS_THRESHOLD_C, "gte"),
        "frost_days_7d": _threshold_count([item.temperature_2m_min for item in windows[7]], FROST_THRESHOLD_C, "lte"),
        "frost_days_30d": _threshold_count([item.temperature_2m_min for item in windows[30]], FROST_THRESHOLD_C, "lte"),
        "drought_proxy_30d": precipitation_30d,
        "growing_degree_days_7d": _growing_degree_days(windows[7], base_temperature),
        "growing_degree_days_30d": _growing_degree_days(windows[30], base_temperature),
        "weather_as_of_date": max(item.observation_date for item in eligible),
    }
    values["missing_flags"] = _missing_flags(windows=windows, values=values)
    values["metadata_json"] = {
        "aggregation_version": WEATHER_DAILY_FEATURE_VERSION,
        "source_table": "weather_observations",
        "windows_used": {"7d": 7, "14d": 14, "30d": 30},
        "heat_stress_threshold": _canonical_decimal(HEAT_STRESS_THRESHOLD_C),
        "frost_threshold": _canonical_decimal(FROST_THRESHOLD_C),
        "gdd_base_temperature": _canonical_decimal(base_temperature),
        "observation_count_7d": len(windows[7]),
        "observation_count_14d": len(windows[14]),
        "observation_count_30d": len(windows[30]),
        "region_code": region.region_code,
        "commodity_family": region.commodity_family,
    }
    return _normalize_feature_values(values)


def _select_regions(session: Session, *, region_code: str | None) -> tuple[WeatherRegion, ...]:
    if region_code:
        region = session.scalar(select(WeatherRegion).where(WeatherRegion.region_code == region_code).limit(1))
        if region is None:
            raise ValueError(f"unknown weather region: {region_code}")
        return (region,)
    region_ids = (
        select(WeatherObservation.region_id)
        .group_by(WeatherObservation.region_id)
        .subquery()
    )
    return tuple(
        session.scalars(
            select(WeatherRegion)
            .join(region_ids, WeatherRegion.id == region_ids.c.region_id)
            .where(WeatherRegion.is_active.is_(True))
            .order_by(WeatherRegion.priority, WeatherRegion.region_code)
        ).all()
    )


def _observation_date_bounds(session: Session, *, regions: tuple[WeatherRegion, ...]) -> tuple[date, date] | None:
    region_ids = [region.id for region in regions]
    if not region_ids:
        return None
    min_date, max_date = session.execute(
        select(func.min(WeatherObservation.observation_date), func.max(WeatherObservation.observation_date)).where(
            WeatherObservation.region_id.in_(region_ids)
        )
    ).one()
    if min_date is None or max_date is None:
        return None
    return min_date, max_date


def _load_observations(
    session: Session,
    *,
    regions: tuple[WeatherRegion, ...],
    to_date: date,
) -> dict[int, list[WeatherObservation]]:
    region_ids = [region.id for region in regions]
    if not region_ids:
        return {}
    rows = session.scalars(
        select(WeatherObservation)
        .where(WeatherObservation.region_id.in_(region_ids), WeatherObservation.observation_date <= to_date)
        .order_by(WeatherObservation.region_id, WeatherObservation.observation_date)
    ).all()
    grouped: dict[int, list[WeatherObservation]] = {}
    for row in rows:
        grouped.setdefault(row.region_id, []).append(row)
    return grouped


def _window(observations: list[WeatherObservation], *, feature_date: date, days: int) -> list[WeatherObservation]:
    start = feature_date - timedelta(days=days - 1)
    return [item for item in observations if start <= item.observation_date <= feature_date]


def _missing_flags(*, windows: dict[int, list[WeatherObservation]], values: dict[str, Any]) -> dict[str, bool]:
    flags = {
        "missing_temperature": values["temperature_30d_mean"] is None
        or values["temperature_min_7d"] is None
        or values["temperature_max_7d"] is None,
        "missing_precipitation": values["precipitation_30d_sum"] is None,
        "incomplete_7d_window": len(windows[7]) < 7,
        "incomplete_14d_window": len(windows[14]) < 14,
        "incomplete_30d_window": len(windows[30]) < 30,
        "missing_region_observations": False,
    }
    return {key: value for key, value in flags.items() if value}


def _gdd_base_temperature(region: WeatherRegion) -> Decimal:
    family = region.commodity_family.lower()
    crop = region.crop.lower()
    text = f"{family} {crop}"
    if "rapeseed" in text or "canola" in text:
        return RAPESEED_GDD_BASE_C
    if "soybean" in text:
        return SOYBEAN_GDD_BASE_C
    return DEFAULT_GDD_BASE_C


def _growing_degree_days(observations: list[WeatherObservation], base_temperature: Decimal) -> Decimal | None:
    values = [item.temperature_2m_mean for item in observations if item.temperature_2m_mean is not None]
    if not values:
        return None
    return _quant(sum(max(Decimal("0"), value - base_temperature) for value in values))


def _mean_decimal(values: list[Decimal | None]) -> Decimal | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return _quant(sum(present) / Decimal(len(present)))


def _sum_decimal(values: list[Decimal | None]) -> Decimal | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return _quant(sum(present))


def _min_decimal(values: list[Decimal | None]) -> Decimal | None:
    present = [value for value in values if value is not None]
    return _quant(min(present)) if present else None


def _max_decimal(values: list[Decimal | None]) -> Decimal | None:
    present = [value for value in values if value is not None]
    return _quant(max(present)) if present else None


def _threshold_count(values: list[Decimal | None], threshold: Decimal, op: str) -> int | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    if op == "gte":
        return sum(1 for value in present if value >= threshold)
    if op == "lte":
        return sum(1 for value in present if value <= threshold)
    raise ValueError(f"unknown threshold op: {op}")


def _normalize_feature_values(values: dict[str, Any]) -> dict[str, Any]:
    numeric_fields = {
        "temperature_7d_mean",
        "temperature_30d_mean",
        "temperature_min_7d",
        "temperature_max_7d",
        "precipitation_7d_sum",
        "precipitation_14d_sum",
        "precipitation_30d_sum",
        "drought_proxy_30d",
        "growing_degree_days_7d",
        "growing_degree_days_30d",
    }
    normalized = dict(values)
    for key in numeric_fields:
        normalized[key] = _quant(normalized.get(key))
    return normalized


def _feature_row_needs_update(row: WeatherDailyFeature, values: dict[str, Any]) -> bool:
    for key, value in values.items():
        if key == "updated_at":
            continue
        if not _values_equal(getattr(row, key), value):
            return True
    return False


def _values_equal(left: Any, right: Any) -> bool:
    if isinstance(left, Decimal) or isinstance(right, Decimal):
        return _quant(left) == _quant(right)
    return left == right


def _write_quality_checks(
    session: Session,
    *,
    region: WeatherRegion,
    feature_date: date,
    values: dict[str, Any] | None,
    checked_at: datetime,
) -> None:
    details = {"region_code": region.region_code, "region_id": region.id, "feature_date": feature_date.isoformat()}
    if values is None:
        _write_check(
            session,
            "weather_daily_observations_present",
            "warning",
            "warning",
            {**details, "missing_region_observations": True},
            checked_at,
        )
        return
    _write_check(session, "weather_daily_region_present", "pass", "info", details, checked_at)
    _write_check(session, "weather_daily_feature_date_valid", "pass", "info", details, checked_at)
    _write_check(session, "weather_daily_observations_present", "pass", "info", details, checked_at)
    no_future = values["weather_as_of_date"] is None or values["weather_as_of_date"] <= feature_date
    _write_check(
        session,
        "weather_daily_no_future_observations",
        "pass" if no_future else "error",
        "info" if no_future else "error",
        {**details, "weather_as_of_date": _date_str(values["weather_as_of_date"])},
        checked_at,
    )
    _write_check(
        session,
        "weather_daily_as_of_not_future",
        "pass" if no_future else "error",
        "info" if no_future else "error",
        {**details, "weather_as_of_date": _date_str(values["weather_as_of_date"])},
        checked_at,
    )
    temperature_reasonable = _temperature_reasonable(values)
    _write_check(
        session,
        "weather_daily_temperature_reasonable",
        "pass" if temperature_reasonable else "warning",
        "info" if temperature_reasonable else "warning",
        details,
        checked_at,
    )
    precipitation_non_negative = all(
        value is None or value >= 0
        for value in (
            values["precipitation_7d_sum"],
            values["precipitation_14d_sum"],
            values["precipitation_30d_sum"],
        )
    )
    _write_check(
        session,
        "weather_daily_precipitation_non_negative",
        "pass" if precipitation_non_negative else "error",
        "info" if precipitation_non_negative else "error",
        details,
        checked_at,
    )
    gdd_non_negative = all(
        value is None or value >= 0
        for value in (values["growing_degree_days_7d"], values["growing_degree_days_30d"])
    )
    _write_check(
        session,
        "weather_daily_gdd_non_negative",
        "pass" if gdd_non_negative else "error",
        "info" if gdd_non_negative else "error",
        details,
        checked_at,
    )
    _write_check(
        session,
        "weather_daily_missing_flags_recorded",
        "pass",
        "info",
        {**details, "missing_flags": values["missing_flags"]},
        checked_at,
    )


def _write_missing_region_check(session: Session, *, region: WeatherRegion, checked_at: datetime) -> None:
    _write_check(
        session,
        "weather_daily_observations_present",
        "warning",
        "warning",
        {
            "region_code": region.region_code,
            "region_id": region.id,
            "missing_region_observations": True,
        },
        checked_at,
    )


def _temperature_reasonable(values: dict[str, Any]) -> bool:
    for field in ("temperature_7d_mean", "temperature_30d_mean", "temperature_min_7d", "temperature_max_7d"):
        value = values.get(field)
        if value is None:
            continue
        if value < Decimal("-80") or value > Decimal("80"):
            return False
    return True


def _write_check(
    session: Session,
    check_name: str,
    status: str,
    severity: str,
    details: dict[str, Any],
    checked_at: datetime,
) -> None:
    session.add(
        DataQualityCheck(
            source_id=None,
            table_name="weather_daily_features",
            check_name=check_name,
            checked_at=checked_at,
            status=status,
            severity=severity,
            details_json=details,
        )
    )


def _date_range(start: date, end: date) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


def _date_str(value: Any) -> str | None:
    if isinstance(value, date):
        return value.isoformat()
    return None


def _canonical_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.normalize(), "f")


def _quant(value: Any, *, scale: int = 8) -> Decimal | None:
    if value is None:
        return None
    quant = Decimal("1").scaleb(-scale)
    return Decimal(value).quantize(quant, rounding=ROUND_HALF_UP)
