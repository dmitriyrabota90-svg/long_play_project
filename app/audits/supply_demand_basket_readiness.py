from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any

from app.features.supply_demand_basket_config import (
    SUPPLY_DEMAND_GLOBAL_BASKET_POLICY_VERSION,
    SupplyDemandCountryWeight,
    accepted_basket_commodity_families,
    reviewed_tier_a_country_weights,
)


READINESS_SCHEMA_VERSION = "supply_demand_basket_readiness_v1"
VALID_AUDIT_SCOPES = frozenset({"local_fixture", "production_inventory_export"})
REAL_WORLD_COUNTRY_CODES = frozenset({"WLD", "WORLD", "WORLD TOTAL", "R00"})
READINESS_STATUSES = frozenset(
    {
        "real_wld_available",
        "basket_ready_full",
        "basket_ready_partial",
        "basket_insufficient_weight",
        "missing_inventory",
    }
)


@dataclass(frozen=True)
class SupplyDemandBasketInventoryRecord:
    product_code: str
    commodity_family: str
    metric_code: str
    country_code: str
    marketing_year: str
    source_as_of_date: date


def load_supply_demand_basket_inventory(path: str | Path) -> list[SupplyDemandBasketInventoryRecord]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        rows = payload.get("observations", payload.get("inventory"))
    else:
        rows = payload
    if not isinstance(rows, list):
        raise ValueError("inventory JSON must be a list or an object with observations/inventory list")
    return [supply_demand_basket_inventory_record_from_mapping(item) for item in rows]


def supply_demand_basket_inventory_record_from_mapping(item: Any) -> SupplyDemandBasketInventoryRecord:
    if not isinstance(item, dict):
        raise ValueError("each inventory record must be an object")
    required = (
        "product_code",
        "commodity_family",
        "metric_code",
        "country_code",
        "marketing_year",
        "source_as_of_date",
    )
    missing = [field for field in required if field not in item or str(item[field]).strip() == ""]
    if missing:
        raise ValueError(f"inventory record missing required fields: {', '.join(missing)}")
    try:
        source_as_of_date = date.fromisoformat(str(item["source_as_of_date"]))
    except ValueError as exc:
        raise ValueError("source_as_of_date must use YYYY-MM-DD format") from exc
    return SupplyDemandBasketInventoryRecord(
        product_code=str(item["product_code"]).strip(),
        commodity_family=str(item["commodity_family"]).strip(),
        metric_code=str(item["metric_code"]).strip(),
        country_code=str(item["country_code"]).strip().upper(),
        marketing_year=str(item["marketing_year"]).strip(),
        source_as_of_date=source_as_of_date,
    )


def audit_supply_demand_basket_readiness(
    records: list[SupplyDemandBasketInventoryRecord],
    *,
    product_code: str,
    commodity_family: str,
    audit_as_of_date: date,
    required_marketing_years: tuple[str, ...],
    audit_scope: str = "local_fixture",
) -> dict[str, Any]:
    if audit_scope not in VALID_AUDIT_SCOPES:
        raise ValueError(f"audit_scope must be one of: {', '.join(sorted(VALID_AUDIT_SCOPES))}")
    years = tuple(dict.fromkeys(str(year).strip() for year in required_marketing_years if str(year).strip()))
    if not years:
        raise ValueError("required_marketing_years must not be empty")

    configured = reviewed_tier_a_country_weights(product_code=product_code, commodity_family=commodity_family)
    if not configured:
        raise ValueError(f"no reviewed Tier A basket config for {product_code}/{commodity_family}")
    by_metric: dict[str, list[SupplyDemandCountryWeight]] = {}
    for item in configured:
        if item.metric_code is not None:
            by_metric.setdefault(item.metric_code, []).append(item)

    accepted_families = accepted_basket_commodity_families(
        product_code=product_code,
        commodity_family=commodity_family,
    )
    scoped_records = [
        record
        for record in records
        if record.product_code == product_code and record.commodity_family in accepted_families
    ]
    matrix = [
        _metric_year_readiness(
            metric_code=metric_code,
            metric_weights=tuple(by_metric[metric_code]),
            records=scoped_records,
            marketing_year=marketing_year,
            audit_as_of_date=audit_as_of_date,
        )
        for metric_code in sorted(by_metric)
        for marketing_year in years
    ]
    collection_plan = _consolidated_collection_plan(matrix)
    future_records_ignored = sum(
        1
        for record in scoped_records
        if record.metric_code in by_metric
        and record.marketing_year in years
        and record.source_as_of_date > audit_as_of_date
    )
    return {
        "schema_version": READINESS_SCHEMA_VERSION,
        "audit_scope": audit_scope,
        "product_code": product_code,
        "commodity_family": commodity_family,
        "accepted_inventory_commodity_families": sorted(accepted_families),
        "audit_as_of_date": audit_as_of_date.isoformat(),
        "required_marketing_years": list(years),
        "policy_version": SUPPLY_DEMAND_GLOBAL_BASKET_POLICY_VERSION,
        "inventory_records_total": len(records),
        "inventory_records_matching_scope": len(scoped_records),
        "future_inventory_records_ignored": future_records_ignored,
        "metric_matrix": matrix,
        "collection_plan": collection_plan,
        "limitations": [
            "Readiness describes only the supplied inventory file.",
            "local_fixture output does not describe or prove current production database coverage.",
            "The plan contains approved Tier A basket countries only and does not execute collection.",
        ],
    }


