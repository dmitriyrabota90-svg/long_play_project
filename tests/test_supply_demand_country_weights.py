from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

from app.features.supply_demand_country_weights import (
    SupplyDemandGlobalBasketDiscoveryRequest,
    SupplyDemandWeightObservation,
    SupplyDemandWeightProposalRequest,
    discover_supply_demand_global_country_baskets,
    load_weight_observations_json,
    propose_supply_demand_country_weights,
)


FIXTURE = Path(__file__).parent / "fixtures" / "supply_demand_country_weight_observations.json"


def test_metric_specific_weights_are_normalized_and_differ_by_metric() -> None:
    proposal = _proposal()

    production_us = _row(proposal, "production_volume", "US")
    exports_us = _row(proposal, "exports_volume", "US")
    production_weights = [_decimal(_row(proposal, "production_volume", country)["proposed_weight"]) for country in ("US", "BR", "AR", "CA")]
    exports_weights = [_decimal(_row(proposal, "exports_volume", country)["proposed_weight"]) for country in ("US", "BR", "AR", "CA")]

    assert sum(production_weights) == Decimal("1.00000000")
    assert sum(exports_weights) == Decimal("1.00000000")
    assert production_us["proposed_weight"] == "0.16417910"
    assert exports_us["proposed_weight"] == "0.08695652"
    assert production_us["proposed_weight"] != exports_us["proposed_weight"]


def test_non_basket_countries_contribute_to_coverage_denominator() -> None:
    proposal = _proposal()

    production_us = _row(proposal, "production_volume", "US")
    exports_us = _row(proposal, "exports_volume", "US")

    assert production_us["basket_coverage_weight"] == "0.62037037"
    assert exports_us["basket_coverage_weight"] == "0.53488372"


def test_future_source_row_is_excluded_by_effective_as_of_date() -> None:
    proposal = _proposal()

    ar = _row(proposal, "production_volume", "AR")

    assert ar["proposed_weight"] == "0.46268657"
    assert ar["maximum_source_as_of_date"] == "2023-03-15"
    assert "2024-02-01" not in ar["source_as_of_coverage"].values()


def test_missing_country_years_are_explicitly_reported() -> None:
    proposal = _proposal()

    ca = _row(proposal, "production_volume", "CA")

    assert ca["available_marketing_years"] == [2020, 2022]
    assert ca["missing_country_years"] == [2021]
    assert ca["proposal_status"] == "proposed_partial_history"


def test_minimum_share_filters_only_when_explicitly_passed() -> None:
    unfiltered = _proposal()
    filtered = _proposal(minimum_share=Decimal("0.08"))

    unfiltered_ca = _row(unfiltered, "exports_volume", "CA")
    filtered_ca = _row(filtered, "exports_volume", "CA")

    assert unfiltered_ca["included_in_proposal"] is True
    assert unfiltered_ca["proposed_weight"] == "0.04347827"
    assert filtered_ca["included_in_proposal"] is False
    assert filtered_ca["proposed_weight"] is None
    assert filtered_ca["proposal_status"] == "below_minimum_share"


def test_ratio_metrics_are_reported_but_not_weighted_directly() -> None:
    proposal = _proposal()

    assert {item["metric_code"] for item in proposal["skipped_metrics"]} == {"stock_to_use_ratio"}
    assert all(row["metric_code"] != "stock_to_use_ratio" for row in proposal["proposal_rows"])


def test_output_contains_required_provenance_fields() -> None:
    proposal = _proposal()
    row = _row(proposal, "production_volume", "US")

    assert proposal["weight_effective_as_of_date"] == "2024-01-15"
    assert proposal["input_marketing_years"] == [2020, 2021, 2022]
    assert row["input_marketing_years"] == [2020, 2021, 2022]
    assert row["weight_effective_as_of_date"] == "2024-01-15"
    assert row["source_as_of_coverage"] == {"2020": "2023-01-15", "2021": "2023-02-15", "2022": "2023-03-15"}
    assert row["maximum_source_as_of_date"] == "2023-03-15"
    assert row["missing_metrics"] == []


def test_generator_is_pure_and_does_not_import_db_layer() -> None:
    module_text = Path("app/features/supply_demand_country_weights.py").read_text(encoding="utf-8")

    assert "app.db" not in module_text
    assert "Session" not in module_text
    assert "sqlalchemy" not in module_text


def test_cli_writes_proposal_to_requested_output_path(tmp_path: Path) -> None:
    output = tmp_path / "soybean_oil_weight_proposal.json"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/propose_supply_demand_country_weights.py",
            "--input",
            str(FIXTURE),
            "--output",
            str(output),
            "--product-code",
            "soybean_oil",
            "--commodity-family",
            "soybean_oil",
            "--effective-as-of-date",
            "2024-01-15",
            "--completed-marketing-year",
            "2022",
            "--lookback-years",
            "3",
            "--candidate-countries",
            "US,BR,AR,CA",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert "proposal_rows=8" in result.stdout
    assert output.exists()
    assert payload["product_code"] == "soybean_oil"
    assert payload["proposal_rows"][0]["weight_effective_as_of_date"] == "2024-01-15"


