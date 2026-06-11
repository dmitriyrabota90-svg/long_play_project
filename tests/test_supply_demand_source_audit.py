from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.discovery import supply_demand_source_audit
from app.discovery.supply_demand_source_audit import (
    CommodityMetricMapping,
    MetricTaxonomyItem,
    SupplyDemandSourceCandidate,
    audit_to_dict,
    build_audit,
    candidate_to_dict,
    commodity_metric_mappings,
    count_by_status,
    mapping_to_dict,
    metric_taxonomy,
    metric_to_dict,
    recommended_first_source,
    render_report,
    source_candidates,
    write_audit_outputs,
)


def test_candidate_schema_serialization_has_required_fields() -> None:
    required_fields = {
        "source_name",
        "source_url",
        "candidate_status",
        "source_type",
        "auth_required",
        "format",
        "frequency",
        "historical_depth",
        "commodity_coverage",
        "geography_coverage",
        "metrics_available",
        "revisions_available",
        "publication_date_available",
        "rate_limits",
        "license_notes",
        "operational_risk",
        "storage_risk",
        "as_of_risk",
        "ml_value",
        "recommended_next_action",
    }

    candidates = source_candidates()

    assert candidates
    for candidate in candidates:
        data = candidate_to_dict(candidate)
        assert required_fields <= set(data)
        assert data["source_name"]
        assert data["source_url"]
        assert data["metrics_available"]


def test_metric_taxonomy_serialization_has_required_fields() -> None:
    required_fields = {"metric_name", "metric_group", "frequency", "ml_value", "as_of_risk"}

    metrics = metric_taxonomy()

    assert metrics
    for metric in metrics:
        data = metric_to_dict(metric)
        assert required_fields <= set(data)
        assert data["metric_name"]
        assert data["frequency"]


def test_commodity_mapping_serialization_has_required_fields() -> None:
    required_fields = {
        "commodity_family",
        "product_code",
        "official_commodity_name",
        "official_metric",
        "relevance",
        "frequency",
        "notes",
    }

    mappings = commodity_metric_mappings()

    assert mappings
    for mapping in mappings:
        data = mapping_to_dict(mapping)
        assert required_fields <= set(data)
        assert data["commodity_family"]
        assert data["official_commodity_name"]


def test_invalid_candidate_status_is_rejected() -> None:
    base = candidate_to_dict(source_candidates()[0])
    base["candidate_status"] = "maybe"

    with pytest.raises(ValueError):
        SupplyDemandSourceCandidate(**base)  # type: ignore[arg-type]


def test_invalid_candidate_source_type_is_rejected() -> None:
    base = candidate_to_dict(source_candidates()[0])
    base["source_type"] = "spreadsheet"

    with pytest.raises(ValueError):
        SupplyDemandSourceCandidate(**base)  # type: ignore[arg-type]


def test_invalid_metric_group_is_rejected() -> None:
    base = metric_to_dict(metric_taxonomy()[0])
    base["metric_group"] = "nice_to_have"

    with pytest.raises(ValueError):
        MetricTaxonomyItem(**base)  # type: ignore[arg-type]


def test_invalid_mapping_relevance_is_rejected() -> None:
    base = mapping_to_dict(commodity_metric_mappings()[0])
    base["relevance"] = "maybe_later"

    with pytest.raises(ValueError):
        CommodityMetricMapping(**base)  # type: ignore[arg-type]


def test_recommended_first_source_is_usda_psd() -> None:
    audit = build_audit()
    candidate = recommended_first_source(audit.candidates)

    assert candidate.source_name == "USDA PSD / FAS PSD Online"
    assert candidate.source_name == audit.recommended_first_source
    assert candidate.candidate_status == "ready_to_probe"
    assert candidate in audit.candidates


def test_status_counts_cover_ready_manual_complex_and_paid_sources() -> None:
    counts = count_by_status()

    assert counts["ready_to_probe"] >= 1
    assert counts["ready_to_prototype"] >= 1
    assert counts["needs_manual_check"] >= 1
    assert counts["high_complexity"] >= 1
    assert counts["paid_later"] >= 1


def test_metric_taxonomy_includes_core_supply_demand_metrics() -> None:
    metrics = {item.metric_name for item in metric_taxonomy()}

    assert {
        "production",
        "production_volume",
        "consumption",
        "domestic_consumption",
        "food_use",
        "feed_use",
        "beginning_stocks",
        "ending_stocks",
        "stock_to_use",
        "planted_area",
        "harvested_area",
        "yield",
        "crush",
        "exports",
        "imports",
        "revisions",
        "production_forecast_revision",
        "ending_stocks_revision",
        "stock_to_use_revision",
        "forecast_month",
        "marketing_year",
        "report_publication_date",
        "reporting_lag",
        "supply_demand_as_of_date",
        "missing_flags",
    } <= metrics


