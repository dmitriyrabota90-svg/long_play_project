from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from app.config.logging import setup_logging
from app.collectors.prices.current_price_source import CurrentPriceSourceCollector


def main() -> None:
    parser = argparse.ArgumentParser(description="Run a collector by name.")
    parser.add_argument("collector_name", help="Collector name to run")
    parser.add_argument("--run-type", choices=["manual", "scheduled"], default="manual")
    parser.add_argument(
        "--collection-slot",
        help="Required for scheduled runs. ISO datetime, for example 2026-05-12T09:00:00+00:00.",
    )
    args = parser.parse_args()

    setup_logging()
    if args.collector_name != "current_price_source":
        print(
            f"Collector '{args.collector_name}' is not implemented yet. "
            "Available collector: current_price_source."
        )
        return

    collection_slot = None
    if args.run_type == "scheduled":
        if not args.collection_slot:
            parser.error("--collection-slot is required when --run-type scheduled")
        try:
            collection_slot = _parse_collection_slot(args.collection_slot)
        except ValueError as exc:
            parser.error(str(exc))

    result = CurrentPriceSourceCollector().run(run_type=args.run_type, collection_slot=collection_slot)
    print(f"run_id={result.run_id}")
    print(f"status={result.status}")
    print(f"records_found={result.records_found}")
    print(f"records_written={result.records_written}")
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