def write_supply_demand_basket_readiness(
    audit: dict[str, Any],
    *,
    output_path: str | Path,
    output_format: str,
) -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if output_format == "json":
        path.write_text(json.dumps(audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    elif output_format == "csv":
        _write_readiness_csv(audit, path)
    elif output_format == "md":
        path.write_text(render_supply_demand_basket_readiness_markdown(audit), encoding="utf-8")
    else:
        raise ValueError("output_format must be json, csv, or md")
    return path


def render_supply_demand_basket_readiness_markdown(audit: dict[str, Any]) -> str:
    lines = [
        "# Tier A Supply-Demand Basket Readiness",
        "",
        f"- Audit scope: `{audit['audit_scope']}`",
        f"- Product: `{audit['product_code']}`",
        f"- Commodity family: `{audit['commodity_family']}`",
        f"- Audit as-of date: `{audit['audit_as_of_date']}`",
        f"- Required marketing years: `{', '.join(audit['required_marketing_years'])}`",
        f"- Policy version: `{audit['policy_version']}`",
        "",
    ]
    if audit["audit_scope"] == "local_fixture":
        lines.extend(
            [
                "**This is a local synthetic demonstration.**",
                "",
                "**It does not describe or prove current production database coverage.**",
                "",
            ]
        )
    lines.extend(
        [
            "## Metric Matrix",
            "",
            "| metric | marketing year | status | available weight | available countries | missing countries | bounded plan |",
            "|---|---|---|---:|---|---|---|",
        ]
    )
    for row in audit["metric_matrix"]:
        lines.append(
            "| {metric_code} | {marketing_year} | {readiness_status} | {available_approved_weight} | {available} | {missing} | {plan} |".format(
                metric_code=row["metric_code"],
                marketing_year=row["marketing_year"],
                readiness_status=row["readiness_status"],
                available_approved_weight=row["available_approved_weight"],
                available=", ".join(row["available_countries"]) or "-",
                missing=", ".join(row["missing_countries"]) or "-",
                plan=", ".join(row["collection_plan_countries"]) or "-",
            )
        )
    lines.extend(
        [
            "",
            "## Consolidated Bounded Plan",
            "",
            "| priority | country | marketing year | required for metrics | maximum weight impact | maximum gap reduction |",
            "|---:|---|---|---|---:|---:|",
        ]
    )
    if audit["collection_plan"]:
        for row in audit["collection_plan"]:
            lines.append(
                f"| {row['priority']} | {row['country_code']} | {row['marketing_year']} | "
                f"{', '.join(row['required_for_metrics'])} | {row['maximum_weight_impact']} | "
                f"{row['maximum_gap_reduction']} |"
            )
    else:
        lines.append("| - | - | - | No collection units required by supplied inventory | - | - |")
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "A real eligible WLD row overrides country-basket requirements for its metric/year. "
            "Future source-as-of rows are ignored. Partial baskets are ready only when available "
            "approved weight is at least 0.75. The collection plan is advisory and does not run collectors.",
            "",
        ]
    )
    return "\n".join(lines)


