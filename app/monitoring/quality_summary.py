from __future__ import annotations

from typing import Any

from sqlalchemy import func, not_, select
from sqlalchemy.orm import Session

from app.db.models import DataQualityCheck
from app.db.session import session_scope

OK_QUALITY_STATUSES = ("pass", "skip")


def is_problematic_quality_status(status: str) -> bool:
    return status not in OK_QUALITY_STATUSES


def problematic_quality_filter():
    return not_(DataQualityCheck.status.in_(OK_QUALITY_STATUSES))


def build_quality_summary(*, limit: int = 20, session: Session | None = None) -> dict[str, Any]:
    if session is not None:
        return _build_quality_summary(session, limit=limit)

    with session_scope() as scoped_session:
        return _build_quality_summary(scoped_session, limit=limit)


def _build_quality_summary(session: Session, *, limit: int) -> dict[str, Any]:
    total_checks = session.scalar(select(func.count()).select_from(DataQualityCheck)) or 0
    checks_by_status = _count_by(session, DataQualityCheck.status)
    checks_by_severity = _count_by(session, DataQualityCheck.severity)
    problematic_count = session.scalar(
        select(func.count()).select_from(DataQualityCheck).where(problematic_quality_filter())
    ) or 0

    last_problematic = session.scalars(
        select(DataQualityCheck)
        .where(problematic_quality_filter())
        .order_by(DataQualityCheck.checked_at.desc(), DataQualityCheck.id.desc())
        .limit(limit)
    ).all()

    return {
        "total_checks": total_checks,
        "checks_by_status": checks_by_status,
        "checks_by_severity": checks_by_severity,
        "pass_checks": checks_by_status.get("pass", 0),
        "skip_checks": checks_by_status.get("skip", 0),
        "problematic_checks": problematic_count,
        "last_problematic_checks": [_quality_check_to_dict(check) for check in last_problematic],
        "conclusion": _conclusion(problematic_count, checks_by_status),
    }


def _count_by(session: Session, column) -> dict[str, int]:
    rows = session.execute(
        select(column, func.count()).select_from(DataQualityCheck).group_by(column).order_by(column)
    ).all()
    return {str(value): int(count) for value, count in rows}


def _quality_check_to_dict(check: DataQualityCheck) -> dict[str, Any]:
    return {
        "id": check.id,
        "table_name": check.table_name,
        "check_name": check.check_name,
        "status": check.status,
        "severity": check.severity,
        "checked_at": check.checked_at.isoformat(),
        "details_json": check.details_json,
    }


def _conclusion(problematic_count: int, checks_by_status: dict[str, int]) -> str:
    if problematic_count == 0:
        return "ok"
    if checks_by_status.get("fail", 0) or checks_by_status.get("failed", 0) or checks_by_status.get("error", 0):
        return "error"
    return "warning"
