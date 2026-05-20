from __future__ import annotations

from app.config.settings import get_settings
from app.scheduler.runner import build_scheduler


def test_scheduler_does_not_register_current_price_job_when_disabled(monkeypatch) -> None:
    monkeypatch.setenv("CURRENT_PRICE_SCHEDULER_ENABLED", "false")
    monkeypatch.delenv("CURRENT_PRICE_TEST_INTERVAL_SECONDS", raising=False)
    get_settings.cache_clear()

    scheduler = build_scheduler()
    job_ids = {job.id for job in scheduler.get_jobs()}

    assert "health_check" in job_ids
    assert "daily_quality_check" in job_ids
    assert not any(job_id.startswith("current_price_source_") for job_id in job_ids)
    assert "current_price_source_test_interval" not in job_ids
    get_settings.cache_clear()


def test_scheduler_registers_current_price_jobs_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("CURRENT_PRICE_SCHEDULER_ENABLED", "true")
    monkeypatch.setenv("CURRENT_PRICE_SCHEDULE_TIMES", "09:00,18:00")
    get_settings.cache_clear()

    scheduler = build_scheduler()
    job_ids = {job.id for job in scheduler.get_jobs()}

    assert "current_price_source_0900" in job_ids
    assert "current_price_source_1800" in job_ids
    get_settings.cache_clear()


def test_scheduler_registers_test_interval_job_when_env_is_set(monkeypatch) -> None:
    monkeypatch.setenv("CURRENT_PRICE_SCHEDULER_ENABLED", "false")
    monkeypatch.setenv("CURRENT_PRICE_TEST_INTERVAL_SECONDS", "60")
    get_settings.cache_clear()

    scheduler = build_scheduler()
    job_ids = {job.id for job in scheduler.get_jobs()}

    assert "current_price_source_test_interval" in job_ids
    assert not any(job_id.startswith("current_price_source_09") for job_id in job_ids)
    get_settings.cache_clear()
