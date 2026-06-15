from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from app.config.logging import setup_logging
from app.features.daily import build_daily_features
from app.features.news_daily import build_news_daily_features
from app.features.supply_demand_daily import build_supply_demand_daily_features
from app.features.trade_daily import build_trade_daily_features
from app.features.weather_daily import build_weather_daily_features


def main() -> None:
    parser = argparse.ArgumentParser(description="Build derived dataset features.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    daily = subparsers.add_parser("daily", help="Build daily product price and FX features.")
    daily.add_argument("--from-date", help="Inclusive start date as YYYY-MM-DD.")
    daily.add_argument("--to-date", help="Inclusive end date as YYYY-MM-DD.")
    weather_daily = subparsers.add_parser("weather_daily", help="Build daily weather features by region.")
    weather_daily.add_argument("--region", help="Optional weather region code.")
    weather_daily.add_argument("--from-date", help="Inclusive start date as YYYY-MM-DD.")
    weather_daily.add_argument("--to-date", help="Inclusive end date as YYYY-MM-DD.")
    news_daily = subparsers.add_parser("news_daily", help="Build daily news/event features by product.")
    news_daily.add_argument("--product", help="Optional product code.")
    news_daily.add_argument("--commodity-family", help="Optional commodity family filter.")
    news_daily.add_argument("--from-date", help="Inclusive start date as YYYY-MM-DD.")
    news_daily.add_argument("--to-date", help="Inclusive end date as YYYY-MM-DD.")
    trade_daily = subparsers.add_parser("trade_daily", help="Build daily product trade features.")
    trade_daily.add_argument("--product", help="Optional product code.")
    trade_daily.add_argument("--from-date", help="Inclusive start date as YYYY-MM-DD.")
    trade_daily.add_argument("--to-date", help="Inclusive end date as YYYY-MM-DD.")
    supply_demand_daily = subparsers.add_parser("supply_demand_daily", help="Build daily product supply-demand features.")
    supply_demand_daily.add_argument("--product", help="Optional product code.")
    supply_demand_daily.add_argument("--from-date", help="Inclusive start date as YYYY-MM-DD.")
    supply_demand_daily.add_argument("--to-date", help="Inclusive end date as YYYY-MM-DD.")
    args = parser.parse_args()

    setup_logging()

    if args.command == "daily":
        from_date = _parse_date_arg(parser, "--from-date", args.from_date)
        to_date = _parse_date_arg(parser, "--to-date", args.to_date)
        if (from_date is None) != (to_date is None):
            parser.error("--from-date and --to-date must be provided together")
        if from_date is not None and to_date is not None and from_date > to_date:
            parser.error("--from-date must be on or before --to-date")
        result = build_daily_features(from_date=from_date, to_date=to_date)
        print(f"products_processed={result.products_processed}")
        print(f"dates_processed={result.dates_processed}")
        print(f"rows_created={result.rows_created}")
        print(f"rows_updated={result.rows_updated}")
        print(f"rows_skipped={result.rows_skipped}")
        print(f"missing_fx_dates={','.join(result.missing_fx_dates)}")
        print(f"warnings_count={result.warnings_count}")
    elif args.command == "weather_daily":
        from_date = _parse_date_arg(parser, "--from-date", args.from_date)
        to_date = _parse_date_arg(parser, "--to-date", args.to_date)
        if (from_date is None) != (to_date is None):
            parser.error("--from-date and --to-date must be provided together")
        if from_date is not None and to_date is not None and from_date > to_date:
            parser.error("--from-date must be on or before --to-date")
        result = build_weather_daily_features(
            region_code=args.region,
            from_date=from_date,
            to_date=to_date,
        )
        print(f"regions_processed={result.regions_processed}")
        print(f"dates_processed={result.dates_processed}")
        print(f"rows_created={result.rows_created}")
        print(f"rows_updated={result.rows_updated}")
        print(f"rows_skipped={result.rows_skipped}")
        print(f"warnings_count={result.warnings_count}")
        print(f"missing_observation_regions={','.join(result.missing_observation_regions)}")
    elif args.command == "news_daily":
        from_date = _parse_date_arg(parser, "--from-date", args.from_date)
        to_date = _parse_date_arg(parser, "--to-date", args.to_date)
        if (from_date is None) != (to_date is None):
            parser.error("--from-date and --to-date must be provided together")
        if from_date is not None and to_date is not None and from_date > to_date:
            parser.error("--from-date must be on or before --to-date")
        result = build_news_daily_features(
            product_code=args.product,
            commodity_family=args.commodity_family,
            from_date=from_date,
            to_date=to_date,
        )
        print(f"products_processed={result.products_processed}")
        print(f"dates_processed={result.dates_processed}")
        print(f"rows_created={result.rows_created}")
        print(f"rows_updated={result.rows_updated}")
        print(f"rows_skipped={result.rows_skipped}")
        print(f"warnings_count={result.warnings_count}")
        print(f"missing_news_products={','.join(result.missing_news_products)}")
    elif args.command == "trade_daily":
        from_date = _parse_date_arg(parser, "--from-date", args.from_date)
        to_date = _parse_date_arg(parser, "--to-date", args.to_date)
        if (from_date is None) != (to_date is None):
            parser.error("--from-date and --to-date must be provided together")
        if from_date is not None and to_date is not None and from_date > to_date:
            parser.error("--from-date must be on or before --to-date")
        result = build_trade_daily_features(
            product_code=args.product,
            from_date=from_date,
            to_date=to_date,
        )
        print(f"products_processed={result.products_processed}")
        print(f"dates_processed={result.dates_processed}")
        print(f"rows_created={result.rows_created}")
        print(f"rows_updated={result.rows_updated}")
        print(f"rows_skipped={result.rows_skipped}")
        print(f"warnings_count={result.warnings_count}")
        print(f"missing_trade_products={','.join(result.missing_trade_products)}")
    elif args.command == "supply_demand_daily":
        from_date = _parse_date_arg(parser, "--from-date", args.from_date)
        to_date = _parse_date_arg(parser, "--to-date", args.to_date)
        if (from_date is None) != (to_date is None):
            parser.error("--from-date and --to-date must be provided together")
        if from_date is not None and to_date is not None and from_date > to_date:
            parser.error("--from-date must be on or before --to-date")
        result = build_supply_demand_daily_features(
            product_code=args.product,
            from_date=from_date,
            to_date=to_date,
        )
        print(f"products_processed={result.products_processed}")
        print(f"dates_processed={result.dates_processed}")
        print(f"rows_created={result.rows_created}")
        print(f"rows_updated={result.rows_updated}")
        print(f"rows_skipped={result.rows_skipped}")
        print(f"warnings_count={result.warnings_count}")
        print(f"missing_products={','.join(result.missing_products)}")
        print(f"observations_used={result.observations_used}")


def _parse_date_arg(parser: argparse.ArgumentParser, name: str, value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        parser.error(f"{name} must use YYYY-MM-DD format")


if __name__ == "__main__":
    main()
