from datetime import date, datetime, timezone
from types import SimpleNamespace

from app.collectors.weather.recovery import plan_weather_recovery, safe_weather_end
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
            )

    import app.collectors.weather.recovery as recovery

    monkeypatch.setattr(recovery, "WeatherRecoveryService", FakeService)
    jobs.weather_recovery_job()

    assert calls == ["regular"]
