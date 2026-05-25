from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, time, timezone
from decimal import Decimal, ROUND_HALF_UP
from statistics import pstdev
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config.settings import get_settings
from app.db.models import DailyProductFeature, DataQualityCheck, FxRate, PriceObservation, Product
from app.db.session import session_scope


FEATURE_VERSION = "daily_features_v1"
FX_PAIRS = ("CNY", "USD", "EUR")
NUMERIC_SCALES = {
    "price_last": 6,
    "price_first": 6,
    "price_min": 6,
    "price_max": 6,
    "price_delta_abs_1d": 6,
    "price_delta_pct_1d": 8,
    "price_intraday_delta_abs": 6,
    "price_intraday_delta_pct": 8,
    "price_rolling_mean_3d": 6,
    "price_rolling_mean_7d": 6,
    "price_rolling_std_7d": 6,
    "cny_rub": 8,
    "usd_rub": 8,
    "eur_rub": 8,
    "cny_rub_delta_abs_1d": 8,
    "cny_rub_delta_pct_1d": 8,
    "usd_rub_delta_abs_1d": 8,
    "usd_rub_delta_pct_1d": 8,
    "eur_rub_delta_abs_1d": 8,
    "eur_rub_delta_pct_1d": 8,
}


@dataclass(frozen=True)
class DailyFeatureBuildResult:
    products_processed: int = 0
    dates_processed: int = 0
    rows_created: int = 0
    rows_updated: int = 0
    rows_skipped: int = 0
    missing_fx_dates: list[str] = field(default_factory=list)
    warnings_count: int = 0


@dataclass(frozen=True)
class _PriceDay:
    product_id: int
    feature_date: date
    observations: tuple[PriceObservation, ...]

    @property
    def ordered(self) -> tuple[PriceObservation, ...]:
        return tuple(sorted(self.observations, key=lambda item: _to_utc(item.observed_at)))

    @property
    def first(self) -> PriceObservation:
        return self.ordered[0]

    @property
    def last(self) -> PriceObservation:
        return self.ordered[-1]


@dataclass(frozen=True)
class _FxAsOf:
    rates: dict[str, FxRate]
    previous_rates: dict[str, FxRate]

    @property
    def fx_as_of_date(self) -> date | None:
        dates = [_to_utc(rate.observed_at).date() for rate in self.rates.values()]
        return max(dates) if dates else None


def build_daily_features(
    *,
    from_date: date | None = None,
    to_date: date | None = None,
    session: Session | None = None,
) -> DailyFeatureBuildResult:
    if session is None:
        with session_scope() as scoped_session:
            return _build_daily_features_with_session(scoped_session, from_date=from_date, to_date=to_date)
    return _build_daily_features_with_session(session, from_date=from_date, to_date=to_date)


