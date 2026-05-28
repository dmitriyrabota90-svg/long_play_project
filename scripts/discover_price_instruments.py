from __future__ import annotations

import argparse
from pathlib import Path

from app.discovery.price_instruments import (
    build_custom_candidate,
    discover_price_instruments,
    write_discovery_outputs,
)


def main() -> None:
    parser = argparse.ArgumentParser(description="Read-only discovery for current-price instrument candidates.")
    parser.add_argument("--output-dir", default="diagnostics/discovery")
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--product-code")
    parser.add_argument("--title")
    parser.add_argument("--endpoint")
    parser.add_argument("--external-code")
    parser.add_argument("--parser-type", choices=("json", "csv"))
    parser.add_argument("--response-prefix")
    parser.add_argument("--price-path", nargs="*")
    parser.add_argument("--price-index", type=int)
    parser.add_argument("--expected-keyword", action="append", default=[])
    args = parser.parse_args()

    custom_fields = [args.product_code, args.title, args.endpoint, args.external_code, args.parser_type]
    if any(custom_fields) and not all(custom_fields):
        parser.error("--product-code, --title, --endpoint, --external-code, and --parser-type must be supplied together")

    candidates = None
    if all(custom_fields):
        candidates = (
            build_custom_candidate(
                product_code=args.product_code,
                title=args.title,
                endpoint=args.endpoint,
                external_code=args.external_code,
                parser_type=args.parser_type,
                response_prefix=args.response_prefix,
                price_path=tuple(args.price_path) if args.price_path else None,
                price_index=args.price_index,
                expected_keywords=tuple(args.expected_keyword),
            ),
        )

    if candidates is None:
        results = discover_price_instruments(timeout=args.timeout)
    else:
        results = discover_price_instruments(candidates=candidates, timeout=args.timeout)
    write_discovery_outputs(results, Path(args.output_dir))

    for result in results:
        print(
            " ".join(
                [
                    f"product_code={result.product_code}",
                    f"status={result.status}",
                    f"external_code={result.external_code or 'not_found'}",
                    f"parser_type={result.parser_type or 'not_found'}",
                    f"sample_price={result.sample_price if result.sample_price is not None else 'not_found'}",
                ]
            )
        )
    print(f"output_dir={args.output_dir}")


if __name__ == "__main__":
    main()