def test_commodity_mappings_include_current_products() -> None:
    mappings = commodity_metric_mappings()
    product_codes = {mapping.product_code for mapping in mappings if mapping.product_code}

    assert {"soybean_oil", "soybean_meal", "rapeseed_oil", "rapeseed_meal"} <= product_codes
    assert any(mapping.commodity_family == "soybean" and mapping.product_code is None for mapping in mappings)
    assert any(mapping.commodity_family == "rapeseed_canola" and mapping.product_code is None for mapping in mappings)


def test_static_fallback_when_live_probe_requested() -> None:
    audit = build_audit(live_probe=True)

    assert audit.live_probing == "not_supported_static_registry_only"
    assert audit.candidates
    assert audit.metric_taxonomy
    assert audit.commodity_metric_mappings


def test_report_generation_mentions_required_sources_and_sections() -> None:
    report = render_report(build_audit())

    assert "USDA PSD / FAS PSD Online" in report
    assert "USDA WASDE" in report
    assert "USDA NASS Quick Stats" in report
    assert "FAOSTAT Crops and Livestock Products / Food Balances" in report
    assert "AMIS Market Database / Monitor" in report
    assert "International Grains Council / IGC" in report
    assert "Statistics Canada / Agriculture Canada" in report
    assert "CONAB Brazil" in report
    assert "Argentina official agriculture/statistics sources" in report
    assert "Eurostat Agriculture" in report
    assert "Proposed Future Schema" in report
    assert "Dedup/Idempotency Policy" in report
    assert "As-Of/Leakage Policy" in report
    assert "Revision Policy" in report


def test_report_generation_mentions_non_goals() -> None:
    report = render_report(build_audit())

    assert "No production DB writes" in report
    assert "No collectors" in report
    assert "No scheduler changes" in report
    assert "No migrations" in report
    assert "No ML model" in report
    assert "No targets" in report
    assert "No live API probing" in report


def test_as_of_policy_is_explicit_in_report() -> None:
    report = render_report(build_audit())

    assert "published_at <= feature_date" in report
    assert "fetched_at <= feature_date" in report
    assert "historical_backfill_allowed" in report
    assert "Do not use future report vintages" in report


def test_json_generation_and_artifacts(tmp_path: Path) -> None:
    audit = build_audit()

    write_audit_outputs(audit, tmp_path)
    json_path = tmp_path / "supply_demand_source_candidates.json"
    report_path = tmp_path / "SUPPLY_DEMAND_SOURCE_AUDIT_REPORT.md"
    data = json.loads(json_path.read_text(encoding="utf-8"))

    assert report_path.exists()
    assert data["live_probing"] == "not_run_static_registry"
    assert data["recommended_first_source"] == "USDA PSD / FAS PSD Online"
    assert data["recommended_first_prototype_scope"]
    assert data["metric_taxonomy"][0]["metric_name"]
    assert data["commodity_metric_mappings"][0]["commodity_family"]
    assert data["candidates"][0]["source_name"]
    assert audit_to_dict(audit)["candidates"]


def test_cli_runs_without_database_or_raw_store(tmp_path: Path) -> None:
    output_dir = tmp_path / "supply_demand_audit"
    env = {**os.environ, "LOG_DIR": str(tmp_path / "logs")}

    result = subprocess.run(
        [sys.executable, "scripts/audit_supply_demand_sources.py", "--output-dir", str(output_dir)],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    assert "phase=6.7A" in result.stdout
    assert "recommended_first_source=USDA PSD / FAS PSD Online" in result.stdout
    assert "metric_taxonomy=25" in result.stdout
    assert "commodity_metric_mappings=9" in result.stdout
    assert "ready_to_probe_or_prototype=2" in result.stdout
    assert (output_dir / "SUPPLY_DEMAND_SOURCE_AUDIT_REPORT.md").exists()
    assert (output_dir / "supply_demand_source_candidates.json").exists()


def test_discovery_module_does_not_use_production_db_or_raw_store() -> None:
    source = Path(supply_demand_source_audit.__file__).read_text(encoding="utf-8")

    assert "from app.db" not in source
    assert "import app.db" not in source
    assert "from app.storage.raw_store" not in source
    assert "import app.storage.raw_store" not in source
