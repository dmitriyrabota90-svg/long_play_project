from __future__ import annotations

import csv
import json
import os
import subprocess
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.audits.supply_demand_basket_readiness import (
    SupplyDemandBasketInventoryRecord,
    audit_supply_demand_basket_readiness,
    load_supply_demand_basket_inventory,
    render_supply_demand_basket_readiness_markdown,
    supply_demand_basket_inventory_record_from_mapping,
    write_supply_demand_basket_readiness,
)
from app.features.supply_demand_basket_config import (
    SUPPLY_DEMAND_TIER_A_GLOBAL_BASKET_METRICS,
    reviewed_tier_a_country_weights,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = PROJECT_ROOT / "tests/fixtures/supply_demand_tier_a_readiness_inventory.json"


def test_readiness_module_remains_pure_and_has_no_db_or_collector_dependencies() -> None:
    module_text = (
        PROJECT_ROOT / "app/audits/supply_demand_basket_readiness.py"
    ).read_text(encoding="utf-8")

    assert "app.db" not in module_text
    assert "sqlalchemy" not in module_text.lower()
    assert "session_scope" not in module_text
    assert "RawStore" not in module_text
    assert "run_collector" not in module_text


def test_readiness_uses_exact_tier_a_config_and_excludes_ca() -> None:
    weights = reviewed_tier_a_country_weights(product_code="soybean_oil", commodity_family="soybean_oil")
    by_metric: dict[str, dict[str, Decimal]] = {}
    for item in weights:
        by_metric.setdefault(item.metric_code or "", {})[item.country_code] = item.weight

    assert set(by_metric) == SUPPLY_DEMAND_TIER_A_GLOBAL_BASKET_METRICS
    assert by_metric["production_volume"] == {
        "CH": Decimal("0.30156174"),
        "US": Decimal("0.20443230"),
        "BR": Decimal("0.18026335"),
        "AR": Decimal("0.11854805"),
    }
    assert set(by_metric["crush_volume"]) == {"CH", "US", "BR", "AR", "IN"}
    assert set(by_metric["domestic_consumption"]) == {"CH", "US", "BR", "IN", "AR", "MX"}
    assert set(by_metric["exports_volume"]) == {"AR", "BR", "RS", "BL", "PA", "US"}
    assert all("CA" not in countries for countries in by_metric.values())


def test_fixture_audit_reports_wld_full_partial_insufficient_and_future_exclusion() -> None:
    audit = _fixture_audit(years=("2023",))
    rows = {row["metric_code"]: row for row in audit["metric_matrix"]}

    assert rows["production_volume"]["readiness_status"] == "real_wld_available"
    assert rows["production_volume"]["collection_plan_countries"] == []
    assert rows["crush_volume"]["readiness_status"] == "basket_ready_full"
    assert rows["domestic_consumption"]["readiness_status"] == "basket_ready_partial"
    assert Decimal(rows["domestic_consumption"]["available_approved_weight"]) >= Decimal("0.75")
    assert rows["exports_volume"]["readiness_status"] == "basket_insufficient_weight"
    assert rows["exports_volume"]["collection_plan_countries"] == ["AR"]
    assert rows["exports_volume"]["source_as_of_coverage"]["future_rows_ignored"] == [
        {"country_code": "RS", "source_as_of_date": "2026-06-25"}
    ]
    assert audit["future_inventory_records_ignored"] == 1


def test_bounded_plan_selects_smallest_missing_weight_prefix() -> None:
    audit = _fixture_audit(years=("2023",))
    exports = next(row for row in audit["metric_matrix"] if row["metric_code"] == "exports_volume")

    assert exports["available_countries"] == ["BR", "US"]
    assert exports["collection_plan_countries"] == ["AR"]
    assert Decimal(exports["available_approved_weight"]) < Decimal("0.75")
    after_ar = (
        Decimal(exports["basket_weights"]["BR"])
        + Decimal(exports["basket_weights"]["US"])
        + Decimal(exports["basket_weights"]["AR"])
    ) / sum((Decimal(value) for value in exports["basket_weights"].values()), Decimal("0"))
    assert after_ar >= Decimal("0.75")
    plan_unit = next(unit for unit in audit["collection_plan"] if unit["country_code"] == "AR")
    assert Decimal(plan_unit["maximum_gap_reduction"]) > 0
    assert plan_unit["priority"] == 1


def test_collection_plan_is_tier_a_only_and_split_by_marketing_year() -> None:
    audit = _fixture_audit(years=("2022", "2023", "2024"))

    assert {row["metric_code"] for row in audit["metric_matrix"]} == SUPPLY_DEMAND_TIER_A_GLOBAL_BASKET_METRICS
    assert all(
        set(unit["required_for_metrics"]) <= SUPPLY_DEMAND_TIER_A_GLOBAL_BASKET_METRICS
        for unit in audit["collection_plan"]
    )
    assert all(unit["country_code"] != "CA" for unit in audit["collection_plan"])
    assert {row["marketing_year"] for row in audit["metric_matrix"]} == {"2022", "2023", "2024"}
    assert any(unit["marketing_year"] == "2024" for unit in audit["collection_plan"])
    production_2022 = _matrix_row(audit, "production_volume", "2022")
    production_2024 = _matrix_row(audit, "production_volume", "2024")
    assert production_2022["readiness_status"] == "basket_ready_full"
    assert production_2024["readiness_status"] == "basket_insufficient_weight"


def test_missing_inventory_status_and_plan_are_explicit() -> None:
    audit = audit_supply_demand_basket_readiness(
        [],
        product_code="soybean_oil",
        commodity_family="soybean_oil",
        audit_as_of_date=date(2026, 6, 19),
        required_marketing_years=("2023",),
    )

    assert {row["readiness_status"] for row in audit["metric_matrix"]} == {"missing_inventory"}
    assert all(row["collection_plan_countries"] for row in audit["metric_matrix"])
    assert audit["inventory_records_matching_scope"] == 0


def test_inventory_validation_rejects_missing_fields_and_bad_dates() -> None:
    with pytest.raises(ValueError, match="missing required fields"):
        supply_demand_basket_inventory_record_from_mapping({"product_code": "soybean_oil"})
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        supply_demand_basket_inventory_record_from_mapping(
            {
                "product_code": "soybean_oil",
                "commodity_family": "soybean_oil",
                "metric_code": "production_volume",
                "country_code": "US",
                "marketing_year": "2023",
                "source_as_of_date": "tomorrow",
            }
        )


def test_audit_scope_defaults_to_local_fixture_and_markdown_disclaims_production() -> None:
    audit = _fixture_audit(years=("2023",))
    markdown = render_supply_demand_basket_readiness_markdown(audit)

    assert audit["audit_scope"] == "local_fixture"
    assert "This is a local synthetic demonstration." in markdown
    assert "It does not describe or prove current production database coverage." in markdown


def test_json_csv_and_markdown_writers_use_explicit_paths(tmp_path: Path) -> None:
    audit = _fixture_audit(years=("2023",))
    json_path = write_supply_demand_basket_readiness(audit, output_path=tmp_path / "readiness.json", output_format="json")
    csv_path = write_supply_demand_basket_readiness(audit, output_path=tmp_path / "readiness.csv", output_format="csv")
    md_path = write_supply_demand_basket_readiness(audit, output_path=tmp_path / "readiness.md", output_format="md")

    assert json.loads(json_path.read_text(encoding="utf-8"))["audit_scope"] == "local_fixture"
    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert {row["row_type"] for row in rows} == {"metric_readiness", "collection_plan"}
    assert "local synthetic demonstration" in md_path.read_text(encoding="utf-8")


def test_cli_generates_local_fixture_json(tmp_path: Path) -> None:
    output = tmp_path / "audit.json"
    env = {**os.environ, "LOG_DIR": str(tmp_path / "logs")}
    result = subprocess.run(
        [
            sys.executable,
            "scripts/audit_supply_demand_basket_readiness.py",
            "--input",
            str(FIXTURE),
            "--output",
            str(output),
            "--product-code",
            "soybean_oil",
            "--commodity-family",
            "soybean_oil",
            "--audit-as-of-date",
            "2026-06-19",
            "--required-marketing-years",
            "2023",
            "--audit-scope",
            "local_fixture",
            "--format",
            "json",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["audit_scope"] == "local_fixture"
    assert "collection_plan_units=" in result.stdout


def test_runtime_family_alias_accepts_soybean_inventory() -> None:
    record = SupplyDemandBasketInventoryRecord(
        product_code="soybean_oil",
        commodity_family="soybean",
        metric_code="production_volume",
        country_code="WLD",
        marketing_year="2023",
        source_as_of_date=date(2026, 6, 19),
    )
    audit = audit_supply_demand_basket_readiness(
        [record],
        product_code="soybean_oil",
        commodity_family="soybean_oil",
        audit_as_of_date=date(2026, 6, 19),
        required_marketing_years=("2023",),
        audit_scope="production_inventory_export",
    )

    assert _matrix_row(audit, "production_volume", "2023")["readiness_status"] == "real_wld_available"
    assert audit["audit_scope"] == "production_inventory_export"


def _fixture_audit(*, years: tuple[str, ...]) -> dict:
    return audit_supply_demand_basket_readiness(
        load_supply_demand_basket_inventory(FIXTURE),
        product_code="soybean_oil",
        commodity_family="soybean_oil",
        audit_as_of_date=date(2026, 6, 19),
        required_marketing_years=years,
        audit_scope="local_fixture",
    )


def _matrix_row(audit: dict, metric_code: str, marketing_year: str) -> dict:
    return next(
        row
        for row in audit["metric_matrix"]
        if row["metric_code"] == metric_code and row["marketing_year"] == marketing_year
    )
