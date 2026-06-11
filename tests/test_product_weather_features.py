from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.db.models import (
    Base,
    DailyProductFeature,
    DataQualityCheck,
    FxRate,
    PriceObservation,
    Product,
    ProductWeatherRegionWeight,
    Source,
    WeatherDailyFeature,
    WeatherRegion,
)
from app.db.seed import seed_database
from app.features.daily import build_daily_features
from app.monitoring.operational_report import build_operational_report


def test_product_weather_features_weighted_average_and_effective_weights() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        product = _seed_price_fx_and_weights(session, product_code="soybean_oil")
        _activate_only_weights(
            session,
            product=product,
            weights={
                "br_mato_grosso_soybean": Decimal("1"),
                "br_parana_soybean": Decimal("3"),
                "br_goias_soybean": Decimal("100"),
            },
            future_region_codes={"br_goias_soybean"},
        )
        _weather_feature(
            session,
            region_code="br_mato_grosso_soybean",
            temperature_30d_mean="20",
            precipitation_30d_sum="10",
            growing_degree_days_30d="100",
        )
        _weather_feature(
            session,
            region_code="br_parana_soybean",
            temperature_30d_mean="30",
            precipitation_30d_sum="30",
            growing_degree_days_30d="200",
        )
        _weather_feature(
            session,
            region_code="br_goias_soybean",
            temperature_30d_mean="99",
            precipitation_30d_sum="99",
            growing_degree_days_30d="99",
        )

        build_daily_features(session=session)
        session.commit()
        feature = _daily_feature(session, product_code="soybean_oil")

    assert feature.weather_temperature_30d_mean_weighted == Decimal("27.50000000")
    assert feature.weather_precipitation_30d_sum_weighted == Decimal("25.00000000")
    assert feature.weather_growing_degree_days_30d_weighted == Decimal("175.00000000")
    assert feature.weather_as_of_date == date(2026, 5, 10)
    assert feature.weather_regions_used == "br_mato_grosso_soybean,br_parana_soybean"
    assert feature.weather_missing_flags is None
    assert feature.features_json["weather_temperature_30d_mean_weighted"] == "27.50000000"
    assert feature.features_json["weather_regions_used"] == feature.weather_regions_used


def test_product_weather_features_partial_missing_regions_use_available_data() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        product = _seed_price_fx_and_weights(session, product_code="soybean_meal")
        _activate_only_weights(
            session,
            product=product,
            weights={
                "br_mato_grosso_soybean": Decimal("1"),
                "br_parana_soybean": Decimal("1"),
            },
        )
        _weather_feature(
            session,
            region_code="br_mato_grosso_soybean",
            temperature_30d_mean="20",
            precipitation_30d_sum="10",
            growing_degree_days_30d="100",
            missing_flags={"incomplete_30d_window": True},
        )

        build_daily_features(session=session)
        session.commit()
        feature = _daily_feature(session, product_code="soybean_meal")

    assert feature.weather_temperature_30d_mean_weighted == Decimal("20.00000000")
    assert feature.weather_precipitation_30d_sum_weighted == Decimal("10.00000000")
    assert feature.weather_growing_degree_days_30d_weighted == Decimal("100.00000000")
    assert feature.weather_regions_used == "br_mato_grosso_soybean"
    assert "partial_weather_regions" in feature.weather_missing_flags
    assert "missing_region:br_parana_soybean" in feature.weather_missing_flags
    assert "br_mato_grosso_soybean:incomplete_30d_window" in feature.weather_missing_flags


