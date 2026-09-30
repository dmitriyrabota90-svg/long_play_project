"""Bounded, resumable recovery planning for Open-Meteo daily observations."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Literal, Sequence

from sqlalchemy import select, text
from sqlalchemy.engine import Connection, Engine

from app.collectors.weather.open_meteo_historical import OpenMeteoHistoricalWeatherCollector
from app.config.settings import get_settings
from app.db.models import WeatherDailyFeature, WeatherObservation, WeatherRegion
from app.db.session import get_engine, session_scope
from app.features.weather_daily import build_weather_daily_features


RecoveryMode = Literal["catchup", "regular"]
_LOCAL_LOCK = threading.Lock()
_POSTGRES_LOCK_KEY = 920_204_217


@dataclass(frozen=True)
class WeatherChunk:
    region_code: str
    from_date: date
    to_date: date
    reason: str


@dataclass(frozen=True)
class WeatherRecoveryPlan:
    mode: RecoveryMode
    lower_bound: date
    safe_end: date
    chunks: tuple[WeatherChunk, ...]
    feature_rebuild_chunks: tuple[WeatherChunk, ...]
    requests_planned: int
    request_budget: int
    backlog_days: int
    budget_exhausted: bool


@dataclass(frozen=True)
class WeatherRecoveryResult:
    status: str
    plan: WeatherRecoveryPlan
    requests_completed: int
    observations_written: int
    observations_skipped: int
    feature_rows_written: int
    errors: tuple[str, ...]
    conflicts_count: int = 0
    collector_errors_count: int = 0
    backlog_remaining_estimate: int | None = None


def safe_weather_end(*, now: datetime, source_delay_days: int) -> date:
    """Return the latest source-safe UTC observation date, never a guessed date."""
    if source_delay_days <= 0:
        raise ValueError("source_delay_days must be positive")
    return now.astimezone(timezone.utc).date() - timedelta(days=source_delay_days)


def plan_weather_recovery(
    *,
    region_codes: Sequence[str],
    observed_dates: dict[str, set[date]],
    feature_dates: dict[str, set[date]] | None,
    lower_bound: date,
    safe_end: date,
    mode: RecoveryMode,
    max_days_per_request: int,
    request_budget: int,
    regular_tail_days: int,
) -> WeatherRecoveryPlan:
    """Make deterministic <=N-day chunks; never request beyond ``safe_end``."""
    if max_days_per_request <= 0 or request_budget <= 0 or regular_tail_days <= 0:
        raise ValueError("weather planner limits must be positive")
    if lower_bound > safe_end:
        return WeatherRecoveryPlan(mode, lower_bound, safe_end, (), (), 0, request_budget, 0, False)
    feature_dates = feature_dates or {}
    candidate_chunks: list[WeatherChunk] = []
    rebuild_chunks: list[WeatherChunk] = []
    backlog_days = 0
    for region_code in sorted(region_codes):
        full_missing = _missing_dates(lower_bound, safe_end, observed_dates.get(region_code, set()))
        backlog_days += len(full_missing)
        requested_lower = lower_bound if mode == "catchup" else max(lower_bound, safe_end - timedelta(days=regular_tail_days - 1))
        missing = _missing_dates(requested_lower, safe_end, observed_dates.get(region_code, set()))
        candidate_chunks.extend(_chunks(region_code, missing, max_days_per_request, "missing_observations"))
        known_without_feature = sorted(observed_dates.get(region_code, set()) - feature_dates.get(region_code, set()))
        rebuild_chunks.extend(_chunks(region_code, known_without_feature, max_days_per_request, "missing_weather_daily_feature"))
    ordered = tuple(candidate_chunks[:request_budget])
    return WeatherRecoveryPlan(
        mode=mode,
        lower_bound=lower_bound,
        safe_end=safe_end,
        chunks=ordered,
        feature_rebuild_chunks=tuple(rebuild_chunks),
        requests_planned=len(ordered),
        request_budget=request_budget,
        backlog_days=backlog_days,
        budget_exhausted=len(candidate_chunks) > request_budget,
    )


class WeatherRecoveryService:
    """Fetch outside database transactions, then persist and build by chunk."""

    def __init__(
        self,
        *,
        collector: OpenMeteoHistoricalWeatherCollector | None = None,
        clock: Callable[[], datetime] | None = None,
        database_lock_factory: Callable[[], "_DatabaseWeatherLock"] | None = None,
    ) -> None:
        self.collector = collector or OpenMeteoHistoricalWeatherCollector()
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self.database_lock_factory = database_lock_factory or _DatabaseWeatherLock

    def run(self, *, mode: RecoveryMode = "regular", dry_run: bool = False, lower_bound: date | None = None) -> WeatherRecoveryResult:
        if not _LOCAL_LOCK.acquire(blocking=False):
            return self._overlap_result(mode=mode, lower_bound=lower_bound, reason="weather recovery already running")
        database_lock: _DatabaseWeatherLock | None = None
        acquired = False
        result: WeatherRecoveryResult | None = None
        release_error: Exception | None = None
        try:
            try:
                database_lock = self.database_lock_factory()
                acquired = database_lock.acquire()
            except Exception as exc:
                result = self._failure_result(mode=mode, lower_bound=lower_bound, message=f"weather lock acquire failed: {exc}")
            else:
                if not acquired:
                    result = self._overlap_result(
                        mode=mode, lower_bound=lower_bound, reason="weather recovery locked by another worker"
                    )
                else:
                    result = self._run_locked(
                        database_lock=database_lock, mode=mode, dry_run=dry_run, lower_bound=lower_bound
                    )
        finally:
            if acquired and database_lock is not None:
                try:
                    database_lock.release()
                except Exception as exc:
                    release_error = exc
            _LOCAL_LOCK.release()
        if release_error is not None:
            return self._failure_result(
                mode=mode,
                lower_bound=lower_bound,
                message=f"weather lock release failed: {release_error}",
                previous=result,
            )
        assert result is not None
        return result

    def _run_locked(
        self,
        *,
        database_lock: "_DatabaseWeatherLock",
        mode: RecoveryMode,
        dry_run: bool,
        lower_bound: date | None,
    ) -> WeatherRecoveryResult:
        plan = self.plan(mode=mode, lower_bound=lower_bound)
        if dry_run:
            return WeatherRecoveryResult("dry_run", plan, 0, 0, 0, 0, (), backlog_remaining_estimate=plan.backlog_days)
        started = time.monotonic()
        settings = get_settings()
        written = skipped = features = completed = conflicts = collector_errors = 0
        recovered_days = 0
        errors: list[str] = []
        rebuilt: set[tuple[str, date, date]] = set()
        for chunk in plan.chunks:
            if time.monotonic() - started >= settings.weather_max_runtime_seconds:
                errors.append("weather runtime budget exhausted")
                break
            region = self._region(chunk.region_code)
            try:
                # HTTP and retry/backoff complete before a write transaction begins.
                response = self.collector.fetch_region_response(region, from_date=chunk.from_date, to_date=chunk.to_date)
                database_lock.assert_owned()
                collected = self.collector.persist_prefetched_response(
                    region_code=chunk.region_code,
                    from_date=chunk.from_date,
                    to_date=chunk.to_date,
                    response=response,
                    run_type="scheduled" if mode == "regular" else "manual",
                )
                completed += 1
                written += collected.records_written
                skipped += collected.skipped_existing
                conflicts += collected.conflicts_count
                collector_errors += collected.errors_count
                has_collector_problem = (
                    collected.status != "success"
                    or collected.conflicts_count > 0
                    or collected.errors_count > 0
                )
                if has_collector_problem:
                    errors.append(
                        f"{chunk.region_code} {chunk.from_date}..{chunk.to_date}: "
                        f"collector status={collected.status} errors={collected.errors_count} "
                        f"conflicts={collected.conflicts_count}"
                    )
                else:
                    recovered_days += (chunk.to_date - chunk.from_date).days + 1
                database_lock.assert_owned()
                build = build_weather_daily_features(
                    region_code=chunk.region_code, from_date=chunk.from_date, to_date=chunk.to_date
                )
                features += build.rows_created + build.rows_updated
                rebuilt.add((chunk.region_code, chunk.from_date, chunk.to_date))
            except Exception as exc:  # chunk failure is resumable; other regions continue
                errors.append(f"{chunk.region_code} {chunk.from_date}..{chunk.to_date}: {exc}")
                if not database_lock.is_owned():
                    errors.append("weather lock ownership lost; stopping before further writes")
                    break
        for chunk in plan.feature_rebuild_chunks:
            marker = (chunk.region_code, chunk.from_date, chunk.to_date)
            if marker in rebuilt:
                continue
            try:
                database_lock.assert_owned()
                build = build_weather_daily_features(
                    region_code=chunk.region_code, from_date=chunk.from_date, to_date=chunk.to_date
                )
                features += build.rows_created + build.rows_updated
            except Exception as exc:
                errors.append(f"feature rebuild {chunk.region_code}: {exc}")
                if not database_lock.is_owned():
                    errors.append("weather lock ownership lost; stopping before further writes")
                    break
        backlog_after = max(0, plan.backlog_days - recovered_days)
        status = "success" if not errors else ("partial_success" if completed or features else "error")
        if status == "success" and plan.budget_exhausted:
            status = "success_with_backlog"
        return WeatherRecoveryResult(
            status,
            plan,
            completed,
            written,
            skipped,
            features,
            tuple(errors),
            conflicts_count=conflicts,
            collector_errors_count=collector_errors,
            backlog_remaining_estimate=backlog_after,
        )

    def _overlap_result(self, *, mode: RecoveryMode, lower_bound: date | None, reason: str) -> WeatherRecoveryResult:
        return WeatherRecoveryResult(
            "skipped_overlap", self._safe_plan(mode=mode, lower_bound=lower_bound), 0, 0, 0, 0, (reason,)
        )

    def _failure_result(
        self,
        *,
        mode: RecoveryMode,
        lower_bound: date | None,
        message: str,
        previous: WeatherRecoveryResult | None = None,
    ) -> WeatherRecoveryResult:
        plan = previous.plan if previous else self._safe_plan(mode=mode, lower_bound=lower_bound)
        errors = (*((previous.errors) if previous else ()), message)
        return WeatherRecoveryResult(
            "error",
            plan,
            previous.requests_completed if previous else 0,
            previous.observations_written if previous else 0,
            previous.observations_skipped if previous else 0,
            previous.feature_rows_written if previous else 0,
            errors,
            conflicts_count=previous.conflicts_count if previous else 0,
            collector_errors_count=previous.collector_errors_count if previous else 0,
            backlog_remaining_estimate=(previous.backlog_remaining_estimate if previous else plan.backlog_days),
        )

    def _safe_plan(self, *, mode: RecoveryMode, lower_bound: date | None) -> WeatherRecoveryPlan:
        try:
            return self.plan(mode=mode, lower_bound=lower_bound)
        except Exception:
            today = self.clock().astimezone(timezone.utc).date()
            lower = lower_bound or today
            return WeatherRecoveryPlan(mode, lower, lower, (), (), 0, 0, 0, False)

    def plan(self, *, mode: RecoveryMode, lower_bound: date | None = None) -> WeatherRecoveryPlan:
        settings = get_settings()
        lower = lower_bound or date.fromisoformat(settings.weather_recovery_start_date)
        safe_end = safe_weather_end(now=self.clock(), source_delay_days=settings.weather_source_delay_days)
        with session_scope() as session:
            regions = session.scalars(select(WeatherRegion).where(WeatherRegion.is_active.is_(True))).all()
            region_ids = {region.id: region.region_code for region in regions}
            observed: dict[str, set[date]] = {region.region_code: set() for region in regions}
            featured: dict[str, set[date]] = {region.region_code: set() for region in regions}
            for region_id, observed_at in session.execute(select(WeatherObservation.region_id, WeatherObservation.observation_date)):
                if region_id in region_ids:
                    observed[region_ids[region_id]].add(observed_at)
            for region_id, feature_date in session.execute(select(WeatherDailyFeature.region_id, WeatherDailyFeature.feature_date)):
                if region_id in region_ids:
                    featured[region_ids[region_id]].add(feature_date)
        return plan_weather_recovery(
            region_codes=tuple(region.region_code for region in regions), observed_dates=observed, feature_dates=featured,
            lower_bound=lower, safe_end=safe_end, mode=mode, max_days_per_request=settings.weather_max_days_per_request,
            request_budget=settings.weather_max_requests_per_run, regular_tail_days=settings.weather_regular_tail_days,
        )

    @staticmethod
    def _region(region_code: str) -> WeatherRegion:
        with session_scope() as session:
            region = session.scalar(select(WeatherRegion).where(WeatherRegion.region_code == region_code))
            if region is None:
                raise ValueError(f"unknown weather region: {region_code}")
            session.expunge(region)
            return region


def _missing_dates(start: date, end: date, present: set[date]) -> list[date]:
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1) if start + timedelta(days=offset) not in present]


def _chunks(region_code: str, dates: Sequence[date], max_days: int, reason: str) -> list[WeatherChunk]:
    if not dates:
        return []
    result: list[WeatherChunk] = []
    run_start = previous = dates[0]
    for current in list(dates[1:]) + [None]:
        if current is not None and current == previous + timedelta(days=1) and (current - run_start).days + 1 <= max_days:
            previous = current
            continue
        result.append(WeatherChunk(region_code, run_start, previous, reason))
        if current is not None:
            run_start = previous = current
    return result


class _DatabaseWeatherLock:
    """A PostgreSQL advisory lock shared by manual CLI and scheduler containers.

    SQLite has no compatible inter-process advisory lock, so local development
    intentionally retains only the process lock above. Production uses PostgreSQL.
    The held connection executes no transaction while HTTP is in flight.
    """

    def __init__(self, *, engine: Engine | None = None) -> None:
        self.engine = engine
        self.connection: Connection | None = None
        self.postgres = False
        self.backend_pid: int | None = None

    def acquire(self) -> bool:
        engine = self.engine or get_engine()
        self.postgres = engine.dialect.name == "postgresql"
        if not self.postgres:
            return True
        connection = engine.connect()
        try:
            acquired = bool(connection.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": _POSTGRES_LOCK_KEY}))
            # A session-level advisory lock survives commit, while the checked-out
            # Connection remains pinned to its physical PostgreSQL backend.
            connection.commit()
            if not acquired:
                connection.close()
                return False
            self.connection = connection
            self.backend_pid = int(connection.scalar(text("SELECT pg_backend_pid()")))
            connection.commit()
            return True
        except Exception:
            connection.rollback()
            connection.close()
            raise

    def is_owned(self) -> bool:
        if not self.postgres:
            return True
        if self.connection is None or self.connection.closed or self.backend_pid is None:
            return False
        try:
            current_pid = int(self.connection.scalar(text("SELECT pg_backend_pid()")))
            self.connection.commit()
            return current_pid == self.backend_pid
        except Exception:
            return False

    def assert_owned(self) -> None:
        if not self.is_owned():
            raise RuntimeError("weather advisory lock ownership is unavailable")

    def release(self) -> None:
        if not self.postgres:
            return
        connection = self.connection
        self.connection = None
        self.backend_pid = None
        if connection is None:
            raise RuntimeError("weather advisory lock connection is unavailable during release")
        try:
            if connection.closed:
                raise RuntimeError("weather advisory lock connection closed before release")
            unlocked = bool(connection.scalar(text("SELECT pg_advisory_unlock(:key)"), {"key": _POSTGRES_LOCK_KEY}))
            connection.commit()
            if not unlocked:
                raise RuntimeError("weather advisory lock was not owned by this connection")
        finally:
            connection.close()
