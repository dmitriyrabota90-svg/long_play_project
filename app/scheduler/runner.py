from __future__ import annotations

import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from app.config.settings import get_settings
from app.scheduler.jobs import (
    cbr_fx_job,
    current_price_source_job,
    current_price_source_test_interval_job,
    daily_quality_check_job,
    health_check_job,
)

logger = logging.getLogger(__name__)


def build_scheduler() -> BlockingScheduler:
    settings = get_settings()
    scheduler = BlockingScheduler(timezone=settings.schedule_timezone)
    scheduler.add_job(health_check_job, "interval", hours=1, id="health_check", replace_existing=True)
    scheduler.add_job(daily_quality_check_job, "cron", hour=3, minute=0, id="daily_quality_check", replace_existing=True)
    logger.info("registered scheduler job id=health_check trigger=interval hours=1")
    logger.info("registered scheduler job id=daily_quality_check trigger=cron time=03:00")
    if settings.current_price_scheduler_enabled:
        for schedule_time in _parse_schedule_times(settings.current_price_schedule_times):
            hour, minute = _parse_schedule_time(schedule_time)
            job_id = f"current_price_source_{hour:02d}{minute:02d}"
            scheduler.add_job(
                current_price_source_job,
                "cron",
                hour=hour,
                minute=minute,
                id=job_id,
                args=[schedule_time],
                replace_existing=True,
            )
            logger.info(
                "registered scheduler job id=%s trigger=cron time=%s timezone=%s",
                job_id,
                schedule_time,
                settings.schedule_timezone,
            )
    else:
        logger.info("current_price_source scheduler disabled by CURRENT_PRICE_SCHEDULER_ENABLED")

    if settings.cbr_fx_scheduler_enabled:
        hour, minute = _parse_schedule_time(settings.cbr_fx_schedule_time)
        scheduler.add_job(
            cbr_fx_job,
            "cron",
            hour=hour,
            minute=minute,
            id="cbr_fx_daily",
            args=[settings.cbr_fx_schedule_time],
            replace_existing=True,
        )
        logger.info(
            "registered scheduler job id=cbr_fx_daily trigger=cron time=%s timezone=%s",
            settings.cbr_fx_schedule_time,
            settings.schedule_timezone,
        )
    else:
        logger.info("cbr_fx scheduler disabled by CBR_FX_SCHEDULER_ENABLED")
    if settings.current_price_test_interval_seconds:
        if settings.current_price_test_interval_seconds <= 0:
            raise ValueError("CURRENT_PRICE_TEST_INTERVAL_SECONDS must be a positive integer")
        scheduler.add_job(
            current_price_source_test_interval_job,
            "interval",
            seconds=settings.current_price_test_interval_seconds,
            id="current_price_source_test_interval",
            replace_existing=True,
        )
        logger.warning(
            "registered TEST scheduler job id=current_price_source_test_interval interval_seconds=%s",
            settings.current_price_test_interval_seconds,
        )
    return scheduler


def start_scheduler() -> None:
    settings = get_settings()
    scheduler = build_scheduler()
    logger.info("starting scheduler timezone=%s app_version=%s", settings.schedule_timezone, settings.app_version)
    scheduler.start()


def _parse_schedule_times(value: str) -> list[str]:
    times = [item.strip() for item in value.split(",") if item.strip()]
    if not times:
        raise ValueError("CURRENT_PRICE_SCHEDULE_TIMES must contain at least one HH:MM value")
    for item in times:
        _parse_schedule_time(item)
    return times


def _parse_schedule_time(value: str) -> tuple[int, int]:
    parts = value.split(":")
    if len(parts) != 2:
        raise ValueError(f"invalid schedule time {value!r}; expected HH:MM")
    hour = int(parts[0])
    minute = int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"invalid schedule time {value!r}; expected HH:MM")
    return hour, minute
