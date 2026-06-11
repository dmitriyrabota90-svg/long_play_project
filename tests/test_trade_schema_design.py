from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DESIGN_DOC = PROJECT_ROOT / "docs" / "TRADE_DATA_DESIGN.md"
SQL_DRAFT = PROJECT_ROOT / "docs" / "sql_drafts" / "0016_trade_schema_draft.sql"


def test_trade_design_doc_exists() -> None:
    assert DESIGN_DOC.exists()


def test_trade_sql_draft_exists() -> None:
    assert SQL_DRAFT.exists()


def test_sql_draft_contains_expected_tables() -> None:
    sql = SQL_DRAFT.read_text(encoding="utf-8")

    assert "DRAFT ONLY. DO NOT APPLY." in sql
    assert "CREATE TABLE trade_commodity_codes" in sql
    assert "CREATE TABLE trade_flows" in sql
    assert "CREATE TABLE product_trade_code_weights" in sql
    assert "CREATE TABLE daily_trade_features" in sql


def test_sql_draft_contains_important_unique_constraints() -> None:
    sql = SQL_DRAFT.read_text(encoding="utf-8")

    assert "uq_trade_commodity_codes_system_code_revision" in sql
    assert "UNIQUE (code_system, commodity_code, hs_revision)" in sql
    assert "uq_trade_flows_identity" in sql
    assert "source_id,\n            trade_commodity_code_id,\n            reporter_code,\n            partner_code" in sql
    assert "flow_direction,\n            frequency,\n            period_start,\n            period_end" in sql
    assert "uq_product_trade_code_weights_identity" in sql
    assert "UNIQUE (product_id, trade_commodity_code_id, role, effective_from)" in sql
    assert "uq_daily_trade_features_product_date" in sql
    assert "UNIQUE (product_id, feature_date)" in sql


def test_sql_draft_contains_required_trade_flow_columns_and_indexes() -> None:
    sql = SQL_DRAFT.read_text(encoding="utf-8")
    required_columns = [
        "raw_response_id",
        "collector_run_id",
        "trade_commodity_code_id",
        "source_record_id",
        "reporter_code",
        "partner_code",
        "flow_direction",
        "trade_period",
        "period_start",
        "period_end",
        "quantity",
        "trade_value_usd",
        "unit_value_usd",
        "published_at",
        "fetched_at",
        "source_record_hash",
        "source_payload_hash",
        "metadata_json",
    ]

    for column in required_columns:
        assert column in sql

    assert "ix_trade_flows_code_period" in sql
    assert "ix_trade_flows_reporter_period" in sql
    assert "ix_trade_flows_partner_period" in sql
    assert "ix_trade_flows_source_fetched" in sql
    assert "ix_trade_flows_record_hash" in sql


def test_design_doc_mentions_first_source_and_hs_codes() -> None:
    text = DESIGN_DOC.read_text(encoding="utf-8")

    assert "UN Comtrade" in text
    assert "First Source Decision" in text
    for hs_code in ("1201", "1507", "2304", "1205", "1514", "2306"):
        assert hs_code in text


def test_design_doc_mentions_reporter_partner_strategy() -> None:
    text = DESIGN_DOC.read_text(encoding="utf-8")

    assert "Country Reporter Partner Policy" in text
    assert "Brazil" in text
    assert "United States" in text
    assert "Argentina" in text
    assert "Canada" in text
    assert "Ukraine" in text
    assert "China as importer/demand proxy" in text
    assert "avoid double-counting" in text or "Avoid double-counting" in text


def test_design_doc_mentions_as_of_and_no_future_leakage_policy() -> None:
    text = DESIGN_DOC.read_text(encoding="utf-8")

    assert "As-Of And Leakage Policy" in text
    assert "published_at <= feature_date" in text
    assert "fetched_at <= feature_date" in text
    assert "historical_backfill_allowed" in text
    assert "future month trade data must never be used" in text
    assert "trade_as_of_date" in text
    assert "less than or equal to `feature_date`" in text


def test_design_doc_marks_phase_65b_as_design_only() -> None:
    text = DESIGN_DOC.read_text(encoding="utf-8")

    assert "Phase 6.5B is a design-only step" in text
    assert "No migration in Phase 6.5B" in text
    assert "No Alembic revision in Phase 6.5B" in text
    assert "No SQLAlchemy model changes in Phase 6.5B" in text
    assert "No collector in Phase 6.5B" in text
    assert "No DB writes in Phase 6.5B" in text
    assert "No scheduler changes in Phase 6.5B" in text
    assert "No ML in Phase 6.5B" in text
    assert "No targets in Phase 6.5B" in text


def test_design_doc_mentions_product_trade_code_weights() -> None:
    text = DESIGN_DOC.read_text(encoding="utf-8")

    assert "Product Trade Code Weights" in text
    assert "product_trade_code_weights" in text
    assert "soybean_oil` -> HS `1507` direct" in text
    assert "rapeseed_meal` -> HS `2306` direct" in text


def test_design_doc_mentions_future_feature_and_export_integration() -> None:
    text = DESIGN_DOC.read_text(encoding="utf-8")

    assert "Future Feature Integration Into Daily Product Features" in text
    assert "daily_trade_features" in text
    assert "daily_product_features" in text
    assert "export_volume_1m" in text
    assert "china_import_volume_1m" in text
    assert "trade_missing_flags" in text
    assert "Future Export Integration" in text


def test_design_doc_mentions_source_seed_design_and_raw_lineage() -> None:
    text = DESIGN_DOC.read_text(encoding="utf-8")

    assert "Source Seeds Design" in text
    assert "un_comtrade" in text
    assert "faostat_trade" in text
    assert "usda_fas_trade" in text
    assert "world_bank_wits" in text
    assert "Source And Raw Lineage" in text
    assert "raw_response_id" in text
    assert "source_record_hash" in text
    assert "source_payload_hash" in text
