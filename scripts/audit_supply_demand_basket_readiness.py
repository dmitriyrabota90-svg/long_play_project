from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.audits.supply_demand_basket_readiness import (  # noqa: E402
    VALID_AUDIT_SCOPES,
    audit_supply_demand_basket_readiness,
    load_supply_demand_basket_inventory,
    write_supply_demand_basket_readiness,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit reviewed Tier A supply-demand basket readiness from a local inventory export."
    )
    parser.add_argument("--input", required=True, type=Path, help="JSON normalized-observation inventory path.")
    parser.add_argument("--output", required=True, type=Path, help="Explicit output artifact path.")
    parser.add_argument("--product-code", default="soybean_oil")
    parser.add_argument("--commodity-family", default="soybean_oil")
    parser.add_argument("--audit-as-of-date", required=True, type=_parse_date)
    parser.add_argument("--required-marketing-years", required=True, type=_parse_years)
    parser.add_argument("--audit-scope", choices=sorted(VALID_AUDIT_SCOPES), default="local_fixture")
    parser.add_argument("--format", choices=("json", "csv", "md"), default="json")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    records = load_supply_demand_basket_inventory(args.input)
    audit = audit_supply_demand_basket_readiness(
        records,
        product_code=args.product_code,
        commodity_family=args.commodity_family,
        audit_as_of_date=args.audit_as_of_date,
        required_marketing_years=args.required_marketing_years,
        audit_scope=args.audit_scope,
    )
    output = write_supply_demand_basket_readiness(audit, output_path=args.output, output_format=args.format)
    status_counts: dict[str, int] = {}
    for row in audit["metric_matrix"]:
        status_counts[row["readiness_status"]] = status_counts.get(row["readiness_status"], 0) + 1
    print(f"output={output}")
    print(f"audit_scope={audit['audit_scope']}")
    print(f"metric_rows={len(audit['metric_matrix'])}")
    print(f"collection_plan_units={len(audit['collection_plan'])}")
    print("statuses=" + ",".join(f"{key}:{status_counts[key]}" for key in sorted(status_counts)))


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD format") from exc


def _parse_years(value: str) -> tuple[str, ...]:
    years = tuple(dict.fromkeys(item.strip() for item in value.split(",") if item.strip()))
    if not years:
        raise argparse.ArgumentTypeError("required marketing years must not be empty")
    return years


if __name__ == "__main__":
    main()
