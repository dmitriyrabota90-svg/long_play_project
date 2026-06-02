from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from importlib import import_module

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db.models import (
    Base,
    CollectorRun,
    HistoricalPriceBar,
    HistoricalPriceBarRevision,
    Product,
    RawResponse,
    Source,
)


historical_bars_migration = import_module("migrations.versions.0005_historical_price_bars")
historical_revisions_migration = import_module("migrations.versions.0006_historical_bar_revisions")


def test_metadata_contains_historical_price_bars() -> None:
    table = Base.metadata.tables["historical_price_bars"]
    expected_columns = {
        "id",
        "product_id",
        "source_id",
        "raw_response_id",
        "collector_run_id",
        "external_code",
        "endpoint_alias",
        "bar_date",
        "bar_timeframe",
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "price",
        "volume",
        "currency",
        "unit",
        "observed_at",
        "published_at",
        "fetched_at",
        "source_record_hash",
        "source_payload_hash",
        "created_at",
        "updated_at",
    }

    assert expected_columns <= set(table.c.keys())
    assert table.c.raw_response_id.nullable is False
    assert table.c.collector_run_id.nullable is False
    assert table.c.source_payload_hash.nullable is False


def test_historical_price_bars_constraints_and_indexes_exist() -> None:
    table = Base.metadata.tables["historical_price_bars"]
    unique_names = {constraint.name for constraint in table.constraints}
    index_names = {index.name for index in table.indexes}

    assert "uq_hist_bars_product_source_endpoint_timeframe_date" in unique_names
    assert {
        "ix_hist_bars_product_bar_date",
        "ix_hist_bars_source_fetched_at",
        "ix_hist_bars_product_source_timeframe_date",
        "ix_hist_bars_raw_response_id",
        "ix_hist_bars_collector_run_id",
        "ix_hist_bars_source_record_hash",
    } <= index_names


def test_migration_revision_metadata() -> None:
    assert historical_bars_migration.revision == "0005_historical_price_bars"
    assert historical_bars_migration.down_revision == "0004_daily_features"
    assert historical_revisions_migration.revision == "0006_historical_bar_revisions"
    assert historical_revisions_migration.down_revision == "0005_historical_price_bars"


def test_metadata_contains_historical_price_bar_revisions() -> None:
    table = Base.metadata.tables["historical_price_bar_revisions"]
    expected_columns = {
        "id",
        "historical_price_bar_id",
        "product_id",
        "source_id",
        "raw_response_id",
        "collector_run_id",
        "revision_reason",
        "revision_number",
        "previous_open",
        "previous_high",
        "previous_low",
        "previous_close",
        "previous_price",
        "previous_volume",
        "previous_currency",
        "previous_unit",
        "previous_observed_at",
        "previous_published_at",
        "previous_fetched_at",
        "previous_source_record_hash",
        "previous_source_payload_hash",
        "new_raw_response_id",
        "new_collector_run_id",
        "new_open",
        "new_high",
        "new_low",
        "new_close",
        "new_price",
        "new_volume",
        "new_observed_at",
        "new_fetched_at",
        "new_source_record_hash",
        "new_source_payload_hash",
        "changed_fields",
        "diff_json",
        "created_at",
    }
    index_names = {index.name for index in table.indexes}

    assert expected_columns <= set(table.c.keys())
    assert table.c.historical_price_bar_id.nullable is False
    assert table.c.changed_fields.nullable is False
    assert table.c.diff_json.nullable is False
    assert {
        "ix_hist_bar_revisions_bar_id",
        "ix_hist_bar_revisions_product_created",
        "ix_hist_bar_revisions_source_created",
        "ix_hist_bar_revisions_created_at",
        "ix_hist_bar_revisions_reason",
    } <= index_names


def test_create_all_creates_historical_price_bars_table() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    inspector = inspect(engine)

    assert "historical_price_bars" in inspector.get_table_names()
    assert "historical_price_bar_revisions" in inspector.get_table_names()
    columns = {column["name"] for column in inspector.get_columns("historical_price_bars")}
    assert "bar_date" in columns
    assert "close_price" in columns


