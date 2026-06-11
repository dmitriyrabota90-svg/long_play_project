from __future__ import annotations

import csv
import importlib.util
import os
import subprocess
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config.settings import Settings, get_settings
from app.db.models import DailyProductFeature, Product
from app.db.session import session_scope
from app.exports.manifest import write_manifest
from app.storage.hashes import sha256_bytes


EXPORT_NAME = "daily_features"
EXPORT_VERSION = "daily_features_v1"
EXPORT_FORMATS = {"csv", "parquet", "both"}
DAILY_FEATURE_COLUMNS = [
    "product_code",
    "product_name",
    "feature_date",
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
    "feature_version",
    "as_of_at",
    "price_last",
    "price_first",
    "price_min",
    "price_max",
    "price_observations_count",
    "price_delta_abs_1d",
    "price_delta_pct_1d",
    "price_intraday_delta_abs",
    "price_intraday_delta_pct",
    "price_rolling_mean_3d",
    "price_rolling_mean_7d",
    "price_rolling_std_7d",
    "cny_rub",
    "usd_rub",
    "eur_rub",
    "cny_rub_delta_abs_1d",
    "cny_rub_delta_pct_1d",
    "usd_rub_delta_abs_1d",
    "usd_rub_delta_pct_1d",
    "eur_rub_delta_abs_1d",
    "eur_rub_delta_pct_1d",
    "fx_as_of_date",
    "energy_brent_usd_per_barrel",
    "energy_wti_usd_per_barrel",
    "energy_henry_hub_usd_mmbtu",
    "energy_diesel_proxy_value",
    "energy_brent_delta_1d",
    "energy_brent_delta_7d",
    "energy_wti_delta_1d",
    "energy_wti_delta_7d",
    "energy_henry_hub_delta_1d",
    "energy_henry_hub_delta_7d",
    "energy_diesel_proxy_delta_7d",
    "energy_as_of_date",
    "energy_brent_as_of_date",
    "energy_wti_as_of_date",
    "energy_henry_hub_as_of_date",
    "energy_diesel_as_of_date",
    "energy_missing_flags",
    "benchmark_soybean_oil_value",
    "benchmark_soybeans_value",
    "benchmark_palm_oil_value",
    "benchmark_maize_value",
    "benchmark_wheat_value",
    "benchmark_fertilizer_index_value",
    "benchmark_soybean_oil_delta_1m",
    "benchmark_soybean_oil_delta_3m",
    "benchmark_soybeans_delta_1m",
    "benchmark_soybeans_delta_3m",
    "benchmark_palm_oil_delta_1m",
    "benchmark_palm_oil_delta_3m",
    "benchmark_maize_delta_1m",
    "benchmark_maize_delta_3m",
    "benchmark_wheat_delta_1m",
    "benchmark_wheat_delta_3m",
    "benchmark_fertilizer_index_delta_1m",
    "benchmark_fertilizer_index_delta_3m",
    "benchmark_as_of_date",
    "benchmark_soybean_oil_as_of_date",
    "benchmark_soybeans_as_of_date",
    "benchmark_palm_oil_as_of_date",
    "benchmark_maize_as_of_date",
    "benchmark_wheat_as_of_date",
    "benchmark_fertilizer_index_as_of_date",
    "benchmark_missing_flags",
    "weather_temperature_7d_mean_weighted",
    "weather_temperature_30d_mean_weighted",
    "weather_temperature_min_7d_weighted",
    "weather_temperature_max_7d_weighted",
    "weather_precipitation_7d_sum_weighted",
    "weather_precipitation_14d_sum_weighted",
    "weather_precipitation_30d_sum_weighted",
    "weather_heat_stress_days_7d_weighted",
    "weather_heat_stress_days_30d_weighted",
    "weather_frost_days_7d_weighted",
    "weather_frost_days_30d_weighted",
    "weather_drought_proxy_30d_weighted",
    "weather_growing_degree_days_7d_weighted",
    "weather_growing_degree_days_30d_weighted",
    "weather_as_of_date",
    "weather_regions_used",
    "weather_missing_flags",
    "news_count_1d",
    "news_count_7d",
    "news_count_30d",
    "event_count_1d",
    "event_count_7d",
    "event_count_30d",
    "bullish_event_count_7d",
    "bearish_event_count_7d",
    "mixed_event_count_7d",
    "export_restriction_count_30d",
    "import_policy_count_30d",
    "war_logistics_count_30d",
    "weather_disaster_count_30d",
    "crop_report_count_30d",
    "biofuel_policy_count_30d",
    "energy_shock_count_30d",
    "demand_shock_count_30d",
    "supply_chain_count_30d",
    "sentiment_proxy_7d",
    "news_as_of_date",
    "news_missing_flags",
    "export_volume_1m",
    "export_volume_3m_avg",
    "export_volume_12m_sum",
    "import_volume_1m",
    "import_volume_3m_avg",
    "import_volume_12m_sum",
    "net_export_volume_1m",
    "export_value_usd_1m",
    "import_value_usd_1m",
    "average_export_unit_value_usd",
    "average_import_unit_value_usd",
    "china_import_volume_1m",
    "major_exporter_volume_1m",
    "major_importer_volume_1m",
    "trade_balance_proxy",
    "trade_yoy_change",
    "trade_as_of_date",
    "reporting_lag_days",
    "trade_missing_flags",
    "created_at",
    "updated_at",
]