def _build_daily_features_with_session(
    session: Session,
    *,
    from_date: date | None,
    to_date: date | None,
) -> DailyFeatureBuildResult:
    settings = get_settings()
    local_tz = ZoneInfo(settings.schedule_timezone)
    bounds = _price_date_bounds(session, local_tz=local_tz)
    if bounds is None:
        return DailyFeatureBuildResult()
    start = from_date or bounds[0]
    end = to_date or bounds[1]
    if start > end:
        raise ValueError("from_date must be on or before to_date")

    price_days = _load_price_days(session, from_date=start, to_date=end, local_tz=local_tz)
    products_processed = len({key[0] for key in price_days})
    dates_processed = len({key[1] for key in price_days})
    daily_last_by_product = _daily_last_prices(session, to_date=end, local_tz=local_tz)
    fx_rates = _load_fx_rates(session, to_date=end)

    rows_created = 0
    rows_updated = 0
    rows_skipped = 0
    missing_fx_dates: set[str] = set()
    warnings_count = 0
    checked_at = datetime.now(timezone.utc)

    for (product_id, feature_date), price_day in sorted(price_days.items(), key=lambda item: (item[0][1], item[0][0])):
        values, warning_names = _feature_values(
            price_day=price_day,
            daily_last_by_product=daily_last_by_product,
            fx_rates=fx_rates,
        )
        if warning_names:
            missing_fx_dates.add(feature_date.isoformat())
            warnings_count += len(warning_names)
        existing = session.scalar(
            select(DailyProductFeature)
            .where(DailyProductFeature.product_id == product_id, DailyProductFeature.feature_date == feature_date)
            .limit(1)
        )
        if existing is None:
            session.add(DailyProductFeature(product_id=product_id, feature_date=feature_date, **values))
            rows_created += 1
        elif _feature_row_needs_update(existing, values):
            for key, value in values.items():
                setattr(existing, key, value)
            existing.updated_at = checked_at
            rows_updated += 1
        else:
            rows_skipped += 1
        session.flush()
        _write_feature_quality_checks(
            session,
            product_id=product_id,
            feature_date=feature_date,
            values=values,
            checked_at=checked_at,
        )

    return DailyFeatureBuildResult(
        products_processed=products_processed,
        dates_processed=dates_processed,
        rows_created=rows_created,
        rows_updated=rows_updated,
        rows_skipped=rows_skipped,
        missing_fx_dates=sorted(missing_fx_dates),
        warnings_count=warnings_count,
    )


def _price_date_bounds(session: Session, *, local_tz: ZoneInfo) -> tuple[date, date] | None:
    values = session.execute(select(PriceObservation.observed_at)).scalars().all()
    if not values:
        return None
    dates = [_to_utc(value).astimezone(local_tz).date() for value in values]
    return min(dates), max(dates)


def _load_price_days(
    session: Session,
    *,
    from_date: date,
    to_date: date,
    local_tz: ZoneInfo,
) -> dict[tuple[int, date], _PriceDay]:
    observations = session.scalars(select(PriceObservation).order_by(PriceObservation.product_id, PriceObservation.observed_at)).all()
    grouped: dict[tuple[int, date], list[PriceObservation]] = {}
    for observation in observations:
        feature_date = _to_utc(observation.observed_at).astimezone(local_tz).date()
        if from_date <= feature_date <= to_date:
            grouped.setdefault((observation.product_id, feature_date), []).append(observation)
    return {
        key: _PriceDay(product_id=key[0], feature_date=key[1], observations=tuple(items))
        for key, items in grouped.items()
    }


def _daily_last_prices(session: Session, *, to_date: date, local_tz: ZoneInfo) -> dict[int, list[tuple[date, Decimal]]]:
    observations = session.scalars(select(PriceObservation).order_by(PriceObservation.product_id, PriceObservation.observed_at)).all()
    grouped: dict[tuple[int, date], PriceObservation] = {}
    for observation in observations:
        feature_date = _to_utc(observation.observed_at).astimezone(local_tz).date()
        if feature_date > to_date:
            continue
        key = (observation.product_id, feature_date)
        existing = grouped.get(key)
        if existing is None or _to_utc(observation.observed_at) > _to_utc(existing.observed_at):
            grouped[key] = observation

    by_product: dict[int, list[tuple[date, Decimal]]] = {}
    for (product_id, feature_date), observation in grouped.items():
        by_product.setdefault(product_id, []).append((feature_date, observation.price))
    for items in by_product.values():
        items.sort(key=lambda item: item[0])
    return by_product


def _load_fx_rates(session: Session, *, to_date: date) -> dict[str, list[FxRate]]:
    cutoff = datetime.combine(to_date, time.max, tzinfo=timezone.utc)
    rates = session.scalars(
        select(FxRate)
        .where(FxRate.quote_currency == "RUB", FxRate.base_currency.in_(FX_PAIRS), FxRate.observed_at <= cutoff)
        .order_by(FxRate.base_currency, FxRate.observed_at)
    ).all()
    by_currency: dict[str, list[FxRate]] = {currency: [] for currency in FX_PAIRS}
    for rate in rates:
        by_currency.setdefault(rate.base_currency, []).append(rate)
    return by_currency