def test_global_basket_ranks_countries_by_metric_specific_historical_share() -> None:
    discovery = _global_discovery()
    production = _basket(discovery, "production_volume")

    assert [row["country_code"] for row in production["ranked_countries"][:5]] == ["MX", "AR", "BR", "US", "CA"]
    assert [row["country_code"] for row in production["selected_countries"]] == ["MX", "AR", "BR"]
    assert production["country_count_required_for_threshold"] == 3
    assert production["cumulative_coverage"] == "0.86111111"
    assert production["proposal_status"] == "threshold_reached"


def test_global_basket_is_metric_specific() -> None:
    discovery = _global_discovery()
    production = _basket(discovery, "production_volume")
    exports = _basket(discovery, "exports_volume")

    assert [row["country_code"] for row in production["selected_countries"]] == ["MX", "AR", "BR"]
    assert [row["country_code"] for row in exports["selected_countries"]] == ["MX", "BR"]
    assert exports["cumulative_coverage"] == "0.83720930"


def test_global_basket_excludes_world_aggregate_rows_from_denominator() -> None:
    observations = load_weight_observations_json(FIXTURE)
    observations.append(
        SupplyDemandWeightObservation(
            product_code="soybean_oil",
            commodity_family="soybean_oil",
            country_code="WLD",
            metric_code="production_volume",
            marketing_year="2022",
            value=Decimal("999999"),
            source_as_of_date=date(2023, 3, 15),
        )
    )

    discovery = _global_discovery(observations=observations)
    production = _basket(discovery, "production_volume")

    assert production["ranked_countries"][0]["country_code"] == "MX"
    assert production["all_available_country_count"] == 5
    assert production["cumulative_coverage"] == "0.86111111"


def test_global_basket_excludes_future_as_of_rows() -> None:
    discovery = _global_discovery()
    production = _basket(discovery, "production_volume")
    ar = _ranked_country(production, "AR")

    assert ar["historical_share"] == "0.28703704"
    assert ar["maximum_source_as_of_date"] == "2023-03-15"
    assert "2024-02-01" not in ar["source_as_of_coverage"].values()


def test_global_basket_reports_missing_country_years() -> None:
    discovery = _global_discovery()
    production = _basket(discovery, "production_volume")
    ca = _ranked_country(production, "CA")

    assert ca["available_marketing_years"] == [2020, 2022]
    assert ca["missing_country_years"] == [2021]


def test_global_basket_reports_threshold_not_reached_under_max_countries() -> None:
    discovery = _global_discovery(max_countries=2)
    production = _basket(discovery, "production_volume")

    assert [row["country_code"] for row in production["selected_countries"]] == ["MX", "AR"]
    assert production["country_count_required_for_threshold"] == 3
    assert production["country_count_selected"] == 2
    assert production["threshold_reached"] is False
    assert production["proposal_status"] == "coverage_requires_review"


def test_global_basket_reports_ratio_metrics_but_does_not_select_them() -> None:
    discovery = _global_discovery()

    assert {item["metric_code"] for item in discovery["skipped_metrics"]} == {"stock_to_use_ratio"}
    assert all(basket["metric_code"] != "stock_to_use_ratio" for basket in discovery["metric_baskets"])


def test_cli_writes_global_basket_discovery_to_requested_output_path(tmp_path: Path) -> None:
    output = tmp_path / "soybean_oil_global_basket.json"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/propose_supply_demand_country_weights.py",
            "--input",
            str(FIXTURE),
            "--output",
            str(output),
            "--product-code",
            "soybean_oil",
            "--commodity-family",
            "soybean_oil",
            "--effective-as-of-date",
            "2024-01-15",
            "--completed-marketing-year",
            "2022",
            "--lookback-years",
            "3",
            "--discover-global-basket",
            "--coverage-threshold",
            "0.80",
            "--max-countries",
            "2",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert "basket_metrics=2" in result.stdout
    assert payload["coverage_threshold"] == "0.80000000"
    assert _basket(payload, "production_volume")["proposal_status"] == "coverage_requires_review"


def _proposal(*, minimum_share: Decimal | None = None):
    return propose_supply_demand_country_weights(
        load_weight_observations_json(FIXTURE),
        SupplyDemandWeightProposalRequest(
            product_code="soybean_oil",
            commodity_family="soybean_oil",
            effective_as_of_date=date(2024, 1, 15),
            completed_marketing_year=2022,
            lookback_years=3,
            candidate_countries=("US", "BR", "AR", "CA"),
            minimum_share=minimum_share,
        ),
    )


def _global_discovery(*, observations: list[SupplyDemandWeightObservation] | None = None, max_countries: int | None = None):
    return discover_supply_demand_global_country_baskets(
        observations or load_weight_observations_json(FIXTURE),
        SupplyDemandGlobalBasketDiscoveryRequest(
            product_code="soybean_oil",
            commodity_family="soybean_oil",
            effective_as_of_date=date(2024, 1, 15),
            completed_marketing_year=2022,
            lookback_years=3,
            coverage_threshold=Decimal("0.80"),
            max_countries=max_countries,
        ),
    )


def _row(proposal, metric_code: str, country_code: str):
    return next(
        row
        for row in proposal["proposal_rows"]
        if row["metric_code"] == metric_code and row["country_code"] == country_code
    )


def _basket(discovery, metric_code: str):
    return next(
        basket
        for basket in discovery["metric_baskets"]
        if basket["metric_code"] == metric_code
    )


def _ranked_country(basket, country_code: str):
    return next(
        row
        for row in basket["ranked_countries"]
        if row["country_code"] == country_code
    )


def _decimal(value: str) -> Decimal:
    return Decimal(value)