class DatasetExportError(RuntimeError):
    pass


class DatasetExportValidationError(DatasetExportError):
    pass


@dataclass(frozen=True)
class DailyFeaturesExportResult:
    export_name: str
    export_version: str
    row_count: int
    column_count: int
    products: list[str]
    feature_date_min: str
    feature_date_max: str
    formats: list[str]
    files: list[dict[str, Any]]
    manifest_path: str
    sha256: dict[str, str]


def export_daily_features(
    *,
    from_date: date | None = None,
    to_date: date | None = None,
    export_format: Literal["csv", "parquet", "both"] = "csv",
    output_dir: Path | str | None = None,
    session: Session | None = None,
    settings: Settings | None = None,
) -> DailyFeaturesExportResult:
    settings = settings or get_settings()
    if export_format not in EXPORT_FORMATS:
        raise DatasetExportValidationError(f"Unsupported export format: {export_format}")
    output_path = _validated_output_dir(output_dir=output_dir, settings=settings)

    if session is None:
        with session_scope() as scoped_session:
            return _export_daily_features_with_session(
                scoped_session,
                from_date=from_date,
                to_date=to_date,
                export_format=export_format,
                output_dir=output_path,
            )
    return _export_daily_features_with_session(
        session,
        from_date=from_date,
        to_date=to_date,
        export_format=export_format,
        output_dir=output_path,
    )


def _export_daily_features_with_session(
    session: Session,
    *,
    from_date: date | None,
    to_date: date | None,
    export_format: str,
    output_dir: Path,
) -> DailyFeaturesExportResult:
    if from_date and to_date and from_date > to_date:
        raise DatasetExportValidationError("from_date must be on or before to_date")
    rows = load_daily_feature_rows(session=session, from_date=from_date, to_date=to_date)
    validate_daily_feature_rows(rows)

    output_dir.mkdir(parents=True, exist_ok=True)
    created_at = datetime.now(timezone.utc)
    timestamp = created_at.strftime("%Y%m%d_%H%M%S")
    base_name = f"{EXPORT_VERSION}_{timestamp}"
    requested_formats = ["csv", "parquet"] if export_format == "both" else [export_format]
    files: list[dict[str, Any]] = []
    sha_by_format: dict[str, str] = {}

    for item_format in requested_formats:
        if item_format == "csv":
            csv_path = output_dir / f"{base_name}.csv"
            _write_csv(csv_path, rows)
            _validate_csv_file(csv_path, expected_rows=len(rows), expected_columns=len(DAILY_FEATURE_COLUMNS))
            digest = _sha256_file(csv_path)
            sha_by_format["csv"] = digest
            files.append(_file_entry(path=csv_path, item_format="csv", digest=digest))
        elif item_format == "parquet":
            _ensure_parquet_available()
            parquet_path = output_dir / f"{base_name}.parquet"
            _write_parquet(parquet_path, rows)
            digest = _sha256_file(parquet_path)
            sha_by_format["parquet"] = digest
            files.append(_file_entry(path=parquet_path, item_format="parquet", digest=digest))
        else:
            raise DatasetExportValidationError(f"Unsupported export format: {item_format}")

    manifest = _build_manifest(
        created_at=created_at,
        rows=rows,
        formats=requested_formats,
        files=files,
        sha256=sha_by_format,
    )
    _validate_manifest(manifest)
    manifest_path = output_dir / f"{base_name}_manifest.json"
    write_manifest(manifest_path, manifest)
    _assert_no_manifest_secrets(manifest_path)

    return DailyFeaturesExportResult(
        export_name=EXPORT_NAME,
        export_version=EXPORT_VERSION,
        row_count=len(rows),
        column_count=len(DAILY_FEATURE_COLUMNS),
        products=manifest["products"],
        feature_date_min=manifest["feature_date_min"],
        feature_date_max=manifest["feature_date_max"],
        formats=requested_formats,
        files=files,
        manifest_path=str(manifest_path),
        sha256=sha_by_format,
    )


