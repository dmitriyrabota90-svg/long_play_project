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
from app.collectors.fx.cbr_fx import CbrFxCollector
from app.collectors.prices.current_price_source import CurrentPriceSourceCollector


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a collector by name.")
    parser.add_argument("collector_name", choices=["current_price_source", "cbr_fx"], help="Collector name to run")
    parser.add_argument("--run-type", choices=["manual", "scheduled"], default="manual")
    parser.add_argument(
        "--collection-slot",
        help="Required for scheduled runs. ISO datetime, for example 2026-05-12T09:00:00+00:00.",
    )
    parser.add_argument("--date", help="CBR FX rate date as YYYY-MM-DD. Only used by cbr_fx.")
    parser.add_argument("--from-date", help="CBR FX backfill start date as YYYY-MM-DD. Only used by cbr_fx.")
    parser.add_argument("--to-date", help="CBR FX backfill end date as YYYY-MM-DD. Only used by cbr_fx.")
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
        if args.run_type != "manual":
            parser.error("--from-date/--to-date backfill only supports the default manual CLI mode")
        try:
            from_date = date.fromisoformat(args.from_date)
            to_date = date.fromisoformat(args.to_date)
        except ValueError:
            parser.error("--from-date and --to-date must use YYYY-MM-DD format")
        if from_date > to_date:
            parser.error("--from-date must be on or before --to-date")

    if args.collector_name == "current_price_source":
        if requested_date is not None or from_date is not None or to_date is not None:
            parser.error("--date/--from-date/--to-date are only supported for cbr_fx")
        result = CurrentPriceSourceCollector().run(run_type=args.run_type, collection_slot=collection_slot)
    else:
        collector = CbrFxCollector()
        if from_date is not None and to_date is not None:
            result = collector.run_backfill(from_date=from_date, to_date=to_date)
        else:
            result = collector.run(
                run_type=args.run_type,
                collection_slot=collection_slot,
                requested_date=requested_date,
            )
    print(f"run_id={result.run_id}")
    print(f"status={result.status}")
    if hasattr(result, "dates_requested"):
        print(f"dates_requested={result.dates_requested}")
        print(f"dates_success={result.dates_success}")
        print(f"dates_failed={result.dates_failed}")
    print(f"records_found={result.records_found}")
    print(f"records_written={result.records_written}")
    if hasattr(result, "skipped_existing"):
        print(f"skipped_existing={result.skipped_existing}")
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
