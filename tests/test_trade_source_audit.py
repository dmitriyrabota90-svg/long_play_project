from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.discovery import trade_source_audit
from app.discovery.trade_source_audit import (
    HSCodeMapping,
    TradeSourceCandidate,
    audit_to_dict,
    build_audit,
    candidate_to_dict,
    count_by_status,
    hs_code_mappings,
    mapping_to_dict,
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
        "commodity_granularity",
        "country_partner_support",
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


def test_hs_mapping_schema_serialization_has_required_fields() -> None:
    required_fields = {
        "commodity_family",
        "product_code",
        "hs_code",
        "hs_description",
        "relevance",
        "notes",
    }

    mappings = hs_code_mappings()

    assert mappings
    for mapping in mappings:
        data = mapping_to_dict(mapping)
        assert required_fields <= set(data)
        assert data["hs_code"]
        assert data["hs_description"]


def test_invalid_candidate_status_is_rejected() -> None:
    base = candidate_to_dict(source_candidates()[0])
    base["candidate_status"] = "maybe"

    with pytest.raises(ValueError):
        TradeSourceCandidate(**base)  # type: ignore[arg-type]


def test_invalid_candidate_source_type_is_rejected() -> None:
    base = candidate_to_dict(source_candidates()[0])
    base["source_type"] = "spreadsheet"

    with pytest.raises(ValueError):
        TradeSourceCandidate(**base)  # type: ignore[arg-type]


def test_invalid_hs_relevance_is_rejected() -> None:
    base = mapping_to_dict(hs_code_mappings()[0])
    base["relevance"] = "nice_to_have"

    with pytest.raises(ValueError):
        HSCodeMapping(**base)  # type: ignore[arg-type]


def test_recommended_first_source_exists() -> None:
    audit = build_audit()
    candidate = recommended_first_source(audit.candidates)

    assert candidate.source_name == "UN Comtrade"
    assert candidate.source_name == audit.recommended_first_source
    assert candidate in audit.candidates
    assert candidate.candidate_status == "ready_to_probe"


def test_status_counts_cover_ready_manual_and_later_sources() -> None:
    counts = count_by_status()

    assert counts["ready_to_probe"] >= 1
    assert counts["ready_to_prototype"] >= 1
    assert counts["needs_manual_check"] >= 1
    assert counts["paid_later"] >= 1
    assert counts["high_complexity"] >= 1


def test_hs_mappings_include_core_oilseed_products() -> None:
    mappings = hs_code_mappings()
    codes_by_family = {mapping.commodity_family: mapping.hs_code for mapping in mappings}
    product_codes = {mapping.product_code for mapping in mappings if mapping.product_code}

    assert codes_by_family["soybean"] == "1201"
    assert codes_by_family["soybean_oil"] == "1507"
    assert codes_by_family["soybean_meal"] == "2304"
    assert codes_by_family["rapeseed_canola"] == "1205"
    assert codes_by_family["rapeseed_oil"] == "1514"
    assert codes_by_family["rapeseed_meal"] == "2306"
    assert {"soybean_oil", "soybean_meal", "rapeseed_oil", "rapeseed_meal"} <= product_codes


def test_static_fallback_when_live_probe_requested() -> None:
    audit = build_audit(live_probe=True)

    assert audit.live_probing == "not_supported_static_registry_only"
    assert audit.candidates
    assert audit.hs_code_mappings


def test_report_generation_mentions_trade_schema_and_non_goals() -> None:
    report = render_report(build_audit())

    assert "UN Comtrade" in report
    assert "FAOSTAT" in report
    assert "USDA FAS / GATS / PSD" in report
    assert "World Bank WITS" in report
    assert "ITC Trade Map" in report
    assert "Eurostat Comext" in report
    assert "National customs" in report
    assert "trade_commodity_codes" in report
    assert "trade_flows" in report
    assert "monthly_trade_features" in report
    assert "No production DB writes" in report
    assert "No collectors" in report
    assert "No ML model" in report
    assert "No targets" in report


def test_as_of_policy_is_explicit_in_report() -> None:
    report = render_report(build_audit())

    assert "published_at <= feature_date" in report
    assert "fetched_at <= feature_date" in report
    assert "historical_backfill_allowed" in report
    assert "Do not use future month trade data" in report


def test_json_generation_and_artifacts(tmp_path: Path) -> None:
    audit = build_audit()

    write_audit_outputs(audit, tmp_path)
    json_path = tmp_path / "trade_source_candidates.json"
    report_path = tmp_path / "TRADE_SOURCE_AUDIT_REPORT.md"
    data = json.loads(json_path.read_text(encoding="utf-8"))

    assert report_path.exists()
    assert data["live_probing"] == "not_run_static_registry"
    assert data["mode"] == "inventory"
    assert data["recommended_first_source"] == "UN Comtrade"
    assert data["recommended_first_prototype_scope"]
    assert data["hs_code_mappings"][0]["commodity_family"]
    assert data["candidates"][0]["source_name"]
    assert audit_to_dict(audit)["candidates"]


def test_cli_runs_without_database_or_raw_store(tmp_path: Path) -> None:
    output_dir = tmp_path / "trade_audit"
    env = {**os.environ, "LOG_DIR": str(tmp_path / "logs")}

    result = subprocess.run(
        [sys.executable, "scripts/audit_trade_sources.py", "--output-dir", str(output_dir)],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    assert "phase=6.5A" in result.stdout
    assert "recommended_first_source=UN Comtrade" in result.stdout
    assert "hs_code_mappings=11" in result.stdout
    assert "ready_to_probe_or_prototype=2" in result.stdout
    assert (output_dir / "TRADE_SOURCE_AUDIT_REPORT.md").exists()
    assert (output_dir / "trade_source_candidates.json").exists()


def test_discovery_module_does_not_use_production_db_or_raw_store() -> None:
    source = Path(trade_source_audit.__file__).read_text(encoding="utf-8")

    assert "from app.db" not in source
    assert "import app.db" not in source
    assert "from app.storage.raw_store" not in source
    assert "import app.storage.raw_store" not in source
