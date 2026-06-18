from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.models import Base, DataQualityCheck, Source
from app.monitoring.current_price_report import build_current_price_health_report
from app.monitoring.operational_report import build_operational_report
from app.monitoring.quality_summary import build_quality_summary, classify_quality_check, is_problematic_quality_status
from app.monitoring.redaction import mask_database_url


def _add_check(
    session,
    *,
    status: str,
    severity: str = "info",
    table_name: str = "price_observations",
    check_name: str | None = None,
    checked_at: datetime | None = None,
    details_json: dict | None = None,
) -> DataQualityCheck:
    check = DataQualityCheck(
        table_name=table_name,
        check_name=check_name or f"check_{status}",
        checked_at=checked_at or datetime.now(timezone.utc),
        status=status,
        severity=severity,
        details_json=details_json or {"status": status},
    )
    session.add(check)
    return check


def _session_factory(database_url: str = "sqlite+pysqlite:///:memory:"):
    engine = create_engine(database_url, future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def test_pass_and_skip_are_not_problematic() -> None:
    assert is_problematic_quality_status("pass") is False
    assert is_problematic_quality_status("skip") is False
    assert is_problematic_quality_status("info") is False


def test_failed_and_warning_are_problematic() -> None:
    assert is_problematic_quality_status("fail") is True
    assert is_problematic_quality_status("failed") is True
    assert is_problematic_quality_status("warning") is True


def test_quality_summary_counts_problematic_checks() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _add_check(session, status="pass")
        _add_check(session, status="skip")
        _add_check(session, status="fail", severity="error")
        _add_check(session, status="warning", severity="warning")
        session.commit()

        summary = build_quality_summary(session=session)

    assert summary["total_checks"] == 4
    assert summary["pass_checks"] == 1
    assert summary["skip_checks"] == 1
    assert summary["problematic_checks"] == 2
    assert summary["active_current_failures"] == 2
    assert summary["known_historical_incidents"] == 0
    assert summary["expected_diagnostic_incidents"] == 0
    assert [item["status"] for item in summary["last_problematic_checks"]] == ["warning", "fail"]
    assert summary["conclusion"] == "error"


def test_quality_summary_ok_when_only_pass_and_skip() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _add_check(session, status="pass")
        _add_check(session, status="skip")
        session.commit()

        summary = build_quality_summary(session=session)

    assert summary["problematic_checks"] == 0
    assert summary["conclusion"] == "ok"
    assert summary["message"] == "quality checks ok"


def test_quality_summary_classifies_known_historical_and_diagnostic_incidents() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        dns_check = _add_check(
            session,
            status="fail",
            severity="error",
            table_name="price_observations",
            check_name="raw_response_present",
            checked_at=datetime(2026, 5, 26, 9, 0, tzinfo=timezone.utc),
            details_json={"raw_response_id": None, "product_id": 1},
        )
        mutable_check = _add_check(
            session,
            status="warning",
            severity="warning",
            table_name="historical_price_bars",
            check_name="historical_existing_bar_hash_changed",
            checked_at=datetime(2026, 5, 29, 12, 0, tzinfo=timezone.utc),
            details_json={"bar_date": "2026-05-28", "policy_decision": "rejected_hash_conflict_no_overwrite"},
        )
        metadata_probe_check = _add_check(
            session,
            status="fail",
            severity="error",
            table_name="raw_responses",
            check_name="supply_demand_normalized_rows_found",
            checked_at=datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc),
            details_json={
                "error": "USDA PSD endpoint returned downloadable dataset metadata, not data rows",
                "request": {"live_probe": True},
            },
        )
        html_probe_check = _add_check(
            session,
            status="fail",
            severity="warning",
            table_name="raw_responses",
            check_name="supply_demand_content_type_expected",
            checked_at=datetime(2026, 6, 15, 12, 1, tzinfo=timezone.utc),
            details_json={"content_type": "text/html; charset=utf-8", "request": {"live_probe": True}},
        )
        session.commit()

        summary = build_quality_summary(session=session)

    assert classify_quality_check(dns_check) == "known_historical_incident"
    assert classify_quality_check(mutable_check) == "known_historical_incident"
    assert classify_quality_check(metadata_probe_check) == "expected_diagnostic_incident"
    assert classify_quality_check(html_probe_check) == "expected_diagnostic_incident"
    assert summary["problematic_checks"] == 4
    assert summary["active_current_failures"] == 0
    assert summary["known_historical_incidents"] == 2
    assert summary["expected_diagnostic_incidents"] == 2
    assert summary["conclusion"] == "ok_with_known_incidents"
    assert summary["message"] == "quality checks ok with known incidents"


def test_quality_summary_keeps_fresh_unknown_failure_active() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _add_check(
            session,
            status="fail",
            severity="error",
            table_name="raw_responses",
            check_name="new_source_parser_failed",
            checked_at=datetime(2026, 6, 15, 13, 0, tzinfo=timezone.utc),
            details_json={"error": "new failure"},
        )
        _add_check(
            session,
            status="fail",
            severity="error",
            table_name="raw_responses",
            check_name="supply_demand_normalized_rows_found",
            checked_at=datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc),
            details_json={
                "error": "USDA PSD endpoint returned HTML shell, not data rows",
                "request": {"live_probe": True},
            },
        )
        session.commit()

        summary = build_quality_summary(session=session)

    assert summary["problematic_checks"] == 2
    assert summary["active_current_failures"] == 1
    assert summary["expected_diagnostic_incidents"] == 1
    assert summary["conclusion"] == "error"
    assert summary["last_active_problematic_checks"][0]["check_name"] == "new_source_parser_failed"


