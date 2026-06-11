from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DESIGN_DOC = PROJECT_ROOT / "docs" / "WEATHER_DATA_DESIGN.md"
SQL_DRAFT = PROJECT_ROOT / "docs" / "sql_drafts" / "0012_weather_schema_draft.sql"


def test_weather_design_doc_exists() -> None:
    assert DESIGN_DOC.exists()


def test_weather_sql_draft_exists() -> None:
    assert SQL_DRAFT.exists()


def test_sql_draft_contains_weather_tables() -> None:
    sql = SQL_DRAFT.read_text(encoding="utf-8")

    assert "DRAFT ONLY. DO NOT APPLY." in sql
    assert "Not an Alembic migration." in sql
    assert "CREATE TABLE weather_regions" in sql
    assert "CREATE TABLE weather_observations" in sql
    assert "CREATE TABLE weather_daily_features" in sql
    assert "CREATE TABLE product_weather_region_weights" in sql


def test_sql_draft_contains_unique_constraints() -> None:
    sql = SQL_DRAFT.read_text(encoding="utf-8")

    assert "uq_weather_regions_code" in sql
    assert "UNIQUE (region_code)" in sql
    assert "uq_weather_obs_source_region_date_freq" in sql
    assert "UNIQUE (source_id, region_id, observation_date, frequency)" in sql
    assert "uq_weather_daily_region_date" in sql
    assert "UNIQUE (region_id, feature_date)" in sql
    assert "uq_product_weather_region_effective" in sql


def test_sql_draft_contains_required_observation_columns() -> None:
    sql = SQL_DRAFT.read_text(encoding="utf-8")
    required_columns = [
        "source_id",
        "raw_response_id",
        "collector_run_id",
        "region_id",
        "source_region_key",
        "observation_date",
        "observed_at",
        "fetched_at",
        "frequency",
        "temperature_2m_mean",
        "temperature_2m_min",
        "temperature_2m_max",
        "precipitation_sum",
        "snowfall_sum",
        "relative_humidity_mean",
        "wind_speed_mean",
        "wind_speed_max",
        "soil_moisture",
        "evapotranspiration",
        "shortwave_radiation",
        "source_record_hash",
        "source_payload_hash",
        "metadata_json",
    ]

    for column in required_columns:
        assert column in sql


def test_design_doc_mentions_sources_and_why_not_era5_first() -> None:
    text = DESIGN_DOC.read_text(encoding="utf-8")

    assert "Open-Meteo Historical Weather API" in text
    assert "NASA POWER" in text
    assert "Why Not Start With ERA5/Copernicus" in text
    assert "gridded payloads are much larger" in text


def test_design_doc_mentions_no_future_leakage_policy() -> None:
    text = DESIGN_DOC.read_text(encoding="utf-8")

    assert "Date Alignment And As-Of/Leakage Policy" in text
    assert "no future leakage" in text
    assert "observation_date <= feature_date" in text
    assert "weather_as_of_date" in text
    assert "historical backfill" in text


def test_design_doc_mentions_region_product_weights() -> None:
    text = DESIGN_DOC.read_text(encoding="utf-8")

    assert "product_weather_region_weights" in text
    assert "Weather regions should not be blindly joined to every product" in text
    assert "first version can use equal weights" in text
    assert "soybean oil and soybean meal use high-priority soybean regions" in text


def test_design_doc_marks_phase_63b_as_design_only() -> None:
    text = DESIGN_DOC.read_text(encoding="utf-8")

    assert "Phase 6.3B is a design-only step" in text
    assert "No migration in Phase 6.3B" in text
    assert "No SQLAlchemy model changes in Phase 6.3B" in text
    assert "No collector" in text
    assert "No DB writes" in text
    assert "No scheduler changes" in text
    assert "No ML model" in text
    assert "No targets" in text
