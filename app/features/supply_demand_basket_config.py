from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any


SUPPLY_DEMAND_GLOBAL_BASKET_POLICY_VERSION = "supply_demand_global_basket_v1"
SUPPLY_DEMAND_GLOBAL_BASKET_SOURCE_COVERAGE_THRESHOLD = Decimal("0.80")
SUPPLY_DEMAND_GLOBAL_BASKET_MIN_AVAILABLE_WEIGHT = Decimal("0.75")
SUPPLY_DEMAND_GLOBAL_BASKET_EFFECTIVE_AS_OF_DATE = date(2026, 6, 19)
SUPPLY_DEMAND_GLOBAL_BASKET_MARKETING_YEARS = (2021, 2022, 2023)
SUPPLY_DEMAND_TIER_A_GLOBAL_BASKET_METRICS = frozenset(
    {
        "production_volume",
        "crush_volume",
        "domestic_consumption",
        "exports_volume",
    }
)


@dataclass(frozen=True)
class SupplyDemandCountryWeight:
    product_code: str
    commodity_family: str
    country_code: str
    weight: Decimal
    metric_code: str | None = None
    policy_version: str = "ad_hoc_country_basket"
    source_coverage_threshold: Decimal | None = None
    minimum_available_weight: Decimal = Decimal("0")
    proposal_effective_as_of_date: date | None = None
    proposal_marketing_years: tuple[int, ...] = ()
    maximum_source_as_of_date: date | None = None
    provenance: Mapping[str, Any] = field(default_factory=dict)
    effective_from: date = date(2020, 1, 1)
    effective_to: date | None = None
    is_active: bool = True


SupplyDemandCountryWeights = Mapping[tuple[str, str], tuple[SupplyDemandCountryWeight, ...]]


def _reviewed_tier_a_country_weight(
    *,
    metric_code: str,
    commodity_family: str,
    country_code: str,
    weight: str,
    selected_countries: tuple[str, ...],
    cumulative_coverage: str,
) -> SupplyDemandCountryWeight:
    return SupplyDemandCountryWeight(
        product_code="soybean_oil",
        commodity_family=commodity_family,
        country_code=country_code,
        weight=Decimal(weight),
        metric_code=metric_code,
        policy_version=SUPPLY_DEMAND_GLOBAL_BASKET_POLICY_VERSION,
        source_coverage_threshold=SUPPLY_DEMAND_GLOBAL_BASKET_SOURCE_COVERAGE_THRESHOLD,
        minimum_available_weight=SUPPLY_DEMAND_GLOBAL_BASKET_MIN_AVAILABLE_WEIGHT,
        proposal_effective_as_of_date=SUPPLY_DEMAND_GLOBAL_BASKET_EFFECTIVE_AS_OF_DATE,
        proposal_marketing_years=SUPPLY_DEMAND_GLOBAL_BASKET_MARKETING_YEARS,
        maximum_source_as_of_date=SUPPLY_DEMAND_GLOBAL_BASKET_EFFECTIVE_AS_OF_DATE,
        provenance={
            "source": "Phase 6.9S USDA_PSD_SOYBEAN_OIL_GLOBAL_BASKET_DISCOVERY",
            "artifact_commodity_family": "soybean_oil",
            "selected_countries": list(selected_countries),
            "cumulative_coverage": cumulative_coverage,
            "tier": "A",
        },
    )


def _reviewed_tier_a_metric_weights(
    *,
    metric_code: str,
    commodity_family: str,
    country_weights: tuple[tuple[str, str], ...],
    cumulative_coverage: str,
) -> tuple[SupplyDemandCountryWeight, ...]:
    selected_countries = tuple(country_code for country_code, _ in country_weights)
    return tuple(
        _reviewed_tier_a_country_weight(
            metric_code=metric_code,
            commodity_family=commodity_family,
            country_code=country_code,
            weight=weight,
            selected_countries=selected_countries,
            cumulative_coverage=cumulative_coverage,
        )
        for country_code, weight in country_weights
    )


REVIEWED_TIER_A_SUPPLY_DEMAND_COUNTRY_WEIGHTS: SupplyDemandCountryWeights = {
    ("soybean_oil", "soybean"): (
        *_reviewed_tier_a_metric_weights(
            metric_code="production_volume",
            commodity_family="soybean",
            country_weights=(
                ("CH", "0.30156174"),
                ("US", "0.20443230"),
                ("BR", "0.18026335"),
                ("AR", "0.11854805"),
            ),
            cumulative_coverage="0.80480543",
        ),
        *_reviewed_tier_a_metric_weights(
            metric_code="crush_volume",
            commodity_family="soybean",
            country_weights=(
                ("CH", "0.31002524"),
                ("US", "0.19838896"),
                ("BR", "0.17250566"),
                ("AR", "0.11500740"),
                ("IN", "0.03274302"),
            ),
            cumulative_coverage="0.82867026",
        ),
        *_reviewed_tier_a_metric_weights(
            metric_code="domestic_consumption",
            commodity_family="soybean",
            country_weights=(
                ("CH", "0.30853244"),
                ("US", "0.20406072"),
                ("BR", "0.14997310"),
                ("IN", "0.09387629"),
                ("AR", "0.03480292"),
                ("MX", "0.02218114"),
            ),
            cumulative_coverage="0.81342660",
        ),
        *_reviewed_tier_a_metric_weights(
            metric_code="exports_volume",
            commodity_family="soybean",
            country_weights=(
                ("AR", "0.43476831"),
                ("BR", "0.19273543"),
                ("RS", "0.06502242"),
                ("BL", "0.04597907"),
                ("PA", "0.04158445"),
                ("US", "0.03748879"),
            ),
            cumulative_coverage="0.81757848",
        ),
    )
}

DEFAULT_SUPPLY_DEMAND_COUNTRY_WEIGHTS: SupplyDemandCountryWeights = (
    REVIEWED_TIER_A_SUPPLY_DEMAND_COUNTRY_WEIGHTS
)


REVIEWED_BASKET_COMMODITY_FAMILY_ALIASES = {
    ("soybean_oil", "soybean_oil"): "soybean",
}


def reviewed_tier_a_country_weights(
    *,
    product_code: str,
    commodity_family: str,
) -> tuple[SupplyDemandCountryWeight, ...]:
    runtime_family = REVIEWED_BASKET_COMMODITY_FAMILY_ALIASES.get(
        (product_code, commodity_family),
        commodity_family,
    )
    return REVIEWED_TIER_A_SUPPLY_DEMAND_COUNTRY_WEIGHTS.get((product_code, runtime_family), ())


def accepted_basket_commodity_families(*, product_code: str, commodity_family: str) -> frozenset[str]:
    runtime_family = REVIEWED_BASKET_COMMODITY_FAMILY_ALIASES.get(
        (product_code, commodity_family),
        commodity_family,
    )
    return frozenset({commodity_family, runtime_family})
