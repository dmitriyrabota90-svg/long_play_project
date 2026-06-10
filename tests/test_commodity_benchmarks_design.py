from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DESIGN_DOC = PROJECT_ROOT / "docs" / "COMMODITY_BENCHMARKS_DESIGN.md"
SQL_DRAFT = PROJECT_ROOT / "docs" / "sql_drafts" / "0010_commodity_benchmarks_draft.sql"


def test_commodity_benchmarks_design_doc_exists() -> None:
    assert DESIGN_DOC.exists()


def test_commodity_benchmarks_sql_draft_exists() -> None:
    assert SQL_DRAFT.exists()


def test_sql_draft_contains_table_and_unique_constraint() -> None:
    sql = SQL_DRAFT.read_text(encoding="utf-8")

    assert "DRAFT ONLY. DO NOT APPLY." in sql
    assert "CREATE TABLE commodity_benchmarks" in sql
    assert "uq_comm_bench_source_code_freq_period" in sql
    assert "UNIQUE (source_id, benchmark_code, frequency, period_start, period_end)" in sql


def test_sql_draft_contains_required_columns() -> None:
    sql = SQL_DRAFT.read_text(encoding="utf-8")
    required_columns = [
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
    ]

    for column in required_columns:
        assert column in sql


def test_design_doc_mentions_world_bank_and_fao() -> None:
    text = DESIGN_DOC.read_text(encoding="utf-8")

    assert "World Bank Pink Sheet" in text
    assert "FAO indices" in text
    assert "FAO Food Price Index" in text


def test_design_doc_mentions_as_of_and_leakage_policy() -> None:
    text = DESIGN_DOC.read_text(encoding="utf-8")

    assert "As-Of And Leakage Policy" in text
    assert "as_collected" in text
    assert "publication_aware" in text
    assert "historical_backfill_allowed" in text
    assert "must not be used for feature dates before it was available" in text


def test_design_doc_mentions_phase_62e_feature_integration() -> None:
    text = DESIGN_DOC.read_text(encoding="utf-8")

    assert "Phase 6.2E Feature Integration" in text
    assert "benchmark_soybean_oil_value" in text
    assert "benchmark_fertilizer_index_delta_3m" in text
    assert "benchmark_missing_flags" in text
    assert "commodity_benchmarks.period_start <= feature_date" in text
    assert "no future leakage" in text


def test_design_doc_marks_phase_62b_as_design_only() -> None:
    text = DESIGN_DOC.read_text(encoding="utf-8")

    assert "Phase 6.2B is a design-only step" in text
    assert "No migration in Phase 6.2B" in text
    assert "No collector" in text
    assert "No DB writes" in text
    assert "No scheduler changes" in text
    assert "No ML model" in text
    assert "No targets" in text