def test_historical_price_bar_insert_and_unique_constraint() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)

    with SessionLocal() as session:
        product = Product(
            code="soybean_meal",
            name="Соевый шрот",
            category="meal",
            unit="metric_ton",
            currency_default="CNY",
        )
        source = Source(
            code="jijinhao_historical_prices",
            name="Jijinhao Historical Prices",
            source_type="price_history",
            base_url="https://api.jijinhao.com/",
        )
        session.add_all([product, source])
        session.flush()
        run = CollectorRun(
            source_id=source.id,
            collector_name="jijinhao_historical_prices_collector",
            started_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
            status="success",
            run_type="manual",
        )
        session.add(run)
        session.flush()
        raw = RawResponse(
            source_id=source.id,
            collector_run_id=run.id,
            fetched_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
            url="https://api.jijinhao.com/quoteCenter/historys.htm",
            method="GET",
            status_code=200,
            content_type="text/html;charset=UTF-8",
            storage_path="data/raw/jijinhao_historical_prices/2026/05/28/1/hash.txt",
            sha256="a" * 64,
            bytes_size=3200,
            parser_version="jijinhao_historys_v1",
        )
        session.add(raw)
        session.flush()

        row = _bar(product.id, source.id, raw.id, run.id)
        session.add(row)
        session.commit()

        loaded = session.scalar(select(HistoricalPriceBar).where(HistoricalPriceBar.product_id == product.id))
        assert loaded is not None
        assert loaded.close_price == Decimal("2990.00000000")

        revision = HistoricalPriceBarRevision(
            historical_price_bar_id=loaded.id,
            product_id=product.id,
            source_id=source.id,
            raw_response_id=raw.id,
            collector_run_id=run.id,
            revision_reason="mutable_latest_bar_update",
            revision_number=1,
            previous_open=loaded.open_price,
            previous_high=loaded.high_price,
            previous_low=loaded.low_price,
            previous_close=loaded.close_price,
            previous_price=loaded.price,
            previous_volume=loaded.volume,
            previous_currency=loaded.currency,
            previous_unit=loaded.unit,
            previous_observed_at=loaded.observed_at,
            previous_published_at=loaded.published_at,
            previous_fetched_at=loaded.fetched_at,
            previous_source_record_hash=loaded.source_record_hash,
            previous_source_payload_hash=loaded.source_payload_hash,
            new_raw_response_id=raw.id,
            new_collector_run_id=run.id,
            new_open=Decimal("2998"),
            new_high=Decimal("3000"),
            new_low=Decimal("2984"),
            new_close=Decimal("2995"),
            new_price=Decimal("2995"),
            new_volume=Decimal("659200"),
            new_observed_at=loaded.observed_at,
            new_fetched_at=loaded.fetched_at,
            new_source_record_hash="c" * 64,
            new_source_payload_hash="d" * 64,
            changed_fields=["close_price", "price", "volume"],
            diff_json={"price": {"old": "2990", "new": "2995", "diff_abs": "5"}},
        )
        session.add(revision)
        session.flush()

        assert revision.revision_number == 1

        session.add(_bar(product.id, source.id, raw.id, run.id, record_hash="b" * 64))
        with pytest.raises(IntegrityError):
            session.commit()


def _bar(
    product_id: int,
    source_id: int,
    raw_response_id: int,
    collector_run_id: int,
    *,
    record_hash: str = "1" * 64,
) -> HistoricalPriceBar:
    return HistoricalPriceBar(
        product_id=product_id,
        source_id=source_id,
        raw_response_id=raw_response_id,
        collector_run_id=collector_run_id,
        external_code="JO_165938",
        endpoint_alias="historys",
        bar_date=date(2026, 5, 25),
        bar_timeframe="daily",
        open_price=Decimal("2998"),
        high_price=Decimal("2999"),
        low_price=Decimal("2984"),
        close_price=Decimal("2990"),
        price=Decimal("2990"),
        volume=Decimal("659103"),
        currency="CNY",
        unit="metric_ton",
        observed_at=datetime(2026, 5, 25, tzinfo=timezone.utc),
        published_at=None,
        fetched_at=datetime(2026, 5, 28, tzinfo=timezone.utc),
        source_record_hash=record_hash,
        source_payload_hash="a" * 64,
    )
