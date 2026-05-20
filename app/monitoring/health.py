from __future__ import annotations

from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config.settings import get_settings
from app.db.models import CollectorRun, Product, Source
from app.db.session import session_scope


def run_health_check(
    *,
    session: Session | None = None,
    raw_data_dir: Path | str | None = None,
    export_data_dir: Path | str | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    raw_dir = Path(raw_data_dir) if raw_data_dir is not None else Path(settings.raw_data_dir)
    export_dir = Path(export_data_dir) if export_data_dir is not None else Path(settings.export_data_dir)

    result: dict[str, Any] = {
        "status": "ok",
        "database": {"ok": False},
        "storage": {
            "raw_data_dir": str(raw_dir),
            "raw_data_dir_ok": raw_dir.exists() and raw_dir.is_dir(),
            "export_data_dir": str(export_dir),
            "export_data_dir_ok": export_dir.exists() and export_dir.is_dir(),
        },
        "products_count": None,
        "sources_count": None,
        "last_collector_run": None,
    }

    try:
        if session is not None:
            _fill_database_health(session, result)
        else:
            with session_scope() as scoped_session:
                _fill_database_health(scoped_session, result)
    except Exception as exc:
        result["database"] = {"ok": False, "error": str(exc)}

    if not result["database"].get("ok") or not result["storage"]["raw_data_dir_ok"] or not result["storage"]["export_data_dir_ok"]:
        result["status"] = "degraded"

    return result


def _fill_database_health(session: Session, result: dict[str, Any]) -> None:
    result["database"] = {"ok": True}
    result["products_count"] = session.scalar(select(func.count()).select_from(Product))
    result["sources_count"] = session.scalar(select(func.count()).select_from(Source))
    last_run = session.scalar(select(CollectorRun).order_by(CollectorRun.started_at.desc()).limit(1))
    if last_run is not None:
        result["last_collector_run"] = {
            "id": last_run.id,
            "collector_name": last_run.collector_name,
            "status": last_run.status,
            "started_at": last_run.started_at.isoformat(),
            "finished_at": last_run.finished_at.isoformat() if last_run.finished_at else None,
        }