def _metric_year_readiness(
    *,
    metric_code: str,
    metric_weights: tuple[SupplyDemandCountryWeight, ...],
    records: list[SupplyDemandBasketInventoryRecord],
    marketing_year: str,
    audit_as_of_date: date,
) -> dict[str, Any]:
    metric_year_records = [
        record
        for record in records
        if record.metric_code == metric_code and record.marketing_year == marketing_year
    ]
    eligible = [record for record in metric_year_records if record.source_as_of_date <= audit_as_of_date]
    future = [record for record in metric_year_records if record.source_as_of_date > audit_as_of_date]
    world_records = [record for record in eligible if record.country_code in REAL_WORLD_COUNTRY_CODES]
    basket_weight_by_country = {item.country_code: item.weight for item in metric_weights}
    basket_countries = list(basket_weight_by_country)
    configured_weight_total = sum(basket_weight_by_country.values(), Decimal("0"))
    latest_by_country = _latest_record_by_country(eligible)
    available_countries = [country for country in basket_countries if country in latest_by_country]
    missing_countries = [country for country in basket_countries if country not in latest_by_country]
    available_raw_weight = sum((basket_weight_by_country[country] for country in available_countries), Decimal("0"))
    available_weight = available_raw_weight / configured_weight_total if configured_weight_total > 0 else Decimal("0")
    minimum_required_weight = max((item.minimum_available_weight for item in metric_weights), default=Decimal("0.75"))

    if world_records:
        readiness_status = "real_wld_available"
        collection_plan_countries: list[str] = []
        coverage_gap = Decimal("0")
    elif len(available_countries) == len(basket_countries):
        readiness_status = "basket_ready_full"
        collection_plan_countries = []
        coverage_gap = Decimal("0")
    elif available_weight >= minimum_required_weight:
        readiness_status = "basket_ready_partial"
        collection_plan_countries = []
        coverage_gap = Decimal("0")
    elif not eligible:
        readiness_status = "missing_inventory"
        coverage_gap = minimum_required_weight
        collection_plan_countries = _minimum_missing_country_set(
            missing_countries=missing_countries,
            weight_by_country=basket_weight_by_country,
            configured_weight_total=configured_weight_total,
            available_raw_weight=available_raw_weight,
            minimum_required_weight=minimum_required_weight,
        )
    else:
        readiness_status = "basket_insufficient_weight"
        coverage_gap = minimum_required_weight - available_weight
        collection_plan_countries = _minimum_missing_country_set(
            missing_countries=missing_countries,
            weight_by_country=basket_weight_by_country,
            configured_weight_total=configured_weight_total,
            available_raw_weight=available_raw_weight,
            minimum_required_weight=minimum_required_weight,
        )
    if readiness_status not in READINESS_STATUSES:
        raise AssertionError(f"unsupported readiness status: {readiness_status}")

    world_latest = max((record.source_as_of_date for record in world_records), default=None)
    selected_dates = [latest_by_country[country].source_as_of_date for country in available_countries]
    if world_latest is not None:
        selected_dates.append(world_latest)
    maximum_available = max(selected_dates) if selected_dates else None
    return {
        "metric_code": metric_code,
        "marketing_year": marketing_year,
        "policy_version": metric_weights[0].policy_version,
        "basket_countries": basket_countries,
        "basket_weights": {country: str(weight) for country, weight in basket_weight_by_country.items()},
        "required_marketing_years": [marketing_year],
        "available_countries": available_countries,
        "missing_countries": missing_countries,
        "available_approved_weight": str(_quant(Decimal("1") if world_records else available_weight)),
        "minimum_required_weight": str(_quant(minimum_required_weight)),
        "coverage_gap": str(_quant(coverage_gap)),
        "readiness_status": readiness_status,
        "source_as_of_coverage": {
            "available_countries": {
                country: latest_by_country[country].source_as_of_date.isoformat()
                for country in available_countries
            },
            "real_wld": world_latest.isoformat() if world_latest else None,
            "future_rows_ignored": [
                {
                    "country_code": record.country_code,
                    "source_as_of_date": record.source_as_of_date.isoformat(),
                }
                for record in sorted(future, key=lambda item: (item.country_code, item.source_as_of_date))
            ],
        },
        "maximum_available_source_as_of_date": maximum_available.isoformat() if maximum_available else None,
        "collection_plan_countries": collection_plan_countries,
        "collection_plan_marketing_years": [marketing_year] if collection_plan_countries else [],
    }


def _minimum_missing_country_set(
    *,
    missing_countries: list[str],
    weight_by_country: dict[str, Decimal],
    configured_weight_total: Decimal,
    available_raw_weight: Decimal,
    minimum_required_weight: Decimal,
) -> list[str]:
    selected: list[str] = []
    accumulated = available_raw_weight
    for country_code in sorted(missing_countries, key=lambda country: (-weight_by_country[country], country)):
        if configured_weight_total > 0 and accumulated / configured_weight_total >= minimum_required_weight:
            break
        selected.append(country_code)
        accumulated += weight_by_country[country_code]
    return selected


