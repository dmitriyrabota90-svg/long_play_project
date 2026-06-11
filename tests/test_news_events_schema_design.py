from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DESIGN_DOC = PROJECT_ROOT / "docs" / "NEWS_EVENTS_DESIGN.md"
SQL_DRAFT = PROJECT_ROOT / "docs" / "sql_drafts" / "0014_news_events_schema_draft.sql"


def test_news_events_design_doc_exists() -> None:
    assert DESIGN_DOC.exists()


def test_news_events_sql_draft_exists() -> None:
    assert SQL_DRAFT.exists()


def test_sql_draft_contains_expected_tables() -> None:
    sql = SQL_DRAFT.read_text(encoding="utf-8")

    assert "DRAFT ONLY. DO NOT APPLY." in sql
    assert "CREATE TABLE news_articles" in sql
    assert "CREATE TABLE commodity_events" in sql
    assert "CREATE TABLE daily_news_features" in sql


def test_sql_draft_contains_important_unique_constraints() -> None:
    sql = SQL_DRAFT.read_text(encoding="utf-8")

    assert "uq_news_articles_source_external_id" in sql
    assert "ON news_articles (source_id, external_id)" in sql
    assert "WHERE external_id IS NOT NULL" in sql
    assert "uq_news_articles_source_article_hash" in sql
    assert "ON news_articles (source_id, article_hash)" in sql
    assert "uq_commodity_events_article_event_family_geo_date_method" in sql
    assert "UNIQUE (news_article_id, event_category, commodity_family, country, region, event_date, extraction_method)" in sql
    assert "uq_daily_news_features_product_date" in sql
    assert "UNIQUE (product_id, feature_date)" in sql


def test_sql_draft_contains_required_news_article_columns() -> None:
    sql = SQL_DRAFT.read_text(encoding="utf-8")
    required_columns = [
        "source_id",
        "raw_response_id",
        "collector_run_id",
        "external_id",
        "url",
        "canonical_url",
        "title",
        "summary",
        "body_text",
        "language",
        "source_name",
        "country",
        "region",
        "published_at",
        "fetched_at",
        "article_hash",
        "source_record_hash",
        "source_payload_hash",
        "metadata_json",
    ]

    for column in required_columns:
        assert column in sql


def test_sql_draft_contains_event_taxonomy_constraints() -> None:
    sql = SQL_DRAFT.read_text(encoding="utf-8")

    for value in (
        "export_restriction",
        "import_policy",
        "war_logistics_disruption",
        "weather_disaster",
        "crop_report",
        "biofuel_policy",
        "energy_shock",
        "currency_macro",
        "demand_shock",
        "supply_chain",
    ):
        assert value in DESIGN_DOC.read_text(encoding="utf-8")

    assert "future_nlp" in sql
    assert "future_llm" in sql
    assert "CHECK (direction_hint IN ('bullish', 'bearish', 'mixed', 'unknown'))" in sql
    assert "CHECK (lag_bucket IN ('same_day', '1_7d', '7_30d', '30d_plus', 'unknown'))" in sql


def test_design_doc_mentions_first_sources() -> None:
    text = DESIGN_DOC.read_text(encoding="utf-8")

    assert "GDELT 2.1" in text
    assert "USDA WASDE and PSD" in text
    assert "FAO" in text
    assert "World Bank" in text


def test_design_doc_mentions_deduplication_policy() -> None:
    text = DESIGN_DOC.read_text(encoding="utf-8")

    assert "Deduplication Policy" in text
    assert "external_id" in text
    assert "Canonical URL" in text or "canonical URL" in text
    assert "source_record_hash" in text
    assert "Raw evidence must be retained" in text


def test_design_doc_mentions_as_of_and_leakage_policy() -> None:
    text = DESIGN_DOC.read_text(encoding="utf-8")

    assert "As-Of And Leakage Policy" in text
    assert "published_at <= feature_date" in text
    assert "fetched_at <= feature_date" in text
    assert "as_collected" in text
    assert "publication_aware" in text
    assert "historical_backfill_allowed" in text
    assert "must not be treated as known on past dates" in text


def test_design_doc_marks_phase_64b_as_design_only() -> None:
    text = DESIGN_DOC.read_text(encoding="utf-8")

    assert "Phase 6.4B is a design-only step" in text
    assert "No migration in Phase 6.4B" in text
    assert "No collector in Phase 6.4B" in text
    assert "No DB writes in Phase 6.4B" in text
    assert "No scheduler changes in Phase 6.4B" in text
    assert "No ML in Phase 6.4B" in text
    assert "No targets in Phase 6.4B" in text
    assert "No LLM classifier in Phase 6.4B" in text


def test_design_doc_mentions_future_feature_and_export_integration() -> None:
    text = DESIGN_DOC.read_text(encoding="utf-8")

    assert "Future Feature Integration Into Daily Product Features" in text
    assert "daily_news_features" in text
    assert "news_count_7d" in text
    assert "crop_report_count_30d" in text
    assert "news_as_of_date" in text
    assert "Future Export Integration" in text
