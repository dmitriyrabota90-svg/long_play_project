"""Validate a local snapshot and construct strict h=1 supervised samples."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from smoke_test import (  # noqa: E402
    CANDIDATE_FEATURES,
    build_supervised_samples,
    load_snapshot,
    validate_snapshot,
    write_csv,
    write_snapshot_metadata,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    root = HERE.parent
    parser.add_argument("--snapshot", type=Path, default=root / "data" / "dataset_snapshot.csv")
    parser.add_argument("--metadata", type=Path, default=root / "data" / "dataset_snapshot_metadata.json")
    parser.add_argument("--samples", type=Path, default=root / "data" / "supervised_samples.csv")
    parser.add_argument("--validation", type=Path, default=root / "reports" / "data_validation.json")
    parser.add_argument("--production-head", required=True)
    parser.add_argument("--extraction-timestamp", default=datetime.now(timezone.utc).isoformat())
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    rows = load_snapshot(args.snapshot)
    validation = validate_snapshot(rows)
    samples = build_supervised_samples(rows)
    by_product = {}
    for product in sorted({row["product_code"] for row in rows}):
        product_samples = [row for row in samples if row["product_code"] == product]
        by_product[product] = len(product_samples)
    validation.update(
        {
            "target": "log(price[t+1] / price[t]) using the next calendar day with both 09:00 and 18:00 slots",
            "sample_counts_by_product": by_product,
            "sample_count_total": len(samples),
            "candidate_features": list(CANDIDATE_FEATURES),
        }
    )
    serializable = []
    for sample in samples:
        record = dict(sample)
        record["feature_date"] = record["feature_date"].isoformat()
        record["target_date"] = record["target_date"].isoformat()
        record["as_of_at"] = record["as_of_at"].isoformat()
        record["fx_as_of_date"] = record["fx_as_of_date"].isoformat()
        serializable.append(record)
    fields = [
        "product_code", "feature_date", "target_date", "as_of_at", "price_last", "future_price",
        "target_return", "price_observations_count", "has_regular_price_slots", "fx_as_of_date", *CANDIDATE_FEATURES,
    ]
    write_csv(args.samples, serializable, fields)
    args.validation.parent.mkdir(parents=True, exist_ok=True)
    args.validation.write_text(json.dumps(validation, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    write_snapshot_metadata(args.metadata, args.snapshot, rows, args.production_head, args.extraction_timestamp)
    print(json.dumps(validation, sort_keys=True))


if __name__ == "__main__":
    main()
