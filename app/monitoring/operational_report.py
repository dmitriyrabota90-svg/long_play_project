from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.collectors.prices.current_price_config import CURRENT_PRICE_INSTRUMENTS
from app.config.settings import get_settings
from app.db.models import (
    CollectorRun,
    CommodityBenchmark,
    CommodityEvent,
    DailyProductFeature,
    DailyNewsFeature,
    DailySupplyDemandFeature,
    DailyTradeFeature,
    DataQualityCheck,
    EnergyPrice,
    FxRate,
    HistoricalPriceBar,
    HistoricalPriceBarRevision,
    NewsArticle,
    PriceObservation,
    ProductWeatherRegionWeight,
    Product,
    ProductSupplyDemandWeight,
    ProductTradeCodeWeight,
    RawResponse,
    Source,
    SupplyDemandCommodity,
    SupplyDemandObservation,
    SupplyDemandRevision,
    TradeCommodityCode,
    TradeFlow,
    WeatherDailyFeature,
    WeatherObservation,
    WeatherRegion,
)
from app.db.session import session_scope
from app.monitoring.quality_summary import build_quality_summary, problematic_quality_filter
from app.monitoring.redaction import mask_database_url
from app.operations.storage import directory_size_bytes


def build_operational_report(*, freshness_hours: int = 24, session: Session | None = None) -> dict[str, Any]:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    freshness_cutoff = now - timedelta(hours=freshness_hours)
    report: dict[str, Any] = {
        "status": "ok",
        "checked_at": now.isoformat(),
        "app_version": settings.app_version,
        "database": {
            "ok": False,
            "database_url": mask_database_url(settings.database_url),
        },
        "paths": {
            "raw_data_dir": str(settings.raw_data_dir),
            "export_data_dir": str(settings.export_data_dir),
            "log_dir": str(settings.log_dir),
        },
        "sizes": {
            "raw_bytes": directory_size_bytes(settings.raw_data_dir),
            "exports_bytes": directory_size_bytes(settings.export_data_dir),
            "logs_bytes": directory_size_bytes(settings.log_dir),
        },
        "last_24h": {
            "collector_runs": 0,
            "raw_responses": 0,
            "price_observations": 0,
            "fx_rates": 0,
            "daily_product_features": 0,
            "energy_prices": 0,
            "problematic_quality_checks": 0,
        },
        "last_runs": {
            "success": None,
            "partial_success": None,
            "error": None,
        },
        "cbr_fx": {
            "last_successful_run": None,
            "fx_rates_last_24h": 0,
        },
        "daily_product_features": {
            "count": 0,
            "last_date": None,
            "last_24h": 0,
            "missing_recent_features": [],
            "energy_coverage": {
                "rows_with_brent": 0,
                "rows_with_wti": 0,
                "rows_with_henry_hub": 0,
                "rows_with_diesel": 0,
                "latest_energy_feature_date": None,
            },
            "benchmark_coverage": {
                "rows_with_soybean_oil_benchmark": 0,
                "rows_with_soybeans_benchmark": 0,
                "rows_with_palm_oil_benchmark": 0,
                "rows_with_maize_benchmark": 0,
                "rows_with_wheat_benchmark": 0,
                "rows_with_fertilizer_benchmark": 0,
                "latest_benchmark_feature_date": None,
            },
            "weather_coverage": {
                "rows_with_weather_temperature_30d": 0,
                "rows_with_weather_precipitation_30d": 0,
                "rows_with_weather_gdd_30d": 0,
                "latest_product_weather_feature_date": None,
            },
            "news_coverage": {
                "rows_with_news_count_7d": 0,
                "rows_with_event_count_7d": 0,
                "rows_with_news_as_of_date": 0,
                "latest_product_news_feature_date": None,
            },
            "trade_coverage": {
                "rows_with_export_volume_1m": 0,
                "rows_with_import_volume_1m": 0,
                "rows_with_trade_as_of_date": 0,
                "latest_product_trade_feature_date": None,
            },
            "supply_demand_coverage": {
                "rows_total": 0,
                "rows_with_production_volume": 0,
                "rows_with_ending_stocks": 0,
                "rows_with_stock_to_use_ratio": 0,
                "rows_with_supply_demand_as_of_date": 0,
                "rows_with_supply_demand_missing_flags": 0,
                "latest_product_supply_demand_feature_date": None,
            },
        },
        "historical_price_bars": {
            "count": 0,
            "last_date": None,
            "last_bar_date": None,
            "last_created_at": None,
            "last_successful_run": None,
            "last_partial_run": None,
        },
        "historical_price_bar_revisions": {
            "count": 0,
            "last_created_at": None,
        },
        "energy_prices": {
            "count": 0,
            "instruments_count": 0,
            "first_period_start": None,
            "last_period_start": None,
            "last_observed_at": None,
            "last_fetched_at": None,
        },
        "commodity_benchmarks": {
            "count": 0,
            "benchmarks_count": 0,
            "first_period_start": None,
            "last_period_start": None,
            "last_observed_at": None,
            "last_fetched_at": None,
        },
        "weather_regions": {
            "count": 0,
            "active_count": 0,
            "high_priority_count": 0,
            "countries_count": 0,
            "commodity_families_count": 0,
        },
        "weather_observations": {
            "count": 0,
            "regions_count": 0,
            "first_observation_date": None,
            "last_observation_date": None,
            "last_fetched_at": None,
        },
        "weather_daily_features": {
            "count": 0,
            "regions_count": 0,
            "first_feature_date": None,
            "last_feature_date": None,
            "latest_weather_as_of_date": None,
        },
        "product_weather_region_weights": {
            "count": 0,
            "active_count": 0,
            "products_count": 0,
            "regions_count": 0,
        },
        "news_articles": {
            "count": 0,
            "sources_count": 0,
            "first_published_at": None,
            "last_published_at": None,
            "last_fetched_at": None,
            "languages_count": 0,
        },
        "commodity_events": {
            "count": 0,
            "categories_count": 0,
            "commodity_families_count": 0,
            "first_event_date": None,
            "last_event_date": None,
            "latest_published_at": None,
        },
        "daily_news_features": {
            "count": 0,
            "products_count": 0,
            "first_feature_date": None,
            "last_feature_date": None,
            "latest_news_as_of_date": None,
        },
        "trade_commodity_codes": {
            "count": 0,
            "active_count": 0,
            "code_systems_count": 0,
            "direct_mappings_count": 0,
            "context_mappings_count": 0,
        },
        "trade_flows": {
            "count": 0,
            "commodities_count": 0,
            "reporters_count": 0,
            "partners_count": 0,
            "first_period_start": None,
            "last_period_start": None,
            "last_fetched_at": None,
        },
        "product_trade_code_weights": {
            "count": 0,
            "active_count": 0,
            "products_count": 0,
            "commodity_codes_count": 0,
        },
        "daily_trade_features": {
            "count": 0,
            "products_count": 0,
            "first_feature_date": None,
            "last_feature_date": None,
            "latest_trade_as_of_date": None,
        },
        "supply_demand_commodities": {
            "count": 0,
            "active_count": 0,
            "metrics_count": 0,
        },
        "supply_demand_observations": {
            "count": 0,
            "commodities_count": 0,
            "countries_count": 0,
            "last_fetched_at": None,
            "last_successful_run": None,
            "last_partial_run": None,
        },
        "supply_demand_revisions": {
            "count": 0,
        },
        "product_supply_demand_weights": {
            "count": 0,
        },
        "daily_supply_demand_features": {
            "count": 0,
            "products_count": 0,
            "first_feature_date": None,
            "last_feature_date": None,
            "latest_supply_demand_as_of_date": None,
        },
        "quality_checks": {
            "total_checks": 0,
            "pass_checks": 0,
            "skip_checks": 0,
            "problematic_checks": 0,
            "conclusion": "ok",
            "message": "quality checks ok",
        },
        "stale_products": [],
    }

    try:
        if session is not None:
            _fill_db_report(session, report, cutoff=cutoff, freshness_cutoff=freshness_cutoff)
        else:
            with session_scope() as scoped_session:
                _fill_db_report(scoped_session, report, cutoff=cutoff, freshness_cutoff=freshness_cutoff)
    except Exception as exc:
        report["database"] = {
            "ok": False,
            "database_url": mask_database_url(settings.database_url),
            "error": str(exc),
        }

    if not report["database"].get("ok") or report["stale_products"]:
        report["status"] = "degraded"
    return report