def test_product_weather_features_missing_all_regions_remain_null() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        product = _seed_price_fx_and_weights(session, product_code="rapeseed_oil")
        _activate_only_weights(
            session,
            product=product,
            weights={
                "ca_saskatchewan_canola": Decimal("1"),
                "ca_alberta_canola": Decimal("1"),
            },
        )

        build_daily_features(session=session)
        session.commit()
        feature = _daily_feature(session, product_code="rapeseed_oil")

    assert feature.weather_temperature_30d_mean_weighted is None
    assert feature.weather_precipitation_30d_sum_weighted is None
    assert feature.weather_growing_degree_days_30d_weighted is None
    assert feature.weather_as_of_date is None
    assert feature.weather_regions_used is None
    assert "missing_all_weather_regions" in feature.weather_missing_flags


def test_product_weather_features_do_not_use_future_weather() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        product = _seed_price_fx_and_weights(session, product_code="rapeseed_meal")
        _activate_only_weights(session, product=product, weights={"ca_saskatchewan_canola": Decimal("1")})
        _weather_feature(
            session,
            region_code="ca_saskatchewan_canola",
            feature_date=date(2026, 5, 9),
            weather_as_of_date=date(2026, 5, 9),
            temperature_30d_mean="20",
            precipitation_30d_sum="10",
            growing_degree_days_30d="100",
        )
        _weather_feature(
            session,
            region_code="ca_saskatchewan_canola",
            feature_date=date(2026, 5, 11),
            weather_as_of_date=date(2026, 5, 11),
            temperature_30d_mean="99",
            precipitation_30d_sum="99",
            growing_degree_days_30d="99",
        )

        build_daily_features(session=session)
        session.commit()
        feature = _daily_feature(session, product_code="rapeseed_meal")
        weather_checks = session.scalars(
            select(DataQualityCheck).where(DataQualityCheck.check_name == "daily_feature_no_future_weather")
        ).all()

    assert feature.feature_date == date(2026, 5, 10)
    assert feature.weather_temperature_30d_mean_weighted == Decimal("20.00000000")
    assert feature.weather_as_of_date == date(2026, 5, 9)
    assert all(check.status == "pass" for check in weather_checks)


def test_product_weather_features_operational_report_coverage() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        product = _seed_price_fx_and_weights(session, product_code="soybean_oil")
        _activate_only_weights(session, product=product, weights={"br_mato_grosso_soybean": Decimal("1")})
        _weather_feature(
            session,
            region_code="br_mato_grosso_soybean",
            temperature_30d_mean="20",
            precipitation_30d_sum="10",
            growing_degree_days_30d="100",
        )

        build_daily_features(session=session)
        session.commit()
        report = build_operational_report(session=session)

    weather_coverage = report["daily_product_features"]["weather_coverage"]
    assert weather_coverage["rows_with_weather_temperature_30d"] == 1
    assert weather_coverage["rows_with_weather_precipitation_30d"] == 1
    assert weather_coverage["rows_with_weather_gdd_30d"] == 1
    assert weather_coverage["latest_product_weather_feature_date"] == "2026-05-10"


def test_product_weather_feature_unique_rows_after_rerun() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        product = _seed_price_fx_and_weights(session, product_code="soybean_oil")
        _activate_only_weights(session, product=product, weights={"br_mato_grosso_soybean": Decimal("1")})
        _weather_feature(
            session,
            region_code="br_mato_grosso_soybean",
            temperature_30d_mean="20",
            precipitation_30d_sum="10",
            growing_degree_days_30d="100",
        )

        first = build_daily_features(session=session)
        second = build_daily_features(session=session)
        session.commit()
        duplicate_count = session.scalar(
            select(func.count()).select_from(
                select(DailyProductFeature.product_id, DailyProductFeature.feature_date)
                .group_by(DailyProductFeature.product_id, DailyProductFeature.feature_date)
                .having(func.count() > 1)
                .subquery()
            )
        )

    assert first.rows_created == 1
    assert second.rows_skipped == 1
    assert duplicate_count == 0


