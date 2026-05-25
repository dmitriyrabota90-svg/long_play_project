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


def main() -> None:
    parser = argparse.ArgumentParser(description="Build derived dataset features.")
    subparsers = parser.add_subparsers(dest="command", required=True)
    daily = subparsers.add_parser("daily", help="Build daily product price and FX features.")
    daily.add_argument("--from-date", help="Inclusive start date as YYYY-MM-DD.")
    daily.add_argument("--to-date", help="Inclusive end date as YYYY-MM-DD.")
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


def _parse_date_arg(parser: argparse.ArgumentParser, name: str, value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        parser.error(f"{name} must use YYYY-MM-DD format")


if __name__ == "__main__":
    main()
