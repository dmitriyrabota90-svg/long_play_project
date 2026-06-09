from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.discovery import commodity_benchmark_audit
from app.discovery.commodity_benchmark_audit import (
    CommodityBenchmarkSourceCandidate,
    audit_to_dict,
    build_audit,
    candidate_to_dict,
    count_by_status,
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
        "candidate_status",
        "data_domain",
        "instruments",
        "format",
        "frequency",
        "history_depth",
        "auth_required",
        "rate_limits",
        "license_notes",
        "operational_risk",
        "unit_notes",
        "publication_delay_notes",
        "ml_value",
        "recommended_next_action",
    }

    candidates = source_candidates()

    assert candidates
    for candidate in candidates:
        data = candidate_to_dict(candidate)
        assert required_fields <= set(data)
        assert data["instruments"]


def test_invalid_candidate_status_is_rejected() -> None:
    base = candidate_to_dict(source_candidates()[0])
    base["candidate_status"] = "maybe_later"

    with pytest.raises(ValueError):
        CommodityBenchmarkSourceCandidate(**base)  # type: ignore[arg-type]


def test_recommended_first_source_is_world_bank() -> None:
    candidate = recommended_first_source()

    assert candidate.source_name == "World Bank Pink Sheet"
    assert candidate.candidate_status == "ready_to_prototype"


def test_at_least_one_ready_to_prototype_source_exists() -> None:
    counts = count_by_status()

    assert counts["ready_to_prototype"] >= 1


def test_high_risk_classification_marks_unofficial_or_commercial_sources() -> None:
    names = {candidate.source_name for candidate in high_risk_candidates()}

    assert "Nasdaq Data Link" in names
    assert "Stooq / Yahoo-like market endpoints" in names
    assert "Jijinhao/Cngold regional source" in names


def test_static_registry_live_probe_fallback() -> None:
    audit = build_audit(live_probe=True)

    assert audit.live_probing == "not_run_static_registry"
    assert audit.candidates


def test_report_generation_mentions_future_schema_and_non_goals() -> None:
    report = render_report(build_audit())

    assert "World Bank Pink Sheet" in report
    assert "commodity_benchmarks" in report
    assert "No production DB writes" in report
    assert "No ML model" in report


def test_json_generation_and_artifacts(tmp_path: Path) -> None:
    audit = build_audit()

    write_audit_outputs(audit, tmp_path)
    json_path = tmp_path / "commodity_benchmark_candidates.json"
    report_path = tmp_path / "COMMODITY_BENCHMARK_AUDIT_REPORT.md"
    data = json.loads(json_path.read_text(encoding="utf-8"))

    assert report_path.exists()
    assert data["live_probing"] == "not_run_static_registry"
    assert data["recommended_first_source"] == "World Bank Pink Sheet"
    assert data["candidates"][0]["source_name"]
    assert audit_to_dict(audit)["candidates"]


def test_cli_runs_without_database_or_raw_store(tmp_path: Path) -> None:
    output_dir = tmp_path / "benchmark_audit"
    env = {**os.environ, "LOG_DIR": str(tmp_path / "logs")}

    result = subprocess.run(
        [sys.executable, "scripts/audit_commodity_benchmarks.py", "--output-dir", str(output_dir)],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    assert "phase=6.2A" in result.stdout
    assert "recommended_first_source=World Bank Pink Sheet" in result.stdout
    assert (output_dir / "COMMODITY_BENCHMARK_AUDIT_REPORT.md").exists()
    assert (output_dir / "commodity_benchmark_candidates.json").exists()


def test_discovery_module_does_not_use_production_db_or_raw_store() -> None:
    source = Path(commodity_benchmark_audit.__file__).read_text(encoding="utf-8")

    assert "from app.db" not in source
    assert "import app.db" not in source
    assert "from app.storage.raw_store" not in source
    assert "import app.storage.raw_store" not in source
