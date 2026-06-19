from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal

from app.features.supply_demand_country_weights import (
    SupplyDemandWeightProposalRequest,
    load_weight_observations_json,
    propose_supply_demand_country_weights,
    write_weight_proposal_json,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Propose reviewed supply-demand country weights from normalized history.")
    parser.add_argument("--input", required=True, help="Input JSON file with normalized historical supply-demand rows.")
    parser.add_argument("--output", required=True, help="Output JSON path for the proposal. Runtime artifact; do not commit.")
    parser.add_argument("--product-code", required=True, help="Product code, for example soybean_oil.")
    parser.add_argument("--commodity-family", required=True, help="Commodity family/slice, for example soybean_oil.")
    parser.add_argument("--effective-as-of-date", required=True, help="Weight effective as-of date in YYYY-MM-DD format.")
    parser.add_argument("--completed-marketing-year", required=True, type=int, help="Last completed marketing year, e.g. 2022.")
    parser.add_argument("--lookback-years", required=True, type=int, help="Explicit lookback window length. No default is inferred.")
    parser.add_argument("--candidate-countries", required=True, help="Comma-separated candidate country codes, e.g. US,BR,AR,CA.")
    parser.add_argument("--minimum-share", help="Optional minimum historical share for inclusion, e.g. 0.05.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    observations = load_weight_observations_json(args.input)
    candidate_countries = tuple(country.strip() for country in args.candidate_countries.split(",") if country.strip())
    request = SupplyDemandWeightProposalRequest(
        product_code=args.product_code,
        commodity_family=args.commodity_family,
        effective_as_of_date=date.fromisoformat(args.effective_as_of_date),
        completed_marketing_year=args.completed_marketing_year,
        lookback_years=args.lookback_years,
        candidate_countries=candidate_countries,
        minimum_share=Decimal(args.minimum_share) if args.minimum_share is not None else None,
    )
    proposal = propose_supply_demand_country_weights(observations, request)
    write_weight_proposal_json(args.output, proposal)
    print(f"proposal_rows={len(proposal['proposal_rows'])}")
    print(f"skipped_metrics={len(proposal['skipped_metrics'])}")
    print(f"output={args.output}")


if __name__ == "__main__":
    main()
