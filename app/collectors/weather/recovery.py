"""Bounded, resumable recovery planning for Open-Meteo daily observations."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Literal, Sequence

from sqlalchemy import select, text

from app.collectors.weather.open_meteo_historical import OpenMeteoHistoricalWeatherCollector
from app.config.settings import get_settings
from app.db.models import WeatherDailyFeature, WeatherObservation, WeatherRegion
from app.db.session import get_session_factory, session_scope
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

    def __init__(self, *, collector: OpenMeteoHistoricalWeatherCollector | None = None, clock: Callable[[], datetime] | None = None) -> None:
        self.collector = collector or OpenMeteoHistoricalWeatherCollector()
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def run(self, *, mode: RecoveryMode = "regular", dry_run: bool = False, lower_bound: date | None = None) -> WeatherRecoveryResult:
        if not _LOCAL_LOCK.acquire(blocking=False):
            plan = self.plan(mode=mode, lower_bound=lower_bound)
            return WeatherRecoveryResult("skipped_overlap", plan, 0, 0, 0, 0, ("weather recovery already running",))
        database_lock = _DatabaseWeatherLock()
        if not database_lock.acquire():
            _LOCAL_LOCK.release()
            plan = self.plan(mode=mode, lower_bound=lower_bound)
            return WeatherRecoveryResult("skipped_overlap", plan, 0, 0, 0, 0, ("weather recovery locked by another worker",))
        try:
            plan = self.plan(mode=mode, lower_bound=lower_bound)
            if dry_run:
                return WeatherRecoveryResult("dry_run", plan, 0, 0, 0, 0, ())
            started = time.monotonic()
            settings = get_settings()
            written = skipped = features = completed = 0
            errors: list[str] = []
            rebuilt: set[tuple[str, date, date]] = set()
            for chunk in plan.chunks:
                if time.monotonic() - started >= settings.weather_max_runtime_seconds:
                    errors.append("weather runtime budget exhausted")
                    break
                region = self._region(chunk.region_code)
                try:
                    # HTTP (and retry/backoff) occurs before a database transaction is opened.
                    response = self.collector.fetch_region_response(region, from_date=chunk.from_date, to_date=chunk.to_date)
                    collected = self.collector.persist_prefetched_response(
                        region_code=chunk.region_code, from_date=chunk.from_date, to_date=chunk.to_date,
                        response=response, run_type="scheduled" if mode == "regular" else "manual",
                    )
                    completed += 1
                    written += collected.records_written
                    skipped += collected.skipped_existing
                    if collected.status == "error":
                        errors.append(collected.error_message or f"collector error for {chunk.region_code}")
                        continue
                    build = build_weather_daily_features(region_code=chunk.region_code, from_date=chunk.from_date, to_date=chunk.to_date)
                    features += build.rows_created + build.rows_updated
                    rebuilt.add((chunk.region_code, chunk.from_date, chunk.to_date))
                except Exception as exc:  # chunk failure is resumable; other regions continue
                    errors.append(f"{chunk.region_code} {chunk.from_date}..{chunk.to_date}: {exc}")
            for chunk in plan.feature_rebuild_chunks:
                marker = (chunk.region_code, chunk.from_date, chunk.to_date)
                if marker in rebuilt:
                    continue
                try:
                    build = build_weather_daily_features(region_code=chunk.region_code, from_date=chunk.from_date, to_date=chunk.to_date)
                    features += build.rows_created + build.rows_updated
                except Exception as exc:
                    errors.append(f"feature rebuild {chunk.region_code}: {exc}")
            status = "success" if not errors else ("partial_success" if completed or features else "error")
            return WeatherRecoveryResult(status, plan, completed, written, skipped, features, tuple(errors))
        finally:
            database_lock.release()
            _LOCAL_LOCK.release()

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
    The held session executes no transaction while HTTP is in flight.
    """

    def __init__(self) -> None:
        self.session = None
        self.postgres = False

    def acquire(self) -> bool:
        session = get_session_factory()()
        self.session = session
        self.postgres = session.bind is not None and session.bind.dialect.name == "postgresql"
        if not self.postgres:
            session.close()
            self.session = None
            return True
        acquired = bool(session.scalar(text("SELECT pg_try_advisory_lock(:key)"), {"key": _POSTGRES_LOCK_KEY}))
        # Session-level advisory locks survive commit; release the implicit read
        # transaction before HTTP work begins.
        session.commit()
        if not acquired:
            session.close()
            self.session = None
        return acquired

    def release(self) -> None:
        if self.session is None:
            return
        try:
            if self.postgres:
                self.session.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": _POSTGRES_LOCK_KEY})
                self.session.commit()
        finally:
            self.session.close()
            self.session = None
