from datetime import date, datetime, timezone
from types import SimpleNamespace

from app.collectors.weather.recovery import (
    WeatherChunk,
    WeatherRecoveryPlan,
    WeatherRecoveryService,
    plan_weather_recovery,
    safe_weather_end,
)
from app.scheduler import jobs


def test_planner_splits_internal_gaps_and_honours_request_limit() -> None:
    plan = plan_weather_recovery(
        region_codes=("a",),
        observed_dates={"a": {date(2026, 6, 2), date(2026, 6, 5)}},
        feature_dates={"a": set()},
        lower_bound=date(2026, 6, 1),
        safe_end=date(2026, 6, 8),
        mode="catchup",
        max_days_per_request=2,
        request_budget=2,
        regular_tail_days=3,
    )
    assert [(chunk.from_date, chunk.to_date) for chunk in plan.chunks] == [
        (date(2026, 6, 1), date(2026, 6, 1)),
        (date(2026, 6, 3), date(2026, 6, 4)),
    ]
    assert plan.backlog_days == 6
    assert plan.budget_exhausted is True


def test_regular_plan_prioritises_recent_tail_and_never_exceeds_safe_end() -> None:
    plan = plan_weather_recovery(
        region_codes=("a", "b"),
        observed_dates={"a": set(), "b": {date(2026, 6, 9)}},
        feature_dates=None,
        lower_bound=date(2026, 6, 1),
        safe_end=date(2026, 6, 10),
        mode="regular",
        max_days_per_request=45,
        request_budget=14,
        regular_tail_days=3,
    )
    assert [(chunk.region_code, chunk.from_date, chunk.to_date) for chunk in plan.chunks] == [
        ("a", date(2026, 6, 8), date(2026, 6, 10)),
        ("b", date(2026, 6, 8), date(2026, 6, 8)),
        ("b", date(2026, 6, 10), date(2026, 6, 10)),
    ]
    assert all(chunk.to_date <= plan.safe_end for chunk in plan.chunks)
    assert plan.backlog_days == 19


def test_safe_end_uses_utc_delay_not_local_wall_clock() -> None:
    assert safe_weather_end(
        now=datetime(2026, 10, 1, 1, tzinfo=timezone.utc), source_delay_days=5
    ) == date(2026, 9, 26)


def test_feature_rebuild_is_planned_without_refetching_observation() -> None:
    plan = plan_weather_recovery(
        region_codes=("a",),
        observed_dates={"a": {date(2026, 6, 1)}},
        feature_dates={"a": set()},
        lower_bound=date(2026, 6, 1),
        safe_end=date(2026, 6, 1),
        mode="catchup",
        max_days_per_request=45,
        request_budget=1,
        regular_tail_days=45,
    )
    assert plan.chunks == ()
    assert plan.feature_rebuild_chunks[0].reason == "missing_weather_daily_feature"


def test_planner_never_makes_a_chunk_longer_than_source_limit() -> None:
    plan = plan_weather_recovery(
        region_codes=("a",),
        observed_dates={"a": set()},
        feature_dates=None,
        lower_bound=date(2026, 6, 1),
        safe_end=date(2026, 7, 31),
        mode="catchup",
        max_days_per_request=45,
        request_budget=10,
        regular_tail_days=45,
    )
    assert [(chunk.from_date, chunk.to_date) for chunk in plan.chunks] == [
        (date(2026, 6, 1), date(2026, 7, 15)),
        (date(2026, 7, 16), date(2026, 7, 31)),
    ]


def test_scheduler_callback_runs_regular_weather_recovery(monkeypatch) -> None:
    calls: list[str] = []

    class FakeService:
        def run(self, *, mode: str):
            calls.append(mode)
            return SimpleNamespace(
                status="success",
                requests_completed=1,
                observations_written=2,
                feature_rows_written=2,
                plan=SimpleNamespace(backlog_days=0),
                errors=(),
                backlog_remaining_estimate=0,
                conflicts_count=0,
            )

    import app.collectors.weather.recovery as recovery

    monkeypatch.setattr(recovery, "WeatherRecoveryService", FakeService)
    jobs.weather_recovery_job()

    assert calls == ["regular"]


def test_scheduler_callback_accepts_partial_result_and_allows_next_run(monkeypatch) -> None:
    statuses = iter(("partial_success", "success"))

    class FakeService:
        def run(self, *, mode: str):
            return SimpleNamespace(
                status=next(statuses),
                requests_completed=1,
                observations_written=0,
                feature_rows_written=0,
                plan=SimpleNamespace(backlog_days=1),
                errors=("visible partial failure",),
                backlog_remaining_estimate=1,
                conflicts_count=0,
            )

    import app.collectors.weather.recovery as recovery

    monkeypatch.setattr(recovery, "WeatherRecoveryService", FakeService)
    jobs.weather_recovery_job()
    jobs.weather_recovery_job()


class _FakeLock:
    def __init__(self, *, acquired: bool = True, release_error: Exception | None = None) -> None:
        self.acquired = acquired
        self.release_error = release_error
        self.released = False

    def acquire(self) -> bool:
        return self.acquired

    def assert_owned(self) -> None:
        return None

    def is_owned(self) -> bool:
        return True

    def release(self) -> None:
        self.released = True
        if self.release_error:
            raise self.release_error


