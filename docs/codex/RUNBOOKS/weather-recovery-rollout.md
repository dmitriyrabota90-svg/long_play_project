# Weather Recovery Rollout

This is a local candidate runbook, not deployment authority.

1. Preview only (no HTTP, raw files, or database writes):

```bash
python scripts/weather_recovery.py --mode catchup --from-date 2026-06-16 --dry-run
```

The CLI prints JSON in every outcome. Exit code `0` means `success` or
`dry_run`; `2` means `partial_success`; `3` means `success_with_backlog`; `4`
means `skipped_overlap`; and `1` means `error`. A completed batch is not proof
that the entire gap is repaired: inspect `errors`, `conflicts_count`,
`collector_errors_count`, `plan.backlog_days`, and
`backlog_remaining_estimate` before continuing.

2. After a separately approved production change window, run one bounded
catch-up and inspect that JSON, collector runs, quality checks, and the
operational report before another run:

```bash
python scripts/weather_recovery.py --mode catchup --from-date 2026-06-16
python scripts/operational_report.py
```

3. Only after the catch-up is stable, opt in to regular collection. Keep all
other schedule values unchanged:

```env
WEATHER_SCHEDULER_ENABLED=true
WEATHER_SCHEDULE_TIME=17:30
WEATHER_SOURCE_DELAY_DAYS=5
WEATHER_MAX_DAYS_PER_REQUEST=45
WEATHER_MAX_REQUESTS_PER_RUN=14
WEATHER_MAX_RUNTIME_SECONDS=300
WEATHER_REGULAR_TAIL_DAYS=45
```

The job executes before the existing 19:30 product builder, uses a PostgreSQL
session-level advisory lock on one checked-out physical connection across
containers, and rebuilds only `weather_daily_features`. It verifies ownership
before writes; loss of the owning connection stops further writes rather than
continuing unlocked. The lock is released only by the owning connection.

The supported CLI has only `--mode`, `--from-date`, and `--dry-run`; it has no
`--region` or `--to-date`. Therefore this runbook provides no one-region or
short-range canary command. Keep scheduled weather disabled and obtain a
separate scoped implementation/approval before attempting such a canary.

It does not make late backfilled weather valid for an earlier strict
as-collected cutoff; no strict cutoff-aware weather mode exists yet.