def load_daily_feature_rows(
    *,
    session: Session,
    from_date: date | None = None,
    to_date: date | None = None,
) -> list[dict[str, Any]]:
    statement = (
        select(DailyProductFeature, Product)
        .join(Product, Product.id == DailyProductFeature.product_id)
        .order_by(DailyProductFeature.feature_date, Product.code)
    )
    if from_date is not None:
        statement = statement.where(DailyProductFeature.feature_date >= from_date)
    if to_date is not None:
        statement = statement.where(DailyProductFeature.feature_date <= to_date)

    rows: list[dict[str, Any]] = []
    for feature, product in session.execute(statement).all():
        rows.append(_row_from_feature(feature, product))
    return rows


def validate_daily_feature_rows(rows: list[dict[str, Any]]) -> None:
    if not rows:
        raise DatasetExportValidationError("daily_features export has no rows")
    seen: set[tuple[str, str]] = set()
    dates: list[str] = []
    for index, row in enumerate(rows, start=1):
        product_code = row.get("product_code")
        feature_date = row.get("feature_date")
        if not product_code:
            raise DatasetExportValidationError(f"row {index} has empty product_code")
        if not feature_date:
            raise DatasetExportValidationError(f"row {index} has empty feature_date")
        key = (str(product_code), str(feature_date))
        if key in seen:
            raise DatasetExportValidationError(f"duplicate daily feature row: {key[0]} {key[1]}")
        seen.add(key)
        dates.append(str(feature_date))
    if min(dates) > max(dates):
        raise DatasetExportValidationError("feature_date range is invalid")


