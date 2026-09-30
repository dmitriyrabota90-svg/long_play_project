"""Opt-in local PostgreSQL proof for session-level advisory lock ownership."""

from __future__ import annotations

import os
import uuid

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.collectors.weather.recovery import _DatabaseWeatherLock


def _run_postgres_lock_integration() -> None:
    database_url = os.environ.get("POSTGRES_LOCK_TEST_URL") or os.environ.get("DATABASE_URL")
    if not database_url:
        raise RuntimeError("POSTGRES_LOCK_TEST_URL or DATABASE_URL is required")
    base_url = make_url(database_url)
    database_name = f"weather_lock_test_{uuid.uuid4().hex}"
    admin_engine = create_engine(base_url.set(database="postgres"), isolation_level="AUTOCOMMIT", future=True)
    test_engine = None
    first = second = None
    try:
        with admin_engine.connect() as connection:
            connection.execute(text(f'CREATE DATABASE "{database_name}"'))
        test_engine = create_engine(base_url.set(database=database_name), pool_size=4, max_overflow=0, future=True)
        first = _DatabaseWeatherLock(engine=test_engine)
        second = _DatabaseWeatherLock(engine=test_engine)

        assert first.acquire() is True
        first_pid = first.backend_pid
        assert first_pid is not None
        # A pooled non-owner connection must neither replace the owner nor acquire its lock.
        with test_engine.connect() as unrelated:
            unrelated_pid = int(unrelated.scalar(text("SELECT pg_backend_pid()")))
        assert unrelated_pid != first_pid
        assert first.is_owned() is True
        assert first.backend_pid == first_pid
        assert second.acquire() is False

        first.release()
        assert second.acquire() is True
        assert second.is_owned() is True
    finally:
        if first is not None:
            try:
                first.release()
            except RuntimeError:
                pass
        if second is not None:
            try:
                second.release()
            except RuntimeError:
                pass
        if test_engine is not None:
            test_engine.dispose()
        with admin_engine.connect() as connection:
            connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
        admin_engine.dispose()


def test_postgres_advisory_lock_uses_one_physical_connection() -> None:
    if os.environ.get("RUN_POSTGRES_LOCK_TEST") != "1":
        import pytest

        pytest.skip("set RUN_POSTGRES_LOCK_TEST=1 against isolated local PostgreSQL")
    _run_postgres_lock_integration()


if __name__ == "__main__":
    _run_postgres_lock_integration()
