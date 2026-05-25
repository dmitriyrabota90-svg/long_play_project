from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.collectors.prices.current_price_config import CURRENT_PRICE_INSTRUMENTS
from app.config.settings import get_settings
from app.db.models import CollectorRun, DataQualityCheck, PriceObservation, Product, Source
from app.db.session import session_scope
from app.monitoring.quality_summary import problematic_quality_filter


def build_current_price_health_report(*, freshness_hours: int = 24, session: Session | None = None) -> dict[str, Any]:
    settings = get_settings()
    raw_dir = Path(settings.raw_data_dir)
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=freshness_hours)
    quality_cutoff = now - timedelta(hours=24)

    report: dict[str, Any] = {
        "status": "ok",
        "checked_at": now.isoformat(),
        "freshness_hours": freshness_hours,
        "database": {"ok": False},
        "raw_storage": {
            "path": str(raw_dir),
            "exists": raw_dir.exists(),
            "is_dir": raw_dir.is_dir(),
        },
        "current_price_source": {
            "last_successful_run": None,
            "last_failed_or_partial_run": None,
            "price_observations_last_24h": 0,
            "problematic_quality_checks_last_24h": 0,
            "stale_products": [],
        },
    }

    try:
        if session is not None:
            _fill_report(session, report, cutoff=cutoff, quality_cutoff=quality_cutoff)
        else:
            with session_scope() as scoped_session:
                _fill_report(scoped_session, report, cutoff=cutoff, quality_cutoff=quality_cutoff)
    except Exception as exc:
        report["database"] = {"ok": False, "error": str(exc)}

    if not report["database"].get("ok") or not report["raw_storage"]["exists"] or report["current_price_source"]["stale_products"]:
        report["status"] = "degraded"
    return report


def _fill_report(
    session: Session,
    report: dict[str, Any],
    *,
    cutoff: datetime,
    quality_cutoff: datetime,
) -> None:
    source = session.scalar(select(Source).where(Source.code == "current_price_source"))
    report["database"] = {"ok": True}
    if source is None:
        report["status"] = "degraded"
        report["current_price_source"]["error"] = "source current_price_source not found"
        return

    last_success = session.scalar(
        select(CollectorRun)
        .where(
            CollectorRun.source_id == source.id,
            CollectorRun.collector_name == "current_price_source_collector",
            CollectorRun.status == "success",
        )
        .order_by(CollectorRun.started_at.desc())
        .limit(1)
    )
    last_failed_or_partial = session.scalar(
        select(CollectorRun)
        .where(
            CollectorRun.source_id == source.id,
            CollectorRun.collector_name == "current_price_source_collector",
            CollectorRun.status.in_(("error", "partial_success")),
        )
        .order_by(CollectorRun.started_at.desc())
        .limit(1)
    )
    report["current_price_source"]["last_successful_run"] = _run_to_dict(last_success)
    report["current_price_source"]["last_failed_or_partial_run"] = _run_to_dict(last_failed_or_partial)
    report["current_price_source"]["price_observations_last_24h"] = session.scalar(
        select(func.count())
        .select_from(PriceObservation)
        .where(
            PriceObservation.source_id == source.id,
            PriceObservation.created_at >= quality_cutoff,
        )
    )
    report["current_price_source"]["problematic_quality_checks_last_24h"] = session.scalar(
        select(func.count())
        .select_from(DataQualityCheck)
        .where(
            DataQualityCheck.source_id == source.id,
            DataQualityCheck.checked_at >= quality_cutoff,
            problematic_quality_filter(),
        )
    )
    report["current_price_source"]["stale_products"] = _stale_products(session, source.id, cutoff)


def _stale_products(session: Session, source_id: int, cutoff: datetime) -> list[dict[str, Any]]:
    stale: list[dict[str, Any]] = []
    for instrument in CURRENT_PRICE_INSTRUMENTS:
        product = session.scalar(select(Product).where(Product.code == instrument.product_code))
        if product is None:
            stale.append({"product_code": instrument.product_code, "reason": "product_not_found"})
            continue
        latest = session.scalar(
            select(PriceObservation)
            .where(
                PriceObservation.source_id == source_id,
                PriceObservation.product_id == product.id,
            )
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