def _fill_db_report(
    session: Session,
    report: dict[str, Any],
    *,
    cutoff: datetime,
    freshness_cutoff: datetime,
) -> None:
    source = session.scalar(select(Source).where(Source.code == "current_price_source"))
    report["database"]["ok"] = True
    report["last_24h"]["collector_runs"] = session.scalar(
        select(func.count()).select_from(CollectorRun).where(CollectorRun.started_at >= cutoff)
    )
    report["last_24h"]["raw_responses"] = session.scalar(
        select(func.count()).select_from(RawResponse).where(RawResponse.fetched_at >= cutoff)
    )
    report["last_24h"]["price_observations"] = session.scalar(
        select(func.count()).select_from(PriceObservation).where(PriceObservation.created_at >= cutoff)
    )
    report["last_24h"]["fx_rates"] = session.scalar(
        select(func.count()).select_from(FxRate).where(FxRate.created_at >= cutoff)
    )
    report["last_24h"]["daily_product_features"] = session.scalar(
        select(func.count()).select_from(DailyProductFeature).where(DailyProductFeature.updated_at >= cutoff)
    )
    report["last_24h"]["energy_prices"] = session.scalar(
        select(func.count()).select_from(EnergyPrice).where(EnergyPrice.fetched_at >= cutoff)
    )
    report["daily_product_features"]["count"] = session.scalar(select(func.count()).select_from(DailyProductFeature))
    last_feature_date = session.scalar(select(func.max(DailyProductFeature.feature_date)))
    report["daily_product_features"]["last_date"] = last_feature_date.isoformat() if last_feature_date else None
    report["daily_product_features"]["last_24h"] = report["last_24h"]["daily_product_features"]
    report["daily_product_features"]["missing_recent_features"] = _missing_recent_features(session, cutoff=cutoff)
    latest_energy_feature_date = session.scalar(
        select(func.max(DailyProductFeature.feature_date)).where(
            or_(
                DailyProductFeature.energy_brent_usd_per_barrel.is_not(None),
                DailyProductFeature.energy_wti_usd_per_barrel.is_not(None),
                DailyProductFeature.energy_henry_hub_usd_mmbtu.is_not(None),
                DailyProductFeature.energy_diesel_proxy_value.is_not(None),
            )
        )
    )
    report["daily_product_features"]["energy_coverage"] = {
        "rows_with_brent": session.scalar(
            select(func.count()).select_from(DailyProductFeature).where(DailyProductFeature.energy_brent_usd_per_barrel.is_not(None))
        ),
        "rows_with_wti": session.scalar(
            select(func.count()).select_from(DailyProductFeature).where(DailyProductFeature.energy_wti_usd_per_barrel.is_not(None))
        ),
        "rows_with_henry_hub": session.scalar(
            select(func.count()).select_from(DailyProductFeature).where(DailyProductFeature.energy_henry_hub_usd_mmbtu.is_not(None))
        ),
        "rows_with_diesel": session.scalar(
            select(func.count()).select_from(DailyProductFeature).where(DailyProductFeature.energy_diesel_proxy_value.is_not(None))
        ),
        "latest_energy_feature_date": latest_energy_feature_date.isoformat() if latest_energy_feature_date else None,
    }
    latest_benchmark_feature_date = session.scalar(
        select(func.max(DailyProductFeature.feature_date)).where(
            or_(
                DailyProductFeature.benchmark_soybean_oil_value.is_not(None),
                DailyProductFeature.benchmark_soybeans_value.is_not(None),
                DailyProductFeature.benchmark_palm_oil_value.is_not(None),
                DailyProductFeature.benchmark_maize_value.is_not(None),
                DailyProductFeature.benchmark_wheat_value.is_not(None),
                DailyProductFeature.benchmark_fertilizer_index_value.is_not(None),
            )
        )
    )
    report["daily_product_features"]["benchmark_coverage"] = {
        "rows_with_soybean_oil_benchmark": session.scalar(
            select(func.count()).select_from(DailyProductFeature).where(DailyProductFeature.benchmark_soybean_oil_value.is_not(None))
        ),
        "rows_with_soybeans_benchmark": session.scalar(
            select(func.count()).select_from(DailyProductFeature).where(DailyProductFeature.benchmark_soybeans_value.is_not(None))
        ),
        "rows_with_palm_oil_benchmark": session.scalar(
            select(func.count()).select_from(DailyProductFeature).where(DailyProductFeature.benchmark_palm_oil_value.is_not(None))
        ),
        "rows_with_maize_benchmark": session.scalar(
            select(func.count()).select_from(DailyProductFeature).where(DailyProductFeature.benchmark_maize_value.is_not(None))
        ),
        "rows_with_wheat_benchmark": session.scalar(
            select(func.count()).select_from(DailyProductFeature).where(DailyProductFeature.benchmark_wheat_value.is_not(None))
        ),
        "rows_with_fertilizer_benchmark": session.scalar(
            select(func.count()).select_from(DailyProductFeature).where(DailyProductFeature.benchmark_fertilizer_index_value.is_not(None))
        ),
        "latest_benchmark_feature_date": latest_benchmark_feature_date.isoformat() if latest_benchmark_feature_date else None,
    }
    latest_product_weather_feature_date = session.scalar(
        select(func.max(DailyProductFeature.feature_date)).where(
            or_(
                DailyProductFeature.weather_temperature_30d_mean_weighted.is_not(None),
                DailyProductFeature.weather_precipitation_30d_sum_weighted.is_not(None),
                DailyProductFeature.weather_growing_degree_days_30d_weighted.is_not(None),
            )
        )
    )
    report["daily_product_features"]["weather_coverage"] = {
        "rows_with_weather_temperature_30d": session.scalar(
            select(func.count())
            .select_from(DailyProductFeature)
            .where(DailyProductFeature.weather_temperature_30d_mean_weighted.is_not(None))
        ),
        "rows_with_weather_precipitation_30d": session.scalar(
            select(func.count())
            .select_from(DailyProductFeature)
            .where(DailyProductFeature.weather_precipitation_30d_sum_weighted.is_not(None))
        ),
        "rows_with_weather_gdd_30d": session.scalar(
            select(func.count())
            .select_from(DailyProductFeature)
            .where(DailyProductFeature.weather_growing_degree_days_30d_weighted.is_not(None))
        ),
        "latest_product_weather_feature_date": (
            latest_product_weather_feature_date.isoformat() if latest_product_weather_feature_date else None
        ),
    }
    latest_product_news_feature_date = session.scalar(
        select(func.max(DailyProductFeature.feature_date)).where(
            or_(
                DailyProductFeature.news_count_7d.is_not(None),
                DailyProductFeature.event_count_7d.is_not(None),
                DailyProductFeature.news_as_of_date.is_not(None),
            )
        )
    )
    report["daily_product_features"]["news_coverage"] = {
        "rows_with_news_count_7d": session.scalar(
            select(func.count()).select_from(DailyProductFeature).where(DailyProductFeature.news_count_7d.is_not(None))
        ),
        "rows_with_event_count_7d": session.scalar(
            select(func.count()).select_from(DailyProductFeature).where(DailyProductFeature.event_count_7d.is_not(None))
        ),
        "rows_with_news_as_of_date": session.scalar(
            select(func.count()).select_from(DailyProductFeature).where(DailyProductFeature.news_as_of_date.is_not(None))
        ),
        "latest_product_news_feature_date": (
            latest_product_news_feature_date.isoformat() if latest_product_news_feature_date else None
        ),
    }
    latest_product_trade_feature_date = session.scalar(
        select(func.max(DailyProductFeature.feature_date)).where(
            or_(
                DailyProductFeature.export_volume_1m.is_not(None),
                DailyProductFeature.import_volume_1m.is_not(None),
                DailyProductFeature.trade_as_of_date.is_not(None),
            )
        )
    )
    report["daily_product_features"]["trade_coverage"] = {
        "rows_with_export_volume_1m": session.scalar(
            select(func.count()).select_from(DailyProductFeature).where(DailyProductFeature.export_volume_1m.is_not(None))
        ),
        "rows_with_import_volume_1m": session.scalar(
            select(func.count()).select_from(DailyProductFeature).where(DailyProductFeature.import_volume_1m.is_not(None))
        ),
        "rows_with_trade_as_of_date": session.scalar(
            select(func.count()).select_from(DailyProductFeature).where(DailyProductFeature.trade_as_of_date.is_not(None))
        ),
        "latest_product_trade_feature_date": (
            latest_product_trade_feature_date.isoformat() if latest_product_trade_feature_date else None
        ),
    }
    latest_product_supply_demand_feature_date = session.scalar(
        select(func.max(DailyProductFeature.feature_date)).where(
            or_(
                DailyProductFeature.production_volume.is_not(None),
                DailyProductFeature.ending_stocks.is_not(None),
                DailyProductFeature.stock_to_use_ratio.is_not(None),
                DailyProductFeature.supply_demand_as_of_date.is_not(None),
            )
        )
    )
    report["daily_product_features"]["supply_demand_coverage"] = {
        "rows_total": session.scalar(select(func.count()).select_from(DailyProductFeature)),
        "rows_with_production_volume": session.scalar(
            select(func.count()).select_from(DailyProductFeature).where(DailyProductFeature.production_volume.is_not(None))
        ),
        "rows_with_ending_stocks": session.scalar(
            select(func.count()).select_from(DailyProductFeature).where(DailyProductFeature.ending_stocks.is_not(None))
        ),
        "rows_with_stock_to_use_ratio": session.scalar(
            select(func.count()).select_from(DailyProductFeature).where(DailyProductFeature.stock_to_use_ratio.is_not(None))
        ),
        "rows_with_supply_demand_as_of_date": session.scalar(
            select(func.count()).select_from(DailyProductFeature).where(DailyProductFeature.supply_demand_as_of_date.is_not(None))
        ),
        "rows_with_supply_demand_missing_flags": session.scalar(
            select(func.count()).select_from(DailyProductFeature).where(DailyProductFeature.supply_demand_missing_flags.is_not(None))
        ),
        "latest_product_supply_demand_feature_date": (
            latest_product_supply_demand_feature_date.isoformat() if latest_product_supply_demand_feature_date else None
        ),
    }
    report["historical_price_bars"]["count"] = session.scalar(select(func.count()).select_from(HistoricalPriceBar))
    last_historical_bar_date = session.scalar(select(func.max(HistoricalPriceBar.bar_date)))
    last_historical_created_at = session.scalar(select(func.max(HistoricalPriceBar.created_at)))
    report["historical_price_bars"]["last_bar_date"] = last_historical_bar_date.isoformat() if last_historical_bar_date else None
    report["historical_price_bars"]["last_date"] = report["historical_price_bars"]["last_bar_date"]
    report["historical_price_bars"]["last_created_at"] = (
        _to_utc(last_historical_created_at).isoformat() if last_historical_created_at else None
    )
    report["historical_price_bar_revisions"]["count"] = session.scalar(
        select(func.count()).select_from(HistoricalPriceBarRevision)
    )
    last_revision_created_at = session.scalar(select(func.max(HistoricalPriceBarRevision.created_at)))
    report["historical_price_bar_revisions"]["last_created_at"] = (
        _to_utc(last_revision_created_at).isoformat() if last_revision_created_at else None
    )
    report["energy_prices"]["count"] = session.scalar(select(func.count()).select_from(EnergyPrice))
    report["energy_prices"]["instruments_count"] = session.scalar(
        select(func.count(func.distinct(EnergyPrice.instrument_code))).select_from(EnergyPrice)
    )
    first_energy_period_start = session.scalar(select(func.min(EnergyPrice.period_start)))
    last_energy_period_start = session.scalar(select(func.max(EnergyPrice.period_start)))
    last_energy_observed_at = session.scalar(select(func.max(EnergyPrice.observed_at)))
    last_energy_fetched_at = session.scalar(select(func.max(EnergyPrice.fetched_at)))
    report["energy_prices"]["first_period_start"] = (
        first_energy_period_start.isoformat() if first_energy_period_start else None
    )
    report["energy_prices"]["last_period_start"] = (
        last_energy_period_start.isoformat() if last_energy_period_start else None
    )
    report["energy_prices"]["last_observed_at"] = (
        _to_utc(last_energy_observed_at).isoformat() if last_energy_observed_at else None
    )
    report["energy_prices"]["last_fetched_at"] = (
        _to_utc(last_energy_fetched_at).isoformat() if last_energy_fetched_at else None
    )
    report["commodity_benchmarks"]["count"] = session.scalar(select(func.count()).select_from(CommodityBenchmark))
    report["commodity_benchmarks"]["benchmarks_count"] = session.scalar(
        select(func.count(func.distinct(CommodityBenchmark.benchmark_code))).select_from(CommodityBenchmark)
    )
    first_benchmark_period_start = session.scalar(select(func.min(CommodityBenchmark.period_start)))
    last_benchmark_period_start = session.scalar(select(func.max(CommodityBenchmark.period_start)))
    last_benchmark_observed_at = session.scalar(select(func.max(CommodityBenchmark.observed_at)))
    last_benchmark_fetched_at = session.scalar(select(func.max(CommodityBenchmark.fetched_at)))
    report["commodity_benchmarks"]["first_period_start"] = (
        first_benchmark_period_start.isoformat() if first_benchmark_period_start else None
    )
    report["commodity_benchmarks"]["last_period_start"] = (
        last_benchmark_period_start.isoformat() if last_benchmark_period_start else None
    )
    report["commodity_benchmarks"]["last_observed_at"] = (
        _to_utc(last_benchmark_observed_at).isoformat() if last_benchmark_observed_at else None
    )
    report["commodity_benchmarks"]["last_fetched_at"] = (
        _to_utc(last_benchmark_fetched_at).isoformat() if last_benchmark_fetched_at else None
    )
    report["weather_regions"] = {
        "count": session.scalar(select(func.count()).select_from(WeatherRegion)),
        "active_count": session.scalar(select(func.count()).select_from(WeatherRegion).where(WeatherRegion.is_active.is_(True))),
        "high_priority_count": session.scalar(select(func.count()).select_from(WeatherRegion).where(WeatherRegion.priority == "high")),
        "countries_count": session.scalar(select(func.count(func.distinct(WeatherRegion.country))).select_from(WeatherRegion)),
        "commodity_families_count": session.scalar(
            select(func.count(func.distinct(WeatherRegion.commodity_family))).select_from(WeatherRegion)
        ),
    }
    first_weather_observation_date = session.scalar(select(func.min(WeatherObservation.observation_date)))
    last_weather_observation_date = session.scalar(select(func.max(WeatherObservation.observation_date)))
    last_weather_observation_fetched_at = session.scalar(select(func.max(WeatherObservation.fetched_at)))
    report["weather_observations"] = {
        "count": session.scalar(select(func.count()).select_from(WeatherObservation)),
        "regions_count": session.scalar(select(func.count(func.distinct(WeatherObservation.region_id))).select_from(WeatherObservation)),
        "first_observation_date": first_weather_observation_date.isoformat() if first_weather_observation_date else None,
        "last_observation_date": last_weather_observation_date.isoformat() if last_weather_observation_date else None,
        "last_fetched_at": _to_utc(last_weather_observation_fetched_at).isoformat() if last_weather_observation_fetched_at else None,
    }
    first_weather_feature_date = session.scalar(select(func.min(WeatherDailyFeature.feature_date)))
    last_weather_feature_date = session.scalar(select(func.max(WeatherDailyFeature.feature_date)))
    latest_weather_as_of_date = session.scalar(select(func.max(WeatherDailyFeature.weather_as_of_date)))
    report["weather_daily_features"] = {
        "count": session.scalar(select(func.count()).select_from(WeatherDailyFeature)),
        "regions_count": session.scalar(select(func.count(func.distinct(WeatherDailyFeature.region_id))).select_from(WeatherDailyFeature)),
        "first_feature_date": first_weather_feature_date.isoformat() if first_weather_feature_date else None,
        "last_feature_date": last_weather_feature_date.isoformat() if last_weather_feature_date else None,
        "latest_weather_as_of_date": latest_weather_as_of_date.isoformat() if latest_weather_as_of_date else None,
    }
    report["product_weather_region_weights"] = {
        "count": session.scalar(select(func.count()).select_from(ProductWeatherRegionWeight)),
        "active_count": session.scalar(
            select(func.count()).select_from(ProductWeatherRegionWeight).where(ProductWeatherRegionWeight.is_active.is_(True))
        ),
        "products_count": session.scalar(
            select(func.count(func.distinct(ProductWeatherRegionWeight.product_id))).select_from(ProductWeatherRegionWeight)
        ),
        "regions_count": session.scalar(
            select(func.count(func.distinct(ProductWeatherRegionWeight.region_id))).select_from(ProductWeatherRegionWeight)
        ),
    }
    first_news_published_at = session.scalar(select(func.min(NewsArticle.published_at)))
    last_news_published_at = session.scalar(select(func.max(NewsArticle.published_at)))
    last_news_fetched_at = session.scalar(select(func.max(NewsArticle.fetched_at)))
    report["news_articles"] = {
        "count": session.scalar(select(func.count()).select_from(NewsArticle)),
        "sources_count": session.scalar(select(func.count(func.distinct(NewsArticle.source_id))).select_from(NewsArticle)),
        "first_published_at": _to_utc(first_news_published_at).isoformat() if first_news_published_at else None,
        "last_published_at": _to_utc(last_news_published_at).isoformat() if last_news_published_at else None,
        "last_fetched_at": _to_utc(last_news_fetched_at).isoformat() if last_news_fetched_at else None,
        "languages_count": session.scalar(select(func.count(func.distinct(NewsArticle.language))).select_from(NewsArticle)),
    }
    first_event_date = session.scalar(select(func.min(CommodityEvent.event_date)))
    last_event_date = session.scalar(select(func.max(CommodityEvent.event_date)))
    latest_event_published_at = session.scalar(select(func.max(CommodityEvent.published_at)))
    report["commodity_events"] = {
        "count": session.scalar(select(func.count()).select_from(CommodityEvent)),
        "categories_count": session.scalar(select(func.count(func.distinct(CommodityEvent.event_category))).select_from(CommodityEvent)),
        "commodity_families_count": session.scalar(
            select(func.count(func.distinct(CommodityEvent.commodity_family))).select_from(CommodityEvent)
        ),
        "first_event_date": first_event_date.isoformat() if first_event_date else None,
        "last_event_date": last_event_date.isoformat() if last_event_date else None,
        "latest_published_at": _to_utc(latest_event_published_at).isoformat() if latest_event_published_at else None,
    }
    first_news_feature_date = session.scalar(select(func.min(DailyNewsFeature.feature_date)))
    last_news_feature_date = session.scalar(select(func.max(DailyNewsFeature.feature_date)))
    latest_news_as_of_date = session.scalar(select(func.max(DailyNewsFeature.news_as_of_date)))
    report["daily_news_features"] = {
        "count": session.scalar(select(func.count()).select_from(DailyNewsFeature)),
        "products_count": session.scalar(select(func.count(func.distinct(DailyNewsFeature.product_id))).select_from(DailyNewsFeature)),
        "first_feature_date": first_news_feature_date.isoformat() if first_news_feature_date else None,
        "last_feature_date": last_news_feature_date.isoformat() if last_news_feature_date else None,
        "latest_news_as_of_date": latest_news_as_of_date.isoformat() if latest_news_as_of_date else None,
    }
    report["trade_commodity_codes"] = {
        "count": session.scalar(select(func.count()).select_from(TradeCommodityCode)),
        "active_count": session.scalar(
            select(func.count()).select_from(TradeCommodityCode).where(TradeCommodityCode.is_active.is_(True))
        ),
        "code_systems_count": session.scalar(
            select(func.count(func.distinct(TradeCommodityCode.code_system))).select_from(TradeCommodityCode)
        ),
        "direct_mappings_count": session.scalar(
            select(func.count()).select_from(TradeCommodityCode).where(TradeCommodityCode.relevance == "direct")
        ),
        "context_mappings_count": session.scalar(
            select(func.count()).select_from(TradeCommodityCode).where(TradeCommodityCode.relevance == "context")
        ),
    }
    first_trade_period_start = session.scalar(select(func.min(TradeFlow.period_start)))
    last_trade_period_start = session.scalar(select(func.max(TradeFlow.period_start)))
    last_trade_fetched_at = session.scalar(select(func.max(TradeFlow.fetched_at)))
    report["trade_flows"] = {
        "count": session.scalar(select(func.count()).select_from(TradeFlow)),
        "commodities_count": session.scalar(select(func.count(func.distinct(TradeFlow.trade_commodity_code_id))).select_from(TradeFlow)),
        "reporters_count": session.scalar(select(func.count(func.distinct(TradeFlow.reporter_code))).select_from(TradeFlow)),
        "partners_count": session.scalar(select(func.count(func.distinct(TradeFlow.partner_code))).select_from(TradeFlow)),
        "first_period_start": first_trade_period_start.isoformat() if first_trade_period_start else None,
        "last_period_start": last_trade_period_start.isoformat() if last_trade_period_start else None,
        "last_fetched_at": _to_utc(last_trade_fetched_at).isoformat() if last_trade_fetched_at else None,
    }
    report["product_trade_code_weights"] = {
        "count": session.scalar(select(func.count()).select_from(ProductTradeCodeWeight)),
        "active_count": session.scalar(
            select(func.count()).select_from(ProductTradeCodeWeight).where(ProductTradeCodeWeight.is_active.is_(True))
        ),
        "products_count": session.scalar(
            select(func.count(func.distinct(ProductTradeCodeWeight.product_id))).select_from(ProductTradeCodeWeight)
        ),
        "commodity_codes_count": session.scalar(
            select(func.count(func.distinct(ProductTradeCodeWeight.trade_commodity_code_id))).select_from(ProductTradeCodeWeight)
        ),
    }
    first_trade_feature_date = session.scalar(select(func.min(DailyTradeFeature.feature_date)))
    last_trade_feature_date = session.scalar(select(func.max(DailyTradeFeature.feature_date)))
    latest_trade_as_of_date = session.scalar(select(func.max(DailyTradeFeature.trade_as_of_date)))
    report["daily_trade_features"] = {
        "count": session.scalar(select(func.count()).select_from(DailyTradeFeature)),
        "products_count": session.scalar(select(func.count(func.distinct(DailyTradeFeature.product_id))).select_from(DailyTradeFeature)),
        "first_feature_date": first_trade_feature_date.isoformat() if first_trade_feature_date else None,
        "last_feature_date": last_trade_feature_date.isoformat() if last_trade_feature_date else None,
        "latest_trade_as_of_date": latest_trade_as_of_date.isoformat() if latest_trade_as_of_date else None,
    }
    report["supply_demand_commodities"] = {
        "count": session.scalar(select(func.count()).select_from(SupplyDemandCommodity)),
        "active_count": session.scalar(
            select(func.count()).select_from(SupplyDemandCommodity).where(SupplyDemandCommodity.is_active.is_(True))
        ),
        "metrics_count": session.scalar(
            select(func.count(func.distinct(SupplyDemandCommodity.metric_name))).select_from(SupplyDemandCommodity)
        ),
    }
    report["supply_demand_observations"] = {
        "count": session.scalar(select(func.count()).select_from(SupplyDemandObservation)),
        "commodities_count": session.scalar(
            select(func.count(func.distinct(SupplyDemandObservation.supply_demand_commodity_id))).select_from(
                SupplyDemandObservation
            )
        ),
        "countries_count": session.scalar(
            select(func.count(func.distinct(SupplyDemandObservation.country_code))).select_from(SupplyDemandObservation)
        ),
        "last_fetched_at": (
            _to_utc(last_supply_demand_fetched_at).isoformat() if (last_supply_demand_fetched_at := session.scalar(
                select(func.max(SupplyDemandObservation.fetched_at))
            )) else None
        ),
    }
    report["supply_demand_revisions"] = {
        "count": session.scalar(select(func.count()).select_from(SupplyDemandRevision)),
    }
    report["product_supply_demand_weights"] = {
        "count": session.scalar(select(func.count()).select_from(ProductSupplyDemandWeight)),
    }
    report["daily_supply_demand_features"] = {
        "count": session.scalar(select(func.count()).select_from(DailySupplyDemandFeature)),
        "products_count": session.scalar(
            select(func.count(func.distinct(DailySupplyDemandFeature.product_id))).select_from(DailySupplyDemandFeature)
        ),
        "first_feature_date": (
            first_supply_demand_feature_date.isoformat() if (first_supply_demand_feature_date := session.scalar(
                select(func.min(DailySupplyDemandFeature.feature_date))
            )) else None
        ),
        "last_feature_date": (
            last_supply_demand_feature_date.isoformat() if (last_supply_demand_feature_date := session.scalar(
                select(func.max(DailySupplyDemandFeature.feature_date))
            )) else None
        ),
        "latest_supply_demand_as_of_date": (
            latest_supply_demand_as_of_date.isoformat() if (latest_supply_demand_as_of_date := session.scalar(
                select(func.max(DailySupplyDemandFeature.supply_demand_as_of_date))
            )) else None
        ),
    }
    report["cbr_fx"]["fx_rates_last_24h"] = report["last_24h"]["fx_rates"]
    report["last_24h"]["problematic_quality_checks"] = session.scalar(
        select(func.count())
        .select_from(DataQualityCheck)
        .where(DataQualityCheck.checked_at >= cutoff, problematic_quality_filter())
    )
    quality_summary = build_quality_summary(session=session)
    report["quality_checks"] = {
        "total_checks": quality_summary["total_checks"],
        "pass_checks": quality_summary["pass_checks"],
        "skip_checks": quality_summary["skip_checks"],
        "problematic_checks": quality_summary["problematic_checks"],
        "conclusion": quality_summary["conclusion"],
        "message": "quality checks ok" if quality_summary["problematic_checks"] == 0 else "quality checks need review",
    }

    for status in ("success", "partial_success", "error"):
        run = session.scalar(
            select(CollectorRun).where(CollectorRun.status == status).order_by(CollectorRun.started_at.desc()).limit(1)
        )
        report["last_runs"][status] = _run_to_dict(run)
    cbr_fx_run = session.scalar(
        select(CollectorRun)
        .where(CollectorRun.collector_name == "cbr_fx_collector", CollectorRun.status == "success")
        .order_by(CollectorRun.started_at.desc())
        .limit(1)
    )
    report["cbr_fx"]["last_successful_run"] = _run_to_dict(cbr_fx_run)
    historical_run = session.scalar(
        select(CollectorRun)
        .where(CollectorRun.collector_name == "jijinhao_historical_prices_collector", CollectorRun.status == "success")
        .order_by(CollectorRun.started_at.desc())
        .limit(1)
    )
    report["historical_price_bars"]["last_successful_run"] = _run_to_dict(historical_run)
    historical_partial_run = session.scalar(
        select(CollectorRun)
        .where(
            CollectorRun.collector_name == "jijinhao_historical_prices_collector",
            CollectorRun.status == "partial_success",
        )
        .order_by(CollectorRun.started_at.desc())
        .limit(1)
    )
    report["historical_price_bars"]["last_partial_run"] = _run_to_dict(historical_partial_run)
    supply_demand_run = session.scalar(
        select(CollectorRun)
        .where(CollectorRun.collector_name == "usda_psd", CollectorRun.status == "success")
        .order_by(CollectorRun.started_at.desc())
        .limit(1)
    )
    report["supply_demand_observations"]["last_successful_run"] = _run_to_dict(supply_demand_run)
    supply_demand_partial_run = session.scalar(
        select(CollectorRun)
        .where(
            CollectorRun.collector_name == "usda_psd",
            CollectorRun.status == "partial_success",
        )
        .order_by(CollectorRun.started_at.desc())
        .limit(1)
    )
    report["supply_demand_observations"]["last_partial_run"] = _run_to_dict(supply_demand_partial_run)

    if source is not None:
        report["stale_products"] = _stale_products(session, source.id, freshness_cutoff)
    else:
        report["stale_products"] = [
            {"product_code": item.product_code, "reason": "source_current_price_source_not_seeded"}
            for item in CURRENT_PRICE_INSTRUMENTS
        ]


