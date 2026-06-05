from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from importlib import import_module

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, CollectorRun, EnergyPrice, RawResponse, Source


energy_prices_migration = import_module("migrations.versions.0008_energy_prices")


def test_metadata_contains_energy_prices() -> None:
    table = Base.metadata.tables["energy_prices"]
    expected_columns = {
        "id",
        "source_id",
        "raw_response_id",
        "collector_run_id",
        "instrument_code",
        "external_id",
        "instrument_name",
        "instrument_category",
        "frequency",
        "period_start",
        "period_end",
        "observed_at",
        "published_at",
        "fetched_at",
        "value",
        "currency",
        "unit",
        "normalized_value",
        "normalized_currency",
        "normalized_unit",
        "source_record_hash",
        "source_payload_hash",
        "metadata_json",
        "created_at",
        "updated_at",
    }

    assert expected_columns <= set(table.c.keys())
    assert table.c.raw_response_id.nullable is False
    assert table.c.collector_run_id.nullable is False
    assert table.c.source_payload_hash.nullable is False


def test_energy_prices_constraints_and_indexes_exist() -> None:
    table = Base.metadata.tables["energy_prices"]
    unique_names = {constraint.name for constraint in table.constraints}
    index_names = {index.name for index in table.indexes}

    assert "uq_energy_source_instr_freq_period" in unique_names
    assert "ck_energy_prices_period_order" in unique_names
    assert "ck_energy_prices_frequency" in unique_names
    assert {
        "ix_energy_source_instr_period",
        "ix_energy_instr_observed",
        "ix_energy_category_observed",
        "ix_energy_fetched_at",
        "ix_energy_raw_response_id",
        "ix_energy_collector_run_id",
        "ix_energy_source_record_hash",
    } <= index_names


def test_energy_prices_migration_revision_metadata() -> None:
    assert energy_prices_migration.revision == "0008_energy_prices"
    assert energy_prices_migration.down_revision == "0007_calendar_features"


def test_create_all_creates_energy_prices_table() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    inspector = inspect(engine)

    assert "energy_prices" in inspector.get_table_names()
    columns = {column["name"] for column in inspector.get_columns("energy_prices")}
    assert "instrument_code" in columns
    assert "period_start" in columns
    assert "source_payload_hash" in columns


def test_energy_price_insert_and_unique_constraint() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)

    with SessionLocal() as session:
        source = Source(
            code="fred_energy_prices",
            name="FRED Energy Prices",
            source_type="energy",
            base_url="https://fred.stlouisfed.org/",
        )
        session.add(source)
        session.flush()
        run = CollectorRun(
            source_id=source.id,
            collector_name="fred_energy_prices_collector",
            started_at=datetime(2026, 6, 5, tzinfo=timezone.utc),
            status="success",
            run_type="manual",
        )
        session.add(run)
        session.flush()
        raw = RawResponse(
            source_id=source.id,
            collector_run_id=run.id,
            fetched_at=datetime(2026, 6, 5, tzinfo=timezone.utc),
            url="https://fred.stlouisfed.org/graph/fredgraph.csv?id=DCOILBRENTEU",
            method="GET",
            status_code=200,
            content_type="text/csv",
            storage_path="data/raw/fred_energy_prices/2026/06/05/1/hash.csv",
            sha256="a" * 64,
            bytes_size=1200,
            parser_version="fred_energy_v1",
        )
        session.add(raw)
        session.flush()

        session.add(_energy_price(source.id, raw.id, run.id))
        session.commit()

        loaded = session.scalar(select(EnergyPrice).where(EnergyPrice.instrument_code == "brent_crude_oil"))
        assert loaded is not None
        assert loaded.value == Decimal("70.12345678")
        assert loaded.raw_response_id == raw.id
        assert loaded.collector_run_id == run.id

        session.add(_energy_price(source.id, raw.id, run.id, source_record_hash="b" * 64))
        with pytest.raises(IntegrityError):
            session.commit()


def _energy_price(
    source_id: int,
    raw_response_id: int,
    collector_run_id: int,
    *,
    source_record_hash: str = "a" * 64,
) -> EnergyPrice:
    return EnergyPrice(
        source_id=source_id,
        raw_response_id=raw_response_id,
        collector_run_id=collector_run_id,
        instrument_code="brent_crude_oil",
        external_id="DCOILBRENTEU",
        instrument_name="Crude Oil Prices: Brent - Europe",
        instrument_category="crude_oil",
        frequency="daily",
        period_start=date(2026, 6, 5),
        period_end=date(2026, 6, 5),
        observed_at=datetime(2026, 6, 5, tzinfo=timezone.utc),
        published_at=None,
        fetched_at=datetime(2026, 6, 5, 12, tzinfo=timezone.utc),
        value=Decimal("70.12345678"),
        currency="USD",
        unit="USD/barrel",
        normalized_value=Decimal("70.12345678"),
        normalized_currency="USD",
        normalized_unit="USD/barrel",
        source_record_hash=source_record_hash,
        source_payload_hash="a" * 64,
        metadata_json={"series_id": "DCOILBRENTEU"},
    )
