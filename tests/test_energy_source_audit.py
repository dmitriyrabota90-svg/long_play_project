from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.discovery import energy_source_audit
from app.discovery.energy_source_audit import (
    EnergySourceCandidate,
    audit_to_dict,
    build_audit,
    candidate_to_dict,
    high_risk_candidates,
    recommended_first_source,
    render_report,
    source_candidates,
    write_audit_outputs,
)


def test_candidates_have_required_fields() -> None:
    required_fields = {
        "source_name",
        "source_url",
        "data_type",
        "instruments",
        "format",
        "frequency",
        "history_depth",
        "auth_required",
        "rate_limits",
        "license_notes",
        "operational_risk",
        "recommended_status",
        "notes",
    }

    candidates = source_candidates()

    assert candidates
    for candidate in candidates:
        data = candidate_to_dict(candidate)
        assert required_fields <= set(data)
        assert data["instruments"]


def test_invalid_status_is_rejected() -> None:
    base = candidate_to_dict(source_candidates()[0])
    base["recommended_status"] = "maybe_later"

    with pytest.raises(ValueError):
        EnergySourceCandidate(**base)  # type: ignore[arg-type]


def test_high_risk_classification_marks_unofficial_sources() -> None:
    names = {candidate.source_name for candidate in high_risk_candidates()}

    assert "Yahoo Finance / Investing / TradingEconomics-like endpoints" in names


def test_recommended_first_source_is_fred() -> None:
    candidate = recommended_first_source()

    assert candidate.source_name == "FRED EIA-derived CSV"
    assert candidate.recommended_status == "ready_to_prototype"


def test_static_fallback_when_live_probe_requested() -> None:
    audit = build_audit(live_probe=True)

    assert audit.live_probing == "not_supported"
    assert audit.candidates


def test_report_generation_mentions_energy_schema_plan() -> None:
    report = render_report(build_audit())

    assert "FRED EIA-derived CSV" in report
    assert "energy_prices" in report
    assert "No production DB writes" in report


def test_json_generation_and_artifacts(tmp_path: Path) -> None:
    audit = build_audit()

    write_audit_outputs(audit, tmp_path)
    json_path = tmp_path / "energy_source_candidates.json"
    report_path = tmp_path / "ENERGY_SOURCE_AUDIT_REPORT.md"
    data = json.loads(json_path.read_text(encoding="utf-8"))

    assert report_path.exists()
    assert data["live_probing"] == "not_run_static_registry"
    assert data["candidates"][0]["source_name"]
    assert audit_to_dict(audit)["candidates"]


def test_discovery_module_does_not_use_production_db_or_raw_store() -> None:
    source = Path(energy_source_audit.__file__).read_text(encoding="utf-8")

    assert "from app.db" not in source
    assert "import app.db" not in source
    assert "from app.storage.raw_store" not in source
    assert "import app.storage.raw_store" not in source