def test_quality_summary_classifies_known_usda_psd_skip_and_mapping_incidents() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        expected_skip_check = _add_check(
            session,
            status="fail",
            severity="warning",
            table_name="supply_demand_observations",
            check_name="supply_demand_malformed_row_skipped",
            checked_at=datetime(2026, 6, 16, 12, 0, tzinfo=timezone.utc),
            details_json={
                "error": "unsupported or missing metric: total_supply",
                "request": {"live_probe": True},
            },
        )
        mapping_gap_check = _add_check(
            session,
            status="fail",
            severity="warning",
            table_name="supply_demand_commodities",
            check_name="supply_demand_mapping_found",
            checked_at=datetime(2026, 6, 16, 12, 1, tzinfo=timezone.utc),
            details_json={
                "product_code": "soybean_oil",
                "metric_name": "crush_volume",
                "request": {"live_probe": True},
            },
        )
        future_unknown_skip = _add_check(
            session,
            status="fail",
            severity="warning",
            table_name="supply_demand_observations",
            check_name="supply_demand_malformed_row_skipped",
            checked_at=datetime(2026, 6, 19, 12, 0, tzinfo=timezone.utc),
            details_json={
                "error": "unsupported metric: new_unknown_metric",
                "request": {"live_probe": True},
            },
        )
        session.commit()

        summary = build_quality_summary(session=session)

    assert classify_quality_check(expected_skip_check) == "expected_diagnostic_incident"
    assert classify_quality_check(mapping_gap_check) == "expected_diagnostic_incident"
    assert classify_quality_check(future_unknown_skip) == "active_current_failure"
    assert summary["problematic_checks"] == 3
    assert summary["expected_diagnostic_incidents"] == 2
    assert summary["active_current_failures"] == 1
    assert summary["last_expected_diagnostic_incidents"][0]["classification_reason"] == (
        "expected_usda_psd_skip_or_mapping_incident_before_phase_6_9k_fix"
    )


def test_operational_report_quality_status_allows_known_incidents() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        _add_check(
            session,
            status="fail",
            severity="error",
            table_name="price_observations",
            check_name="price_is_not_null",
            checked_at=datetime(2026, 5, 26, 9, 0, tzinfo=timezone.utc),
            details_json={"raw_response_id": None, "product_id": 1},
        )
        _add_check(
            session,
            status="fail",
            severity="error",
            table_name="raw_responses",
            check_name="supply_demand_normalized_rows_found",
            checked_at=datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc),
            details_json={
                "error": "USDA PSD endpoint returned downloadable dataset metadata, not data rows",
                "request": {"live_probe": True},
            },
        )
        session.commit()

        report = build_operational_report(freshness_hours=24, session=session)

    assert report["quality_checks"]["conclusion"] == "ok_with_known_incidents"
    assert report["quality_checks"]["active_current_failures"] == 0
    assert report["quality_checks"]["known_historical_incidents"] == 1
    assert report["quality_checks"]["expected_diagnostic_incidents"] == 1


def test_current_price_health_uses_problematic_quality_filter() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        source = Source(code="current_price_source", name="Current price source", source_type="price")
        session.add(source)
        session.flush()
        _add_check(session, status="pass")
        _add_check(session, status="skip")
        session.query(DataQualityCheck).update({DataQualityCheck.source_id: source.id})
        _add_check(session, status="warning", severity="warning")
        warning_check = session.query(DataQualityCheck).order_by(DataQualityCheck.id.desc()).first()
        warning_check.source_id = source.id
        session.commit()

        report = build_current_price_health_report(session=session)

    current_price = report["current_price_source"]
    assert "quality_failures_last_24h" not in current_price
    assert current_price["problematic_quality_checks_last_24h"] == 1


def test_database_url_is_masked() -> None:
    masked = mask_database_url("postgresql+psycopg2://collector:secret@postgres:5432/commodity_dataset")

    assert masked == "postgresql+psycopg2://collector:***@postgres:5432/commodity_dataset"
    assert "secret" not in masked


def test_operational_report_does_not_print_database_password() -> None:
    SessionLocal = _session_factory()
    with SessionLocal() as session:
        report = build_operational_report(freshness_hours=24, session=session)

    rendered = json.dumps(report, ensure_ascii=False)
    assert "collector_password" not in rendered
    assert report["database"]["database_url"] == (
        "postgresql+psycopg2://collector:***@postgres:5432/commodity_dataset"
    )


def test_quality_summary_cli_outputs_summary(tmp_path: Path) -> None:
    db_path = tmp_path / "quality.sqlite"
    database_url = f"sqlite+pysqlite:///{db_path}"
    SessionLocal = _session_factory(database_url)
    with SessionLocal() as session:
        _add_check(session, status="pass")
        _add_check(session, status="skip")
        session.commit()

    env = os.environ.copy()
    env["DATABASE_URL"] = database_url
    env["LOG_DIR"] = str(tmp_path / "logs")
    result = subprocess.run(
        [sys.executable, "scripts/quality_summary.py", "--limit", "5"],
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    summary = json.loads(result.stdout)
    assert summary["total_checks"] == 2
    assert summary["problematic_checks"] == 0
    assert summary["message"] == "quality checks ok"
