from __future__ import annotations

import os
import subprocess
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.config.settings import get_settings
from app.db.models import Base, DailyProductFeature, DataQualityCheck, FxRate, PriceObservation, Product, Source
from app.features.daily import build_daily_features


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
