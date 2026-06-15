from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DESIGN_DOC = PROJECT_ROOT / "docs" / "SUPPLY_DEMAND_DESIGN.md"
SQL_DRAFT = PROJECT_ROOT / "docs" / "sql_drafts" / "0018_supply_demand_schema_draft.sql"


def test_supply_demand_design_doc_exists() -> None:
    assert DESIGN_DOC.exists()


def test_supply_demand_sql_draft_exists() -> None:
    assert SQL_DRAFT.exists()


def test_sql_draft_contains_expected_tables() -> None:
    sql = SQL_DRAFT.read_text(encoding="utf-8")

    assert "DRAFT ONLY. DO NOT APPLY." in sql
    assert "CREATE TABLE supply_demand_commodities" in sql
    assert "CREATE TABLE supply_demand_observations" in sql
    assert "CREATE TABLE supply_demand_revisions" in sql
    assert "CREATE TABLE product_supply_demand_weights" in sql
    assert "CREATE TABLE daily_supply_demand_features" in sql


def test_sql_draft_contains_important_unique_constraints() -> None:
    sql = SQL_DRAFT.read_text(encoding="utf-8")

    assert "uq_supply_demand_commodities_source_metric" in sql
    assert "UNIQUE (source_id, source_commodity_code, source_metric_code, metric_name)" in sql
    assert "uq_supply_demand_observations_identity" in sql
    assert "source_id,\n            supply_demand_commodity_id,\n            country_code" in sql
    assert "marketing_year,\n            report_year,\n            report_month,\n            estimate_type" in sql
    assert "uq_supply_demand_revisions_obs_number" in sql
    assert "UNIQUE (supply_demand_observation_id, revision_number)" in sql
    assert "uq_product_supply_demand_weights_identity" in sql
    assert "UNIQUE (product_id, supply_demand_commodity_id, role, effective_from)" in sql
    assert "uq_daily_supply_demand_features_product_date" in sql
    assert "UNIQUE (product_id, feature_date)" in sql


def test_sql_draft_contains_required_observation_columns_and_indexes() -> None:
    sql = SQL_DRAFT.read_text(encoding="utf-8")
    required_columns = [
        "raw_response_id",
        "collector_run_id",
        "supply_demand_commodity_id",
        "source_record_id",
        "country_code",
        "marketing_year",
        "marketing_year_start",
        "marketing_year_end",
        "report_month",
        "report_year",
        "report_published_at",
        "observed_period_start",
        "observed_period_end",
        "estimate_type",
        "metric_value",
        "metric_unit",
        "is_forecast",
        "is_revision",
        "published_at",
        "fetched_at",
        "source_record_hash",
        "source_payload_hash",
        "metadata_json",
    ]

    for column in required_columns:
        assert column in sql

    assert "ix_supply_demand_obs_commodity_year" in sql
    assert "ix_supply_demand_obs_country_year" in sql
    assert "ix_supply_demand_obs_report_published" in sql
    assert "ix_supply_demand_obs_published_at" in sql
    assert "ix_supply_demand_obs_fetched_at" in sql
    assert "ix_supply_demand_obs_record_hash" in sql


def test_design_doc_mentions_first_source_and_scope() -> None:
    text = DESIGN_DOC.read_text(encoding="utf-8")

    assert "USDA PSD / FAS PSD Online" in text
    assert "First Source Decision" in text
    assert "First Prototype Scope" in text
    for phrase in (
        "soybeans",
        "soybean oil",
        "soybean meal",
        "rapeseed/canola",
        "rapeseed oil",
        "rapeseed meal",
    ):
        assert phrase in text


def test_design_doc_mentions_wasde_and_high_complexity_deferral() -> None:
    text = DESIGN_DOC.read_text(encoding="utf-8")

    assert "WASDE" in text
    assert "CONAB Brazil" in text or "CONAB" in text
    assert "Argentina" in text
    assert "Statistics Canada" in text
    assert "IGC" in text
    assert "not the best first production" in text
    assert "schema driver" in text


