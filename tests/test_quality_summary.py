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
from app.monitoring.quality_summary import build_quality_summary, is_problematic_quality_status
from app.monitoring.redaction import mask_database_url


def _add_check(session, *, status: str, severity: str = "info") -> None:
    session.add(
        DataQualityCheck(
            table_name="price_observations",
            check_name=f"check_{status}",
            checked_at=datetime.now(timezone.utc),
            status=status,
            severity=severity,
            details_json={"status": status},
        )
    )


def _session_factory(database_url: str = "sqlite+pysqlite:///:memory:"):
    engine = create_engine(database_url, future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, future=True)


def test_pass_and_skip_are_not_problematic() -> None:
    assert is_problematic_quality_status("pass") is False
    assert is_problematic_quality_status("skip") is False


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