def _row_from_feature(feature: DailyProductFeature, product: Product) -> dict[str, Any]:
    row = {
        "product_code": product.code,
        "product_name": product.name,
        "feature_date": feature.feature_date,
        "calendar_year": feature.calendar_year,
        "calendar_month": feature.calendar_month,
        "calendar_quarter": feature.calendar_quarter,
        "calendar_week_of_year": feature.calendar_week_of_year,
        "calendar_day_of_year": feature.calendar_day_of_year,
        "calendar_day_of_week": feature.calendar_day_of_week,
        "calendar_is_month_start": feature.calendar_is_month_start,
        "calendar_is_month_end": feature.calendar_is_month_end,
        "calendar_is_quarter_start": feature.calendar_is_quarter_start,
        "calendar_is_quarter_end": feature.calendar_is_quarter_end,
        "calendar_sin_day_of_year": feature.calendar_sin_day_of_year,
        "calendar_cos_day_of_year": feature.calendar_cos_day_of_year,
        "calendar_sin_month": feature.calendar_sin_month,
        "calendar_cos_month": feature.calendar_cos_month,
        "calendar_season": feature.calendar_season,
        "feature_version": feature.feature_version,
        "as_of_at": feature.as_of_at,
        "price_last": feature.price_last,
        "price_first": feature.price_first,
        "price_min": feature.price_min,
        "price_max": feature.price_max,
        "price_observations_count": feature.price_observations_count,
        "price_delta_abs_1d": feature.price_delta_abs_1d,
        "price_delta_pct_1d": feature.price_delta_pct_1d,
        "price_intraday_delta_abs": feature.price_intraday_delta_abs,
        "price_intraday_delta_pct": feature.price_intraday_delta_pct,
        "price_rolling_mean_3d": feature.price_rolling_mean_3d,
        "price_rolling_mean_7d": feature.price_rolling_mean_7d,
        "price_rolling_std_7d": feature.price_rolling_std_7d,
        "cny_rub": feature.cny_rub,
        "usd_rub": feature.usd_rub,
        "eur_rub": feature.eur_rub,
        "cny_rub_delta_abs_1d": feature.cny_rub_delta_abs_1d,
        "cny_rub_delta_pct_1d": feature.cny_rub_delta_pct_1d,
        "usd_rub_delta_abs_1d": feature.usd_rub_delta_abs_1d,
        "usd_rub_delta_pct_1d": feature.usd_rub_delta_pct_1d,
        "eur_rub_delta_abs_1d": feature.eur_rub_delta_abs_1d,
        "eur_rub_delta_pct_1d": feature.eur_rub_delta_pct_1d,
        "fx_as_of_date": feature.fx_as_of_date,
        "energy_brent_usd_per_barrel": feature.energy_brent_usd_per_barrel,
        "energy_wti_usd_per_barrel": feature.energy_wti_usd_per_barrel,
        "energy_henry_hub_usd_mmbtu": feature.energy_henry_hub_usd_mmbtu,
        "energy_diesel_proxy_value": feature.energy_diesel_proxy_value,
        "energy_brent_delta_1d": feature.energy_brent_delta_1d,
        "energy_brent_delta_7d": feature.energy_brent_delta_7d,
        "energy_wti_delta_1d": feature.energy_wti_delta_1d,
        "energy_wti_delta_7d": feature.energy_wti_delta_7d,
        "energy_henry_hub_delta_1d": feature.energy_henry_hub_delta_1d,
        "energy_henry_hub_delta_7d": feature.energy_henry_hub_delta_7d,
        "energy_diesel_proxy_delta_7d": feature.energy_diesel_proxy_delta_7d,
        "energy_as_of_date": feature.energy_as_of_date,
        "energy_brent_as_of_date": feature.energy_brent_as_of_date,
        "energy_wti_as_of_date": feature.energy_wti_as_of_date,
        "energy_henry_hub_as_of_date": feature.energy_henry_hub_as_of_date,
        "energy_diesel_as_of_date": feature.energy_diesel_as_of_date,
        "energy_missing_flags": feature.energy_missing_flags,
        "benchmark_soybean_oil_value": feature.benchmark_soybean_oil_value,
        "benchmark_soybeans_value": feature.benchmark_soybeans_value,
        "benchmark_palm_oil_value": feature.benchmark_palm_oil_value,
        "benchmark_maize_value": feature.benchmark_maize_value,
        "benchmark_wheat_value": feature.benchmark_wheat_value,
        "benchmark_fertilizer_index_value": feature.benchmark_fertilizer_index_value,
        "benchmark_soybean_oil_delta_1m": feature.benchmark_soybean_oil_delta_1m,
        "benchmark_soybean_oil_delta_3m": feature.benchmark_soybean_oil_delta_3m,
        "benchmark_soybeans_delta_1m": feature.benchmark_soybeans_delta_1m,
        "benchmark_soybeans_delta_3m": feature.benchmark_soybeans_delta_3m,
        "benchmark_palm_oil_delta_1m": feature.benchmark_palm_oil_delta_1m,
        "benchmark_palm_oil_delta_3m": feature.benchmark_palm_oil_delta_3m,
        "benchmark_maize_delta_1m": feature.benchmark_maize_delta_1m,
        "benchmark_maize_delta_3m": feature.benchmark_maize_delta_3m,
        "benchmark_wheat_delta_1m": feature.benchmark_wheat_delta_1m,
        "benchmark_wheat_delta_3m": feature.benchmark_wheat_delta_3m,
        "benchmark_fertilizer_index_delta_1m": feature.benchmark_fertilizer_index_delta_1m,
        "benchmark_fertilizer_index_delta_3m": feature.benchmark_fertilizer_index_delta_3m,
        "benchmark_as_of_date": feature.benchmark_as_of_date,
        "benchmark_soybean_oil_as_of_date": feature.benchmark_soybean_oil_as_of_date,
        "benchmark_soybeans_as_of_date": feature.benchmark_soybeans_as_of_date,
        "benchmark_palm_oil_as_of_date": feature.benchmark_palm_oil_as_of_date,
        "benchmark_maize_as_of_date": feature.benchmark_maize_as_of_date,
        "benchmark_wheat_as_of_date": feature.benchmark_wheat_as_of_date,
        "benchmark_fertilizer_index_as_of_date": feature.benchmark_fertilizer_index_as_of_date,
        "benchmark_missing_flags": feature.benchmark_missing_flags,
        "weather_temperature_7d_mean_weighted": feature.weather_temperature_7d_mean_weighted,
        "weather_temperature_30d_mean_weighted": feature.weather_temperature_30d_mean_weighted,
        "weather_temperature_min_7d_weighted": feature.weather_temperature_min_7d_weighted,
        "weather_temperature_max_7d_weighted": feature.weather_temperature_max_7d_weighted,
        "weather_precipitation_7d_sum_weighted": feature.weather_precipitation_7d_sum_weighted,
        "weather_precipitation_14d_sum_weighted": feature.weather_precipitation_14d_sum_weighted,
        "weather_precipitation_30d_sum_weighted": feature.weather_precipitation_30d_sum_weighted,
        "weather_heat_stress_days_7d_weighted": feature.weather_heat_stress_days_7d_weighted,
        "weather_heat_stress_days_30d_weighted": feature.weather_heat_stress_days_30d_weighted,
        "weather_frost_days_7d_weighted": feature.weather_frost_days_7d_weighted,
        "weather_frost_days_30d_weighted": feature.weather_frost_days_30d_weighted,
        "weather_drought_proxy_30d_weighted": feature.weather_drought_proxy_30d_weighted,
        "weather_growing_degree_days_7d_weighted": feature.weather_growing_degree_days_7d_weighted,
        "weather_growing_degree_days_30d_weighted": feature.weather_growing_degree_days_30d_weighted,
        "weather_as_of_date": feature.weather_as_of_date,
        "weather_regions_used": feature.weather_regions_used,
        "weather_missing_flags": feature.weather_missing_flags,
        "news_count_1d": feature.news_count_1d,
        "news_count_7d": feature.news_count_7d,
        "news_count_30d": feature.news_count_30d,
        "event_count_1d": feature.event_count_1d,
        "event_count_7d": feature.event_count_7d,
        "event_count_30d": feature.event_count_30d,
        "bullish_event_count_7d": feature.bullish_event_count_7d,
        "bearish_event_count_7d": feature.bearish_event_count_7d,
        "mixed_event_count_7d": feature.mixed_event_count_7d,
        "export_restriction_count_30d": feature.export_restriction_count_30d,
        "import_policy_count_30d": feature.import_policy_count_30d,
        "war_logistics_count_30d": feature.war_logistics_count_30d,
        "weather_disaster_count_30d": feature.weather_disaster_count_30d,
        "crop_report_count_30d": feature.crop_report_count_30d,
        "biofuel_policy_count_30d": feature.biofuel_policy_count_30d,
        "energy_shock_count_30d": feature.energy_shock_count_30d,
        "demand_shock_count_30d": feature.demand_shock_count_30d,
        "supply_chain_count_30d": feature.supply_chain_count_30d,
        "sentiment_proxy_7d": feature.sentiment_proxy_7d,
        "news_as_of_date": feature.news_as_of_date,
        "news_missing_flags": feature.news_missing_flags,
        "export_volume_1m": feature.export_volume_1m,
        "export_volume_3m_avg": feature.export_volume_3m_avg,
        "export_volume_12m_sum": feature.export_volume_12m_sum,
        "import_volume_1m": feature.import_volume_1m,
        "import_volume_3m_avg": feature.import_volume_3m_avg,
        "import_volume_12m_sum": feature.import_volume_12m_sum,
        "net_export_volume_1m": feature.net_export_volume_1m,
        "export_value_usd_1m": feature.export_value_usd_1m,
        "import_value_usd_1m": feature.import_value_usd_1m,
        "average_export_unit_value_usd": feature.average_export_unit_value_usd,
        "average_import_unit_value_usd": feature.average_import_unit_value_usd,
        "china_import_volume_1m": feature.china_import_volume_1m,
        "major_exporter_volume_1m": feature.major_exporter_volume_1m,
        "major_importer_volume_1m": feature.major_importer_volume_1m,
        "trade_balance_proxy": feature.trade_balance_proxy,
        "trade_yoy_change": feature.trade_yoy_change,
        "trade_as_of_date": feature.trade_as_of_date,
        "reporting_lag_days": feature.reporting_lag_days,
        "trade_missing_flags": feature.trade_missing_flags,
        "created_at": feature.created_at,
        "updated_at": feature.updated_at,
    }
    return {column: _export_value(row[column]) for column in DAILY_FEATURE_COLUMNS}


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=DAILY_FEATURE_COLUMNS, extrasaction="raise")
        writer.writeheader()
        writer.writerows(rows)


