from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any


ADDITIVE_SUPPLY_DEMAND_METRICS = {
    "production_volume",
    "beginning_stocks",
    "ending_stocks",
    "imports_volume",
    "exports_volume",
    "domestic_consumption",
    "crush_volume",
    "food_use",
}
RATIO_SUPPLY_DEMAND_METRICS = {
    "stock_to_use_ratio",
}


@dataclass(frozen=True)
class SupplyDemandWeightObservation:
    product_code: str
    commodity_family: str
    country_code: str
    metric_code: str
    marketing_year: str
    value: Decimal
    source_as_of_date: date


@dataclass(frozen=True)
class SupplyDemandWeightProposalRequest:
    product_code: str
    commodity_family: str
    effective_as_of_date: date
    completed_marketing_year: int
    lookback_years: int
    candidate_countries: tuple[str, ...]
    minimum_share: Decimal | None = None


def load_weight_observations_json(path: str | Path) -> list[SupplyDemandWeightObservation]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = raw.get("observations", raw) if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        raise ValueError("input JSON must be a list or an object with observations=list")
    return [supply_demand_weight_observation_from_mapping(item) for item in rows]


def write_weight_proposal_json(path: str | Path, proposal: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(proposal, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def supply_demand_weight_observation_from_mapping(item: dict[str, Any]) -> SupplyDemandWeightObservation:
    return SupplyDemandWeightObservation(
        product_code=str(item["product_code"]),
        commodity_family=str(item["commodity_family"]),
        country_code=str(item["country_code"]),
        metric_code=str(item["metric_code"]),
        marketing_year=str(item["marketing_year"]),
        value=Decimal(str(item["value"])),
        source_as_of_date=date.fromisoformat(str(item["source_as_of_date"])),
    )


def propose_supply_demand_country_weights(
    observations: list[SupplyDemandWeightObservation],
    request: SupplyDemandWeightProposalRequest,
) -> dict[str, Any]:
    if request.lookback_years <= 0:
        raise ValueError("lookback_years must be positive")
    if not request.candidate_countries:
        raise ValueError("candidate_countries must not be empty")
    if request.minimum_share is not None and request.minimum_share < 0:
        raise ValueError("minimum_share must be nonnegative")

    input_years = _input_marketing_years(request.completed_marketing_year, request.lookback_years)
    filtered = _latest_valid_rows_by_identity(observations, request=request, input_years=input_years)
    additive_metrics = sorted({key[0] for key in filtered if key[0] in ADDITIVE_SUPPLY_DEMAND_METRICS})
    skipped_metrics = sorted({row.metric_code for row in observations if row.metric_code in RATIO_SUPPLY_DEMAND_METRICS})

    proposals: list[dict[str, Any]] = []
    for metric_code in additive_metrics:
        proposals.extend(_metric_country_proposals(metric_code=metric_code, rows=filtered, request=request, input_years=input_years))

    missing_metrics = sorted(ADDITIVE_SUPPLY_DEMAND_METRICS - set(additive_metrics))
    return {
        "product_code": request.product_code,
        "commodity_family": request.commodity_family,
        "weight_effective_as_of_date": request.effective_as_of_date.isoformat(),
        "completed_marketing_year": request.completed_marketing_year,
        "lookback_years": request.lookback_years,
        "input_marketing_years": input_years,
        "candidate_countries": list(request.candidate_countries),
        "minimum_share": str(_quant(request.minimum_share)) if request.minimum_share is not None else None,
        "proposal_rows": proposals,
        "missing_metrics": missing_metrics,
        "skipped_metrics": [
            {
                "metric_code": metric_code,
                "reason": "ratio_metric_not_weighted_directly",
            }
            for metric_code in skipped_metrics
        ],
        "methodology": {
            "weight_formula": "sum(candidate_country_metric_value) / sum(included_candidate_country_metric_value)",
            "source_data_coverage": "sum(included_candidate_country_metric_value) / sum(all_valid_available_country_metric_value)",
            "no_leakage_rule": "source_as_of_date <= weight_effective_as_of_date",
            "ratio_policy": "stock_to_use_ratio is derived after aggregation, not weighted directly",
        },
    }


def _metric_country_proposals(
    *,
    metric_code: str,
    rows: dict[tuple[str, str, str], SupplyDemandWeightObservation],
    request: SupplyDemandWeightProposalRequest,
    input_years: list[int],
) -> list[dict[str, Any]]:
    country_totals = _country_totals(metric_code=metric_code, rows=rows, countries=request.candidate_countries, input_years=input_years)
    all_country_total = sum(
        row.value
        for (row_metric, _, _), row in rows.items()
        if row_metric == metric_code
    )
    candidate_total = sum(country_totals.values())
    historical_shares = {
        country_code: (country_total / candidate_total if candidate_total else None)
        for country_code, country_total in country_totals.items()
    }
    included_countries = [
        country_code
        for country_code, share in historical_shares.items()
        if share is not None and (request.minimum_share is None or share >= request.minimum_share)
    ]
    included_total = sum(country_totals[country_code] for country_code in included_countries)
    final_weights = _final_included_weights(
        included_countries=included_countries,
        country_totals=country_totals,
        included_total=included_total,
    )
    basket_coverage_weight = included_total / all_country_total if all_country_total else None

    result = []
    for country_code in request.candidate_countries:
        available_years = _available_years(metric_code=metric_code, country_code=country_code, rows=rows, input_years=input_years)
        missing_years = [year for year in input_years if year not in available_years]
        source_as_of_coverage = _source_as_of_coverage(metric_code=metric_code, country_code=country_code, rows=rows, input_years=input_years)
        country_total = country_totals.get(country_code, Decimal("0"))
        historical_share = historical_shares.get(country_code)
        included = country_code in included_countries
        if country_total == 0:
            status = "missing_data"
        elif not included:
            status = "below_minimum_share"
        elif missing_years:
            status = "proposed_partial_history"
        else:
            status = "proposed"
        result.append(
            {
                "metric_code": metric_code,
                "country_code": country_code,
                "proposed_weight": str(final_weights[country_code]) if included else None,
                "historical_share": str(_quant(historical_share)) if historical_share is not None else None,
                "basket_coverage_weight": str(_quant(basket_coverage_weight)) if basket_coverage_weight is not None else None,
                "input_marketing_years": input_years,
                "available_marketing_years": available_years,
                "missing_country_years": missing_years,
                "missing_metrics": [metric_code] if country_total == 0 else [],
                "source_as_of_coverage": source_as_of_coverage,
                "maximum_source_as_of_date": _maximum_source_as_of_date(source_as_of_coverage),
                "weight_effective_as_of_date": request.effective_as_of_date.isoformat(),
                "proposal_status": status,
                "included_in_proposal": included,
            }
        )
    return result


def _final_included_weights(
    *,
    included_countries: list[str],
    country_totals: dict[str, Decimal],
    included_total: Decimal,
) -> dict[str, Decimal]:
    if not included_countries or included_total <= 0:
        return {}
    result: dict[str, Decimal] = {}
    for country_code in included_countries[:-1]:
        result[country_code] = _quant(country_totals[country_code] / included_total) or Decimal("0.00000000")
    result[included_countries[-1]] = Decimal("1.00000000") - sum(result.values(), Decimal("0"))
    return result


def _latest_valid_rows_by_identity(
    observations: list[SupplyDemandWeightObservation],
    *,
    request: SupplyDemandWeightProposalRequest,
    input_years: list[int],
) -> dict[tuple[str, str, str], SupplyDemandWeightObservation]:
    input_year_set = set(input_years)
    latest: dict[tuple[str, str, str], SupplyDemandWeightObservation] = {}
    for row in observations:
        if row.product_code != request.product_code or row.commodity_family != request.commodity_family:
            continue
        marketing_year = _marketing_year_int(row.marketing_year)
        if marketing_year not in input_year_set:
            continue
        if row.source_as_of_date > request.effective_as_of_date:
            continue
        key = (row.metric_code, row.country_code, str(marketing_year))
        existing = latest.get(key)
        if existing is None or row.source_as_of_date > existing.source_as_of_date:
            latest[key] = row
    return latest


def _input_marketing_years(completed_marketing_year: int, lookback_years: int) -> list[int]:
    first_year = completed_marketing_year - lookback_years + 1
    return list(range(first_year, completed_marketing_year + 1))


def _country_totals(
    *,
    metric_code: str,
    rows: dict[tuple[str, str, str], SupplyDemandWeightObservation],
    countries: tuple[str, ...],
    input_years: list[int],
) -> dict[str, Decimal]:
    totals = {country_code: Decimal("0") for country_code in countries}
    for country_code in countries:
        for year in input_years:
            row = rows.get((metric_code, country_code, str(year)))
            if row is not None:
                totals[country_code] += row.value
    return totals


def _available_years(
    *,
    metric_code: str,
    country_code: str,
    rows: dict[tuple[str, str, str], SupplyDemandWeightObservation],
    input_years: list[int],
) -> list[int]:
    return [year for year in input_years if (metric_code, country_code, str(year)) in rows]


def _source_as_of_coverage(
    *,
    metric_code: str,
    country_code: str,
    rows: dict[tuple[str, str, str], SupplyDemandWeightObservation],
    input_years: list[int],
) -> dict[str, str]:
    result = {}
    for year in input_years:
        row = rows.get((metric_code, country_code, str(year)))
        if row is not None:
            result[str(year)] = row.source_as_of_date.isoformat()
    return result


def _maximum_source_as_of_date(source_as_of_coverage: dict[str, str]) -> str | None:
    if not source_as_of_coverage:
        return None
    return max(source_as_of_coverage.values())


def _marketing_year_int(marketing_year: str) -> int | None:
    value = str(marketing_year).strip()
    if not value:
        return None
    try:
        return int(value[:4])
    except ValueError:
        return None


def _quant(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return value.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
