from __future__ import annotations

from importlib import import_module

from app.db.models import DailyProductFeature


calendar_migration = import_module("migrations.versions.0007_calendar_features")


CALENDAR_COLUMNS = {
    "calendar_year",
    "calendar_month",
    "calendar_quarter",
    "calendar_week_of_year",
    "calendar_day_of_year",
    "calendar_day_of_week",
    "calendar_is_month_start",
    "calendar_is_month_end",
    "calendar_is_quarter_start",
    "calendar_is_quarter_end",
    "calendar_sin_day_of_year",
    "calendar_cos_day_of_year",
    "calendar_sin_month",
    "calendar_cos_month",
    "calendar_season",
}


def test_daily_product_feature_metadata_contains_calendar_columns() -> None:
    assert CALENDAR_COLUMNS <= set(DailyProductFeature.__table__.c.keys())


def test_calendar_features_migration_revision_metadata() -> None:
    assert calendar_migration.revision == "0007_calendar_features"
    assert calendar_migration.down_revision == "0006_historical_bar_revisions"
