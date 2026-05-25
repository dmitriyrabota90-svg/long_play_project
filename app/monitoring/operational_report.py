from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.collectors.prices.current_price_config import CURRENT_PRICE_INSTRUMENTS
from app.config.settings import get_settings
from app.db.models import CollectorRun, DataQualityCheck, PriceObservation, Product, RawResponse, Source
from app.db.session import session_scope
from app.monitoring.quality_summary import build_quality_summary, problematic_quality_filter
from app.monitoring.redaction import mask_database_url
from app.operations.storage import directory_size_bytes


def build_operational_report(*, freshness_hours: int = 24, session: Session | None = None) -> dict[str, Any]:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=24)
    freshness_cutoff = now - timedelta(hours=freshness_hours)
    report: dict[str, Any] = {
        "status": "ok",
        "checked_at": now.isoformat(),
        "app_version": settings.app_version,
        "database": {
            "ok": False,
            "database_url": mask_database_url(settings.database_url),
        },
        "paths": {
            "raw_data_dir": str(settings.raw_data_dir),
            "export_data_dir": str(settings.export_data_dir),
            "log_dir": str(settings.log_dir),
        },
        "sizes": {
            "raw_bytes": directory_size_bytes(settings.raw_data_dir),
            "exports_bytes": directory_size_bytes(settings.export_data_dir),
            "logs_bytes": directory_size_bytes(settings.log_dir),
        },
        "last_24h": {
            "collector_runs": 0,
            "raw_responses": 0,
            "price_observations": 0,
            "problematic_quality_checks": 0,
        },
        "last_runs": {
            "success": None,
            "partial_success": None,
            "error": None,
        },
        "quality_checks": {
            "total_checks": 0,
            "pass_checks": 0,
            "skip_checks": 0,
            "problematic_checks": 0,
            "conclusion": "ok",
            "message": "quality checks ok",
        },
        "stale_products": [],
    }

    try:
        if session is not None:
            _fill_db_report(session, report, cutoff=cutoff, freshness_cutoff=freshness_cutoff)
        else:
            with session_scope() as scoped_session:
                _fill_db_report(scoped_session, report, cutoff=cutoff, freshness_cutoff=freshness_cutoff)
    except Exception as exc:
        report["database"] = {
            "ok": False,
            "database_url": mask_database_url(settings.database_url),
            "error": str(exc),
        }

    if not report["database"].get("ok") or report["stale_products"]:
        report["status"] = "degraded"
    return report


def _fill_db_report(
    session: Session,
    report: dict[str, Any],
    *,
    cutoff: datetime,
    freshness_cutoff: datetime,
) -> None:
    source = session.scalar(select(Source).where(Source.code == "current_price_source"))
    report["database"]["ok"] = True
    report["last_24h"]["collector_runs"] = session.scalar(
        select(func.count()).select_from(CollectorRun).where(CollectorRun.started_at >= cutoff)
    )
    report["last_24h"]["raw_responses"] = session.scalar(
        select(func.count()).select_from(RawResponse).where(RawResponse.fetched_at >= cutoff)
    )
    report["last_24h"]["price_observations"] = session.scalar(
        select(func.count()).select_from(PriceObservation).where(PriceObservation.created_at >= cutoff)
    )
    report["last_24h"]["problematic_quality_checks"] = session.scalar(
        select(func.count())
        .select_from(DataQualityCheck)
        .where(DataQualityCheck.checked_at >= cutoff, problematic_quality_filter())
    )
    quality_summary = build_quality_summary(session=session)
    report["quality_checks"] = {
        "total_checks": quality_summary["total_checks"],
        "pass_checks": quality_summary["pass_checks"],
        "skip_checks": quality_summary["skip_checks"],
        "problematic_checks": quality_summary["problematic_checks"],
        "conclusion": quality_summary["conclusion"],
        "message": "quality checks ok" if quality_summary["problematic_checks"] == 0 else "quality checks need review",
    }

    for status in ("success", "partial_success", "error"):
        run = session.scalar(
            select(CollectorRun).where(CollectorRun.status == status).order_by(CollectorRun.started_at.desc()).limit(1)
        )
        report["last_runs"][status] = _run_to_dict(run)

    if source is not None:
        report["stale_products"] = _stale_products(session, source.id, freshness_cutoff)
    else:
        report["stale_products"] = [
            {"product_code": item.product_code, "reason": "source_current_price_source_not_seeded"}
            for item in CURRENT_PRICE_INSTRUMENTS
        ]


def _stale_products(session: Session, source_id: int, cutoff: datetime) -> list[dict[str, Any]]:
    stale = []
    for instrument in CURRENT_PRICE_INSTRUMENTS:
        product = session.scalar(select(Product).where(Product.code == instrument.product_code))
        if product is None:
            stale.append({"product_code": instrument.product_code, "reason": "product_not_seeded"})
            continue
        latest = session.scalar(
            select(PriceObservation)
            .where(PriceObservation.source_id == source_id, PriceObservation.product_id == product.id)
            .order_by(PriceObservation.observed_at.desc())
            .limit(1)
        )
        if latest is None:
            stale.append({"product_code": instrument.product_code, "reason": "no_price_observation"})
        elif _to_utc(latest.observed_at) < cutoff:
            stale.append(
                {
                    "product_code": instrument.product_code,
                    "reason": "stale_price",
                    "latest_observed_at": _to_utc(latest.observed_at).isoformat(),
                }
            )
    return stale


def _run_to_dict(run: CollectorRun | None) -> dict[str, Any] | None:
    if run is None:
        return None
    return {
        "id": run.id,
        "collector_name": run.collector_name,
        "status": run.status,
        "run_type": run.run_type,
        "collection_slot": _to_utc(run.collection_slot).isoformat() if run.collection_slot else None,
        "started_at": _to_utc(run.started_at).isoformat(),
        "finished_at": _to_utc(run.finished_at).isoformat() if run.finished_at else None,
        "records_found": run.records_found,
        "records_written": run.records_written,
        "error_message": run.error_message,
    }


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)