def _write_parquet(path: Path, rows: list[dict[str, Any]]) -> None:
    import pandas as pd

    frame = pd.DataFrame(rows, columns=DAILY_FEATURE_COLUMNS)
    frame.to_parquet(path, index=False)


def _ensure_parquet_available() -> None:
    if importlib.util.find_spec("pyarrow") is None and importlib.util.find_spec("fastparquet") is None:
        raise DatasetExportValidationError(
            "Parquet export is not available because pyarrow/fastparquet is not installed."
        )


def _validate_csv_file(path: Path, *, expected_rows: int, expected_columns: int) -> None:
    if not path.exists():
        raise DatasetExportValidationError(f"CSV export was not created: {path}")
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.reader(handle)
        header = next(reader, None)
        if header is None:
            raise DatasetExportValidationError("CSV export is empty")
        row_count = sum(1 for _ in reader)
    if len(header) != expected_columns:
        raise DatasetExportValidationError(
            f"CSV column count mismatch: expected {expected_columns}, got {len(header)}"
        )
    if row_count != expected_rows:
        raise DatasetExportValidationError(f"CSV row count mismatch: expected {expected_rows}, got {row_count}")


def _build_manifest(
    *,
    created_at: datetime,
    rows: list[dict[str, Any]],
    formats: list[str],
    files: list[dict[str, Any]],
    sha256: dict[str, str],
) -> dict[str, Any]:
    products = sorted({str(row["product_code"]) for row in rows})
    feature_dates = sorted(str(row["feature_date"]) for row in rows)
    return {
        "export_name": EXPORT_NAME,
        "export_version": EXPORT_VERSION,
        "created_at": created_at.isoformat(),
        "git_commit": _git_commit(),
        "source_tables": [
            "daily_product_features",
            "products",
            "commodity_benchmarks",
            "weather_daily_features",
            "product_weather_region_weights",
            "daily_news_features",
            "commodity_events",
            "news_articles",
            "daily_trade_features",
            "trade_flows",
            "product_trade_code_weights",
            "trade_commodity_codes",
        ],
        "row_count": len(rows),
        "column_count": len(DAILY_FEATURE_COLUMNS),
        "columns": DAILY_FEATURE_COLUMNS,
        "products": products,
        "feature_date_min": feature_dates[0],
        "feature_date_max": feature_dates[-1],
        "formats": formats,
        "files": files,
        "sha256": sha256,
        "database_snapshot_note": "Export generated from the current PostgreSQL snapshot at run time.",
        "as_of_policy": (
            "Export v1 uses daily_product_features as stored. Current snapshot prices, CBR FX, FRED energy, "
            "World Bank commodity benchmarks, Open-Meteo-derived product weather features, and deterministic "
            "rule-based news/event features are used according to the current feature builder logic. "
            "Product trade aggregates are copied from daily_trade_features when their trade_as_of_date is "
            "not later than the product feature_date."
        ),
        "leakage_note": (
            "Historical bars are not used in daily features v1. World Bank benchmark features use "
            "period_start <= feature_date in Phase 6.2E. Product weather features use region-level "
            "weather_daily_features with feature_date <= product feature_date and weather_as_of_date <= "
            "product feature_date. News/event features use daily_news_features with news_as_of_date <= "
            "product feature_date. Trade features use daily_trade_features with trade_as_of_date <= "
            "product feature_date. ML targets and future-looking labels are not included."
        ),
        "included_sources": [
            "daily_product_features",
            "current_price_source snapshots through the feature builder",
            "CBR FX rates through the feature builder",
            "FRED energy prices through the feature builder",
            "World Bank Pink Sheet commodity benchmarks through the feature builder",
            "Open-Meteo region weather aggregates through product_weather_region_weights",
            "Rule-based commodity events and daily news aggregates through the feature builder",
            "UN Comtrade trade flows through daily_trade_features and product_trade_code_weights",
        ],
        "excluded_sources": [
            "historical_price_bars",
            "historical_price_bar_revisions",
            "news_items",
            "dataset targets",
            "sunflower products",
            "ML model outputs",
        ],
        "known_limitations": [
            "This export is features-only and does not include labels or model targets.",
            "Daily features currently do not use historical_price_bars.",
            "World Bank benchmark features are monthly and forward-filled by period_start.",
            "Phase 6.2E benchmark as-of logic uses period_start <= feature_date; future export modes may add published_at/fetched_at cutoffs.",
            "Weather features use first-version equal product-region weights and centroid region proxies.",
            "Weather missing flags identify partial or absent regional coverage.",
            "News/event features are deterministic keyword-rule aggregates, not semantic NLP/LLM classifications.",
            "News missing flags identify absent articles, absent events, or partial source coverage.",
            "Trade features are monthly aggregates forward-filled by strict as-of date and may lag source releases.",
            "Trade missing flags identify absent trade mappings, absent trade flows, or incomplete history windows.",
            "Only products present in daily_product_features are exported.",
            "Sunflower products, ML targets, and ML outputs are not implemented in export v1.",
        ],
    }


