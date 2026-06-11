from __future__ import annotations

import calendar
import math
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from statistics import pstdev
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config.settings import get_settings
from app.db.models import (
    CommodityBenchmark,
    DailyNewsFeature,
    DailyProductFeature,
    DataQualityCheck,
    EnergyPrice,
    FxRate,
    PriceObservation,
    Product,
    ProductWeatherRegionWeight,
    Source,
    WeatherDailyFeature,
    WeatherRegion,
)
from app.db.session import session_scope


FEATURE_VERSION = "daily_features_v1"
FX_PAIRS = ("CNY", "USD", "EUR")
FRED_ENERGY_SOURCE_CODE = "fred_energy_prices"
WORLD_BANK_BENCHMARK_SOURCE_CODE = "world_bank_pink_sheet"
ENERGY_FEATURE_SPECS = {
    "brent": {
        "instrument_code": "DCOILBRENTEU",
        "value_field": "energy_brent_usd_per_barrel",
        "as_of_field": "energy_brent_as_of_date",
        "missing_flag": "missing_energy_brent",
        "delta_fields": {
            1: "energy_brent_delta_1d",
            7: "energy_brent_delta_7d",
        },
    },
    "wti": {
        "instrument_code": "DCOILWTICO",
        "value_field": "energy_wti_usd_per_barrel",
        "as_of_field": "energy_wti_as_of_date",
        "missing_flag": "missing_energy_wti",
        "delta_fields": {
            1: "energy_wti_delta_1d",
            7: "energy_wti_delta_7d",
        },
    },
    "henry_hub": {
        "instrument_code": "DHHNGSP",
        "value_field": "energy_henry_hub_usd_mmbtu",
        "as_of_field": "energy_henry_hub_as_of_date",
        "missing_flag": "missing_energy_henry_hub",
        "delta_fields": {
            1: "energy_henry_hub_delta_1d",
            7: "energy_henry_hub_delta_7d",
        },
    },
    "diesel": {
        "instrument_code": "GASDESW",
        "value_field": "energy_diesel_proxy_value",
        "as_of_field": "energy_diesel_as_of_date",
        "missing_flag": "missing_energy_diesel",
        "delta_fields": {
            7: "energy_diesel_proxy_delta_7d",
        },
    },
}
BENCHMARK_FEATURE_SPECS = {
    "soybean_oil": {
        "benchmark_code": "world_bank_soybean_oil",
        "value_field": "benchmark_soybean_oil_value",
        "as_of_field": "benchmark_soybean_oil_as_of_date",
        "missing_flag": "missing_benchmark_soybean_oil",
        "delta_fields": {1: "benchmark_soybean_oil_delta_1m", 3: "benchmark_soybean_oil_delta_3m"},
    },
    "soybeans": {
        "benchmark_code": "world_bank_soybeans",
        "value_field": "benchmark_soybeans_value",
        "as_of_field": "benchmark_soybeans_as_of_date",
        "missing_flag": "missing_benchmark_soybeans",
        "delta_fields": {1: "benchmark_soybeans_delta_1m", 3: "benchmark_soybeans_delta_3m"},
    },
    "palm_oil": {
        "benchmark_code": "world_bank_palm_oil",
        "value_field": "benchmark_palm_oil_value",
        "as_of_field": "benchmark_palm_oil_as_of_date",
        "missing_flag": "missing_benchmark_palm_oil",
        "delta_fields": {1: "benchmark_palm_oil_delta_1m", 3: "benchmark_palm_oil_delta_3m"},
    },
    "maize": {
        "benchmark_code": "world_bank_maize",
        "value_field": "benchmark_maize_value",
        "as_of_field": "benchmark_maize_as_of_date",
        "missing_flag": "missing_benchmark_maize",
        "delta_fields": {1: "benchmark_maize_delta_1m", 3: "benchmark_maize_delta_3m"},
    },
    "wheat": {
        "benchmark_code": "world_bank_wheat",
        "value_field": "benchmark_wheat_value",
        "as_of_field": "benchmark_wheat_as_of_date",
        "missing_flag": "missing_benchmark_wheat",
        "delta_fields": {1: "benchmark_wheat_delta_1m", 3: "benchmark_wheat_delta_3m"},
    },
    "fertilizer_index": {
        "benchmark_code": "world_bank_fertilizer_index",
        "value_field": "benchmark_fertilizer_index_value",
        "as_of_field": "benchmark_fertilizer_index_as_of_date",
        "missing_flag": "missing_benchmark_fertilizer_index",
        "delta_fields": {
            1: "benchmark_fertilizer_index_delta_1m",
            3: "benchmark_fertilizer_index_delta_3m",
        },
    },
}
WEATHER_FEATURE_SPECS = {
    "temperature_7d_mean": "weather_temperature_7d_mean_weighted",
    "temperature_30d_mean": "weather_temperature_30d_mean_weighted",
    "temperature_min_7d": "weather_temperature_min_7d_weighted",
    "temperature_max_7d": "weather_temperature_max_7d_weighted",
    "precipitation_7d_sum": "weather_precipitation_7d_sum_weighted",
    "precipitation_14d_sum": "weather_precipitation_14d_sum_weighted",
    "precipitation_30d_sum": "weather_precipitation_30d_sum_weighted",
    "heat_stress_days_7d": "weather_heat_stress_days_7d_weighted",
    "heat_stress_days_30d": "weather_heat_stress_days_30d_weighted",
    "frost_days_7d": "weather_frost_days_7d_weighted",
    "frost_days_30d": "weather_frost_days_30d_weighted",
    "drought_proxy_30d": "weather_drought_proxy_30d_weighted",
    "growing_degree_days_7d": "weather_growing_degree_days_7d_weighted",
    "growing_degree_days_30d": "weather_growing_degree_days_30d_weighted",
}
NEWS_PRODUCT_FEATURE_FIELDS = (
    "news_count_1d",
    "news_count_7d",
    "news_count_30d",
    "event_count_1d",
    "event_count_7d",
    "event_count_30d",
    "bullish_event_count_7d",
    "bearish_event_count_7d",
    "mixed_event_count_7d",
    "export_restriction_count_30d",
    "import_policy_count_30d",
    "war_logistics_count_30d",
    "weather_disaster_count_30d",
    "crop_report_count_30d",
    "biofuel_policy_count_30d",
    "energy_shock_count_30d",
    "demand_shock_count_30d",
    "supply_chain_count_30d",
    "sentiment_proxy_7d",
    "news_as_of_date",
)
SEASONS_BY_MONTH = {
    1: "winter",
    2: "winter",
    3: "spring",
    4: "spring",
    5: "spring",
    6: "summer",
    7: "summer",
    8: "summer",
    9: "autumn",
    10: "autumn",
    11: "autumn",
    12: "winter",
}
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
    "energy_brent_usd_per_barrel": 8,
    "energy_wti_usd_per_barrel": 8,
    "energy_henry_hub_usd_mmbtu": 8,
    "energy_diesel_proxy_value": 8,
    "energy_brent_delta_1d": 8,
    "energy_brent_delta_7d": 8,
    "energy_wti_delta_1d": 8,
    "energy_wti_delta_7d": 8,
    "energy_henry_hub_delta_1d": 8,
    "energy_henry_hub_delta_7d": 8,
    "energy_diesel_proxy_delta_7d": 8,
    "benchmark_soybean_oil_value": 8,
    "benchmark_soybeans_value": 8,
    "benchmark_palm_oil_value": 8,
    "benchmark_maize_value": 8,
    "benchmark_wheat_value": 8,
    "benchmark_fertilizer_index_value": 8,
    "benchmark_soybean_oil_delta_1m": 8,
    "benchmark_soybean_oil_delta_3m": 8,
    "benchmark_soybeans_delta_1m": 8,
    "benchmark_soybeans_delta_3m": 8,
    "benchmark_palm_oil_delta_1m": 8,
    "benchmark_palm_oil_delta_3m": 8,
    "benchmark_maize_delta_1m": 8,
    "benchmark_maize_delta_3m": 8,
    "benchmark_wheat_delta_1m": 8,
    "benchmark_wheat_delta_3m": 8,
    "benchmark_fertilizer_index_delta_1m": 8,
    "benchmark_fertilizer_index_delta_3m": 8,
    "weather_temperature_7d_mean_weighted": 8,
    "weather_temperature_30d_mean_weighted": 8,
    "weather_temperature_min_7d_weighted": 8,
    "weather_temperature_max_7d_weighted": 8,
    "weather_precipitation_7d_sum_weighted": 8,
    "weather_precipitation_14d_sum_weighted": 8,
    "weather_precipitation_30d_sum_weighted": 8,
    "weather_heat_stress_days_7d_weighted": 8,
    "weather_heat_stress_days_30d_weighted": 8,
    "weather_frost_days_7d_weighted": 8,
    "weather_frost_days_30d_weighted": 8,
    "weather_drought_proxy_30d_weighted": 8,
    "weather_growing_degree_days_7d_weighted": 8,
    "weather_growing_degree_days_30d_weighted": 8,
    "sentiment_proxy_7d": 8,
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


