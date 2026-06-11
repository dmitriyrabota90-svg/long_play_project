from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from importlib import import_module
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.db.models import (
    Base,
    CollectorRun,
    DailyTradeFeature,
    Product,
    ProductTradeCodeWeight,
    RawResponse,
    Source,
    TradeCommodityCode,
    TradeFlow,
)


trade_schema_migration = import_module("migrations.versions.0016_trade_schema")


def test_metadata_contains_trade_tables() -> None:
    assert "trade_commodity_codes" in Base.metadata.tables
    assert "trade_flows" in Base.metadata.tables
    assert "product_trade_code_weights" in Base.metadata.tables
    assert "daily_trade_features" in Base.metadata.tables


def test_trade_commodity_codes_columns_constraints_and_indexes() -> None:
    table = Base.metadata.tables["trade_commodity_codes"]
    expected_columns = {
        "id",
        "source_id",
        "code_system",
        "commodity_code",
        "commodity_name",
        "hs_code",
        "hs_revision",
        "commodity_family",
        "product_code",
        "relevance",
        "unit_hint",
        "is_active",
        "metadata_json",
        "created_at",
        "updated_at",
    }
    constraint_names = {constraint.name for constraint in table.constraints}
    index_names = {index.name for index in table.indexes}

    assert expected_columns <= set(table.c.keys())
    assert table.c.source_id.nullable is True
    assert table.c.code_system.nullable is False
    assert "uq_trade_codes_system_code_rev" in constraint_names
    assert "ck_trade_codes_relevance" in constraint_names
    assert {
        "ix_trade_codes_family",
        "ix_trade_codes_product_code",
        "ix_trade_codes_hs_code",
        "ix_trade_codes_is_active",
    } <= index_names


def test_trade_flows_columns_constraints_indexes_and_foreign_keys() -> None:
    table = Base.metadata.tables["trade_flows"]
    expected_columns = {
        "id",
        "source_id",
        "raw_response_id",
        "collector_run_id",
        "trade_commodity_code_id",
        "source_record_id",
        "reporter_code",
        "reporter_name",
        "partner_code",
        "partner_name",
        "flow_direction",
        "trade_period",
        "period_start",
        "period_end",
        "frequency",
        "quantity",
        "quantity_unit",
        "trade_value_usd",
        "trade_value_local",
        "currency",
        "unit_value_usd",
        "net_weight_kg",
        "gross_weight_kg",
        "published_at",
        "fetched_at",
        "source_record_hash",
        "source_payload_hash",
        "metadata_json",
        "created_at",
        "updated_at",
    }
    constraint_names = {constraint.name for constraint in table.constraints}
    index_names = {index.name for index in table.indexes}
    fk_columns = {fk.parent.name for fk in table.foreign_keys}

    assert expected_columns <= set(table.c.keys())
    assert {"source_id", "raw_response_id", "collector_run_id", "trade_commodity_code_id"} <= fk_columns
    assert "uq_trade_flows_identity" in constraint_names
    assert "ck_trade_flows_direction" in constraint_names
    assert "ck_trade_flows_frequency" in constraint_names
    assert "ck_trade_flows_period_order" in constraint_names
    assert {
        "ix_trade_flows_code_period",
        "ix_trade_flows_reporter_period",
        "ix_trade_flows_partner_period",
        "ix_trade_flows_direction_period",
        "ix_trade_flows_source_fetched",
        "ix_trade_flows_raw_response_id",
        "ix_trade_flows_collector_run_id",
        "ix_trade_flows_record_hash",
    } <= index_names
    unique = next(constraint for constraint in table.constraints if constraint.name == "uq_trade_flows_identity")
    assert "source_record_hash" not in {column.name for column in unique.columns}


def test_product_trade_weights_and_daily_trade_features_constraints() -> None:
    weights_table = Base.metadata.tables["product_trade_code_weights"]
    daily_table = Base.metadata.tables["daily_trade_features"]

    assert "uq_product_trade_code_weight" in {constraint.name for constraint in weights_table.constraints}
    assert "ck_product_trade_weight_relevance" in {constraint.name for constraint in weights_table.constraints}
    assert "ck_product_trade_weight_nonnegative" in {constraint.name for constraint in weights_table.constraints}
    assert {
        "ix_product_trade_weight_product_active",
        "ix_product_trade_weight_code_active",
        "ix_product_trade_weight_effective",
    } <= {index.name for index in weights_table.indexes}
    assert "uq_daily_trade_features_product_date" in {constraint.name for constraint in daily_table.constraints}
    assert "ck_daily_trade_features_as_of" in {constraint.name for constraint in daily_table.constraints}
    assert {
        "ix_daily_trade_features_product_date",
        "ix_daily_trade_features_feature_date",
        "ix_daily_trade_features_as_of",
    } <= {index.name for index in daily_table.indexes}


def test_trade_schema_migration_revision_metadata() -> None:
    migration_text = Path(trade_schema_migration.__file__).read_text(encoding="utf-8")

    assert trade_schema_migration.revision == "0016_trade_schema"
    assert trade_schema_migration.down_revision == "0015_product_news_features"
    assert "op.create_table(\n        \"trade_commodity_codes\"" in migration_text
    assert "op.create_table(\n        \"trade_flows\"" in migration_text
    assert "op.create_table(\n        \"product_trade_code_weights\"" in migration_text
    assert "op.create_table(\n        \"daily_trade_features\"" in migration_text


