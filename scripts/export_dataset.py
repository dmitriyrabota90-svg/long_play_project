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
from app.exports.daily_features_export import EXPORT_NAME, DatasetExportError, export_daily_features


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD format") from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export dataset artifacts.")
    parser.add_argument("--list", action="store_true", help="List available dataset exports.")
    subparsers = parser.add_subparsers(dest="command")

    daily = subparsers.add_parser("daily_features", help="Export daily_product_features v1.")
    daily.add_argument("--from-date", type=_parse_date, default=None, help="Inclusive start date YYYY-MM-DD.")
    daily.add_argument("--to-date", type=_parse_date, default=None, help="Inclusive end date YYYY-MM-DD.")
    daily.add_argument("--format", choices=["csv", "parquet", "both"], default="csv", help="Output format.")
    daily.add_argument("--output-dir", type=Path, default=None, help="Output directory under data/exports.")
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    if args.list:
        print(EXPORT_NAME)
        return
    if args.command is None:
        parser.error("a command is required unless --list is used")
    setup_logging()
    try:
        if args.command == "daily_features":
            result = export_daily_features(
                from_date=args.from_date,
                to_date=args.to_date,
                export_format=args.format,
                output_dir=args.output_dir,
            )
        else:
            parser.error(f"Unsupported command: {args.command}")
            return
    except DatasetExportError as exc:
        print(f"export failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(f"export_name={result.export_name}")
    print(f"export_version={result.export_version}")
    print(f"row_count={result.row_count}")
    print(f"column_count={result.column_count}")
    print(f"products={','.join(result.products)}")
    print(f"feature_date_min={result.feature_date_min}")
    print(f"feature_date_max={result.feature_date_max}")
    print(f"formats={','.join(result.formats)}")
    for item in result.files:
        print(f"{item['format']}_path={item['path']}")
        print(f"{item['format']}_sha256={item['sha256']}")
    print(f"manifest_path={result.manifest_path}")


if __name__ == "__main__":
    main()
