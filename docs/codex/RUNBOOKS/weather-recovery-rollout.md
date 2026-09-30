# Weather Recovery Rollout

This is a local candidate runbook, not deployment authority.

1. Preview only (no HTTP, raw files, or database writes):

```bash
python scripts/weather_recovery.py --mode catchup --from-date 2026-06-16 --dry-run
```

2. After a separately approved production change window, run one bounded
catch-up and inspect the JSON result, collector runs, quality checks, and the
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

The job executes before the existing 19:30 product builder, uses PostgreSQL
advisory locking across containers, and rebuilds only `weather_daily_features`.
It does not make late backfilled weather valid for an earlier strict
as-collected cutoff; no strict cutoff-aware weather mode exists yet.