def test_design_doc_mentions_metric_taxonomy() -> None:
    text = DESIGN_DOC.read_text(encoding="utf-8")

    for metric in (
        "production_volume",
        "production_forecast_revision",
        "domestic_consumption",
        "food_use",
        "feed_use",
        "industrial_use",
        "crush_volume",
        "processing_volume",
        "exports_volume",
        "imports_volume",
        "beginning_stocks",
        "ending_stocks",
        "stock_to_use_ratio",
        "planted_area",
        "harvested_area",
        "yield",
        "forecast_month",
        "marketing_year",
        "report_publication_date",
        "reporting_lag_days",
    ):
        assert metric in text


def test_design_doc_mentions_product_official_mapping() -> None:
    text = DESIGN_DOC.read_text(encoding="utf-8")

    assert "Product-To-Official-Commodity Mapping" in text
    assert "`soybean_oil`" in text
    assert "`soybean_meal`" in text
    assert "`rapeseed_oil`" in text
    assert "`rapeseed_meal`" in text
    assert "seed balance" in text
    assert "crush context" in text


def test_design_doc_mentions_marketing_year_forecast_actual_and_units() -> None:
    text = DESIGN_DOC.read_text(encoding="utf-8")

    assert "Marketing Year Policy" in text
    assert "Marketing-year labels are source-specific" in text
    assert "Forecast Vs Actual Policy" in text
    assert "is_forecast=true" in text
    assert "estimate_type" in text
    assert "Units And Normalization Policy" in text
    assert "metric_unit" in text
    assert "unit_hint" in text


def test_design_doc_mentions_as_of_and_no_future_leakage_policy() -> None:
    text = DESIGN_DOC.read_text(encoding="utf-8")

    assert "As-Of/Leakage Policy" in text
    assert "report_published_at <= feature_date" in text
    assert "fetched_at <= feature_date" in text
    assert "supply_demand_as_of_date <= feature_date" in text
    assert "historical_backfill_allowed" in text
    assert "publication_aware" in text
    assert "as_collected" in text
    assert "Do not use future WASDE/PSD revisions" in text


def test_design_doc_mentions_revision_and_dedup_policy() -> None:
    text = DESIGN_DOC.read_text(encoding="utf-8")

    assert "Deduplication/Idempotency Policy" in text
    assert "same `source_record_hash`: skip" in text
    assert "changed `source_record_hash`" in text
    assert "Revision/Change Detection Policy" in text
    assert "supply_demand_revisions" in text
    assert "old/new value" in text


def test_design_doc_marks_phase_67b_as_design_only() -> None:
    text = DESIGN_DOC.read_text(encoding="utf-8")

    assert "Phase 6.7B is a design-only step" in text
    assert "No migration in Phase 6.7B" in text
    assert "No Alembic revision in Phase 6.7B" in text
    assert "No SQLAlchemy model changes in Phase 6.7B" in text
    assert "No collector in Phase 6.7B" in text
    assert "No DB writes in Phase 6.7B" in text
    assert "No scheduler changes in Phase 6.7B" in text
    assert "No ML in Phase 6.7B" in text
    assert "No targets in Phase 6.7B" in text


def test_design_doc_mentions_future_feature_and_export_integration() -> None:
    text = DESIGN_DOC.read_text(encoding="utf-8")

    assert "Phase 6.7E Feature Integration Into `daily_product_features`" in text
    assert "daily_supply_demand_features" in text
    assert "daily_product_features" in text
    assert "supply_demand_missing_flags" in text
    assert "Phase 6.7E Export Integration" in text
    assert "DATASET_DICTIONARY.md" in text
    assert "SOURCE_TO_FEATURE_LINEAGE.md" in text


def test_design_doc_mentions_source_seed_design_and_raw_lineage() -> None:
    text = DESIGN_DOC.read_text(encoding="utf-8")

    assert "Source Seed Design" in text
    assert "`usda_psd`" in text
    assert "`usda_wasde`" in text
    assert "`faostat_supply_demand`" in text
    assert "`usda_nass_quickstats`" in text
    assert "Source/Raw Lineage" in text
    assert "raw_response_id" in text
    assert "source_record_hash" in text
    assert "source_payload_hash" in text
