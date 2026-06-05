from __future__ import annotations

import logging
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app.config.settings import get_settings
from app.monitoring.health import run_health_check
from app.quality.checks import run_daily_quality_check

logger = logging.getLogger(__name__)


def health_check_job() -> None:
    logger.info("scheduler job started job=health_check")
    result = run_health_check()
    logger.info("scheduler job finished job=health_check status=%s", result["status"])


def daily_quality_check_job() -> None:
    logger.info("scheduler job started job=daily_quality_check")
    result = run_daily_quality_check()
    logger.info("scheduler job finished job=daily_quality_check status=%s", result["status"])


def current_price_source_job(schedule_time: str | None = None) -> None:
    from app.collectors.prices.current_price_source import CurrentPriceSourceCollector

    try:
        collection_slot = _collection_slot_for_schedule_time(schedule_time) if schedule_time else None
        logger.info(
            "scheduler job started job=current_price_source schedule_time=%s collection_slot=%s",
            schedule_time,
            collection_slot.isoformat() if collection_slot else None,
        )
        result = CurrentPriceSourceCollector().run(run_type="scheduled", collection_slot=collection_slot)
        logger.info(
            "scheduler job finished job=current_price_source run_id=%s status=%s records_written=%s errors_count=%s",
            result.run_id,
            result.status,
            result.records_written,
            result.errors_count,
        )
    except Exception:
        logger.exception("scheduler job failed job=current_price_source schedule_time=%s", schedule_time)


def cbr_fx_job(schedule_time: str | None = None) -> None:
    from app.collectors.fx.cbr_fx import CbrFxCollector

    try:
        collection_slot = _collection_slot_for_schedule_time(schedule_time) if schedule_time else None
        requested_date = None
        if collection_slot is not None:
            requested_date = collection_slot.astimezone(ZoneInfo(get_settings().schedule_timezone)).date()
        logger.info(
            "scheduler job started job=cbr_fx schedule_time=%s collection_slot=%s requested_date=%s",
            schedule_time,
            collection_slot.isoformat() if collection_slot else None,
            requested_date.isoformat() if requested_date else None,
        )
        result = CbrFxCollector().run(
            run_type="scheduled",
            collection_slot=collection_slot,
            requested_date=requested_date,
        )
        logger.info(
            "scheduler job finished job=cbr_fx run_id=%s status=%s records_written=%s errors_count=%s",
            result.run_id,
            result.status,
            result.records_written,
            result.errors_count,
        )
    except Exception:
        logger.exception("scheduler job failed job=cbr_fx schedule_time=%s", schedule_time)


def daily_feature_builder_job() -> None:
    from app.features.daily import build_daily_features

    try:
        logger.info("scheduler job started job=daily_feature_builder")
        result = build_daily_features()
        logger.info(
            "scheduler job finished job=daily_feature_builder products_processed=%s dates_processed=%s "
            "rows_created=%s rows_updated=%s rows_skipped=%s missing_fx_dates=%s warnings_count=%s",
            result.products_processed,
            result.dates_processed,
            result.rows_created,
            result.rows_updated,
            result.rows_skipped,
            result.missing_fx_dates,
            result.warnings_count,
        )
    except Exception:
        logger.exception("scheduler job failed job=daily_feature_builder")


def current_price_source_test_interval_job() -> None:
    from app.collectors.prices.current_price_source import CurrentPriceSourceCollector

    collection_slot = datetime.now(timezone.utc).replace(microsecond=0)
    try:
        logger.info(
            "scheduler test interval job started job=current_price_source collection_slot=%s",
            collection_slot.isoformat(),
        )
        result = CurrentPriceSourceCollector().run(run_type="scheduled", collection_slot=collection_slot)
        logger.info(
            "scheduler test interval job finished job=current_price_source run_id=%s status=%s records_written=%s errors_count=%s",
            result.run_id,
            result.status,
            result.records_written,
            result.errors_count,
        )
    except Exception:
        logger.exception("scheduler test interval job failed job=current_price_source")


def _collection_slot_for_schedule_time(schedule_time: str) -> datetime:
    settings = get_settings()
    hour, minute = (int(part) for part in schedule_time.split(":", maxsplit=1))
    local_tz = ZoneInfo(settings.schedule_timezone)
    now_local = datetime.now(local_tz)
    slot_local = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return slot_local.astimezone(timezone.utc)
