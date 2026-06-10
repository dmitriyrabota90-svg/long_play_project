from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.discovery import weather_source_audit
from app.discovery.weather_source_audit import (
    WeatherRegion,
    WeatherSourceCandidate,
    audit_to_dict,
    build_audit,
    candidate_to_dict,
    count_by_status,
    recommended_first_source,
    recommended_regions,
    region_to_dict,
    render_report,
    source_candidates,
    write_audit_outputs,
)


def test_candidate_schema_serialization_has_required_fields() -> None:
    required_fields = {
        "source_name",
        "source_url",
        "candidate_status",
        "auth_required",
        "format",
        "spatial_model",
        "variables_available",
        "historical_depth",
        "frequency",
        "rate_limits",
        "license_notes",
        "operational_risk",
        "storage_risk",
        "ml_value",
        "recommended_next_action",
    }

    candidates = source_candidates()

    assert candidates
    for candidate in candidates:
        data = candidate_to_dict(candidate)
        assert required_fields <= set(data)
        assert data["variables_available"]


def test_region_schema_serialization_has_required_fields() -> None:
    required_fields = {
        "region_code",
        "region_name",
        "country",
        "crop",
        "commodity_family",
        "role",
        "latitude",
        "longitude",
        "aggregation_strategy",
        "priority",
        "reason_for_ml",
    }

    regions = recommended_regions()

    assert regions
    for region in regions:
        data = region_to_dict(region)
        assert required_fields <= set(data)
        assert -90 <= data["latitude"] <= 90
        assert -180 <= data["longitude"] <= 180


def test_invalid_candidate_status_is_rejected() -> None:
    base = candidate_to_dict(source_candidates()[0])
    base["candidate_status"] = "maybe_later"

    with pytest.raises(ValueError):
        WeatherSourceCandidate(**base)  # type: ignore[arg-type]


def test_invalid_region_priority_is_rejected() -> None:
    base = region_to_dict(recommended_regions()[0])
    base["priority"] = "urgent"

    with pytest.raises(ValueError):
        WeatherRegion(**base)  # type: ignore[arg-type]


def test_recommended_first_source_is_open_meteo() -> None:
    candidate = recommended_first_source()

    assert candidate.source_name == "Open-Meteo Historical Weather API"
    assert candidate.candidate_status == "ready_to_prototype"


def test_status_counts_include_ready_and_high_complexity() -> None:
    counts = count_by_status()

    assert counts["ready_to_prototype"] >= 1
    assert counts["high_complexity"] >= 1
    assert counts["needs_manual_check"] >= 1


def test_recommended_regions_include_soybean_and_rapeseed_regions() -> None:
    regions = recommended_regions()
    families = {region.commodity_family for region in regions}
    high_priority_codes = {region.region_code for region in regions if region.priority == "high"}

    assert "soybean" in families
    assert "rapeseed" in families
    assert "br_mt_soybean_belt" in high_priority_codes
    assert "ca_sk_canola_belt" in high_priority_codes


def test_static_fallback_when_live_probe_requested() -> None:
    audit = build_audit(live_probe=True)

    assert audit.live_probing == "not_supported_static_registry_only"
    assert audit.candidates
    assert audit.recommended_regions


def test_report_generation_mentions_weather_schema_and_non_goals() -> None:
    report = render_report(build_audit())

    assert "Open-Meteo Historical Weather API" in report
    assert "weather_regions" in report
    assert "weather_observations" in report
    assert "No production DB writes" in report
    assert "No ML model" in report


def test_json_generation_and_artifacts(tmp_path: Path) -> None:
    audit = build_audit()

    write_audit_outputs(audit, tmp_path)
    json_path = tmp_path / "weather_source_candidates.json"
    report_path = tmp_path / "WEATHER_SOURCE_AUDIT_REPORT.md"
    data = json.loads(json_path.read_text(encoding="utf-8"))

    assert report_path.exists()
    assert data["live_probing"] == "not_run_static_registry"
    assert data["recommended_first_source"] == "Open-Meteo Historical Weather API"
    assert data["recommended_regions"][0]["region_code"]
    assert data["candidates"][0]["source_name"]
    assert audit_to_dict(audit)["candidates"]


def test_cli_runs_without_database_or_raw_store(tmp_path: Path) -> None:
    output_dir = tmp_path / "weather_audit"
    env = {**os.environ, "LOG_DIR": str(tmp_path / "logs")}

    result = subprocess.run(
        [sys.executable, "scripts/audit_weather_sources.py", "--output-dir", str(output_dir)],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    assert "phase=6.3A" in result.stdout
    assert "recommended_first_source=Open-Meteo Historical Weather API" in result.stdout
    assert (output_dir / "WEATHER_SOURCE_AUDIT_REPORT.md").exists()
    assert (output_dir / "weather_source_candidates.json").exists()


def test_discovery_module_does_not_use_production_db_or_raw_store() -> None:
    source = Path(weather_source_audit.__file__).read_text(encoding="utf-8")

    assert "from app.db" not in source
    assert "import app.db" not in source
    assert "from app.storage.raw_store" not in source
    assert "import app.storage.raw_store" not in source