@dataclass(frozen=True)
class _WeatherWeight:
    product_id: int
    region_id: int
    region_code: str
    weight: Decimal
    effective_from: date
    effective_to: date | None


def build_calendar_features(feature_date: date) -> dict[str, Any]:
    """Return deterministic calendar features for one local feature date."""

    day_of_year = feature_date.timetuple().tm_yday
    days_in_year = 366 if calendar.isleap(feature_date.year) else 365
    month = feature_date.month
    next_day = feature_date + timedelta(days=1)
    quarter = ((month - 1) // 3) + 1
    angle_day = 2 * math.pi * day_of_year / days_in_year
    angle_month = 2 * math.pi * month / 12

    return {
        "calendar_year": feature_date.year,
        "calendar_month": month,
        "calendar_quarter": quarter,
        "calendar_week_of_year": feature_date.isocalendar().week,
        "calendar_day_of_year": day_of_year,
        "calendar_day_of_week": feature_date.isoweekday(),
        "calendar_is_month_start": feature_date.day == 1,
        "calendar_is_month_end": next_day.day == 1,
        "calendar_is_quarter_start": month in {1, 4, 7, 10} and feature_date.day == 1,
        "calendar_is_quarter_end": next_day.day == 1 and next_day.month in {1, 4, 7, 10},
        "calendar_sin_day_of_year": math.sin(angle_day),
        "calendar_cos_day_of_year": math.cos(angle_day),
        "calendar_sin_month": math.sin(angle_month),
        "calendar_cos_month": math.cos(angle_month),
        "calendar_season": SEASONS_BY_MONTH[month],
    }


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
    energy_prices = _load_energy_prices(session, to_date=end)
    benchmark_prices = _load_commodity_benchmarks(session, to_date=end)
    weather_weights = _load_product_weather_weights(session)
    weather_features = _load_weather_daily_features(session, to_date=end)
    news_features = _load_daily_news_features(session, to_date=end)

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
            energy_prices=energy_prices,
            benchmark_prices=benchmark_prices,
            weather_weights=weather_weights,
            weather_features=weather_features,
            news_features=news_features,
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


def _load_energy_prices(session: Session, *, to_date: date) -> dict[str, list[EnergyPrice]]:
    source_id = session.scalar(select(Source.id).where(Source.code == FRED_ENERGY_SOURCE_CODE).limit(1))
    instrument_codes = [str(spec["instrument_code"]) for spec in ENERGY_FEATURE_SPECS.values()]
    by_instrument: dict[str, list[EnergyPrice]] = {instrument_code: [] for instrument_code in instrument_codes}
    if source_id is None:
        return by_instrument
    prices = session.scalars(
        select(EnergyPrice)
        .where(
            EnergyPrice.source_id == source_id,
            EnergyPrice.instrument_code.in_(instrument_codes),
            EnergyPrice.period_start <= to_date,
        )
        .order_by(EnergyPrice.instrument_code, EnergyPrice.period_start, EnergyPrice.fetched_at, EnergyPrice.id)
    ).all()
    for price in prices:
        by_instrument.setdefault(price.instrument_code, []).append(price)
    return by_instrument


def _load_commodity_benchmarks(session: Session, *, to_date: date) -> dict[str, list[CommodityBenchmark]]:
    source_id = session.scalar(select(Source.id).where(Source.code == WORLD_BANK_BENCHMARK_SOURCE_CODE).limit(1))
    benchmark_codes = [str(spec["benchmark_code"]) for spec in BENCHMARK_FEATURE_SPECS.values()]
    by_code: dict[str, list[CommodityBenchmark]] = {benchmark_code: [] for benchmark_code in benchmark_codes}
    if source_id is None:
        return by_code
    rows = session.scalars(
        select(CommodityBenchmark)
        .where(
            CommodityBenchmark.source_id == source_id,
            CommodityBenchmark.benchmark_code.in_(benchmark_codes),
            CommodityBenchmark.period_start <= to_date,
        )
        .order_by(CommodityBenchmark.benchmark_code, CommodityBenchmark.period_start, CommodityBenchmark.fetched_at, CommodityBenchmark.id)
    ).all()
    for row in rows:
        by_code.setdefault(row.benchmark_code, []).append(row)
    return by_code


def _load_product_weather_weights(session: Session) -> dict[int, list[_WeatherWeight]]:
    rows = session.execute(
        select(ProductWeatherRegionWeight, WeatherRegion.region_code)
        .join(WeatherRegion, WeatherRegion.id == ProductWeatherRegionWeight.region_id)
        .where(ProductWeatherRegionWeight.is_active.is_(True), WeatherRegion.is_active.is_(True))
        .order_by(ProductWeatherRegionWeight.product_id, WeatherRegion.region_code)
    ).all()
    by_product: dict[int, list[_WeatherWeight]] = {}
    for weight, region_code in rows:
        by_product.setdefault(weight.product_id, []).append(
            _WeatherWeight(
                product_id=weight.product_id,
                region_id=weight.region_id,
                region_code=region_code,
                weight=weight.weight,
                effective_from=weight.effective_from,
                effective_to=weight.effective_to,
            )
        )
    return by_product


def _load_weather_daily_features(session: Session, *, to_date: date) -> dict[int, list[WeatherDailyFeature]]:
    rows = session.scalars(
        select(WeatherDailyFeature)
        .where(WeatherDailyFeature.feature_date <= to_date)
        .order_by(WeatherDailyFeature.region_id, WeatherDailyFeature.feature_date)
    ).all()
    by_region: dict[int, list[WeatherDailyFeature]] = {}
    for row in rows:
        by_region.setdefault(row.region_id, []).append(row)
    return by_region


def _load_daily_news_features(session: Session, *, to_date: date) -> dict[int, list[DailyNewsFeature]]:
    rows = session.scalars(
        select(DailyNewsFeature)
        .where(DailyNewsFeature.feature_date <= to_date)
        .order_by(DailyNewsFeature.product_id, DailyNewsFeature.feature_date)
    ).all()
    by_product: dict[int, list[DailyNewsFeature]] = {}
    for row in rows:
        by_product.setdefault(row.product_id, []).append(row)
    return by_product


def _feature_values(
    *,
    price_day: _PriceDay,
    daily_last_by_product: dict[int, list[tuple[date, Decimal]]],
    fx_rates: dict[str, list[FxRate]],
    energy_prices: dict[str, list[EnergyPrice]],
    benchmark_prices: dict[str, list[CommodityBenchmark]],
    weather_weights: dict[int, list[_WeatherWeight]],
    weather_features: dict[int, list[WeatherDailyFeature]],
    news_features: dict[int, list[DailyNewsFeature]],
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
    values.update(build_calendar_features(price_day.feature_date))
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
    values.update(_energy_feature_values(energy_prices, price_day.feature_date))
    values.update(_benchmark_feature_values(benchmark_prices, price_day.feature_date))
    values.update(
        _weather_feature_values(
            product_id=price_day.product_id,
            feature_date=price_day.feature_date,
            weather_weights=weather_weights,
            weather_features=weather_features,
        )
    )
    values.update(
        _news_feature_values(
            product_id=price_day.product_id,
            feature_date=price_day.feature_date,
            news_features=news_features,
        )
    )

    values = _normalize_feature_values(values)
    values["features_json"] = _features_json(values)
    return values, warnings


def _news_feature_values(
    *,
    product_id: int,
    feature_date: date,
    news_features: dict[int, list[DailyNewsFeature]],
) -> dict[str, Any]:
    values: dict[str, Any] = {field: None for field in NEWS_PRODUCT_FEATURE_FIELDS}
    values["news_missing_flags"] = None
    feature = _daily_news_as_of(news_features.get(product_id, []), feature_date)
    if feature is None:
        values["news_missing_flags"] = "missing_daily_news_features"
        return values
    if feature.news_as_of_date is not None and feature.news_as_of_date > feature_date:
        values["news_missing_flags"] = "future_news_as_of"
        return values

    for field in NEWS_PRODUCT_FEATURE_FIELDS:
        values[field] = getattr(feature, field)
    flags = _truthy_news_missing_flags(feature.missing_flags)
    values["news_missing_flags"] = ",".join(flags) if flags else None
    return values


def _daily_news_as_of(items: list[DailyNewsFeature], feature_date: date) -> DailyNewsFeature | None:
    eligible = [item for item in items if item.feature_date <= feature_date]
    return eligible[-1] if eligible else None


def _truthy_news_missing_flags(flags: Any) -> list[str]:
    if not isinstance(flags, dict):
        return []
    return [str(name) for name, value in flags.items() if value]


def _energy_feature_values(
    energy_prices: dict[str, list[EnergyPrice]],
    feature_date: date,
) -> dict[str, Any]:
    values: dict[str, Any] = {
        "energy_as_of_date": None,
        "energy_missing_flags": None,
    }
    for spec in ENERGY_FEATURE_SPECS.values():
        values[str(spec["value_field"])] = None
        values[str(spec["as_of_field"])] = None
        for delta_field in dict(spec["delta_fields"]).values():
            values[str(delta_field)] = None

    as_of_dates: list[date] = []
    missing_flags: list[str] = []
    for spec in ENERGY_FEATURE_SPECS.values():
        instrument_code = str(spec["instrument_code"])
        current = _energy_as_of(energy_prices.get(instrument_code, []), feature_date)
        if current is None:
            missing_flags.append(str(spec["missing_flag"]))
            continue
        current_value = _energy_value(current)
        values[str(spec["value_field"])] = current_value
        values[str(spec["as_of_field"])] = current.period_start
        as_of_dates.append(current.period_start)
        for days, delta_field in dict(spec["delta_fields"]).items():
            previous = _energy_as_of(energy_prices.get(instrument_code, []), feature_date - timedelta(days=int(days)))
            previous_value = _energy_value(previous) if previous is not None else None
            values[str(delta_field)] = current_value - previous_value if previous_value is not None else None

    values["energy_as_of_date"] = max(as_of_dates) if as_of_dates else None
    values["energy_missing_flags"] = ",".join(missing_flags) if missing_flags else None
    return values


def _energy_as_of(items: list[EnergyPrice], feature_date: date) -> EnergyPrice | None:
    eligible = [item for item in items if item.period_start <= feature_date]
    return eligible[-1] if eligible else None


def _energy_value(item: EnergyPrice) -> Decimal:
    return item.normalized_value if item.normalized_value is not None else item.value


def _benchmark_feature_values(
    benchmark_prices: dict[str, list[CommodityBenchmark]],
    feature_date: date,
) -> dict[str, Any]:
    values: dict[str, Any] = {
        "benchmark_as_of_date": None,
        "benchmark_missing_flags": None,
    }
    for spec in BENCHMARK_FEATURE_SPECS.values():
        values[str(spec["value_field"])] = None
        values[str(spec["as_of_field"])] = None
        for delta_field in dict(spec["delta_fields"]).values():
            values[str(delta_field)] = None

    as_of_dates: list[date] = []
    missing_flags: list[str] = []
    for spec in BENCHMARK_FEATURE_SPECS.values():
        benchmark_code = str(spec["benchmark_code"])
        current = _benchmark_as_of(benchmark_prices.get(benchmark_code, []), feature_date)
        if current is None:
            missing_flags.append(str(spec["missing_flag"]))
            continue
        current_value = _benchmark_value(current)
        values[str(spec["value_field"])] = current_value
        values[str(spec["as_of_field"])] = current.period_start
        as_of_dates.append(current.period_start)
        for months, delta_field in dict(spec["delta_fields"]).items():
            previous = _benchmark_as_of(
                benchmark_prices.get(benchmark_code, []),
                _subtract_months(feature_date, int(months)),
            )
            previous_value = _benchmark_value(previous) if previous is not None else None
            values[str(delta_field)] = current_value - previous_value if previous_value is not None else None

    values["benchmark_as_of_date"] = max(as_of_dates) if as_of_dates else None
    values["benchmark_missing_flags"] = ",".join(missing_flags) if missing_flags else None
    return values


def _weather_feature_values(
    *,
    product_id: int,
    feature_date: date,
    weather_weights: dict[int, list[_WeatherWeight]],
    weather_features: dict[int, list[WeatherDailyFeature]],
) -> dict[str, Any]:
    values: dict[str, Any] = {
        output_field: None
        for output_field in WEATHER_FEATURE_SPECS.values()
    }
    values.update(
        {
            "weather_as_of_date": None,
            "weather_regions_used": None,
            "weather_missing_flags": None,
        }
    )
    active_weights = _active_weather_weights(weather_weights.get(product_id, []), feature_date)
    if not active_weights:
        values["weather_missing_flags"] = "missing_product_weather_region_weights"
        return values

    selected: list[tuple[_WeatherWeight, WeatherDailyFeature]] = []
    missing_flags: list[str] = []
    as_of_dates: list[date] = []
    used_region_codes: list[str] = []

    for weight in active_weights:
        feature = _weather_as_of(weather_features.get(weight.region_id, []), feature_date)
        if feature is None:
            missing_flags.append(f"missing_region:{weight.region_code}")
            continue
        feature_as_of = feature.weather_as_of_date or feature.feature_date
        if feature_as_of > feature_date:
            missing_flags.append(f"future_weather_as_of:{weight.region_code}")
            continue
        selected.append((weight, feature))
        as_of_dates.append(feature_as_of)
        if _weather_feature_has_any_value(feature):
            used_region_codes.append(weight.region_code)
        for flag_name in _truthy_weather_missing_flags(feature.missing_flags):
            missing_flags.append(f"{weight.region_code}:{flag_name}")

    if not selected:
        missing_flags.append("missing_all_weather_regions")
    elif len(selected) < len(active_weights):
        missing_flags.append("partial_weather_regions")
    if selected and not used_region_codes:
        missing_flags.append("missing_all_weather_values")

    for source_field, output_field in WEATHER_FEATURE_SPECS.items():
        values[output_field] = _weighted_weather_value(selected, source_field=source_field)
    values["weather_as_of_date"] = max(as_of_dates) if as_of_dates else None
    values["weather_regions_used"] = ",".join(used_region_codes) if used_region_codes else None
    values["weather_missing_flags"] = ",".join(_dedupe(missing_flags)) if missing_flags else None
    return values


def _active_weather_weights(weights: list[_WeatherWeight], feature_date: date) -> list[_WeatherWeight]:
    return [
        weight
        for weight in weights
        if weight.effective_from <= feature_date and (weight.effective_to is None or weight.effective_to >= feature_date)
    ]


def _weather_as_of(items: list[WeatherDailyFeature], feature_date: date) -> WeatherDailyFeature | None:
    eligible = [item for item in items if item.feature_date <= feature_date]
    return eligible[-1] if eligible else None


def _weighted_weather_value(
    selected: list[tuple[_WeatherWeight, WeatherDailyFeature]],
    *,
    source_field: str,
) -> Decimal | None:
    numerator = Decimal("0")
    denominator = Decimal("0")
    for weight, feature in selected:
        value = getattr(feature, source_field)
        if value is None:
            continue
        numerator += Decimal(value) * weight.weight
        denominator += weight.weight
    if denominator == 0:
        return None
    return numerator / denominator


def _weather_feature_has_any_value(feature: WeatherDailyFeature) -> bool:
    return any(getattr(feature, source_field) is not None for source_field in WEATHER_FEATURE_SPECS)


def _truthy_weather_missing_flags(flags: Any) -> list[str]:
    if not isinstance(flags, dict):
        return []
    return [str(name) for name, value in flags.items() if value]


def _benchmark_as_of(items: list[CommodityBenchmark], feature_date: date) -> CommodityBenchmark | None:
    eligible = [item for item in items if item.period_start <= feature_date]
    return eligible[-1] if eligible else None


def _benchmark_value(item: CommodityBenchmark) -> Decimal:
    return item.normalized_value if item.normalized_value is not None else item.value


def _subtract_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 - months
    year = month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


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
    energy_as_of_dates = [
        values.get("energy_brent_as_of_date"),
        values.get("energy_wti_as_of_date"),
        values.get("energy_henry_hub_as_of_date"),
        values.get("energy_diesel_as_of_date"),
    ]
    no_future_energy = all(item is None or item <= feature_date for item in energy_as_of_dates)
    _write_check(
        session,
        "daily_feature_no_future_energy",
        "pass" if no_future_energy else "error",
        "error" if not no_future_energy else "info",
        {
            **details,
            "energy_brent_as_of_date": values["energy_brent_as_of_date"].isoformat() if values.get("energy_brent_as_of_date") else None,
            "energy_wti_as_of_date": values["energy_wti_as_of_date"].isoformat() if values.get("energy_wti_as_of_date") else None,
            "energy_henry_hub_as_of_date": values["energy_henry_hub_as_of_date"].isoformat() if values.get("energy_henry_hub_as_of_date") else None,
            "energy_diesel_as_of_date": values["energy_diesel_as_of_date"].isoformat() if values.get("energy_diesel_as_of_date") else None,
            "energy_missing_flags": values.get("energy_missing_flags"),
        },
        checked_at,
    )
    benchmark_as_of_dates = [
        values.get("benchmark_soybean_oil_as_of_date"),
        values.get("benchmark_soybeans_as_of_date"),
        values.get("benchmark_palm_oil_as_of_date"),
        values.get("benchmark_maize_as_of_date"),
        values.get("benchmark_wheat_as_of_date"),
        values.get("benchmark_fertilizer_index_as_of_date"),
    ]
    no_future_benchmark = all(item is None or item <= feature_date for item in benchmark_as_of_dates)
    _write_check(
        session,
        "daily_feature_no_future_benchmark",
        "pass" if no_future_benchmark else "error",
        "error" if not no_future_benchmark else "info",
        {
            **details,
            "benchmark_soybean_oil_as_of_date": values["benchmark_soybean_oil_as_of_date"].isoformat()
            if values.get("benchmark_soybean_oil_as_of_date")
            else None,
            "benchmark_soybeans_as_of_date": values["benchmark_soybeans_as_of_date"].isoformat()
            if values.get("benchmark_soybeans_as_of_date")
            else None,
            "benchmark_palm_oil_as_of_date": values["benchmark_palm_oil_as_of_date"].isoformat()
            if values.get("benchmark_palm_oil_as_of_date")
            else None,
            "benchmark_maize_as_of_date": values["benchmark_maize_as_of_date"].isoformat()
            if values.get("benchmark_maize_as_of_date")
            else None,
            "benchmark_wheat_as_of_date": values["benchmark_wheat_as_of_date"].isoformat()
            if values.get("benchmark_wheat_as_of_date")
            else None,
            "benchmark_fertilizer_index_as_of_date": values["benchmark_fertilizer_index_as_of_date"].isoformat()
            if values.get("benchmark_fertilizer_index_as_of_date")
            else None,
            "benchmark_missing_flags": values.get("benchmark_missing_flags"),
        },
        checked_at,
    )
    no_future_weather = values.get("weather_as_of_date") is None or values["weather_as_of_date"] <= feature_date
    _write_check(
        session,
        "daily_feature_no_future_weather",
        "pass" if no_future_weather else "error",
        "error" if not no_future_weather else "info",
        {
            **details,
            "weather_as_of_date": values["weather_as_of_date"].isoformat()
            if values.get("weather_as_of_date")
            else None,
            "weather_regions_used": values.get("weather_regions_used"),
            "weather_missing_flags": values.get("weather_missing_flags"),
        },
        checked_at,
    )
    _write_check(
        session,
        "daily_feature_weather_coverage_recorded",
        "pass",
        "info",
        {
            **details,
            "weather_regions_used": values.get("weather_regions_used"),
            "weather_missing_flags": values.get("weather_missing_flags"),
        },
        checked_at,
    )
    no_future_news = values.get("news_as_of_date") is None or values["news_as_of_date"] <= feature_date
    _write_check(
        session,
        "daily_feature_no_future_news",
        "pass" if no_future_news else "error",
        "error" if not no_future_news else "info",
        {
            **details,
            "news_as_of_date": values["news_as_of_date"].isoformat()
            if values.get("news_as_of_date")
            else None,
            "news_missing_flags": values.get("news_missing_flags"),
        },
        checked_at,
    )
    _write_check(
        session,
        "daily_feature_news_coverage_recorded",
        "pass",
        "info",
        {
            **details,
            "news_count_7d": values.get("news_count_7d"),
            "event_count_7d": values.get("event_count_7d"),
            "news_missing_flags": values.get("news_missing_flags"),
        },
        checked_at,
    )
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
    if isinstance(left, float) or isinstance(right, float):
        if left is None or right is None:
            return left is right
        return math.isclose(float(left), float(right), rel_tol=0.0, abs_tol=1e-12)
    return left == right


def _features_json(values: dict[str, Any]) -> dict[str, Any]:
    return {key: _json_value(value) for key, value in values.items() if key not in {"features_json"}}


def _json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _dedupe(values: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


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
