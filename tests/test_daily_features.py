from __future__ import annotations

import os
import subprocess
import sys
import calendar
import math
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.config.settings import get_settings
from app.db.models import (
    Base,
    CommodityBenchmark,
    DailyNewsFeature,
    DailyProductFeature,
    DataQualityCheck,
    EnergyPrice,
    FxRate,
    PriceObservation,
    Product,
    Source,
)
from app.features.daily import build_calendar_features, build_daily_features


def _session_factory(database_url: str = "sqlite+pysqlite:///:memory:"):
    engine = create_engine(database_url, future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def _seed_product(session, *, code: str = "WHEAT") -> Product:
    product = Product(code=code, name=code.title(), category="grain", unit="t", currency_default="CNY")
    session.add(product)
    session.flush()
    return product


def _seed_source(session, *, code: str = "current_price_source", source_type: str = "price") -> Source:
    source = Source(code=code, name=code, source_type=source_type, base_url="https://example.test")
    session.add(source)
    session.flush()
    return source


def _price(session, *, product_id: int, source_id: int, observed_at: datetime, price: str) -> None:
    session.add(
        PriceObservation(
            product_id=product_id,
            source_id=source_id,
            raw_response_id=1,
            observed_at=observed_at,
            published_at=None,
            price=Decimal(price),
            currency="CNY",
            unit="t",
            source_record_hash=f"{product_id}-{observed_at.isoformat()}-{price}",
        )
    )


def _fx(session, *, source_id: int, currency: str, observed_at: datetime, rate: str) -> None:
    session.add(
        FxRate(
            source_id=source_id,
            raw_response_id=1,
            base_currency=currency,
            quote_currency="RUB",
            rate=Decimal(rate),
            observed_at=observed_at,
            published_at=None,
        )
    )


def _seed_fx_set(session, *, source_id: int, observed_at: datetime, cny: str = "10", usd: str = "70", eur: str = "80") -> None:
    _fx(session, source_id=source_id, currency="CNY", observed_at=observed_at, rate=cny)
    _fx(session, source_id=source_id, currency="USD", observed_at=observed_at, rate=usd)
    _fx(session, source_id=source_id, currency="EUR", observed_at=observed_at, rate=eur)


def _energy(
    session,
    *,
    source_id: int,
    instrument_code: str,
    period_start: date,
    value: str,
    frequency: str = "daily",
) -> None:
    session.add(
        EnergyPrice(
            source_id=source_id,
            raw_response_id=1,
            collector_run_id=1,
            instrument_code=instrument_code,
            external_id=instrument_code,
            instrument_name=instrument_code,
            instrument_category="energy",
            frequency=frequency,
            period_start=period_start,
            period_end=period_start,
            observed_at=datetime.combine(period_start, datetime.min.time(), tzinfo=timezone.utc),
            published_at=None,
            fetched_at=datetime.combine(period_start, datetime.min.time(), tzinfo=timezone.utc),
            value=Decimal(value),
            currency="USD",
            unit="source_unit",
            normalized_value=Decimal(value),
            normalized_currency="USD",
            normalized_unit="source_unit",
            source_record_hash=f"{instrument_code}-{period_start.isoformat()}-{value}",
            source_payload_hash="a" * 64,
            metadata_json=None,
        )
    )


def _benchmark(
    session,
    *,
    source_id: int,
    benchmark_code: str,
    period_start: date,
    value: str,
    currency: str | None = "USD",
    unit: str = "source_unit",
) -> None:
    period_end = date(period_start.year, period_start.month, calendar.monthrange(period_start.year, period_start.month)[1])
    session.add(
        CommodityBenchmark(
            source_id=source_id,
            raw_response_id=1,
            collector_run_id=1,
            benchmark_code=benchmark_code,
            external_id=benchmark_code,
            benchmark_name=benchmark_code,
            benchmark_category="test_benchmark",
            commodity_family="test_family",
            geography="global",
            frequency="monthly",
            period_start=period_start,
            period_end=period_end,
            observed_at=datetime.combine(period_end, datetime.min.time(), tzinfo=timezone.utc),
            published_at=None,
            fetched_at=datetime.combine(period_end, datetime.min.time(), tzinfo=timezone.utc),
            value=Decimal(value),
            currency=currency,
            unit=unit,
            normalized_value=Decimal(value),
            normalized_currency=currency,
            normalized_unit=unit,
            source_record_hash=f"{benchmark_code}-{period_start.isoformat()}-{value}",
            source_payload_hash="b" * 64,
            metadata_json=None,
        )
    )


def test_feature_date_uses_europe_moscow_timezone() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        product = _seed_product(session)
        price_source = _seed_source(session)
        fx_source = _seed_source(session, code="cbr_fx", source_type="fx")
        _price(session, product_id=product.id, source_id=price_source.id, observed_at=datetime(2026, 5, 20, 21, 30, tzinfo=timezone.utc), price="100")
        _seed_fx_set(session, source_id=fx_source.id, observed_at=datetime(2026, 5, 21, tzinfo=timezone.utc))

        result = build_daily_features(session=session)
        session.commit()
        feature = session.scalar(select(DailyProductFeature))

    assert result.rows_created == 1
    assert feature.feature_date == date(2026, 5, 21)


def test_build_calendar_features_basic_iso_and_cyclic_values() -> None:
    feature_date = date(2026, 6, 1)
    values = build_calendar_features(feature_date)
    day_of_year = feature_date.timetuple().tm_yday

    assert values["calendar_year"] == 2026
    assert values["calendar_month"] == 6
    assert values["calendar_quarter"] == 2
    assert values["calendar_week_of_year"] == feature_date.isocalendar().week
    assert values["calendar_day_of_year"] == day_of_year
    assert values["calendar_day_of_week"] == 1
    assert values["calendar_season"] == "summer"
    assert math.isclose(values["calendar_sin_day_of_year"], math.sin(2 * math.pi * day_of_year / 365))
    assert math.isclose(values["calendar_cos_day_of_year"], math.cos(2 * math.pi * day_of_year / 365))
    assert math.isclose(values["calendar_sin_month"], math.sin(2 * math.pi * 6 / 12))
    assert math.isclose(values["calendar_cos_month"], math.cos(2 * math.pi * 6 / 12))
    for key in ("calendar_sin_day_of_year", "calendar_cos_day_of_year", "calendar_sin_month", "calendar_cos_month"):
        assert -1 <= values[key] <= 1


def test_build_calendar_features_leap_year_boundaries_and_seasons() -> None:
    leap_end = build_calendar_features(date(2024, 12, 31))
    quarter_start = build_calendar_features(date(2026, 4, 1))
    season_by_month = {1: "winter", 2: "winter", 3: "spring", 4: "spring", 5: "spring", 6: "summer", 7: "summer", 8: "summer", 9: "autumn", 10: "autumn", 11: "autumn", 12: "winter"}

    assert leap_end["calendar_day_of_year"] == 366
    assert math.isclose(leap_end["calendar_sin_day_of_year"], math.sin(2 * math.pi * 366 / 366))
    assert leap_end["calendar_is_month_end"] is True
    assert leap_end["calendar_is_quarter_end"] is True
    assert leap_end["calendar_season"] == "winter"
    assert quarter_start["calendar_is_month_start"] is True
    assert quarter_start["calendar_is_quarter_start"] is True
    for month, season in season_by_month.items():
        assert build_calendar_features(date(2026, month, 15))["calendar_season"] == season


def test_daily_price_fields_and_intraday_delta() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        product = _seed_product(session)
        price_source = _seed_source(session)
        fx_source = _seed_source(session, code="cbr_fx", source_type="fx")
        _price(session, product_id=product.id, source_id=price_source.id, observed_at=datetime(2026, 5, 20, 6, tzinfo=timezone.utc), price="100")
        _price(session, product_id=product.id, source_id=price_source.id, observed_at=datetime(2026, 5, 20, 15, tzinfo=timezone.utc), price="110")
        _seed_fx_set(session, source_id=fx_source.id, observed_at=datetime(2026, 5, 20, tzinfo=timezone.utc))

        build_daily_features(session=session)
        session.commit()
        feature = session.scalar(select(DailyProductFeature))

    assert feature.price_first == Decimal("100.000000")
    assert feature.price_last == Decimal("110.000000")
    assert feature.price_min == Decimal("100.000000")
    assert feature.price_max == Decimal("110.000000")
    assert feature.price_observations_count == 2
    assert feature.price_intraday_delta_abs == Decimal("10.000000")
    assert feature.price_intraday_delta_pct == Decimal("0.10000000")
    assert feature.calendar_year == 2026
    assert feature.calendar_month == 5
    assert feature.calendar_season == "spring"


def test_daily_build_copies_news_event_features() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        product = _seed_product(session, code="soybean_oil")
        price_source = _seed_source(session)
        fx_source = _seed_source(session, code="cbr_fx", source_type="fx")
        _price(session, product_id=product.id, source_id=price_source.id, observed_at=datetime(2026, 6, 10, 15, tzinfo=timezone.utc), price="100")
        _seed_fx_set(session, source_id=fx_source.id, observed_at=datetime(2026, 6, 10, tzinfo=timezone.utc))
        session.add(
            DailyNewsFeature(
                product_id=product.id,
                commodity_family="soybean",
                feature_date=date(2026, 6, 10),
                news_count_1d=1,
                news_count_7d=2,
                news_count_30d=3,
                event_count_1d=1,
                event_count_7d=3,
                event_count_30d=4,
                bullish_event_count_7d=1,
                bearish_event_count_7d=1,
                mixed_event_count_7d=1,
                export_restriction_count_30d=1,
                import_policy_count_30d=1,
                war_logistics_count_30d=0,
                weather_disaster_count_30d=0,
                crop_report_count_30d=1,
                biofuel_policy_count_30d=0,
                energy_shock_count_30d=1,
                demand_shock_count_30d=0,
                supply_chain_count_30d=0,
                sentiment_proxy_7d=Decimal("0"),
                news_as_of_date=date(2026, 6, 10),
                missing_flags={"partial_source_coverage": True},
                metadata_json={"test": True},
            )
        )

        build_daily_features(session=session)
        session.commit()
        feature = session.scalar(select(DailyProductFeature))

    assert feature.news_count_7d == 2
    assert feature.event_count_7d == 3
    assert feature.export_restriction_count_30d == 1
    assert feature.crop_report_count_30d == 1
    assert feature.sentiment_proxy_7d == Decimal("0E-8")
    assert feature.news_as_of_date == date(2026, 6, 10)
    assert feature.news_missing_flags == "partial_source_coverage"
    assert feature.features_json["news_count_7d"] == 2


def test_price_delta_and_rolling_windows_require_full_window() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        product = _seed_product(session)
        price_source = _seed_source(session)
        fx_source = _seed_source(session, code="cbr_fx", source_type="fx")
        for offset, price in enumerate(["100", "110", "120", "130", "140", "150", "160"], start=20):
            _price(session, product_id=product.id, source_id=price_source.id, observed_at=datetime(2026, 5, offset, 15, tzinfo=timezone.utc), price=price)
        _seed_fx_set(session, source_id=fx_source.id, observed_at=datetime(2026, 5, 20, tzinfo=timezone.utc))

        build_daily_features(session=session)
        session.commit()
        features = session.scalars(select(DailyProductFeature).order_by(DailyProductFeature.feature_date)).all()

    assert features[0].price_delta_abs_1d is None
    assert features[1].price_delta_abs_1d == Decimal("10.000000")
    assert features[1].price_delta_pct_1d == Decimal("0.10000000")
    assert features[1].price_rolling_mean_3d is None
    assert features[2].price_rolling_mean_3d == Decimal("110.000000")
    assert features[5].price_rolling_mean_7d is None
    assert features[6].price_rolling_mean_7d == Decimal("130.000000")
    assert features[6].price_rolling_std_7d is not None


def test_fx_as_of_uses_last_available_without_future_and_weekend_rate() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        product = _seed_product(session)
        price_source = _seed_source(session)
        fx_source = _seed_source(session, code="cbr_fx", source_type="fx")
        _price(session, product_id=product.id, source_id=price_source.id, observed_at=datetime(2026, 5, 24, 15, tzinfo=timezone.utc), price="100")
        _seed_fx_set(session, source_id=fx_source.id, observed_at=datetime(2026, 5, 23, tzinfo=timezone.utc), cny="10", usd="70", eur="80")
        _seed_fx_set(session, source_id=fx_source.id, observed_at=datetime(2026, 5, 25, tzinfo=timezone.utc), cny="99", usd="99", eur="99")

        build_daily_features(session=session)
        session.commit()
        feature = session.scalar(select(DailyProductFeature))

    assert feature.feature_date == date(2026, 5, 24)
    assert feature.cny_rub == Decimal("10.00000000")
    assert feature.usd_rub == Decimal("70.00000000")
    assert feature.eur_rub == Decimal("80.00000000")
    assert feature.fx_as_of_date == date(2026, 5, 23)


def test_fx_delta_uses_previous_available_observed_at() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        product = _seed_product(session)
        price_source = _seed_source(session)
        fx_source = _seed_source(session, code="cbr_fx", source_type="fx")
        _price(session, product_id=product.id, source_id=price_source.id, observed_at=datetime(2026, 5, 22, 15, tzinfo=timezone.utc), price="100")
        _seed_fx_set(session, source_id=fx_source.id, observed_at=datetime(2026, 5, 20, tzinfo=timezone.utc), cny="10", usd="70", eur="80")
        _seed_fx_set(session, source_id=fx_source.id, observed_at=datetime(2026, 5, 22, tzinfo=timezone.utc), cny="11", usd="77", eur="88")

        build_daily_features(session=session)
        session.commit()
        feature = session.scalar(select(DailyProductFeature))

    assert feature.cny_rub_delta_abs_1d == Decimal("1.00000000")
    assert feature.cny_rub_delta_pct_1d == Decimal("0.10000000")


def test_energy_features_use_as_of_without_future_leakage() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        product = _seed_product(session)
        price_source = _seed_source(session)
        fx_source = _seed_source(session, code="cbr_fx", source_type="fx")
        energy_source = _seed_source(session, code="fred_energy_prices", source_type="energy")
        _price(session, product_id=product.id, source_id=price_source.id, observed_at=datetime(2026, 5, 22, 15, tzinfo=timezone.utc), price="100")
        _seed_fx_set(session, source_id=fx_source.id, observed_at=datetime(2026, 5, 22, tzinfo=timezone.utc))
        _energy(session, source_id=energy_source.id, instrument_code="DCOILBRENTEU", period_start=date(2026, 5, 20), value="70")
        _energy(session, source_id=energy_source.id, instrument_code="DCOILBRENTEU", period_start=date(2026, 5, 23), value="99")

        result = build_daily_features(session=session)
        session.commit()
        feature = session.scalar(select(DailyProductFeature))

    assert result.warnings_count == 0
    assert feature.energy_brent_usd_per_barrel == Decimal("70.00000000")
    assert feature.energy_brent_as_of_date == date(2026, 5, 20)
    assert feature.energy_as_of_date == date(2026, 5, 20)
    assert "missing_energy_wti" in feature.energy_missing_flags


def test_energy_features_populate_deltas_and_weekly_diesel_forward_fill() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        product = _seed_product(session)
        price_source = _seed_source(session)
        fx_source = _seed_source(session, code="cbr_fx", source_type="fx")
        energy_source = _seed_source(session, code="fred_energy_prices", source_type="energy")
        for day in (20, 27):
            _price(session, product_id=product.id, source_id=price_source.id, observed_at=datetime(2026, 5, day, 15, tzinfo=timezone.utc), price="100")
        _seed_fx_set(session, source_id=fx_source.id, observed_at=datetime(2026, 5, 20, tzinfo=timezone.utc))
        for code, first, prior, current in (
            ("DCOILBRENTEU", "70", "76", "77"),
            ("DCOILWTICO", "60", "63", "65"),
            ("DHHNGSP", "2", "2.5", "3"),
        ):
            _energy(session, source_id=energy_source.id, instrument_code=code, period_start=date(2026, 5, 20), value=first)
            _energy(session, source_id=energy_source.id, instrument_code=code, period_start=date(2026, 5, 26), value=prior)
            _energy(session, source_id=energy_source.id, instrument_code=code, period_start=date(2026, 5, 27), value=current)
        _energy(session, source_id=energy_source.id, instrument_code="GASDESW", period_start=date(2026, 5, 20), value="3.5", frequency="weekly")
        _energy(session, source_id=energy_source.id, instrument_code="GASDESW", period_start=date(2026, 5, 25), value="3.8", frequency="weekly")

        build_daily_features(session=session)
        session.commit()
        feature = session.scalar(select(DailyProductFeature).where(DailyProductFeature.feature_date == date(2026, 5, 27)))

    assert feature.energy_brent_usd_per_barrel == Decimal("77.00000000")
    assert feature.energy_brent_delta_1d == Decimal("1.00000000")
    assert feature.energy_brent_delta_7d == Decimal("7.00000000")
    assert feature.energy_wti_delta_1d == Decimal("2.00000000")
    assert feature.energy_wti_delta_7d == Decimal("5.00000000")
    assert feature.energy_henry_hub_delta_1d == Decimal("0.50000000")
    assert feature.energy_henry_hub_delta_7d == Decimal("1.00000000")
    assert feature.energy_diesel_proxy_value == Decimal("3.80000000")
    assert feature.energy_diesel_as_of_date == date(2026, 5, 25)
    assert feature.energy_diesel_proxy_delta_7d == Decimal("0.30000000")
    assert feature.energy_missing_flags is None


def test_energy_missing_flags_when_current_values_are_unavailable() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        product = _seed_product(session)
        price_source = _seed_source(session)
        fx_source = _seed_source(session, code="cbr_fx", source_type="fx")
        energy_source = _seed_source(session, code="fred_energy_prices", source_type="energy")
        _price(session, product_id=product.id, source_id=price_source.id, observed_at=datetime(2026, 5, 20, 15, tzinfo=timezone.utc), price="100")
        _seed_fx_set(session, source_id=fx_source.id, observed_at=datetime(2026, 5, 20, tzinfo=timezone.utc))
        _energy(session, source_id=energy_source.id, instrument_code="DCOILBRENTEU", period_start=date(2026, 5, 20), value="70")

        build_daily_features(session=session)
        session.commit()
        feature = session.scalar(select(DailyProductFeature))

    assert feature.energy_brent_usd_per_barrel == Decimal("70.00000000")
    assert feature.energy_wti_usd_per_barrel is None
    assert feature.energy_henry_hub_usd_mmbtu is None
    assert feature.energy_diesel_proxy_value is None
    assert feature.energy_missing_flags == "missing_energy_wti,missing_energy_henry_hub,missing_energy_diesel"
    assert feature.features_json["energy_missing_flags"] == feature.energy_missing_flags


def test_benchmark_features_use_as_of_without_future_leakage() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        product = _seed_product(session)
        price_source = _seed_source(session)
        fx_source = _seed_source(session, code="cbr_fx", source_type="fx")
        benchmark_source = _seed_source(session, code="world_bank_pink_sheet", source_type="commodity_benchmark")
        _price(session, product_id=product.id, source_id=price_source.id, observed_at=datetime(2026, 5, 22, 15, tzinfo=timezone.utc), price="100")
        _seed_fx_set(session, source_id=fx_source.id, observed_at=datetime(2026, 5, 22, tzinfo=timezone.utc))
        _benchmark(session, source_id=benchmark_source.id, benchmark_code="world_bank_soybean_oil", period_start=date(2026, 5, 1), value="1000")
        _benchmark(session, source_id=benchmark_source.id, benchmark_code="world_bank_soybean_oil", period_start=date(2026, 6, 1), value="9999")

        result = build_daily_features(session=session)
        session.commit()
        feature = session.scalar(select(DailyProductFeature))
        check = session.scalar(
            select(DataQualityCheck)
            .where(DataQualityCheck.check_name == "daily_feature_no_future_benchmark")
            .limit(1)
        )

    assert result.warnings_count == 0
    assert feature.benchmark_soybean_oil_value == Decimal("1000.00000000")
    assert feature.benchmark_soybean_oil_as_of_date == date(2026, 5, 1)
    assert feature.benchmark_as_of_date == date(2026, 5, 1)
    assert feature.benchmark_soybean_oil_delta_1m is None
    assert "missing_benchmark_soybeans" in feature.benchmark_missing_flags
    assert feature.features_json["benchmark_soybean_oil_as_of_date"] == "2026-05-01"
    assert check.status == "pass"
    assert check.details_json["benchmark_soybean_oil_as_of_date"] == "2026-05-01"


def test_benchmark_features_forward_fill_and_monthly_deltas() -> None:
    SessionLocal = _session_factory()
    benchmark_cases = (
        ("world_bank_soybean_oil", "benchmark_soybean_oil", "80", "95", "100"),
        ("world_bank_soybeans", "benchmark_soybeans", "400", "430", "450"),
        ("world_bank_palm_oil", "benchmark_palm_oil", "700", "720", "740"),
        ("world_bank_maize", "benchmark_maize", "180", "190", "200"),
        ("world_bank_wheat", "benchmark_wheat", "220", "240", "250"),
        ("world_bank_fertilizer_index", "benchmark_fertilizer_index", "100", "110", "120"),
    )
    with SessionLocal() as session:
        product = _seed_product(session)
        price_source = _seed_source(session)
        fx_source = _seed_source(session, code="cbr_fx", source_type="fx")
        benchmark_source = _seed_source(session, code="world_bank_pink_sheet", source_type="commodity_benchmark")
        for day in (20, 27):
            _price(session, product_id=product.id, source_id=price_source.id, observed_at=datetime(2026, 5, day, 15, tzinfo=timezone.utc), price="100")
        _seed_fx_set(session, source_id=fx_source.id, observed_at=datetime(2026, 5, 20, tzinfo=timezone.utc))
        for benchmark_code, _field_prefix, feb, apr, may in benchmark_cases:
            _benchmark(session, source_id=benchmark_source.id, benchmark_code=benchmark_code, period_start=date(2026, 2, 1), value=feb)
            _benchmark(session, source_id=benchmark_source.id, benchmark_code=benchmark_code, period_start=date(2026, 4, 1), value=apr)
            _benchmark(session, source_id=benchmark_source.id, benchmark_code=benchmark_code, period_start=date(2026, 5, 1), value=may)

        build_daily_features(session=session)
        session.commit()
        feature = session.scalar(select(DailyProductFeature).where(DailyProductFeature.feature_date == date(2026, 5, 27)))

    assert feature.benchmark_missing_flags is None
    assert feature.benchmark_as_of_date == date(2026, 5, 1)
    assert feature.benchmark_soybean_oil_value == Decimal("100.00000000")
    assert feature.benchmark_soybean_oil_delta_1m == Decimal("5.00000000")
    assert feature.benchmark_soybean_oil_delta_3m == Decimal("20.00000000")
    assert feature.benchmark_soybeans_delta_1m == Decimal("20.00000000")
    assert feature.benchmark_soybeans_delta_3m == Decimal("50.00000000")
    assert feature.benchmark_palm_oil_delta_1m == Decimal("20.00000000")
    assert feature.benchmark_maize_delta_3m == Decimal("20.00000000")
    assert feature.benchmark_wheat_delta_1m == Decimal("10.00000000")
    assert feature.benchmark_fertilizer_index_delta_3m == Decimal("20.00000000")
    assert feature.features_json["benchmark_missing_flags"] is None


def test_benchmark_missing_flags_when_current_values_are_unavailable() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        product = _seed_product(session)
        price_source = _seed_source(session)
        fx_source = _seed_source(session, code="cbr_fx", source_type="fx")
        benchmark_source = _seed_source(session, code="world_bank_pink_sheet", source_type="commodity_benchmark")
        _price(session, product_id=product.id, source_id=price_source.id, observed_at=datetime(2026, 5, 20, 15, tzinfo=timezone.utc), price="100")
        _seed_fx_set(session, source_id=fx_source.id, observed_at=datetime(2026, 5, 20, tzinfo=timezone.utc))
        _benchmark(session, source_id=benchmark_source.id, benchmark_code="world_bank_soybean_oil", period_start=date(2026, 5, 1), value="1000")

        build_daily_features(session=session)
        session.commit()
        feature = session.scalar(select(DailyProductFeature))

    assert feature.benchmark_soybean_oil_value == Decimal("1000.00000000")
    assert feature.benchmark_soybeans_value is None
    assert feature.benchmark_palm_oil_value is None
    assert feature.benchmark_missing_flags == (
        "missing_benchmark_soybeans,"
        "missing_benchmark_palm_oil,"
        "missing_benchmark_maize,"
        "missing_benchmark_wheat,"
        "missing_benchmark_fertilizer_index"
    )
    assert feature.features_json["benchmark_missing_flags"] == feature.benchmark_missing_flags


def test_repeated_build_upserts_without_duplicates_and_updates() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        product = _seed_product(session)
        price_source = _seed_source(session)
        fx_source = _seed_source(session, code="cbr_fx", source_type="fx")
        _price(session, product_id=product.id, source_id=price_source.id, observed_at=datetime(2026, 5, 20, 6, tzinfo=timezone.utc), price="100")
        _seed_fx_set(session, source_id=fx_source.id, observed_at=datetime(2026, 5, 20, tzinfo=timezone.utc))

        first = build_daily_features(session=session)
        second = build_daily_features(session=session)
        feature = session.scalar(select(DailyProductFeature))
        feature.price_last = Decimal("1")
        third = build_daily_features(session=session)
        session.commit()
        count = session.scalar(select(func.count()).select_from(DailyProductFeature))
        feature = session.scalar(select(DailyProductFeature))

    assert first.rows_created == 1
    assert second.rows_skipped == 1
    assert third.rows_updated == 1
    assert count == 1
    assert feature.price_last == Decimal("100.000000")


def test_existing_rows_update_calendar_fields() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        product = _seed_product(session)
        price_source = _seed_source(session)
        fx_source = _seed_source(session, code="cbr_fx", source_type="fx")
        _price(session, product_id=product.id, source_id=price_source.id, observed_at=datetime(2026, 6, 1, 15, tzinfo=timezone.utc), price="100")
        _seed_fx_set(session, source_id=fx_source.id, observed_at=datetime(2026, 6, 1, tzinfo=timezone.utc))

        first = build_daily_features(session=session)
        feature = session.scalar(select(DailyProductFeature))
        feature.calendar_year = None
        feature.calendar_season = None
        second = build_daily_features(session=session)
        session.commit()
        feature = session.scalar(select(DailyProductFeature))

    assert first.rows_created == 1
    assert second.rows_updated == 1
    assert feature.calendar_year == 2026
    assert feature.calendar_month == 6
    assert feature.calendar_season == "summer"
    assert feature.features_json["calendar_year"] == 2026


def test_quality_checks_are_created() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        product = _seed_product(session)
        price_source = _seed_source(session)
        fx_source = _seed_source(session, code="cbr_fx", source_type="fx")
        _price(session, product_id=product.id, source_id=price_source.id, observed_at=datetime(2026, 5, 20, 6, tzinfo=timezone.utc), price="100")
        _seed_fx_set(session, source_id=fx_source.id, observed_at=datetime(2026, 5, 20, tzinfo=timezone.utc))

        build_daily_features(session=session)
        session.commit()
        check_names = set(session.scalars(select(DataQualityCheck.check_name)).all())

    assert "daily_feature_price_present" in check_names
    assert "daily_feature_no_future_fx" in check_names
    assert "daily_feature_no_future_benchmark" in check_names
    assert "daily_feature_no_future_weather" in check_names
    assert "daily_feature_weather_coverage_recorded" in check_names
    assert "daily_feature_unique_product_date" in check_names


def test_build_features_cli_with_and_without_dates(tmp_path: Path) -> None:
    db_path = tmp_path / "features.db"
    database_url = f"sqlite+pysqlite:///{db_path}"
    SessionLocal = _session_factory(database_url)
    with SessionLocal() as session:
        product = _seed_product(session)
        price_source = _seed_source(session)
        fx_source = _seed_source(session, code="cbr_fx", source_type="fx")
        _price(session, product_id=product.id, source_id=price_source.id, observed_at=datetime(2026, 5, 20, 6, tzinfo=timezone.utc), price="100")
        _seed_fx_set(session, source_id=fx_source.id, observed_at=datetime(2026, 5, 20, tzinfo=timezone.utc))
        session.commit()

    env = {**os.environ, "DATABASE_URL": database_url, "LOG_DIR": str(tmp_path / "logs")}
    get_settings.cache_clear()
    first = subprocess.run(
        [sys.executable, "scripts/build_features.py", "daily", "--from-date", "2026-05-20", "--to-date", "2026-05-20"],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    second = subprocess.run(
        [sys.executable, "scripts/build_features.py", "daily"],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    get_settings.cache_clear()

    assert "rows_created=1" in first.stdout
    assert "rows_skipped=1" in second.stdout
