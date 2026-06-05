from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DESIGN_DOC = PROJECT_ROOT / "docs" / "ENERGY_PRICES_DESIGN.md"
SQL_DRAFT = PROJECT_ROOT / "docs" / "sql_drafts" / "0008_energy_prices_draft.sql"


def test_energy_prices_design_doc_exists() -> None:
    assert DESIGN_DOC.exists()


def test_energy_prices_sql_draft_exists() -> None:
    assert SQL_DRAFT.exists()


def test_sql_draft_contains_table_and_unique_constraint() -> None:
    sql = SQL_DRAFT.read_text(encoding="utf-8")

    assert "DRAFT ONLY. DO NOT APPLY." in sql
    assert "CREATE TABLE energy_prices" in sql
    assert "uq_energy_prices_source_instrument_frequency_period" in sql
    assert "UNIQUE (source_id, instrument_code, frequency, period_start, period_end)" in sql


def test_sql_draft_contains_required_columns() -> None:
    sql = SQL_DRAFT.read_text(encoding="utf-8")
    required_columns = [
        "source_id",
        "raw_response_id",
        "collector_run_id",
        "instrument_code",
        "instrument_name",
        "instrument_category",
        "external_id",
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


def test_design_doc_mentions_as_of_and_leakage_policy() -> None:
    text = DESIGN_DOC.read_text(encoding="utf-8")

    assert "As-Of And Leakage Policy" in text
    assert "as_collected" in text
    assert "publication_aware" in text
    assert "historical backfill must not be treated as known in the past" in text


def test_design_doc_mentions_first_recommended_instruments() -> None:
    text = DESIGN_DOC.read_text(encoding="utf-8")

    for series_id in ("DCOILBRENTEU", "DCOILWTICO", "DHHNGSP", "GASDESW"):
        assert series_id in text


def test_design_doc_is_design_only() -> None:
    text = DESIGN_DOC.read_text(encoding="utf-8")

    assert "does not add an Alembic migration" in text
    assert "does not change SQLAlchemy models" in text
    assert "does not implement a collector" in text