def test_create_all_creates_trade_tables() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    table_names = set(inspector.get_table_names())

    assert "trade_commodity_codes" in table_names
    assert "trade_flows" in table_names
    assert "product_trade_code_weights" in table_names
    assert "daily_trade_features" in table_names


def test_trade_rows_insert_and_unique_constraints() -> None:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, future=True)

    with SessionLocal() as session:
        source = Source(
            code="un_comtrade",
            name="UN Comtrade",
            source_type="trade",
            base_url="https://comtradeplus.un.org/",
        )
        product = Product(
            code="soybean_oil",
            name="Soybean oil",
            category="oil",
            unit="metric_ton",
            currency_default="USD",
        )
        session.add_all([source, product])
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
            url="https://comtradeplus.un.org/",
            method="GET",
            status_code=200,
            content_type="application/json",
            storage_path="data/raw/un_comtrade/2026/06/11/1/hash.json",
            sha256="a" * 64,
            bytes_size=2000,
            parser_version="un_comtrade_v1",
        )
        trade_code = _trade_code()
        session.add_all([raw, trade_code])
        session.flush()

        session.add(_trade_flow(source.id, raw.id, run.id, trade_code.id))
        session.add(_product_trade_weight(product.id, trade_code.id))
        session.add(_daily_trade_feature(product.id))
        session.commit()

        loaded_flow = session.scalar(select(TradeFlow).where(TradeFlow.source_record_hash == "record" + "a" * 58))
        assert loaded_flow is not None
        assert loaded_flow.source_record_hash == "record" + "a" * 58
        assert loaded_flow.raw_response_id == raw.id
        assert loaded_flow.collector_run_id == run.id
        assert loaded_flow.trade_commodity_code_id == trade_code.id

        session.add(_trade_flow(source.id, raw.id, run.id, trade_code.id, source_record_hash="record" + "b" * 58))
        with pytest.raises(IntegrityError):
            session.commit()


def _trade_code() -> TradeCommodityCode:
    return TradeCommodityCode(
        source_id=None,
        code_system="HS",
        commodity_code="1507",
        commodity_name="Soybean oil",
        hs_code="1507",
        hs_revision="generic",
        commodity_family="soybean",
        product_code="soybean_oil",
        relevance="direct",
        unit_hint="metric_ton",
        is_active=True,
        metadata_json={"design_phase": "6.5C"},
    )


def _trade_flow(
    source_id: int,
    raw_response_id: int,
    collector_run_id: int,
    trade_commodity_code_id: int,
    *,
    source_record_hash: str = "record" + "a" * 58,
) -> TradeFlow:
    return TradeFlow(
        source_id=source_id,
        raw_response_id=raw_response_id,
        collector_run_id=collector_run_id,
        trade_commodity_code_id=trade_commodity_code_id,
        source_record_id="row-1",
        reporter_code="BR",
        reporter_name="Brazil",
        partner_code="CN",
        partner_name="China",
        flow_direction="export",
        trade_period="2026-05",
        period_start=date(2026, 5, 1),
        period_end=date(2026, 5, 31),
        frequency="monthly",
        quantity=Decimal("1000.00000000"),
        quantity_unit="metric_ton",
        trade_value_usd=Decimal("850000.00000000"),
        trade_value_local=None,
        currency=None,
        unit_value_usd=Decimal("850.00000000"),
        net_weight_kg=Decimal("1000000.00000000"),
        gross_weight_kg=None,
        published_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
        fetched_at=datetime(2026, 6, 11, tzinfo=timezone.utc),
        source_record_hash=source_record_hash,
        source_payload_hash="a" * 64,
        metadata_json={"source": "test"},
    )


def _product_trade_weight(product_id: int, trade_commodity_code_id: int) -> ProductTradeCodeWeight:
    return ProductTradeCodeWeight(
        product_id=product_id,
        trade_commodity_code_id=trade_commodity_code_id,
        weight=Decimal("1.00000000"),
        relevance="direct",
        role="direct_trade_proxy",
        effective_from=date(2020, 1, 1),
        effective_to=None,
        is_active=True,
        metadata_json={"design_phase": "6.5C"},
    )


def _daily_trade_feature(product_id: int) -> DailyTradeFeature:
    return DailyTradeFeature(
        product_id=product_id,
        feature_date=date(2026, 6, 11),
        export_volume_1m=Decimal("1000.00000000"),
        export_volume_3m_avg=None,
        export_volume_12m_sum=None,
        import_volume_1m=None,
        import_volume_3m_avg=None,
        import_volume_12m_sum=None,
        net_export_volume_1m=Decimal("1000.00000000"),
        export_value_usd_1m=Decimal("850000.00000000"),
        import_value_usd_1m=None,
        average_export_unit_value_usd=Decimal("850.00000000"),
        average_import_unit_value_usd=None,
        china_import_volume_1m=Decimal("1000.00000000"),
        major_exporter_volume_1m=Decimal("1000.00000000"),
        major_importer_volume_1m=None,
        trade_balance_proxy=Decimal("1000.00000000"),
        trade_yoy_change=None,
        trade_as_of_date=date(2026, 6, 10),
        reporting_lag_days=10,
        missing_flags={"missing_import": True},
        metadata_json={"source": "test"},
    )
