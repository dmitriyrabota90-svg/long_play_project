from __future__ import annotations

import json
import os
import subprocess
import sys
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest

from app.audits.usda_psd_tier_a_source_contract import (
    audit_usda_psd_tier_a_source_contract,
    render_usda_psd_tier_a_source_contract_markdown,
    write_usda_psd_tier_a_source_contract_report,
)
from app.features.supply_demand_basket_config import (
    SUPPLY_DEMAND_TIER_A_GLOBAL_BASKET_METRICS,
    reviewed_tier_a_country_weights,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = PROJECT_ROOT / "tests/fixtures/usda_psd/tier_a_source_contract_sample.csv"


def test_audit_scope_comes_exactly_from_approved_tier_a_config() -> None:
    audit = _audit_fixture()
    weights = reviewed_tier_a_country_weights(product_code="soybean_oil", commodity_family="soybean_oil")
    expected: dict[str, list[str]] = {}
    for item in weights:
        expected.setdefault(item.metric_code or "", []).append(item.country_code)

    assert audit["tier_a_countries_by_metric"] == expected
    assert set(audit["tier_a_metrics"]) == SUPPLY_DEMAND_TIER_A_GLOBAL_BASKET_METRICS
    assert "imports_volume" not in audit["tier_a_metrics"]
    assert "stock_to_use_ratio" not in audit["tier_a_metrics"]
    assert all("CA" not in countries for countries in audit["tier_a_countries_by_metric"].values())


def test_supported_country_metric_year_is_available() -> None:
    audit = _audit_fixture()
    row = _cell(audit, "production_volume", "US", "2023")

    assert row["status"] == "available"
    assert row["raw_rows_found"] == 1
    assert row["normalized_rows_available"] == 1
    assert row["raw_country_name"] == "United States"
    assert row["raw_metric_names"] == ["Production"]
    assert row["normalized_metric_codes"] == ["production_volume"]


def test_missing_required_raw_row_is_explicit() -> None:
    audit = _audit_fixture()
    row = _cell(audit, "production_volume", "CH", "2023")

    assert row["status"] == "missing_raw_row"
    assert row["raw_rows_found"] == 0
    assert row["mapping_or_parser_issue"] is None


def test_expected_unsupported_metric_is_informational() -> None:
    audit = _audit_fixture()
    expected = audit["expected_unsupported_rows_sample"]

    assert audit["expected_unsupported_rows_count"] == 1
    assert expected[0]["raw_metric_name"] == "Total Supply"
    assert expected[0]["normalized_metric_code"] == "total_supply"
    assert expected[0]["status"] == "expected_unsupported_metric"
    assert expected[0]["reason"] == "aggregate_total_supply_not_feature_metric"


@pytest.mark.parametrize(
    ("metric_code", "country_code", "raw_country_name"),
    (
        ("crush_volume", "IN", "India"),
        ("domestic_consumption", "IN", "India"),
        ("domestic_consumption", "MX", "Mexico"),
        ("exports_volume", "RS", "Russia"),
        ("exports_volume", "BL", "Bolivia"),
        ("exports_volume", "PA", "Paraguay"),
    ),
)
def test_verified_tier_a_country_mapping_is_available(
    metric_code: str,
    country_code: str,
    raw_country_name: str,
) -> None:
    audit = _audit_fixture()
    row = _cell(audit, metric_code, country_code, "2023")

    assert row["raw_rows_found"] == 1
    assert row["normalized_rows_available"] == 1
    assert row["status"] == "available"
    assert row["raw_country_name"] == raw_country_name
    assert row["mapping_or_parser_issue"] is None


def test_invalid_numeric_value_is_parser_failure() -> None:
    audit = _audit_fixture()
    row = _cell(audit, "exports_volume", "US", "2023")

    assert row["raw_rows_found"] == 1
    assert row["normalized_rows_available"] == 0
    assert row["status"] == "unexpected_parser_failure"
    assert "metric value is invalid" in row["mapping_or_parser_issue"]


def test_zip_input_and_markdown_output_are_supported(tmp_path: Path) -> None:
    zip_path = tmp_path / "psd_oilseeds_csv.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(FIXTURE, arcname="psd_oilseeds.csv")
    audit = audit_usda_psd_tier_a_source_contract(
        source_path=zip_path,
        product_code="soybean_oil",
        marketing_years=("2023",),
    )
    output = write_usda_psd_tier_a_source_contract_report(
        audit,
        output_path=tmp_path / "report.md",
        output_format="markdown",
    )

    assert audit["raw_csv_member_name"] == "psd_oilseeds.csv"
    assert "local source-contract audit" in output.read_text(encoding="utf-8")


def test_source_ready_candidates_are_not_production_gap_claims() -> None:
    audit = _audit_fixture()
    markdown = render_usda_psd_tier_a_source_contract_markdown(audit)

    assert audit["limitations"][1] == "It does not prove production database inventory or execute a production backfill."
    assert "not claims that production is missing them" in markdown


def test_audit_module_has_no_db_rawstore_or_collector_orchestration_dependency() -> None:
    module_text = (PROJECT_ROOT / "app/audits/usda_psd_tier_a_source_contract.py").read_text(encoding="utf-8")

    assert "app.db" not in module_text
    assert "sqlalchemy" not in module_text.lower()
    assert "session_scope" not in module_text
    assert "RawStore" not in module_text
    assert "UsdaPsdCollector" not in module_text


def test_json_writer_and_cli_use_explicit_paths(tmp_path: Path) -> None:
    audit = _audit_fixture()
    output = write_usda_psd_tier_a_source_contract_report(
        audit,
        output_path=tmp_path / "audit.json",
        output_format="json",
    )
    assert json.loads(output.read_text(encoding="utf-8"))["product_code"] == "soybean_oil"

    cli_output = tmp_path / "cli.json"
    env = {**os.environ, "LOG_DIR": str(tmp_path / "logs")}
    result = subprocess.run(
        [
            sys.executable,
            "scripts/audit_usda_psd_tier_a_source_contract.py",
            "--csv-path",
            str(FIXTURE),
            "--output",
            str(cli_output),
            "--product-code",
            "soybean_oil",
            "--marketing-years",
            "2023",
            "--format",
            "json",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert cli_output.exists()
    assert "unexpected_issues_count=" in result.stdout


def test_real_config_weights_remain_unchanged() -> None:
    weights = reviewed_tier_a_country_weights(product_code="soybean_oil", commodity_family="soybean_oil")
    production = {item.country_code: item.weight for item in weights if item.metric_code == "production_volume"}

    assert production == {
        "CH": Decimal("0.30156174"),
        "US": Decimal("0.20443230"),
        "BR": Decimal("0.18026335"),
        "AR": Decimal("0.11854805"),
    }


def test_country_mapping_fix_does_not_activate_tier_b_or_tier_c_metrics() -> None:
    audit = _audit_fixture()

    assert set(audit["tier_a_metrics"]) == {
        "production_volume",
        "crush_volume",
        "domestic_consumption",
        "exports_volume",
    }
    assert "imports_volume" not in audit["tier_a_metrics"]
    assert "stock_to_use_ratio" not in audit["tier_a_metrics"]


def _audit_fixture() -> dict:
    return audit_usda_psd_tier_a_source_contract(
        source_path=FIXTURE,
        product_code="soybean_oil",
        marketing_years=("2023",),
    )


def _cell(audit: dict, metric_code: str, country_code: str, marketing_year: str) -> dict:
    return next(
        row
        for row in audit["availability_matrix"]
        if row["metric_code"] == metric_code
        and row["country_code"] == country_code
        and row["marketing_year"] == marketing_year
    )
