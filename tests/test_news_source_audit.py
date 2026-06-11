from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.discovery import news_source_audit
from app.discovery.news_source_audit import (
    EventTaxonomyItem,
    NewsSourceCandidate,
    audit_to_dict,
    build_audit,
    candidate_to_dict,
    count_by_status,
    recommended_first_source,
    render_report,
    source_candidates,
    taxonomy_to_dict,
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
        "expected_fields",
        "historical_depth",
        "rate_limits",
        "license_notes",
        "operational_risk",
        "noise_risk",
        "language",
        "regions_covered",
        "commodity_relevance",
        "recommended_next_action",
    }

    candidates = source_candidates()

    assert candidates
    for candidate in candidates:
        data = candidate_to_dict(candidate)
        assert required_fields <= set(data)
        assert data["expected_fields"]
        assert data["regions_covered"]


def test_event_taxonomy_serialization_has_required_fields() -> None:
    required_fields = {
        "event_category",
        "affected_commodity_family",
        "expected_direction_hint",
        "expected_lag_days",
        "useful_text_fields",
        "why_useful_for_ml",
    }

    taxonomy = build_audit().event_taxonomy

    assert taxonomy
    for item in taxonomy:
        data = taxonomy_to_dict(item)
        assert required_fields <= set(data)
        assert data["affected_commodity_family"]
        assert data["useful_text_fields"]


def test_invalid_candidate_status_is_rejected() -> None:
    base = candidate_to_dict(source_candidates()[0])
    base["candidate_status"] = "later"

    with pytest.raises(ValueError):
        NewsSourceCandidate(**base)  # type: ignore[arg-type]


def test_invalid_event_direction_is_rejected() -> None:
    base = taxonomy_to_dict(build_audit().event_taxonomy[0])
    base["expected_direction_hint"] = "certainly_up"

    with pytest.raises(ValueError):
        EventTaxonomyItem(**base)  # type: ignore[arg-type]


def test_recommended_first_source_exists_in_candidates() -> None:
    audit = build_audit()
    candidate = recommended_first_source(audit.candidates)

    assert candidate.source_name == audit.recommended_first_source
    assert candidate in audit.candidates
    assert candidate.candidate_status == "ready_to_prototype"


def test_status_counts_include_ready_and_risky_candidates() -> None:
    counts = count_by_status()

    assert counts["ready_to_prototype"] >= 1
    assert counts["ready_to_probe"] >= 1
    assert counts["needs_manual_check"] >= 1
    assert counts["high_risk"] >= 1
    assert counts["paid_later"] >= 1


def test_taxonomy_contains_required_event_categories() -> None:
    categories = {item.event_category for item in build_audit().event_taxonomy}

    assert {
        "export_restriction",
        "import_policy",
        "weather_disaster",
        "crop_report",
        "war_logistics_disruption",
        "supply_chain",
    } <= categories


def test_static_fallback_when_live_probe_requested() -> None:
    audit = build_audit(live_probe=True)

    assert audit.live_probing == "not_supported_static_registry_only"
    assert audit.candidates
    assert audit.event_taxonomy


def test_report_generation_mentions_schema_proposal_and_non_goals() -> None:
    report = render_report(build_audit())

    assert "GDELT 2.1 DOC/Event APIs" in report
    assert "news_articles" in report
    assert "commodity_events" in report
    assert "daily_news_features" in report
    assert "No production DB writes" in report
    assert "No collector" in report
    assert "No ML" in report
    assert "No LLM classifier" in report


def test_json_generation_and_artifacts(tmp_path: Path) -> None:
    audit = build_audit()

    write_audit_outputs(audit, tmp_path)
    json_path = tmp_path / "news_source_candidates.json"
    report_path = tmp_path / "NEWS_SOURCE_AUDIT_REPORT.md"
    data = json.loads(json_path.read_text(encoding="utf-8"))

    assert report_path.exists()
    assert data["live_probing"] == "not_run_static_registry"
    assert data["mode"] == "inventory"
    assert data["recommended_first_source"] == "GDELT 2.1 DOC/Event APIs"
    assert data["recommended_first_event_layer"]
    assert data["event_taxonomy"][0]["event_category"]
    assert data["candidates"][0]["source_name"]
    assert audit_to_dict(audit)["candidates"]


def test_cli_runs_without_database_or_raw_store(tmp_path: Path) -> None:
    output_dir = tmp_path / "news_audit"
    env = {**os.environ, "LOG_DIR": str(tmp_path / "logs")}

    result = subprocess.run(
        [sys.executable, "scripts/audit_news_sources.py", "--output-dir", str(output_dir)],
        cwd=Path(__file__).resolve().parents[1],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )

    assert "phase=6.4A" in result.stdout
    assert "recommended_first_source=GDELT 2.1 DOC/Event APIs" in result.stdout
    assert "event_categories=10" in result.stdout
    assert (output_dir / "NEWS_SOURCE_AUDIT_REPORT.md").exists()
    assert (output_dir / "news_source_candidates.json").exists()


def test_discovery_module_does_not_use_production_db_or_raw_store() -> None:
    source = Path(news_source_audit.__file__).read_text(encoding="utf-8")

    assert "from app.db" not in source
    assert "import app.db" not in source
    assert "from app.storage.raw_store" not in source
    assert "import app.storage.raw_store" not in source
