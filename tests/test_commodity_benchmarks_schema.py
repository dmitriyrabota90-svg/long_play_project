from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from importlib import import_module

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, CollectorRun, CommodityBenchmark, RawResponse, Source


commodity_benchmarks_migration = import_module("migrations.versions.0010_commodity_benchmarks")


def test_metadata_contains_commodity_benchmarks() -> None:
    table = Base.metadata.tables["commodity_benchmarks"]
    expected_columns = {
        "id",
        "source_id",
        "raw_response_id",
        "collector_run_id",
        "benchmark_code",
        "external_id",
        "benchmark_name",
        "benchmark_category",
        "commodity_family",
        "geography",
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
    assert table.c.source_id.nullable is False
    assert table.c.raw_response_id.nullable is False
    assert table.c.collector_run_id.nullable is False
    assert table.c.source_payload_hash.nullable is False


def test_commodity_benchmarks_constraints_and_indexes_exist() -> None:
    table = Base.metadata.tables["commodity_benchmarks"]
    unique_names = {constraint.name for constraint in table.constraints}
    index_names = {index.name for index in table.indexes}

    assert "uq_comm_bench_source_code_freq_period" in unique_names
    assert "ck_comm_bench_period_order" in unique_names
    assert "ck_comm_bench_frequency" in unique_names
    assert {
        "ix_comm_bench_source_code_period",
        "ix_comm_bench_code_observed",
        "ix_comm_bench_category_observed",
        "ix_comm_bench_family_observed",
        "ix_comm_bench_fetched_at",
        "ix_comm_bench_raw_response_id",
        "ix_comm_bench_collector_run_id",
        "ix_comm_bench_source_record_hash",
    } <= index_names


def test_commodity_benchmarks_migration_revision_metadata() -> None:
    assert commodity_benchmarks_migration.revision == "0010_commodity_benchmarks"
    assert commodity_benchmarks_migration.down_revision == "0009_energy_features"


def test_create_all_creates_commodity_benchmarks_table() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    inspector = inspect(engine)

    assert "commodity_benchmarks" in inspector.get_table_names()
    columns = {column["name"] for column in inspector.get_columns("commodity_benchmarks")}
    assert "benchmark_code" in columns
    assert "period_start" in columns
    assert "source_payload_hash" in columns


def test_commodity_benchmark_insert_and_unique_constraint() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)

    with SessionLocal() as session:
        source = Source(
            code="world_bank_pink_sheet",
            name="World Bank Pink Sheet",
            source_type="benchmark",
            base_url="https://www.worldbank.org/en/research/commodity-markets",
        )
        session.add(source)
        session.flush()
        run = CollectorRun(
            source_id=source.id,
            collector_name="world_bank_pink_sheet_collector",
            started_at=datetime(2026, 6, 9, tzinfo=timezone.utc),
            status="success",
            run_type="manual",
        )
        session.add(run)
        session.flush()
        raw = RawResponse(
            source_id=source.id,
            collector_run_id=run.id,
            fetched_at=datetime(2026, 6, 9, tzinfo=timezone.utc),
            url="https://www.worldbank.org/en/research/commodity-markets",
            method="GET",
            status_code=200,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            storage_path="data/raw/world_bank_pink_sheet/2026/06/09/1/hash.xlsx",
            sha256="a" * 64,
            bytes_size=1200,
            parser_version="world_bank_pink_sheet_v1",
        )
        session.add(raw)
        session.flush()

        session.add(_benchmark(source.id, raw.id, run.id))
        session.commit()

        loaded = session.scalar(select(CommodityBenchmark).where(CommodityBenchmark.benchmark_code == "world_bank_soybean_oil"))
        assert loaded is not None
        assert loaded.value == Decimal("1000.12345678")
        assert loaded.raw_response_id == raw.id
        assert loaded.collector_run_id == run.id

        session.add(_benchmark(source.id, raw.id, run.id, source_record_hash="b" * 64))
        with pytest.raises(IntegrityError):
            session.commit()


def _benchmark(
    source_id: int,
    raw_response_id: int,
    collector_run_id: int,
    *,
    source_record_hash: str = "a" * 64,
) -> CommodityBenchmark:
    return CommodityBenchmark(
        source_id=source_id,
        raw_response_id=raw_response_id,
        collector_run_id=collector_run_id,
        benchmark_code="world_bank_soybean_oil",
        external_id="Pink Sheet soybean oil series",
        benchmark_name="World Bank soybean oil benchmark",
        benchmark_category="vegetable_oil",
        commodity_family="soybean",
        geography="global",
        frequency="monthly",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        observed_at=datetime(2026, 5, 31, tzinfo=timezone.utc),
        published_at=None,
        fetched_at=datetime(2026, 6, 9, tzinfo=timezone.utc),
        value=Decimal("1000.12345678"),
        currency="USD",
        unit="USD/metric_ton",
        normalized_value=Decimal("1000.12345678"),
        normalized_currency="USD",
        normalized_unit="USD/metric_ton",
        source_record_hash=source_record_hash,
        source_payload_hash="a" * 64,
        metadata_json={"sheet": "Monthly Prices", "column": "Soybean oil"},
    )