def _feature_values(
    *,
    price_day: _PriceDay,
    daily_last_by_product: dict[int, list[tuple[date, Decimal]]],
    fx_rates: dict[str, list[FxRate]],
) -> tuple[dict[str, Any], list[str]]:
    ordered = price_day.ordered
    prices = [item.price for item in ordered]
    price_first = ordered[0].price
    price_last = ordered[-1].price
    as_of_at = _to_utc(ordered[-1].observed_at)
    previous_price = _previous_price(daily_last_by_product.get(price_day.product_id, []), price_day.feature_date)
    intraday_abs = price_last - price_first if len(ordered) >= 2 else None
    intraday_pct = _pct(intraday_abs, price_first) if intraday_abs is not None else None
    price_delta_abs = price_last - previous_price if previous_price is not None else None
    price_delta_pct = _pct(price_delta_abs, previous_price) if price_delta_abs is not None else None
    rolling_values = _rolling_values(daily_last_by_product.get(price_day.product_id, []), price_day.feature_date)
    fx_as_of = _fx_as_of(fx_rates, price_day.feature_date)
    warnings: list[str] = []

    values: dict[str, Any] = {
        "as_of_at": as_of_at,
        "feature_version": FEATURE_VERSION,
        "price_last": price_last,
        "price_first": price_first,
        "price_min": min(prices),
        "price_max": max(prices),
        "price_observations_count": len(ordered),
        "price_delta_abs_1d": price_delta_abs,
        "price_delta_pct_1d": price_delta_pct,
        "price_intraday_delta_abs": intraday_abs,
        "price_intraday_delta_pct": intraday_pct,
        "price_rolling_mean_3d": rolling_values["mean_3d"],
        "price_rolling_mean_7d": rolling_values["mean_7d"],
        "price_rolling_std_7d": rolling_values["std_7d"],
        "fx_as_of_date": fx_as_of.fx_as_of_date,
    }
    for currency in FX_PAIRS:
        field = f"{currency.lower()}_rub"
        rate = fx_as_of.rates.get(currency)
        previous_rate = fx_as_of.previous_rates.get(currency)
        if rate is None:
            warnings.append(f"missing_fx_{currency.lower()}")
            values[field] = None
            values[f"{field}_delta_abs_1d"] = None
            values[f"{field}_delta_pct_1d"] = None
            continue
        delta_abs = rate.rate - previous_rate.rate if previous_rate is not None else None
        values[field] = rate.rate
        values[f"{field}_delta_abs_1d"] = delta_abs
        values[f"{field}_delta_pct_1d"] = _pct(delta_abs, previous_rate.rate) if delta_abs is not None else None

    values = _normalize_feature_values(values)
    values["features_json"] = _features_json(values)
    return values, warnings


def _previous_price(items: list[tuple[date, Decimal]], feature_date: date) -> Decimal | None:
    previous = [price for item_date, price in items if item_date < feature_date]
    return previous[-1] if previous else None


def _rolling_values(items: list[tuple[date, Decimal]], feature_date: date) -> dict[str, Decimal | None]:
    values = [price for item_date, price in items if item_date <= feature_date]
    last3 = values[-3:]
    last7 = values[-7:]
    return {
        "mean_3d": _mean(last3) if len(last3) == 3 else None,
        "mean_7d": _mean(last7) if len(last7) == 7 else None,
        "std_7d": _std(last7) if len(last7) == 7 else None,
    }


def _fx_as_of(fx_rates: dict[str, list[FxRate]], feature_date: date) -> _FxAsOf:
    cutoff = datetime.combine(feature_date, time.max, tzinfo=timezone.utc)
    current: dict[str, FxRate] = {}
    previous: dict[str, FxRate] = {}
    for currency in FX_PAIRS:
        eligible = [rate for rate in fx_rates.get(currency, []) if _to_utc(rate.observed_at) <= cutoff]
        if not eligible:
            continue
        current_rate = eligible[-1]
        current[currency] = current_rate
        older = [rate for rate in eligible[:-1] if _to_utc(rate.observed_at) < _to_utc(current_rate.observed_at)]
        if older:
            previous[currency] = older[-1]
    return _FxAsOf(rates=current, previous_rates=previous)