def _validate_manifest(manifest: dict[str, Any]) -> None:
    if manifest["row_count"] <= 0:
        raise DatasetExportValidationError("manifest row_count must be positive")
    if manifest["column_count"] != len(manifest["columns"]):
        raise DatasetExportValidationError("manifest column_count does not match columns")
    if manifest["feature_date_min"] > manifest["feature_date_max"]:
        raise DatasetExportValidationError("manifest feature_date range is invalid")
    if not manifest["files"]:
        raise DatasetExportValidationError("manifest does not list output files")


def _assert_no_manifest_secrets(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    forbidden = ("DATABASE_URL", "postgresql+psycopg2://", "collector_password", "TELEGRAM_TOKEN")
    matches = [item for item in forbidden if item in text]
    if matches:
        raise DatasetExportValidationError(f"manifest contains forbidden secret markers: {', '.join(matches)}")


def _file_entry(*, path: Path, item_format: str, digest: str) -> dict[str, Any]:
    return {
        "format": item_format,
        "path": str(path),
        "bytes_size": path.stat().st_size,
        "sha256": digest,
    }


def _sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def _export_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def _validated_output_dir(*, output_dir: Path | str | None, settings: Settings) -> Path:
    export_root = settings.export_data_dir.resolve()
    candidate = Path(output_dir) if output_dir is not None else settings.export_data_dir
    candidate = candidate.resolve()
    if candidate != export_root and export_root not in candidate.parents:
        raise DatasetExportValidationError(f"output-dir must stay under {export_root}")
    return candidate


def _git_commit() -> str:
    env_commit = os.getenv("APP_GIT_COMMIT", "").strip()
    if env_commit:
        return env_commit
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return result.stdout.strip() or "unknown"