def _consolidated_collection_plan(matrix: list[dict[str, Any]]) -> list[dict[str, Any]]:
    units: dict[tuple[str, str], dict[str, Any]] = {}
    for row in matrix:
        raw_weights = {country: Decimal(weight) for country, weight in row["basket_weights"].items()}
        total = sum(raw_weights.values(), Decimal("0"))
        for country_code in row["collection_plan_countries"]:
            key = (country_code, row["marketing_year"])
            impact = raw_weights[country_code] / total if total else Decimal("0")
            unit = units.setdefault(
                key,
                {
                    "country_code": country_code,
                    "marketing_year": row["marketing_year"],
                    "required_for_metrics": set(),
                    "maximum_weight_impact": Decimal("0"),
                    "maximum_gap_reduction": Decimal("0"),
                },
            )
            gap_reduction = min(impact, Decimal(row["coverage_gap"]))
            unit["required_for_metrics"].add(row["metric_code"])
            unit["maximum_weight_impact"] = max(unit["maximum_weight_impact"], impact)
            unit["maximum_gap_reduction"] = max(unit["maximum_gap_reduction"], gap_reduction)
    ranked = sorted(
        units.values(),
        key=lambda item: (
            -item["maximum_gap_reduction"],
            -item["maximum_weight_impact"],
            item["marketing_year"],
            item["country_code"],
        ),
    )
    return [
        {
            "country_code": item["country_code"],
            "marketing_year": item["marketing_year"],
            "required_for_metrics": sorted(item["required_for_metrics"]),
            "maximum_weight_impact": str(_quant(item["maximum_weight_impact"])),
            "maximum_gap_reduction": str(_quant(item["maximum_gap_reduction"])),
            "priority": priority,
            "reason": "Missing approved Tier A country needed by an unsatisfied 0.75 basket threshold.",
        }
        for priority, item in enumerate(ranked, start=1)
    ]


def _latest_record_by_country(
    records: list[SupplyDemandBasketInventoryRecord],
) -> dict[str, SupplyDemandBasketInventoryRecord]:
    latest: dict[str, SupplyDemandBasketInventoryRecord] = {}
    for record in records:
        existing = latest.get(record.country_code)
        if existing is None or record.source_as_of_date > existing.source_as_of_date:
            latest[record.country_code] = record
    return latest


def _write_readiness_csv(audit: dict[str, Any], path: Path) -> None:
    fieldnames = (
        "row_type",
        "audit_scope",
        "product_code",
        "commodity_family",
        "metric_code",
        "marketing_year",
        "policy_version",
        "required_marketing_years",
        "readiness_status",
        "basket_countries",
        "basket_weights",
        "available_countries",
        "missing_countries",
        "available_approved_weight",
        "minimum_required_weight",
        "coverage_gap",
        "source_as_of_coverage",
        "collection_plan_countries",
        "collection_plan_marketing_years",
        "maximum_available_source_as_of_date",
        "country_code",
        "required_for_metrics",
        "maximum_weight_impact",
        "maximum_gap_reduction",
        "priority",
        "reason",
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="raise")
        writer.writeheader()
        for row in audit["metric_matrix"]:
            writer.writerow(
                {
                    "row_type": "metric_readiness",
                    "audit_scope": audit["audit_scope"],
                    "product_code": audit["product_code"],
                    "commodity_family": audit["commodity_family"],
                    "metric_code": row["metric_code"],
                    "marketing_year": row["marketing_year"],
                    "policy_version": row["policy_version"],
                    "required_marketing_years": json.dumps(row["required_marketing_years"]),
                    "readiness_status": row["readiness_status"],
                    "basket_countries": json.dumps(row["basket_countries"]),
                    "basket_weights": json.dumps(row["basket_weights"], sort_keys=True),
                    "available_countries": json.dumps(row["available_countries"]),
                    "missing_countries": json.dumps(row["missing_countries"]),
                    "available_approved_weight": row["available_approved_weight"],
                    "minimum_required_weight": row["minimum_required_weight"],
                    "coverage_gap": row["coverage_gap"],
                    "source_as_of_coverage": json.dumps(row["source_as_of_coverage"], sort_keys=True),
                    "collection_plan_countries": json.dumps(row["collection_plan_countries"]),
                    "collection_plan_marketing_years": json.dumps(row["collection_plan_marketing_years"]),
                    "maximum_available_source_as_of_date": row["maximum_available_source_as_of_date"],
                }
            )
        for row in audit["collection_plan"]:
            writer.writerow(
                {
                    "row_type": "collection_plan",
                    "audit_scope": audit["audit_scope"],
                    "product_code": audit["product_code"],
                    "commodity_family": audit["commodity_family"],
                    "marketing_year": row["marketing_year"],
                    "country_code": row["country_code"],
                    "required_for_metrics": json.dumps(row["required_for_metrics"]),
                    "maximum_weight_impact": row["maximum_weight_impact"],
                    "maximum_gap_reduction": row["maximum_gap_reduction"],
                    "priority": row["priority"],
                    "reason": row["reason"],
                }
            )


def _quant(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)