def _single_chunk_plan(*, budget_exhausted: bool = False) -> WeatherRecoveryPlan:
    return WeatherRecoveryPlan(
        mode="regular",
        lower_bound=date(2026, 6, 1),
        safe_end=date(2026, 6, 1),
        chunks=(WeatherChunk("a", date(2026, 6, 1), date(2026, 6, 1), "missing_observations"),),
        feature_rebuild_chunks=(),
        requests_planned=1,
        request_budget=1,
        backlog_days=1,
        budget_exhausted=budget_exhausted,
    )


def test_partial_collector_result_and_hash_conflict_are_visible(monkeypatch) -> None:
    plan = _single_chunk_plan()
    collector = SimpleNamespace(
        fetch_region_response=lambda *args, **kwargs: object(),
        persist_prefetched_response=lambda **kwargs: SimpleNamespace(
            status="partial_success", records_written=1, skipped_existing=0, conflicts_count=1, errors_count=1
        ),
    )
    service = WeatherRecoveryService(collector=collector, database_lock_factory=_FakeLock)
    monkeypatch.setattr(service, "plan", lambda **kwargs: plan)
    monkeypatch.setattr(service, "_region", lambda region_code: SimpleNamespace(region_code=region_code))
    import app.collectors.weather.recovery as recovery

    monkeypatch.setattr(recovery, "build_weather_daily_features", lambda **kwargs: SimpleNamespace(rows_created=1, rows_updated=0))

    result = service.run()

    assert result.status == "partial_success"
    assert result.conflicts_count == 1
    assert result.collector_errors_count == 1
    assert "conflicts=1" in result.errors[0]


def test_expected_existing_skip_remains_success(monkeypatch) -> None:
    plan = _single_chunk_plan()
    collector = SimpleNamespace(
        fetch_region_response=lambda *args, **kwargs: object(),
        persist_prefetched_response=lambda **kwargs: SimpleNamespace(
            status="success", records_written=0, skipped_existing=1, conflicts_count=0, errors_count=0
        ),
    )
    service = WeatherRecoveryService(collector=collector, database_lock_factory=_FakeLock)
    monkeypatch.setattr(service, "plan", lambda **kwargs: plan)
    monkeypatch.setattr(service, "_region", lambda region_code: SimpleNamespace(region_code=region_code))
    import app.collectors.weather.recovery as recovery

    monkeypatch.setattr(recovery, "build_weather_daily_features", lambda **kwargs: SimpleNamespace(rows_created=0, rows_updated=0))

    result = service.run()

    assert result.status == "success"
    assert result.observations_skipped == 1
    assert result.errors == ()


def test_budget_backlog_is_not_reported_as_full_recovery(monkeypatch) -> None:
    plan = _single_chunk_plan(budget_exhausted=True)
    service = WeatherRecoveryService(database_lock_factory=_FakeLock)
    monkeypatch.setattr(service, "plan", lambda **kwargs: plan)
    monkeypatch.setattr(service, "_region", lambda region_code: SimpleNamespace(region_code=region_code))
    service.collector = SimpleNamespace(
        fetch_region_response=lambda *args, **kwargs: object(),
        persist_prefetched_response=lambda **kwargs: SimpleNamespace(
            status="success", records_written=1, skipped_existing=0, conflicts_count=0, errors_count=0
        ),
    )
    import app.collectors.weather.recovery as recovery

    monkeypatch.setattr(recovery, "build_weather_daily_features", lambda **kwargs: SimpleNamespace(rows_created=1, rows_updated=0))

    result = service.run()

    assert result.status == "success_with_backlog"
    assert result.backlog_remaining_estimate == 0


def test_lock_acquire_and_release_failures_do_not_leak_local_lock(monkeypatch) -> None:
    plan = _single_chunk_plan()
    attempts = iter((RuntimeError("acquire failed"), _FakeLock(release_error=RuntimeError("release failed")), _FakeLock()))

    class Factory:
        def __call__(self):
            next_item = next(attempts)
            if isinstance(next_item, Exception):
                raise next_item
            return next_item

    service = WeatherRecoveryService(database_lock_factory=Factory())
    monkeypatch.setattr(service, "plan", lambda **kwargs: plan)

    first = service.run(dry_run=True)
    second = service.run(dry_run=True)
    third = service.run(dry_run=True)

    assert first.status == "error"
    assert second.status == "error"
    assert third.status == "dry_run"


def test_dry_run_never_calls_http_or_persistence(monkeypatch) -> None:
    plan = _single_chunk_plan()

    def forbidden(*args, **kwargs):
        raise AssertionError("dry-run must not call collector")

    service = WeatherRecoveryService(
        collector=SimpleNamespace(fetch_region_response=forbidden, persist_prefetched_response=forbidden),
        database_lock_factory=_FakeLock,
    )
    monkeypatch.setattr(service, "plan", lambda **kwargs: plan)

    result = service.run(dry_run=True)

    assert result.status == "dry_run"
    assert result.backlog_remaining_estimate == 1