def _write_feature_quality_checks(
    session: Session,
    *,
    product_id: int,
    feature_date: date,
    values: dict[str, Any],
    checked_at: datetime,
) -> None:
    details = {"product_id": product_id, "feature_date": feature_date.isoformat()}
    _write_check(session, "daily_feature_price_present", "pass" if values["price_last"] is not None else "error", "error" if values["price_last"] is None else "info", details, checked_at)
    _write_check(session, "daily_feature_fx_cny_present", "pass" if values["cny_rub"] is not None else "warning", "warning" if values["cny_rub"] is None else "info", details, checked_at)
    no_future_fx = values["fx_as_of_date"] is None or values["fx_as_of_date"] <= feature_date
    _write_check(session, "daily_feature_no_future_fx", "pass" if no_future_fx else "error", "error" if not no_future_fx else "info", {**details, "fx_as_of_date": values["fx_as_of_date"].isoformat() if values["fx_as_of_date"] else None}, checked_at)
    no_future_price = _to_utc(values["as_of_at"]).date() <= feature_date
    _write_check(session, "daily_feature_no_future_price", "pass" if no_future_price else "error", "error" if not no_future_price else "info", {**details, "as_of_at": values["as_of_at"].isoformat()}, checked_at)
    duplicate_count = session.scalar(
        select(func.count())
        .select_from(DailyProductFeature)
        .where(DailyProductFeature.product_id == product_id, DailyProductFeature.feature_date == feature_date)
    )
    _write_check(session, "daily_feature_unique_product_date", "pass" if duplicate_count == 1 else "error", "error" if duplicate_count != 1 else "info", {**details, "rows_count": duplicate_count}, checked_at)
    positive_count = (values["price_observations_count"] or 0) > 0
    _write_check(session, "daily_feature_price_observations_count_positive", "pass" if positive_count else "error", "error" if not positive_count else "info", {**details, "price_observations_count": values["price_observations_count"]}, checked_at)


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
            table_name="daily_product_features",
            check_name=check_name,
            checked_at=checked_at,
            status=status,
            severity=severity,
            details_json=details,
        )
    )


def _feature_row_needs_update(row: DailyProductFeature, values: dict[str, Any]) -> bool:
    for key, value in values.items():
        if key == "updated_at":
            continue
        if not _values_equal(getattr(row, key), value):
            return True
    return False


def _normalize_feature_values(values: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(values)
    for key, scale in NUMERIC_SCALES.items():
        normalized[key] = _quant(normalized.get(key), scale=scale)
    return normalized


def _values_equal(left: Any, right: Any) -> bool:
    if isinstance(left, datetime) or isinstance(right, datetime):
        if left is None or right is None:
            return left is right
        return _to_utc(left) == _to_utc(right)
    if isinstance(left, Decimal) or isinstance(right, Decimal):
        return _quant(left) == _quant(right)
    return left == right


def _features_json(values: dict[str, Any]) -> dict[str, Any]:
    return {key: _json_value(value) for key, value in values.items() if key not in {"features_json"}}


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _pct(delta: Decimal | None, base: Decimal | None) -> Decimal | None:
    if delta is None or base is None or base == 0:
        return None
    return _quant(delta / base, scale=8)


def _mean(values: list[Decimal]) -> Decimal:
    return _quant(sum(values) / Decimal(len(values)), scale=6)


def _std(values: list[Decimal]) -> Decimal:
    return _quant(Decimal(str(pstdev([float(value) for value in values]))), scale=6)


def _quant(value: Any, *, scale: int = 8) -> Decimal | None:
    if value is None:
        return None
    quant = Decimal("1").scaleb(-scale)
    return Decimal(value).quantize(quant, rounding=ROUND_HALF_UP)


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
