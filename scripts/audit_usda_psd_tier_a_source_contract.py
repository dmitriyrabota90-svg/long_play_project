from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.audits.usda_psd_tier_a_source_contract import (  # noqa: E402
    audit_usda_psd_tier_a_source_contract,
    write_usda_psd_tier_a_source_contract_report,
)
from app.collectors.supply_demand.usda_psd_config import (  # noqa: E402
    DOWNLOADABLE_DATASET_ENDPOINT,
    HEADERS,
    REQUEST_TIMEOUT,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Audit the local USDA PSD ZIP/CSV contract for reviewed Tier A baskets.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--zip-path", type=Path)
    source.add_argument("--csv-path", type=Path)
    source.add_argument(
        "--download-to",
        type=Path,
        help="Explicit temporary ZIP destination under /tmp; downloads the project-config USDA PSD URL.",
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--product-code", default="soybean_oil")
    parser.add_argument("--marketing-years", required=True, type=_parse_years)
    parser.add_argument("--format", choices=("json", "md", "markdown"), default="json")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    source_path = args.zip_path or args.csv_path
    if args.download_to is not None:
        source_path = _download_to_tmp(args.download_to)
    audit = audit_usda_psd_tier_a_source_contract(
        source_path=source_path,
        product_code=args.product_code,
        marketing_years=args.marketing_years,
    )
    output = write_usda_psd_tier_a_source_contract_report(
        audit,
        output_path=args.output,
        output_format=args.format,
    )
    status_counts: dict[str, int] = {}
    for row in audit["availability_matrix"]:
        status_counts[row["status"]] = status_counts.get(row["status"], 0) + 1
    print(f"output={output}")
    print(f"source_path={source_path}")
    print(f"source_size_bytes={audit['source_size_bytes']}")
    print(f"raw_csv_member_name={audit['raw_csv_member_name']}")
    print(f"matrix_rows={len(audit['availability_matrix'])}")
    print(f"unexpected_issues_count={audit['unexpected_issues_count']}")
    print("statuses=" + ",".join(f"{key}:{status_counts[key]}" for key in sorted(status_counts)))


def _download_to_tmp(path: Path) -> Path:
    resolved = path.expanduser().resolve()
    tmp_root = Path("/tmp").resolve()
    if not resolved.is_relative_to(tmp_root):
        raise ValueError("--download-to must resolve under /tmp")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    response = httpx.get(
        DOWNLOADABLE_DATASET_ENDPOINT,
        headers=HEADERS,
        timeout=REQUEST_TIMEOUT,
        follow_redirects=True,
    )
    response.raise_for_status()
    resolved.write_bytes(response.content)
    return resolved


def _parse_years(value: str) -> tuple[str, ...]:
    years = tuple(dict.fromkeys(item.strip() for item in value.split(",") if item.strip()))
    if not years:
        raise argparse.ArgumentTypeError("marketing years must not be empty")
    return years


if __name__ == "__main__":
    main()