def _stale_products(session: Session, source_id: int, cutoff: datetime) -> list[dict[str, Any]]:
    stale = []
    for instrument in CURRENT_PRICE_INSTRUMENTS:
        product = session.scalar(select(Product).where(Product.code == instrument.product_code))
        if product is None:
            stale.append({"product_code": instrument.product_code, "reason": "product_not_seeded"})
            continue
        latest = session.scalar(
            select(PriceObservation)
            .where(PriceObservation.source_id == source_id, PriceObservation.product_id == product.id)
            .order_by(PriceObservation.observed_at.desc())
            .limit(1)
        )
        if latest is None:
            stale.append({"product_code": instrument.product_code, "reason": "no_price_observation"})
        elif _to_utc(latest.observed_at) < cutoff:
            stale.append(
                {
                    "product_code": instrument.product_code,
                    "reason": "stale_price",
                    "latest_observed_at": _to_utc(latest.observed_at).isoformat(),
                }
            )
    return stale


def _missing_recent_features(session: Session, *, cutoff: datetime) -> list[dict[str, Any]]:
    local_tz = ZoneInfo(get_settings().schedule_timezone)
    recent = session.scalars(select(PriceObservation).where(PriceObservation.created_at >= cutoff)).all()
    missing: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for observation in recent:
        feature_date = _to_utc(observation.observed_at).astimezone(local_tz).date()
        key = (observation.product_id, feature_date.isoformat())
        if key in seen:
            continue
        seen.add(key)
        exists = session.scalar(
            select(DailyProductFeature.id)
            .where(DailyProductFeature.product_id == observation.product_id, DailyProductFeature.feature_date == feature_date)
            .limit(1)
        )
        if exists is None:
            missing.append({"product_id": observation.product_id, "feature_date": feature_date.isoformat()})
    return missing


def _run_to_dict(run: CollectorRun | None) -> dict[str, Any] | None:
    if run is None:
        return None
    return {
        "id": run.id,
        "collector_name": run.collector_name,
        "status": run.status,
        "run_type": run.run_type,
        "collection_slot": _to_utc(run.collection_slot).isoformat() if run.collection_slot else None,
        "started_at": _to_utc(run.started_at).isoformat(),
        "finished_at": _to_utc(run.finished_at).isoformat() if run.finished_at else None,
        "records_found": run.records_found,
        "records_written": run.records_written,
        "error_message": run.error_message,
    }


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
