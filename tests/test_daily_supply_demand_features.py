from __future__ import annotations

import os
import subprocess
import sys
from datetime import date, datetime, timezone
from decimal import Decimal
from importlib import import_module
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from app.config.settings import get_settings
from app.db.models import (
    Base,
    CollectorRun,
    DailyProductFeature,
    DailySupplyDemandFeature,
    Product,
    ProductSupplyDemandWeight,
    RawResponse,
    Source,
    SupplyDemandCommodity,
    SupplyDemandObservation,
)
from app.features.supply_demand_daily import (
    DEFAULT_SUPPLY_DEMAND_COUNTRY_WEIGHTS,
    REVIEWED_TIER_A_SUPPLY_DEMAND_COUNTRY_WEIGHTS,
    SUPPLY_DEMAND_GLOBAL_BASKET_POLICY_VERSION,
    SUPPLY_DEMAND_TIER_A_GLOBAL_BASKET_METRICS,
    SupplyDemandCountryWeight,
    build_supply_demand_daily_features,
)


product_supply_demand_migration = import_module("migrations.versions.0019_supply_demand_features")


def _session_factory(database_url: str = "sqlite+pysqlite:///:memory:"):
    engine = create_engine(database_url, future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def test_product_supply_demand_feature_columns_and_migration_metadata() -> None:
    table = Base.metadata.tables["daily_product_features"]
    expected_columns = {
        "production_volume",
        "domestic_consumption",
        "food_use",
        "feed_use",
        "crush_volume",
        "exports_volume",
        "imports_volume",
        "beginning_stocks",
        "ending_stocks",
        "stock_to_use_ratio",
        "planted_area",
        "harvested_area",
        "yield_value",
        "production_forecast_revision",
        "ending_stocks_revision",
        "stock_to_use_revision",
        "forecast_month",
        "marketing_year",
        "report_published_at",
        "supply_demand_as_of_date",
        "supply_demand_reporting_lag_days",
        "supply_demand_missing_flags",
    }
    migration_text = Path(product_supply_demand_migration.__file__).read_text(encoding="utf-8")

    assert expected_columns <= set(table.c.keys())
    assert product_supply_demand_migration.revision == "0019_supply_demand_features"
    assert product_supply_demand_migration.down_revision == "0018_supply_demand_schema"
    assert "op.add_column(\"daily_product_features\"" in migration_text
    assert "supply_demand_missing_flags" in migration_text


def test_supply_demand_daily_builder_creates_features_and_is_idempotent() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        context = _seed_base(session)
        _add_observation(
            session,
            context=context,
            metric_name="production_volume",
            value="1000",
            report_month=5,
            published_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
        )
        _add_observation(
            session,
            context=context,
            metric_name="production_volume",
            value="1100",
            report_month=6,
            published_at=datetime(2026, 6, 12, tzinfo=timezone.utc),
        )
        _add_observation(session, context=context, metric_name="domestic_consumption", value="500", report_month=6)
        _add_observation(session, context=context, metric_name="crush_volume", value="450", report_month=6)
        _add_observation(session, context=context, metric_name="exports_volume", value="120", report_month=6)
        _add_observation(session, context=context, metric_name="imports_volume", value="30", report_month=6)
        _add_observation(session, context=context, metric_name="beginning_stocks", value="80", report_month=6)
        _add_observation(session, context=context, metric_name="ending_stocks", value="100", report_month=6)
        _add_observation(session, context=context, metric_name="stock_to_use_ratio", value="0.20", report_month=6)
        _add_observation(session, context=context, metric_name="planted_area", value="200", report_month=6)
        _add_observation(session, context=context, metric_name="harvested_area", value="190", report_month=6)
        _add_observation(session, context=context, metric_name="yield", value="5.5", report_month=6)

        first = build_supply_demand_daily_features(
            product_code=context.product.code,
            from_date=date(2026, 6, 15),
            to_date=date(2026, 6, 15),
            session=session,
        )
        second = build_supply_demand_daily_features(
            product_code=context.product.code,
            from_date=date(2026, 6, 15),
            to_date=date(2026, 6, 15),
            session=session,
        )
        feature = session.scalar(select(DailySupplyDemandFeature).where(DailySupplyDemandFeature.product_id == context.product.id))
        rows_count = session.scalar(select(func.count()).select_from(DailySupplyDemandFeature))

    assert first.rows_created == 1
    assert second.rows_skipped == 1
    assert rows_count == 1
    assert feature.production_volume == Decimal("1100.00000000")
    assert feature.domestic_consumption == Decimal("500.00000000")
    assert feature.crush_volume == Decimal("450.00000000")
    assert feature.ending_stocks == Decimal("100.00000000")
    assert feature.stock_to_use_ratio == Decimal("0.20000000")
    assert feature.yield_value == Decimal("5.50000000")
    assert feature.production_forecast_revision == Decimal("100.00000000")
    assert feature.supply_demand_as_of_date == date(2026, 6, 12)
    assert feature.reporting_lag_days == 3
    assert feature.forecast_month == 6
    assert feature.marketing_year == "2025/26"
    assert feature.missing_flags == {"missing_forecast_revision": True}
    assert first.observations_used == 11


def test_supply_demand_daily_builder_excludes_future_published_observations() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        context = _seed_base(session)
        _add_observation(
            session,
            context=context,
            metric_name="production_volume",
            value="100",
            report_month=5,
            published_at=datetime(2026, 6, 10, tzinfo=timezone.utc),
        )
        _add_observation(
            session,
            context=context,
            metric_name="production_volume",
            value="999",
            report_month=6,
            published_at=datetime(2026, 6, 20, tzinfo=timezone.utc),
        )

        build_supply_demand_daily_features(
            product_code=context.product.code,
            from_date=date(2026, 6, 15),
            to_date=date(2026, 6, 15),
            session=session,
        )
        feature = session.scalar(select(DailySupplyDemandFeature).where(DailySupplyDemandFeature.product_id == context.product.id))

    assert feature.production_volume == Decimal("100.00000000")
    assert feature.supply_demand_as_of_date == date(2026, 6, 10)
    assert feature.reporting_lag_days == 5


def test_supply_demand_daily_builder_marks_observations_after_feature_date_window() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        context = _seed_base(session, metrics=("production_volume",))
        _add_observation(
            session,
            context=context,
            metric_name="production_volume",
            value="1000",
            report_month=5,
            published_at=datetime(2026, 6, 16, tzinfo=timezone.utc),
            country_code="US",
            country_name="United States",
        )

        result = build_supply_demand_daily_features(
            product_code=context.product.code,
            from_date=date(2026, 6, 15),
            to_date=date(2026, 6, 15),
            session=session,
        )
        feature = session.scalar(select(DailySupplyDemandFeature).where(DailySupplyDemandFeature.product_id == context.product.id))

    assert result.observations_used == 0
    assert feature.production_volume is None
    assert feature.supply_demand_as_of_date is None
    assert feature.missing_flags["supply_demand_observations_after_feature_date_window"] is True
    assert "no_supply_demand_observations" not in feature.missing_flags
    assert feature.metadata_json["future_supply_demand_as_of_dates"] == ["2026-06-16"]


def test_supply_demand_daily_builder_uses_observation_on_same_as_of_date() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        context = _seed_base(session, metrics=("production_volume",))
        _add_observation(
            session,
            context=context,
            metric_name="production_volume",
            value="1000",
            report_month=5,
            published_at=datetime(2026, 6, 16, tzinfo=timezone.utc),
        )

        result = build_supply_demand_daily_features(
            product_code=context.product.code,
            from_date=date(2026, 6, 16),
            to_date=date(2026, 6, 16),
            session=session,
        )
        feature = session.scalar(select(DailySupplyDemandFeature).where(DailySupplyDemandFeature.product_id == context.product.id))

    assert result.observations_used == 1
    assert feature.production_volume == Decimal("1000.00000000")
    assert feature.supply_demand_as_of_date == date(2026, 6, 16)
    assert feature.reporting_lag_days == 0


def test_supply_demand_daily_builder_forwards_observation_after_as_of_date() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        context = _seed_base(session, metrics=("production_volume",))
        _add_observation(
            session,
            context=context,
            metric_name="production_volume",
            value="1000",
            report_month=5,
            published_at=datetime(2026, 6, 16, tzinfo=timezone.utc),
        )

        result = build_supply_demand_daily_features(
            product_code=context.product.code,
            from_date=date(2026, 6, 17),
            to_date=date(2026, 6, 17),
            session=session,
        )
        feature = session.scalar(select(DailySupplyDemandFeature).where(DailySupplyDemandFeature.product_id == context.product.id))

    assert result.observations_used == 1
    assert feature.production_volume == Decimal("1000.00000000")
    assert feature.supply_demand_as_of_date == date(2026, 6, 16)
    assert feature.reporting_lag_days == 1


def test_supply_demand_daily_builder_preserves_explicit_legacy_country_fallback() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        context = _seed_base(session, metrics=("production_volume",))
        _add_observation(
            session,
            context=context,
            metric_name="production_volume",
            value="1000",
            report_month=5,
            published_at=datetime(2026, 6, 16, tzinfo=timezone.utc),
            country_code="US",
            country_name="United States",
        )

        result = build_supply_demand_daily_features(
            product_code=context.product.code,
            from_date=date(2026, 6, 16),
            to_date=date(2026, 6, 16),
            session=session,
            country_weights={},
        )
        feature = session.scalar(select(DailySupplyDemandFeature).where(DailySupplyDemandFeature.product_id == context.product.id))

    assert result.observations_used == 1
    assert feature.production_volume == Decimal("1000.00000000")
    assert feature.metadata_json["selected_country_policy"] == "prefer_WLD_else_weighted_latest_known_rows"


def test_supply_demand_daily_builder_prefers_world_row_over_country_basket() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        context = _seed_base(session, metrics=("production_volume",))
        _add_observation(
            session,
            context=context,
            metric_name="production_volume",
            value="1000",
            report_month=5,
            country_code="WLD",
            country_name="World",
        )
        _add_observation(
            session,
            context=context,
            metric_name="production_volume",
            value="2000",
            report_month=5,
            country_code="US",
            country_name="United States",
        )

        result = build_supply_demand_daily_features(
            product_code=context.product.code,
            from_date=date(2026, 6, 15),
            to_date=date(2026, 6, 15),
            session=session,
            country_weights=_country_basket(context.product.code, "soybean", {"US": "0.60", "BR": "0.40"}),
        )
        feature = session.scalar(select(DailySupplyDemandFeature).where(DailySupplyDemandFeature.product_id == context.product.id))

    assert result.observations_used == 1
    assert feature.production_volume == Decimal("1000.00000000")
    provenance = feature.metadata_json["country_aggregation"]["production_volume"]["components"][0]
    assert provenance["mode"] == "WLD"
    assert provenance["selected_countries"] == ["WLD"]


def test_supply_demand_daily_builder_aggregates_configured_country_basket() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        context = _seed_base(
            session,
            metrics=("production_volume", "domestic_consumption", "ending_stocks", "stock_to_use_ratio"),
        )
        for country_code, country_name, production, domestic, ending in (
            ("US", "United States", "100", "50", "10"),
            ("BR", "Brazil", "200", "50", "20"),
            ("AR", "Argentina", "300", "100", "30"),
        ):
            _add_observation(
                session,
                context=context,
                metric_name="production_volume",
                value=production,
                report_month=5,
                country_code=country_code,
                country_name=country_name,
            )
            _add_observation(
                session,
                context=context,
                metric_name="domestic_consumption",
                value=domestic,
                report_month=5,
                country_code=country_code,
                country_name=country_name,
            )
            _add_observation(
                session,
                context=context,
                metric_name="ending_stocks",
                value=ending,
                report_month=5,
                country_code=country_code,
                country_name=country_name,
            )
            _add_observation(
                session,
                context=context,
                metric_name="stock_to_use_ratio",
                value="9.99",
                report_month=5,
                country_code=country_code,
                country_name=country_name,
            )

        result = build_supply_demand_daily_features(
            product_code=context.product.code,
            from_date=date(2026, 6, 15),
            to_date=date(2026, 6, 15),
            session=session,
            country_weights=_country_basket(context.product.code, "soybean", {"US": "0.50", "BR": "0.30", "AR": "0.20"}),
        )
        feature = session.scalar(select(DailySupplyDemandFeature).where(DailySupplyDemandFeature.product_id == context.product.id))

    assert result.observations_used == 9
    assert feature.production_volume == Decimal("170.00000000")
    assert feature.domestic_consumption == Decimal("60.00000000")
    assert feature.ending_stocks == Decimal("17.00000000")
    assert feature.stock_to_use_ratio == Decimal("0.28333333")
    assert feature.metadata_json["selected_country_policy"] == "prefer_WLD_else_configured_country_basket_else_latest_known_country"
    provenance = feature.metadata_json["country_aggregation"]["production_volume"]["components"][0]
    assert provenance["mode"] == "configured_country_weighted_basket"
    assert provenance["selected_countries"] == ["US", "BR", "AR"]
    assert provenance["renormalized"] is False


def test_supply_demand_daily_builder_renormalizes_missing_country_and_blocks_future_rows() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        context = _seed_base(session, metrics=("production_volume",))
        _add_observation(
            session,
            context=context,
            metric_name="production_volume",
            value="100",
            report_month=5,
            published_at=datetime(2026, 6, 15, tzinfo=timezone.utc),
            country_code="US",
            country_name="United States",
        )
        _add_observation(
            session,
            context=context,
            metric_name="production_volume",
            value="200",
            report_month=5,
            published_at=datetime(2026, 6, 16, tzinfo=timezone.utc),
            country_code="BR",
            country_name="Brazil",
        )
        _add_observation(
            session,
            context=context,
            metric_name="production_volume",
            value="10000",
            report_month=5,
            published_at=datetime(2026, 6, 20, tzinfo=timezone.utc),
            country_code="AR",
            country_name="Argentina",
        )

        result = build_supply_demand_daily_features(
            product_code=context.product.code,
            from_date=date(2026, 6, 16),
            to_date=date(2026, 6, 16),
            session=session,
            country_weights=_country_basket(context.product.code, "soybean", {"US": "0.50", "BR": "0.30", "AR": "0.20"}),
        )
        feature = session.scalar(select(DailySupplyDemandFeature).where(DailySupplyDemandFeature.product_id == context.product.id))

    assert result.observations_used == 2
    assert feature.production_volume == Decimal("137.50000000")
    assert feature.supply_demand_as_of_date == date(2026, 6, 16)
    assert feature.reporting_lag_days == 0
    assert feature.missing_flags["partial_country_basket"] is True
    provenance = feature.metadata_json["country_aggregation"]["production_volume"]["components"][0]
    assert provenance["selected_countries"] == ["US", "BR"]
    assert provenance["missing_configured_countries"] == ["AR"]
    assert provenance["renormalized"] is True
    assert "10000.00000000" not in {str(feature.production_volume)}


def test_supply_demand_reviewed_tier_a_config_uses_exact_metric_specific_weights() -> None:
    weights = REVIEWED_TIER_A_SUPPLY_DEMAND_COUNTRY_WEIGHTS[("soybean_oil", "soybean")]
    by_metric: dict[str, list[SupplyDemandCountryWeight]] = {}
    for item in weights:
        by_metric.setdefault(item.metric_code or "", []).append(item)

    assert set(by_metric) == SUPPLY_DEMAND_TIER_A_GLOBAL_BASKET_METRICS
    assert [item.country_code for item in by_metric["production_volume"]] == ["CH", "US", "BR", "AR"]
    assert [item.weight for item in by_metric["production_volume"]] == [
        Decimal("0.30156174"),
        Decimal("0.20443230"),
        Decimal("0.18026335"),
        Decimal("0.11854805"),
    ]
    assert [item.country_code for item in by_metric["crush_volume"]] == ["CH", "US", "BR", "AR", "IN"]
    assert [item.country_code for item in by_metric["domestic_consumption"]] == ["CH", "US", "BR", "IN", "AR", "MX"]
    assert [item.country_code for item in by_metric["exports_volume"]] == ["AR", "BR", "RS", "BL", "PA", "US"]
    assert all(item.policy_version == SUPPLY_DEMAND_GLOBAL_BASKET_POLICY_VERSION for item in weights)
    assert all(item.minimum_available_weight == Decimal("0.75") for item in weights)
    assert all(item.country_code != "CA" for item in weights)
    assert DEFAULT_SUPPLY_DEMAND_COUNTRY_WEIGHTS is REVIEWED_TIER_A_SUPPLY_DEMAND_COUNTRY_WEIGHTS


def test_supply_demand_reviewed_tier_a_wld_overrides_basket() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        context = _seed_base(session, metrics=("production_volume",))
        _add_observation(
            session,
            context=context,
            metric_name="production_volume",
            value="1000",
            report_month=5,
            country_code="WLD",
            country_name="World",
        )
        _add_observation(
            session,
            context=context,
            metric_name="production_volume",
            value="9999",
            report_month=5,
            country_code="CH",
            country_name="China",
        )

        build_supply_demand_daily_features(
            product_code=context.product.code,
            from_date=date(2026, 6, 15),
            to_date=date(2026, 6, 15),
            session=session,
        )
        feature = session.scalar(select(DailySupplyDemandFeature).where(DailySupplyDemandFeature.product_id == context.product.id))

    provenance = feature.metadata_json["country_aggregation"]["production_volume"]["components"][0]
    assert feature.production_volume == Decimal("1000.00000000")
    assert provenance["mode"] == "WLD"
    assert provenance["policy_decision"] == "supply_demand_real_wld"


def test_supply_demand_default_path_uses_all_reviewed_tier_a_metric_baskets() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        context = _seed_base(
            session,
            metrics=("production_volume", "crush_volume", "domestic_consumption", "exports_volume"),
        )
        _add_country_metric_rows(
            session,
            context=context,
            metric_name="production_volume",
            values={"CH": "100", "US": "200", "BR": "300", "AR": "400", "MX": "9999"},
        )
        _add_country_metric_rows(
            session,
            context=context,
            metric_name="crush_volume",
            values={"CH": "10", "US": "20", "BR": "30", "AR": "40", "IN": "50"},
        )
        _add_country_metric_rows(
            session,
            context=context,
            metric_name="domestic_consumption",
            values={"CH": "500", "US": "400", "BR": "300", "IN": "200", "AR": "100", "MX": "50"},
        )
        _add_country_metric_rows(
            session,
            context=context,
            metric_name="exports_volume",
            values={"AR": "60", "BR": "50", "RS": "40", "BL": "30", "PA": "20", "US": "10"},
        )

        result = build_supply_demand_daily_features(
            product_code=context.product.code,
            from_date=date(2026, 6, 15),
            to_date=date(2026, 6, 15),
            session=session,
        )
        feature = session.scalar(select(DailySupplyDemandFeature).where(DailySupplyDemandFeature.product_id == context.product.id))

    production_weights = _reviewed_metric_weights("production_volume")
    expected_production = _weighted_average({"CH": "100", "US": "200", "BR": "300", "AR": "400"}, production_weights)
    assert result.observations_used == 21
    assert feature.production_volume == expected_production
    assert feature.crush_volume is not None
    assert feature.domestic_consumption is not None
    assert feature.exports_volume is not None
    provenance = {
        metric: feature.metadata_json["country_aggregation"][metric]["components"][0]
        for metric in SUPPLY_DEMAND_TIER_A_GLOBAL_BASKET_METRICS
    }
    assert all(item["policy_decision"] == "supply_demand_global_basket_v1" for item in provenance.values())
    assert provenance["production_volume"]["selected_countries"] == ["CH", "US", "BR", "AR"]
    assert provenance["crush_volume"]["selected_countries"] == ["CH", "US", "BR", "AR", "IN"]
    assert provenance["domestic_consumption"]["selected_countries"] == ["CH", "US", "BR", "IN", "AR", "MX"]
    assert provenance["exports_volume"]["selected_countries"] == ["AR", "BR", "RS", "BL", "PA", "US"]
    assert "MX" not in provenance["production_volume"]["selected_countries"]
    assert provenance["production_volume"]["minimum_available_weight"] == "0.75"


def test_supply_demand_reviewed_tier_a_partial_basket_renormalizes_above_threshold_without_future_leakage() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        context = _seed_base(session, metrics=("production_volume",))
        _add_observation(
            session,
            context=context,
            metric_name="production_volume",
            value="100",
            report_month=5,
            published_at=datetime(2026, 6, 15, tzinfo=timezone.utc),
            country_code="CH",
            country_name="CH",
        )
        _add_observation(
            session,
            context=context,
            metric_name="production_volume",
            value="200",
            report_month=5,
            published_at=datetime(2026, 6, 16, tzinfo=timezone.utc),
            country_code="US",
            country_name="US",
        )
        _add_observation(
            session,
            context=context,
            metric_name="production_volume",
            value="300",
            report_month=5,
            published_at=datetime(2026, 6, 16, tzinfo=timezone.utc),
            country_code="BR",
            country_name="BR",
        )
        _add_observation(
            session,
            context=context,
            metric_name="production_volume",
            value="10000",
            report_month=5,
            published_at=datetime(2026, 6, 20, tzinfo=timezone.utc),
            country_code="AR",
            country_name="AR",
        )

        build_supply_demand_daily_features(
            product_code=context.product.code,
            from_date=date(2026, 6, 16),
            to_date=date(2026, 6, 16),
            session=session,
        )
        feature = session.scalar(select(DailySupplyDemandFeature).where(DailySupplyDemandFeature.product_id == context.product.id))

    weights = _reviewed_metric_weights("production_volume")
    expected = _weighted_average({"CH": "100", "US": "200", "BR": "300"}, weights)
    provenance = feature.metadata_json["country_aggregation"]["production_volume"]["components"][0]
    assert feature.production_volume == expected
    assert feature.supply_demand_as_of_date == date(2026, 6, 16)
    assert feature.missing_flags["supply_demand_global_basket_partial_weight"] is True
    assert provenance["policy_decision"] == "supply_demand_global_basket_partial_weight"
    assert provenance["missing_configured_countries"] == ["AR"]
    assert "10000.00000000" not in {str(feature.production_volume)}


def test_supply_demand_reviewed_tier_a_insufficient_weight_leaves_metric_missing_without_latest_fallback() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        context = _seed_base(session, metrics=("production_volume",))
        _add_observation(
            session,
            context=context,
            metric_name="production_volume",
            value="100",
            report_month=5,
            country_code="CH",
            country_name="CH",
        )
        _add_observation(
            session,
            context=context,
            metric_name="production_volume",
            value="9999",
            report_month=6,
            country_code="MX",
            country_name="Mexico",
        )

        build_supply_demand_daily_features(
            product_code=context.product.code,
            from_date=date(2026, 6, 15),
            to_date=date(2026, 6, 15),
            session=session,
        )
        feature = session.scalar(select(DailySupplyDemandFeature).where(DailySupplyDemandFeature.product_id == context.product.id))

    provenance = feature.metadata_json["country_aggregation"]["production_volume"]["components"][0]
    assert feature.production_volume is None
    assert feature.missing_flags["supply_demand_global_basket_insufficient_weight"] is True
    assert provenance["policy_decision"] == "supply_demand_global_basket_insufficient_weight"
    assert provenance["selected_countries"] == ["CH"]
    assert provenance["available_approved_basket_weight"] < "0.75"


def test_supply_demand_reviewed_tier_a_keeps_tier_b_c_metrics_deferred() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        context = _seed_base(session, metrics=("imports_volume", "stock_to_use_ratio"))
        _add_observation(
            session,
            context=context,
            metric_name="imports_volume",
            value="111",
            report_month=5,
            country_code="US",
            country_name="United States",
        )
        _add_observation(
            session,
            context=context,
            metric_name="stock_to_use_ratio",
            value="9.99",
            report_month=5,
            country_code="US",
            country_name="United States",
        )

        build_supply_demand_daily_features(
            product_code=context.product.code,
            from_date=date(2026, 6, 15),
            to_date=date(2026, 6, 15),
            session=session,
        )
        feature = session.scalar(select(DailySupplyDemandFeature).where(DailySupplyDemandFeature.product_id == context.product.id))

    configured_metrics = {item.metric_code for item in REVIEWED_TIER_A_SUPPLY_DEMAND_COUNTRY_WEIGHTS[("soybean_oil", "soybean")]}
    assert configured_metrics == SUPPLY_DEMAND_TIER_A_GLOBAL_BASKET_METRICS
    assert "imports_volume" not in configured_metrics
    assert "stock_to_use_ratio" not in configured_metrics
    assert feature.imports_volume == Decimal("111.00000000")
    assert feature.stock_to_use_ratio is None
    imports_provenance = feature.metadata_json["country_aggregation"]["imports_volume"]["components"][0]
    assert imports_provenance["policy_decision"] == "supply_demand_latest_country_fallback"


def test_supply_demand_daily_default_bounds_extend_to_latest_observation_as_of_date() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        context = _seed_base(session, metrics=("production_volume",))
        session.add(
            DailyProductFeature(
                product_id=context.product.id,
                feature_date=date(2026, 6, 15),
                as_of_at=datetime(2026, 6, 15, 15, tzinfo=timezone.utc),
                features_json={"test": True},
                feature_version="test",
            )
        )
        _add_observation(
            session,
            context=context,
            metric_name="production_volume",
            value="1000",
            report_month=5,
            published_at=datetime(2026, 6, 16, tzinfo=timezone.utc),
            country_code="US",
            country_name="United States",
        )

        result = build_supply_demand_daily_features(
            product_code=context.product.code,
            session=session,
            country_weights={},
        )
        features = session.scalars(
            select(DailySupplyDemandFeature).where(DailySupplyDemandFeature.product_id == context.product.id).order_by(DailySupplyDemandFeature.feature_date)
        ).all()

    assert result.dates_processed == 2
    assert result.observations_used == 1
    assert [feature.feature_date for feature in features] == [date(2026, 6, 15), date(2026, 6, 16)]
    assert features[0].production_volume is None
    assert features[0].missing_flags["supply_demand_observations_after_feature_date_window"] is True
    assert features[1].production_volume == Decimal("1000.00000000")
    assert features[1].supply_demand_as_of_date == date(2026, 6, 16)


def test_supply_demand_daily_builder_derives_stock_to_use_when_source_ratio_missing() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        context = _seed_base(session, metrics=("domestic_consumption", "ending_stocks"))
        _add_observation(session, context=context, metric_name="domestic_consumption", value="500", report_month=6)
        _add_observation(session, context=context, metric_name="ending_stocks", value="125", report_month=6)

        build_supply_demand_daily_features(
            product_code=context.product.code,
            from_date=date(2026, 6, 15),
            to_date=date(2026, 6, 15),
            session=session,
        )
        feature = session.scalar(select(DailySupplyDemandFeature).where(DailySupplyDemandFeature.product_id == context.product.id))

    assert feature.stock_to_use_ratio == Decimal("0.25000000")
    assert "missing_stock_to_use_ratio" not in feature.missing_flags


def test_supply_demand_daily_builder_records_missing_flags_without_observations_or_weights() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        product = Product(code="rapeseed_oil", name="Rapeseed oil", category="oil", unit="metric_ton", currency_default="USD")
        session.add(product)
        session.flush()

        result = build_supply_demand_daily_features(
            product_code=product.code,
            from_date=date(2026, 6, 15),
            to_date=date(2026, 6, 15),
            session=session,
        )
        feature = session.scalar(select(DailySupplyDemandFeature).where(DailySupplyDemandFeature.product_id == product.id))

    assert result.rows_created == 1
    assert result.warnings_count == 1
    assert result.missing_products == ["rapeseed_oil"]
    assert feature.supply_demand_as_of_date is None
    assert feature.missing_flags == {"no_product_supply_demand_weights": True}


def test_supply_demand_daily_builder_respects_active_weight_dates() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        context = _seed_base(session)
        for weight in session.scalars(select(ProductSupplyDemandWeight)).all():
            weight.effective_to = date(2026, 6, 1)
        _add_observation(session, context=context, metric_name="production_volume", value="1000", report_month=6)

        build_supply_demand_daily_features(
            product_code=context.product.code,
            from_date=date(2026, 6, 15),
            to_date=date(2026, 6, 15),
            session=session,
        )
        feature = session.scalar(select(DailySupplyDemandFeature).where(DailySupplyDemandFeature.product_id == context.product.id))

    assert feature.production_volume is None
    assert feature.missing_flags == {"no_product_supply_demand_weights": True}


def test_supply_demand_daily_cli(tmp_path: Path) -> None:
    db_path = tmp_path / "features.db"
    database_url = f"sqlite+pysqlite:///{db_path}"
    SessionLocal = _session_factory(database_url)
    with SessionLocal() as session:
        context = _seed_base(session, metrics=("production_volume",))
        _add_country_metric_rows(
            session,
            context=context,
            metric_name="production_volume",
            values={"CH": "100", "US": "200", "BR": "300", "AR": "400"},
        )
        product_id = context.product.id
        session.commit()

    env = {**os.environ, "DATABASE_URL": database_url, "LOG_DIR": str(tmp_path / "logs")}
    get_settings.cache_clear()
    result = subprocess.run(
        [
            sys.executable,
            "scripts/build_features.py",
            "supply_demand_daily",
            "--product",
            "soybean_oil",
            "--from-date",
            "2026-06-15",
            "--to-date",
            "2026-06-15",
        ],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    get_settings.cache_clear()

    with SessionLocal() as session:
        feature = session.scalar(select(DailySupplyDemandFeature).where(DailySupplyDemandFeature.product_id == product_id))
        provenance = feature.metadata_json["country_aggregation"]["production_volume"]["components"][0]

    assert "products_processed=1" in result.stdout
    assert "rows_created=1" in result.stdout
    assert "observations_used=4" in result.stdout
    assert provenance["policy_decision"] == "supply_demand_global_basket_v1"
    assert provenance["selected_countries"] == ["CH", "US", "BR", "AR"]
    assert provenance["policy_decision"] != "supply_demand_latest_country_fallback"


class _Context:
    def __init__(self, product: Product, source: Source, run: CollectorRun, raw: RawResponse, commodities: dict[str, SupplyDemandCommodity]):
        self.product = product
        self.source = source
        self.run = run
        self.raw = raw
        self.commodities = commodities


def _seed_base(
    session,
    *,
    metrics: tuple[str, ...] = (
        "production_volume",
        "domestic_consumption",
        "crush_volume",
        "exports_volume",
        "imports_volume",
        "beginning_stocks",
        "ending_stocks",
        "stock_to_use_ratio",
        "planted_area",
        "harvested_area",
        "yield",
    ),
) -> _Context:
    product = Product(code="soybean_oil", name="Soybean oil", category="oil", unit="metric_ton", currency_default="USD")
    source = Source(code="usda_psd", name="USDA PSD", source_type="supply_demand", base_url="https://apps.fas.usda.gov/")
    session.add_all([product, source])
    session.flush()
    run = CollectorRun(
        source_id=source.id,
        collector_name="usda_psd",
        started_at=datetime(2026, 6, 14, tzinfo=timezone.utc),
        status="success",
        run_type="manual",
    )
    session.add(run)
    session.flush()
    raw = RawResponse(
        source_id=source.id,
        collector_run_id=run.id,
        fetched_at=datetime(2026, 6, 14, tzinfo=timezone.utc),
        url="https://apps.fas.usda.gov/psdonline/test",
        method="GET",
        status_code=200,
        content_type="application/json",
        storage_path="data/raw/usda_psd/2026/06/14/1/hash.json",
        sha256="a" * 64,
        bytes_size=2000,
        parser_version="usda_psd_v1",
    )
    session.add(raw)
    session.flush()
    commodities: dict[str, SupplyDemandCommodity] = {}
    for metric_name in metrics:
        commodity = SupplyDemandCommodity(
            source_id=source.id,
            source_commodity_code="psd_needs_verification_soybean_oil",
            source_commodity_name="Soybean oil",
            source_metric_code=f"psd_needs_verification_{metric_name}",
            source_metric_name=metric_name.replace("_", " ").title(),
            commodity_family="soybean",
            product_code="soybean_oil",
            metric_name=metric_name,
            metric_group="area_yield" if metric_name in {"planted_area", "harvested_area", "yield"} else "production",
            unit_hint="metric_ton",
            frequency="monthly_report",
            relevance="direct",
            is_active=True,
            metadata_json={"test": True},
        )
        session.add(commodity)
        session.flush()
        session.add(
            ProductSupplyDemandWeight(
                product_id=product.id,
                supply_demand_commodity_id=commodity.id,
                weight=Decimal("1.00000000"),
                relevance="direct",
                role="direct_supply_demand_proxy",
                effective_from=date(2020, 1, 1),
                effective_to=None,
                is_active=True,
                metadata_json={"test": True},
            )
        )
        commodities[metric_name] = commodity
    session.flush()
    return _Context(product, source, run, raw, commodities)


def _country_basket(
    product_code: str,
    commodity_family: str,
    weights: dict[str, str],
) -> dict[tuple[str, str], tuple[SupplyDemandCountryWeight, ...]]:
    return {
        (product_code, commodity_family): tuple(
            SupplyDemandCountryWeight(
                product_code=product_code,
                commodity_family=commodity_family,
                country_code=country_code,
                weight=Decimal(weight),
            )
            for country_code, weight in weights.items()
        )
    }


def _reviewed_metric_weights(metric_code: str) -> dict[str, Decimal]:
    return {
        item.country_code: item.weight
        for item in REVIEWED_TIER_A_SUPPLY_DEMAND_COUNTRY_WEIGHTS[("soybean_oil", "soybean")]
        if item.metric_code == metric_code
    }


def _weighted_average(values: dict[str, str], weights: dict[str, Decimal]) -> Decimal:
    selected = {country_code: Decimal(value) for country_code, value in values.items() if country_code in weights}
    denominator = sum((weights[country_code] for country_code in selected), Decimal("0"))
    numerator = sum((selected[country_code] * weights[country_code] for country_code in selected), Decimal("0"))
    return (numerator / denominator).quantize(Decimal("0.00000001"))


def _add_country_metric_rows(
    session,
    *,
    context: _Context,
    metric_name: str,
    values: dict[str, str],
) -> None:
    for country_code, value in values.items():
        _add_observation(
            session,
            context=context,
            metric_name=metric_name,
            value=value,
            report_month=5,
            country_code=country_code,
            country_name=country_code,
        )


def _add_observation(
    session,
    *,
    context: _Context,
    metric_name: str,
    value: str,
    report_month: int,
    published_at: datetime | None = datetime(2026, 6, 12, tzinfo=timezone.utc),
    country_code: str = "WLD",
    country_name: str = "World",
) -> None:
    commodity = context.commodities[metric_name]
    session.add(
        SupplyDemandObservation(
            source_id=context.source.id,
            raw_response_id=context.raw.id,
            collector_run_id=context.run.id,
            supply_demand_commodity_id=commodity.id,
            source_record_id=f"{metric_name}-{report_month}-{value}",
            country_code=country_code,
            country_name=country_name,
            region_code=None,
            region_name=None,
            marketing_year="2025/26",
            marketing_year_start=date(2025, 10, 1),
            marketing_year_end=date(2026, 9, 30),
            report_month=report_month,
            report_year=2026,
            report_published_at=published_at,
            observed_period_start=date(2025, 10, 1),
            observed_period_end=date(2026, 9, 30),
            frequency="monthly_report",
            estimate_type="forecast",
            metric_value=Decimal(value),
            metric_unit="metric_ton",
            value_usd=None,
            is_forecast=True,
            is_revision=False,
            published_at=published_at,
            fetched_at=datetime(2026, 6, 14, tzinfo=timezone.utc),
            source_record_hash=(f"{metric_name}{report_month}{value}" + "a" * 64)[:64],
            source_payload_hash="a" * 64,
            metadata_json={"test": True},
        )
    )
    session.flush()
