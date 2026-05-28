from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from app.discovery.historical_price_probe import endpoint_aliases, probe_historical_prices


def main() -> None:
    parser = argparse.ArgumentParser(description="Diagnostics-only historical price probe for confirmed Jijinhao instruments.")
    parser.add_argument("--endpoint", choices=endpoint_aliases(), required=True)
    parser.add_argument("--all-confirmed", action="store_true", help="Probe all confirmed production instruments.")
    parser.add_argument("--product-code", action="append", default=[], help="Probe one or more product codes.")
    parser.add_argument("--days", type=int, default=30)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--output-dir", default="diagnostics/historical_price_probe")
    parser.add_argument(
        "--no-db-compare",
        action="store_true",
        help="Skip read-only comparison against production price_observations.",
    )
    args = parser.parse_args()

    if args.all_confirmed and args.product_code:
        parser.error("--all-confirmed and --product-code are mutually exclusive")
    if not args.all_confirmed and not args.product_code:
        parser.error("supply --all-confirmed or at least one --product-code")

    product_codes = None if args.all_confirmed else tuple(args.product_code)
    run = probe_historical_prices(
        endpoint_alias=args.endpoint,
        product_codes=product_codes,
        days=args.days,
        timeout=args.timeout,
        output_dir=Path(args.output_dir),
        include_comparison=not args.no_db_compare,
    )

    print(f"endpoint={run.endpoint_alias}")
    print(f"days={run.days}")
    print(f"products={len(run.products)}")
    for product in run.products:
        print(
            " ".join(
                [
                    f"product_code={product.product_code}",
                    f"external_code={product.external_code}",
                    f"status={product.status}",
                    f"http_status={product.http_status}",
                    f"bytes_size={product.bytes_size}",
                    f"rows_count={product.rows_count}",
                ]
            )
        )
    print(f"comparisons={len(run.comparisons)}")
    if run.comparison_error:
        print(f"comparison_error={run.comparison_error}")
    print(f"output_dir={args.output_dir}")


if __name__ == "__main__":
    main()
