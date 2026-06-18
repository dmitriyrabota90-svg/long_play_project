from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from app.config.logging import setup_logging
from app.collectors.benchmarks.world_bank_pink_sheet import WorldBankPinkSheetCollector
from app.collectors.benchmarks.world_bank_pink_sheet_config import is_known_benchmark
from app.collectors.energy.fred_energy_prices import FredEnergyPricesCollector, is_known_series
from app.collectors.fx.cbr_fx import CbrFxCollector
from app.collectors.historical.jijinhao_historical_prices import JijinhaoHistoricalPricesCollector
from app.collectors.news.gdelt_config import is_known_query_key
from app.collectors.news.gdelt_news import GdeltNewsCollector
from app.collectors.prices.current_price_source import CurrentPriceSourceCollector
from app.collectors.supply_demand.usda_psd import UsdaPsdCollector
from app.collectors.trade.un_comtrade import UnComtradeCollector
from app.collectors.weather.open_meteo_config import MAX_DAYS_PER_RUN as OPEN_METEO_MAX_DAYS_PER_RUN
from app.collectors.weather.open_meteo_historical import OpenMeteoHistoricalWeatherCollector


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a collector by name.")
    parser.add_argument(
        "collector_name",
        choices=[
            "current_price_source",
            "cbr_fx",
            "jijinhao_historical_prices",
            "fred_energy_prices",
            "gdelt_news",
            "world_bank_pink_sheet",
            "open_meteo_historical_weather",
            "un_comtrade",
            "usda_psd",
        ],
        help="Collector name to run",
    )
    parser.add_argument("--run-type", choices=["manual", "scheduled", "backfill"], default="manual")
    parser.add_argument(
        "--collection-slot",
        help="Required for scheduled runs. ISO datetime, for example 2026-05-12T09:00:00+00:00.",
    )
    parser.add_argument("--date", help="CBR FX rate date as YYYY-MM-DD. Only used by cbr_fx.")
    parser.add_argument(
        "--from-date",
        help="Inclusive start date as YYYY-MM-DD. Used by cbr_fx, energy, benchmark, weather, and news collectors.",
    )
    parser.add_argument(
        "--to-date",
        help="Inclusive end date as YYYY-MM-DD. Used by cbr_fx, energy, benchmark, weather, and news collectors.",
    )
    parser.add_argument("--endpoint", default="historys", help="Historical collector endpoint alias. Phase 4.6 supports only historys.")
    parser.add_argument("--product-code", help="Optional product code for jijinhao_historical_prices.")
    parser.add_argument("--days", type=int, default=30, help="Historical collector lookback window. Phase 4.6 max is 30.")
    parser.add_argument("--series", help="Optional FRED series id for fred_energy_prices, for example DCOILBRENTEU.")
    parser.add_argument("--benchmark", help="Optional World Bank Pink Sheet benchmark code.")
    parser.add_argument("--region", help="Optional weather region code for open_meteo_historical_weather.")
    parser.add_argument("--query-key", help="Optional GDELT news query preset key, for example soybean.")
    parser.add_argument("--query", help="Optional custom GDELT news query string.")
    parser.add_argument("--maxrecords", type=int, help="Optional GDELT or UN Comtrade maxrecords value.")
    parser.add_argument("--hs-code", help="Required HS code for un_comtrade, for example 1507.")
    parser.add_argument("--from-period", help="Inclusive monthly period as YYYY-MM. Used by un_comtrade.")
    parser.add_argument("--to-period", help="Inclusive monthly period as YYYY-MM. Used by un_comtrade.")
    parser.add_argument("--reporter", help="Reporter code for un_comtrade, for example BRA.")
    parser.add_argument("--partner", help="Partner code for un_comtrade, for example WLD.")
    parser.add_argument("--flow", choices=["import", "export", "re_export", "re_import"], default="export")
    parser.add_argument("--commodity-family", help="Required commodity family for usda_psd, for example soybean_oil.")
    parser.add_argument("--from-marketing-year", type=int, help="Inclusive start marketing year for usda_psd.")
    parser.add_argument("--to-marketing-year", type=int, help="Inclusive end marketing year for usda_psd.")
    parser.add_argument("--country", help="Country code for usda_psd, for example WLD.")
    parser.add_argument("--dry-run", action="store_true", help="Parse and persist raw evidence without normalized writes. Used by usda_psd.")
    parser.add_argument("--fixture-file", help="Local USDA PSD fixture JSON, CSV, or ZIP file. Used by usda_psd.")
    parser.add_argument("--live-probe", action="store_true", help="Opt in to a bounded USDA PSD live probe. Used by usda_psd.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    setup_logging()

    collection_slot = None
    if args.run_type == "scheduled":
        if not args.collection_slot:
            parser.error("--collection-slot is required when --run-type scheduled")
        try:
            collection_slot = _parse_collection_slot(args.collection_slot)
        except ValueError as exc:
            parser.error(str(exc))

    requested_date = None
    if args.date:
        try:
            requested_date = date.fromisoformat(args.date)
        except ValueError:
            parser.error("--date must use YYYY-MM-DD format")

    from_date = None
    to_date = None
    if args.from_date or args.to_date:
        if not args.from_date or not args.to_date:
            parser.error("--from-date and --to-date must be provided together")
        if args.date:
            parser.error("--date cannot be combined with --from-date/--to-date")
        if args.collector_name == "cbr_fx" and args.run_type != "manual":
            parser.error("--from-date/--to-date backfill only supports the default manual CLI mode")
        if (
            args.collector_name
            in {"fred_energy_prices", "world_bank_pink_sheet", "open_meteo_historical_weather", "gdelt_news"}
            and args.run_type == "scheduled"
        ):
            parser.error(f"scheduled runs are not supported for {args.collector_name}")
        try:
            from_date = date.fromisoformat(args.from_date)
            to_date = date.fromisoformat(args.to_date)
        except ValueError:
            parser.error("--from-date and --to-date must use YYYY-MM-DD format")
        if from_date > to_date:
            parser.error("--from-date must be on or before --to-date")
        if args.collector_name == "open_meteo_historical_weather":
            days_count = (to_date - from_date).days + 1
            if days_count > OPEN_METEO_MAX_DAYS_PER_RUN:
                parser.error(f"--from-date/--to-date range exceeds {OPEN_METEO_MAX_DAYS_PER_RUN} days")

    if args.collector_name != "jijinhao_historical_prices" and args.product_code:
        parser.error("--product-code is only supported for jijinhao_historical_prices")
    if args.collector_name != "jijinhao_historical_prices" and args.endpoint != "historys":
        parser.error("--endpoint is only supported for jijinhao_historical_prices")
    if args.collector_name != "jijinhao_historical_prices" and args.days != 30:
        parser.error("--days is only supported for jijinhao_historical_prices")
    if args.collector_name != "fred_energy_prices" and args.series:
        parser.error("--series is only supported for fred_energy_prices")
    if args.collector_name != "world_bank_pink_sheet" and args.benchmark:
        parser.error("--benchmark is only supported for world_bank_pink_sheet")
    if args.collector_name != "open_meteo_historical_weather" and args.region:
        parser.error("--region is only supported for open_meteo_historical_weather")
    if args.collector_name != "gdelt_news" and args.query_key:
        parser.error("--query-key is only supported for gdelt_news")
    if args.collector_name != "gdelt_news" and args.query:
        parser.error("--query is only supported for gdelt_news")
    if args.collector_name not in {"gdelt_news", "un_comtrade", "usda_psd"} and args.maxrecords is not None:
        parser.error("--maxrecords is only supported for gdelt_news, un_comtrade, and usda_psd")
    if args.collector_name != "un_comtrade":
        if args.hs_code or args.from_period or args.to_period or args.reporter or args.partner:
            parser.error("--hs-code/--from-period/--to-period/--reporter/--partner are only supported for un_comtrade")
        if args.flow != "export":
            parser.error("--flow is only supported for un_comtrade")
    if args.collector_name != "usda_psd":
        if (
            args.commodity_family
            or args.from_marketing_year is not None
            or args.to_marketing_year is not None
            or args.country
            or args.fixture_file
            or args.live_probe
            or args.dry_run
        ):
            parser.error(
                "--commodity-family/--from-marketing-year/--to-marketing-year/--country/"
                "--fixture-file/--live-probe/--dry-run are only supported for usda_psd"
            )

    if args.collector_name == "current_price_source":
        if requested_date is not None or from_date is not None or to_date is not None:
            parser.error(
                "--date/--from-date/--to-date are only supported for cbr_fx, "
                "fred_energy_prices, and world_bank_pink_sheet"
            )
        if args.run_type == "backfill":
            parser.error("--run-type backfill is not supported for current_price_source")
        result = CurrentPriceSourceCollector().run(run_type=args.run_type, collection_slot=collection_slot)
    elif args.collector_name == "cbr_fx":
        if args.run_type == "backfill":
            parser.error("use --from-date/--to-date for cbr_fx backfill")
        collector = CbrFxCollector()
        if from_date is not None and to_date is not None:
            result = collector.run_backfill(from_date=from_date, to_date=to_date)
        else:
            result = collector.run(
                run_type=args.run_type,
                collection_slot=collection_slot,
                requested_date=requested_date,
            )
    elif args.collector_name == "jijinhao_historical_prices":
        if args.endpoint != "historys":
            parser.error(f"{args.endpoint} is not supported for production historical collector in Phase 4.6")
        if requested_date is not None or from_date is not None or to_date is not None or collection_slot is not None:
            parser.error("date, date ranges, and collection slots are not supported for jijinhao_historical_prices")
        if args.run_type == "scheduled":
            parser.error("scheduled runs are not supported for jijinhao_historical_prices in Phase 4.6")
        result = JijinhaoHistoricalPricesCollector().run(
            product_code=args.product_code,
            days=args.days,
            run_type=args.run_type,
            endpoint_alias=args.endpoint,
        )
    elif args.collector_name == "fred_energy_prices":
        if requested_date is not None or collection_slot is not None:
            parser.error("--date and --collection-slot are not supported for fred_energy_prices")
        if args.run_type == "scheduled":
            parser.error("scheduled runs are not supported for fred_energy_prices")
        if args.series and not is_known_series(args.series):
            parser.error(f"unknown FRED energy series: {args.series}")
        result = FredEnergyPricesCollector().run(
            series_id=args.series,
            from_date=from_date,
            to_date=to_date,
            run_type=args.run_type,
        )
    elif args.collector_name == "open_meteo_historical_weather":
        if requested_date is not None or collection_slot is not None:
            parser.error("--date and --collection-slot are not supported for open_meteo_historical_weather")
        if from_date is None or to_date is None:
            parser.error("--from-date and --to-date are required for open_meteo_historical_weather")
        if args.run_type == "scheduled":
            parser.error("scheduled runs are not supported for open_meteo_historical_weather")
        result = OpenMeteoHistoricalWeatherCollector().run(
            region_code=args.region,
            from_date=from_date,
            to_date=to_date,
            run_type=args.run_type,
        )
    elif args.collector_name == "gdelt_news":
        if requested_date is not None or collection_slot is not None:
            parser.error("--date and --collection-slot are not supported for gdelt_news")
        if from_date is None or to_date is None:
            parser.error("--from-date and --to-date are required for gdelt_news")
        if args.run_type != "manual":
            parser.error("gdelt_news is manual-only in Phase 6.4D")
        if bool(args.query_key) == bool(args.query):
            parser.error("provide exactly one of --query-key or --query for gdelt_news")
        if args.query_key and not is_known_query_key(args.query_key):
            parser.error(f"unknown GDELT query-key: {args.query_key}")
        result = GdeltNewsCollector().run(
            query_key=args.query_key,
            query=args.query,
            from_date=from_date,
            to_date=to_date,
            maxrecords=args.maxrecords,
            run_type=args.run_type,
        )
    elif args.collector_name == "un_comtrade":
        if requested_date is not None or collection_slot is not None:
            parser.error("--date and --collection-slot are not supported for un_comtrade")
        if from_date is not None or to_date is not None:
            parser.error("--from-date/--to-date are not supported for un_comtrade; use --from-period/--to-period")
        if args.run_type == "scheduled":
            parser.error("scheduled runs are not supported for un_comtrade")
        missing = [
            name
            for name, value in (
                ("--hs-code", args.hs_code),
                ("--from-period", args.from_period),
                ("--to-period", args.to_period),
                ("--reporter", args.reporter),
                ("--partner", args.partner),
            )
            if not value
        ]
        if missing:
            parser.error(f"{', '.join(missing)} are required for un_comtrade")
        result = UnComtradeCollector().run(
            hs_code=args.hs_code,
            from_period=args.from_period,
            to_period=args.to_period,
            reporter=args.reporter,
            partner=args.partner,
            flow=args.flow,
            maxrecords=args.maxrecords,
            run_type=args.run_type,
        )
    elif args.collector_name == "usda_psd":
        if requested_date is not None or collection_slot is not None:
            parser.error("--date and --collection-slot are not supported for usda_psd")
        if from_date is not None or to_date is not None:
            parser.error("--from-date/--to-date are not supported for usda_psd; use --from-marketing-year/--to-marketing-year")
        if args.run_type == "scheduled":
            parser.error("scheduled runs are not supported for usda_psd")
        missing = [
            name
            for name, value in (
                ("--commodity-family", args.commodity_family),
                ("--from-marketing-year", args.from_marketing_year),
                ("--to-marketing-year", args.to_marketing_year),
                ("--country", args.country),
            )
            if value in (None, "")
        ]
        if missing:
            parser.error(f"{', '.join(missing)} are required for usda_psd")
        if bool(args.fixture_file) == bool(args.live_probe):
            parser.error("provide exactly one of --fixture-file or --live-probe for usda_psd")
        result = UsdaPsdCollector().run(
            commodity_family=args.commodity_family,
            from_marketing_year=args.from_marketing_year,
            to_marketing_year=args.to_marketing_year,
            country=args.country,
            maxrecords=args.maxrecords,
            dry_run=args.dry_run,
            fixture_file=args.fixture_file,
            live_probe=args.live_probe,
            run_type=args.run_type,
        )
    else:
        if requested_date is not None or collection_slot is not None:
            parser.error("--date and --collection-slot are not supported for world_bank_pink_sheet")
        if args.run_type != "manual":
            parser.error("world_bank_pink_sheet is manual-only in Phase 6.2D")
        if args.benchmark and not is_known_benchmark(args.benchmark):
            parser.error(f"unknown World Bank Pink Sheet benchmark: {args.benchmark}")
        result = WorldBankPinkSheetCollector().run(
            benchmark_code=args.benchmark,
            from_date=from_date,
            to_date=to_date,
            run_type=args.run_type,
        )
    print(f"run_id={result.run_id}")
    print(f"status={result.status}")
    if hasattr(result, "endpoint_alias"):
        print(f"endpoint_alias={result.endpoint_alias}")
    if hasattr(result, "query_key"):
        print(f"query_key={result.query_key}")
    if hasattr(result, "query"):
        print(f"query={result.query}")
    if hasattr(result, "maxrecords"):
        print(f"maxrecords={result.maxrecords}")
    if hasattr(result, "hs_code"):
        print(f"hs_code={result.hs_code}")
        print(f"from_period={result.from_period}")
        print(f"to_period={result.to_period}")
        print(f"reporter={result.reporter}")
        print(f"partner={result.partner}")
        print(f"flow={result.flow}")
    if hasattr(result, "commodity_family"):
        print(f"commodity_family={result.commodity_family}")
        print(f"from_marketing_year={result.from_marketing_year}")
        print(f"to_marketing_year={result.to_marketing_year}")
        print(f"country={result.country}")
        print(f"dry_run={result.dry_run}")
        print(f"fixture_file={result.fixture_file}")
        print(f"live_probe={result.live_probe}")
    if hasattr(result, "products_processed"):
        print(f"products_processed={result.products_processed}")
    if hasattr(result, "series_requested"):
        print(f"series_requested={result.series_requested}")
        print(f"series_success={result.series_success}")
        print(f"series_failed={result.series_failed}")
    if hasattr(result, "benchmarks_requested"):
        print(f"benchmarks_requested={result.benchmarks_requested}")
        print(f"benchmarks_success={result.benchmarks_success}")
        print(f"benchmarks_failed={result.benchmarks_failed}")
    if hasattr(result, "regions_requested"):
        print(f"regions_requested={result.regions_requested}")
        print(f"regions_success={result.regions_success}")
        print(f"regions_failed={result.regions_failed}")
    if hasattr(result, "benchmarks"):
        print(f"benchmarks={','.join(result.benchmarks)}")
    if hasattr(result, "instruments"):
        print(f"instruments={','.join(result.instruments)}")
    if hasattr(result, "regions"):
        print(f"regions={','.join(result.regions)}")
    if hasattr(result, "from_date"):
        print(f"from_date={result.from_date}")
        print(f"to_date={result.to_date}")
    if hasattr(result, "dates_requested"):
        print(f"dates_requested={result.dates_requested}")
        print(f"dates_success={result.dates_success}")
        print(f"dates_failed={result.dates_failed}")
    print(f"records_found={result.records_found}")
    print(f"records_written={result.records_written}")
    if hasattr(result, "skipped_existing"):
        print(f"skipped_existing={result.skipped_existing}")
    if hasattr(result, "skipped_unmapped"):
        print(f"skipped_unmapped={result.skipped_unmapped}")
    if hasattr(result, "updated_existing"):
        print(f"updated_existing={result.updated_existing}")
    if hasattr(result, "revisions_written"):
        print(f"revisions_written={result.revisions_written}")
    if hasattr(result, "conflicts_count"):
        print(f"conflicts_count={result.conflicts_count}")
    if hasattr(result, "skipped_malformed"):
        print(f"skipped_malformed={result.skipped_malformed}")
    if hasattr(result, "skipped_expected"):
        print(f"skipped_expected={result.skipped_expected}")
    if hasattr(result, "observed_at_values"):
        print(f"observed_at_values={','.join(result.observed_at_values)}")
    if hasattr(result, "currency_pairs"):
        print(f"currency_pairs={','.join(result.currency_pairs)}")
    print(f"errors_count={result.errors_count}")
    if result.error_message:
        print("errors:")
        print(result.error_message)


def _parse_collection_slot(value: str) -> datetime:
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError(f"invalid collection-slot ISO datetime: {value}") from exc
    if parsed.tzinfo is None:
        raise ValueError("collection-slot must include timezone offset")
    return parsed.astimezone(timezone.utc)


if __name__ == "__main__":
    main()
