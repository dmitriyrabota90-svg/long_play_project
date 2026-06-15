from __future__ import annotations

import calendar
import os
import subprocess
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from importlib import import_module
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.config.settings import get_settings
from app.db.models import (
    Base,
    CollectorRun,
    DailyProductFeature,
    DailyTradeFeature,
    Product,
    ProductTradeCodeWeight,
    RawResponse,
    Source,
    TradeCommodityCode,
    TradeFlow,
)
from app.features.trade_daily import build_trade_daily_features


product_trade_migration = import_module("migrations.versions.0017_trade_features")


def _session_factory(database_url: str = "sqlite+pysqlite:///:memory:"):
    engine = create_engine(database_url, future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def _seed_base(session):
    product = Product(
        code="soybean_oil",
        name="Soybean oil",
        category="oil",
        unit="metric_ton",
        currency_default="USD",
    )
    source = Source(
        code="un_comtrade",
        name="UN Comtrade",
        source_type="trade",
        base_url="https://comtradeplus.un.org/",
    )
    session.add_all([product, source])
    session.flush()
    run = CollectorRun(
        source_id=source.id,
        collector_name="un_comtrade_collector",
        started_at=datetime(2026, 6, 11, tzinfo=timezone.utc),
        status="success",
        run_type="manual",
    )
    session.add(run)
    session.flush()
    raw = RawResponse(
        source_id=source.id,
        collector_run_id=run.id,
        fetched_at=datetime(2026, 6, 11, tzinfo=timezone.utc),
        url="https://comtradeplus.un.org/test",
        method="GET",
        status_code=200,
        content_type="application/json",
        storage_path="data/raw/un_comtrade/2026/06/11/1/hash.json",
        sha256="a" * 64,
        bytes_size=2000,
        parser_version="un_comtrade_v1",
    )
    trade_code = TradeCommodityCode(
        source_id=source.id,
        code_system="HS",
        commodity_code="1507",
        commodity_name="Soybean oil",
        hs_code="1507",
        hs_revision="generic",
        commodity_family="soybean",
        product_code=product.code,
        relevance="direct",
        unit_hint="metric_ton",
        is_active=True,
        metadata_json={"test": True},
    )
    session.add_all([raw, trade_code])
    session.flush()
    session.add(
        ProductTradeCodeWeight(
            product_id=product.id,
            trade_commodity_code_id=trade_code.id,
            weight=Decimal("1.00000000"),
            relevance="direct",
            role="direct_trade_proxy",
            effective_from=date(2020, 1, 1),
            effective_to=None,
            is_active=True,
            metadata_json={"test": True},
        )
    )
    session.flush()
    return product, source, run, raw, trade_code


def _period_end(period_start: date) -> date:
    return date(period_start.year, period_start.month, calendar.monthrange(period_start.year, period_start.month)[1])


def _add_trade_flow(
    session,
    *,
    source_id: int,
    raw_response_id: int,
    collector_run_id: int,
    trade_commodity_code_id: int,
    period_start: date,
    flow_direction: str,
    reporter_code: str,
    partner_code: str,
    quantity: str,
    trade_value_usd: str,
    published_at: datetime,
) -> None:
    period_end = _period_end(period_start)
    session.add(
        TradeFlow(
            source_id=source_id,
            raw_response_id=raw_response_id,
            collector_run_id=collector_run_id,
            trade_commodity_code_id=trade_commodity_code_id,
            source_record_id=f"{reporter_code}-{partner_code}-{flow_direction}-{period_start.isoformat()}",
            reporter_code=reporter_code,
            reporter_name=reporter_code,
            partner_code=partner_code,
            partner_name=partner_code,
            flow_direction=flow_direction,
            trade_period=period_start.strftime("%Y-%m"),
            period_start=period_start,
            period_end=period_end,
            frequency="monthly",
            quantity=Decimal(quantity),
            quantity_unit="metric_ton",
            trade_value_usd=Decimal(trade_value_usd),
            trade_value_local=None,
            currency=None,
            unit_value_usd=None,
            net_weight_kg=None,
            gross_weight_kg=None,
            published_at=published_at,
            fetched_at=published_at,
            source_record_hash=(f"{reporter_code}{partner_code}{flow_direction}{period_start:%Y%m}" + "a" * 64)[:64],
            source_payload_hash="b" * 64,
            metadata_json={"test": True},
        )
    )


def _month_sequence() -> list[date]:
    return [
        date(2025, 5, 1),
        date(2025, 6, 1),
        date(2025, 7, 1),
        date(2025, 8, 1),
        date(2025, 9, 1),
        date(2025, 10, 1),
        date(2025, 11, 1),
        date(2025, 12, 1),
        date(2026, 1, 1),
        date(2026, 2, 1),
        date(2026, 3, 1),
        date(2026, 4, 1),
        date(2026, 5, 1),
    ]


def test_product_trade_feature_columns_and_migration_metadata() -> None:
    table = Base.metadata.tables["daily_product_features"]
    expected_columns = {
        "export_volume_1m",
        "export_volume_3m_avg",
        "export_volume_12m_sum",
        "import_volume_1m",
        "import_volume_3m_avg",
        "import_volume_12m_sum",
        "net_export_volume_1m",
        "export_value_usd_1m",
        "import_value_usd_1m",
        "average_export_unit_value_usd",
        "average_import_unit_value_usd",
        "china_import_volume_1m",
        "major_exporter_volume_1m",
        "major_importer_volume_1m",
        "trade_balance_proxy",
        "trade_yoy_change",
        "trade_as_of_date",
        "reporting_lag_days",
        "trade_missing_flags",
    }
    migration_text = Path(product_trade_migration.__file__).read_text(encoding="utf-8")

    assert expected_columns <= set(table.c.keys())
    assert product_trade_migration.revision == "0017_trade_features"
    assert product_trade_migration.down_revision == "0016_trade_schema"
    assert "op.add_column(\"daily_product_features\"" in migration_text
    assert "trade_missing_flags" in migration_text


def test_trade_daily_builder_creates_monthly_as_of_features_and_is_idempotent() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        product, source, run, raw, trade_code = _seed_base(session)
        for index, period_start in enumerate(_month_sequence(), start=1):
            _add_trade_flow(
                session,
                source_id=source.id,
                raw_response_id=raw.id,
                collector_run_id=run.id,
                trade_commodity_code_id=trade_code.id,
                period_start=period_start,
                flow_direction="export",
                reporter_code="BRA",
                partner_code="CHN",
                quantity=str(100 * index),
                trade_value_usd=str(1000 * index),
                published_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
            )
            _add_trade_flow(
                session,
                source_id=source.id,
                raw_response_id=raw.id,
                collector_run_id=run.id,
                trade_commodity_code_id=trade_code.id,
                period_start=period_start,
                flow_direction="import",
                reporter_code="CHN",
                partner_code="BRA",
                quantity=str(10 * index),
                trade_value_usd=str(100 * index),
                published_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
            )

        first = build_trade_daily_features(
            product_code=product.code,
            from_date=date(2026, 6, 15),
            to_date=date(2026, 6, 15),
            session=session,
        )
        second = build_trade_daily_features(
            product_code=product.code,
            from_date=date(2026, 6, 15),
            to_date=date(2026, 6, 15),
            session=session,
        )
        feature = session.scalar(select(DailyTradeFeature).where(DailyTradeFeature.product_id == product.id))
        rows_count = session.scalar(select(func.count()).select_from(DailyTradeFeature))

    assert first.rows_created == 1
    assert second.rows_skipped == 1
    assert rows_count == 1
    assert feature.export_volume_1m == Decimal("1300.00000000")
    assert feature.import_volume_1m == Decimal("130.00000000")
    assert feature.export_volume_3m_avg == Decimal("1200.00000000")
    assert feature.import_volume_3m_avg == Decimal("120.00000000")
    assert feature.export_volume_12m_sum == Decimal("9000.00000000")
    assert feature.import_volume_12m_sum == Decimal("900.00000000")
    assert feature.net_export_volume_1m == Decimal("1170.00000000")
    assert feature.trade_balance_proxy == Decimal("1170.00000000")
    assert feature.average_export_unit_value_usd == Decimal("10.00000000")
    assert feature.average_import_unit_value_usd == Decimal("10.00000000")
    assert feature.china_import_volume_1m == Decimal("130.00000000")
    assert feature.major_exporter_volume_1m == Decimal("1300.00000000")
    assert feature.major_importer_volume_1m == Decimal("130.00000000")
    assert feature.trade_yoy_change == Decimal("12.00000000")
    assert feature.trade_as_of_date == date(2026, 6, 10)
    assert feature.reporting_lag_days == 5
    assert feature.missing_flags == {}


def test_trade_daily_builder_does_not_use_future_published_rows() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        product, source, run, raw, trade_code = _seed_base(session)
        _add_trade_flow(
            session,
            source_id=source.id,
            raw_response_id=raw.id,
            collector_run_id=run.id,
            trade_commodity_code_id=trade_code.id,
            period_start=date(2026, 4, 1),
            flow_direction="export",
            reporter_code="BRA",
            partner_code="CHN",
            quantity="100",
            trade_value_usd="1000",
            published_at=datetime(2026, 5, 10, tzinfo=timezone.utc),
        )
        _add_trade_flow(
            session,
            source_id=source.id,
            raw_response_id=raw.id,
            collector_run_id=run.id,
            trade_commodity_code_id=trade_code.id,
            period_start=date(2026, 5, 1),
            flow_direction="export",
            reporter_code="BRA",
            partner_code="CHN",
            quantity="999",
            trade_value_usd="9990",
            published_at=datetime(2026, 6, 20, tzinfo=timezone.utc),
        )

        build_trade_daily_features(
            product_code=product.code,
            from_date=date(2026, 6, 15),
            to_date=date(2026, 6, 15),
            session=session,
        )
        feature = session.scalar(select(DailyTradeFeature).where(DailyTradeFeature.product_id == product.id))

    assert feature.export_volume_1m == Decimal("100.00000000")
    assert feature.trade_as_of_date == date(2026, 5, 10)
    assert feature.reporting_lag_days == 36


def test_trade_daily_builder_records_missing_flags_without_flows_or_weights() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        product = Product(
            code="rapeseed_oil",
            name="Rapeseed oil",
            category="oil",
            unit="metric_ton",
            currency_default="USD",
        )
        session.add(product)
        session.flush()

        result = build_trade_daily_features(
            product_code=product.code,
            from_date=date(2026, 6, 15),
            to_date=date(2026, 6, 15),
            session=session,
        )
        feature = session.scalar(select(DailyTradeFeature).where(DailyTradeFeature.product_id == product.id))

    assert result.rows_created == 1
    assert result.warnings_count == 1
    assert result.missing_trade_products == ["rapeseed_oil"]
    assert feature.trade_as_of_date is None
    assert feature.missing_flags == {"no_product_trade_code_weights": True}


def test_build_features_cli_trade_daily(tmp_path: Path) -> None:
    db_path = tmp_path / "features.db"
    database_url = f"sqlite+pysqlite:///{db_path}"
    SessionLocal = _session_factory(database_url)
    with SessionLocal() as session:
        _seed_base(session)
        session.commit()

    env = {**os.environ, "DATABASE_URL": database_url, "LOG_DIR": str(tmp_path / "logs")}
    get_settings.cache_clear()
    result = subprocess.run(
        [
            sys.executable,
            "scripts/build_features.py",
            "trade_daily",
            "--product",
            "soybean_oil",
            "--from-date",
            "2026-06-15",
            "--to-date",
            "2026-06-15",
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    get_settings.cache_clear()

    assert "products_processed=1" in result.stdout
    assert "rows_created=1" in result.stdout
    assert "warnings_count=1" in result.stdout