def _session_factory(database_url: str = "sqlite+pysqlite:///:memory:"):
    engine = create_engine(database_url, future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def _seed_price_fx_and_weights(session, *, product_code: str) -> Product:
    seed_database(session)
    product = session.scalar(select(Product).where(Product.code == product_code))
    price_source = session.scalar(select(Source).where(Source.code == "current_price_source"))
    fx_source = session.scalar(select(Source).where(Source.code == "cbr_fx"))
    assert product is not None
    assert price_source is not None
    assert fx_source is not None
    session.add(
        PriceObservation(
            product_id=product.id,
            source_id=price_source.id,
            raw_response_id=1,
            observed_at=datetime(2026, 5, 10, 12, tzinfo=timezone.utc),
            published_at=None,
            price=Decimal("100"),
            currency="CNY",
            unit="metric_ton",
            source_record_hash=f"{product_code}-2026-05-10",
        )
    )
    for currency, rate in {"CNY": "10", "USD": "70", "EUR": "80"}.items():
        session.add(
            FxRate(
                source_id=fx_source.id,
                raw_response_id=1,
                base_currency=currency,
                quote_currency="RUB",
                rate=Decimal(rate),
                observed_at=datetime(2026, 5, 10, tzinfo=timezone.utc),
                published_at=None,
            )
        )
    session.flush()
    return product


def _activate_only_weights(
    session,
    *,
    product: Product,
    weights: dict[str, Decimal],
    future_region_codes: set[str] | None = None,
) -> None:
    future_region_codes = future_region_codes or set()
    rows = session.scalars(
        select(ProductWeatherRegionWeight).where(ProductWeatherRegionWeight.product_id == product.id)
    ).all()
    region_codes_by_id = {
        region.id: region.region_code
        for region in session.scalars(select(WeatherRegion)).all()
    }
    for row in rows:
        region_code = region_codes_by_id[row.region_id]
        if region_code not in weights:
            row.is_active = False
            continue
        row.is_active = True
        row.weight = weights[region_code]
        row.effective_from = date(2026, 5, 11) if region_code in future_region_codes else date(2020, 1, 1)
        row.effective_to = None
    session.flush()


def _weather_feature(
    session,
    *,
    region_code: str,
    feature_date: date = date(2026, 5, 10),
    weather_as_of_date: date = date(2026, 5, 10),
    temperature_30d_mean: str,
    precipitation_30d_sum: str,
    growing_degree_days_30d: str,
    missing_flags: dict[str, bool] | None = None,
) -> None:
    region = session.scalar(select(WeatherRegion).where(WeatherRegion.region_code == region_code))
    assert region is not None
    session.add(
        WeatherDailyFeature(
            region_id=region.id,
            feature_date=feature_date,
            temperature_7d_mean=Decimal(temperature_30d_mean),
            temperature_30d_mean=Decimal(temperature_30d_mean),
            temperature_min_7d=Decimal("1"),
            temperature_max_7d=Decimal("30"),
            precipitation_7d_sum=Decimal(precipitation_30d_sum),
            precipitation_14d_sum=Decimal(precipitation_30d_sum),
            precipitation_30d_sum=Decimal(precipitation_30d_sum),
            heat_stress_days_7d=1,
            heat_stress_days_30d=2,
            frost_days_7d=0,
            frost_days_30d=0,
            drought_proxy_30d=Decimal(precipitation_30d_sum),
            growing_degree_days_7d=Decimal(growing_degree_days_30d),
            growing_degree_days_30d=Decimal(growing_degree_days_30d),
            weather_as_of_date=weather_as_of_date,
            missing_flags=missing_flags,
            metadata_json={"fixture": True},
        )
    )
    session.flush()


def _daily_feature(session, *, product_code: str) -> DailyProductFeature:
    product = session.scalar(select(Product).where(Product.code == product_code))
    assert product is not None
    feature = session.scalar(
        select(DailyProductFeature)
        .where(DailyProductFeature.product_id == product.id, DailyProductFeature.feature_date == date(2026, 5, 10))
        .limit(1)
    )
    assert feature is not None
    return feature
