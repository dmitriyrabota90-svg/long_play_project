# Deployment Guide

This project is deployed as an independent Docker Compose application. It is not a Telegram bot and does not depend on Telegram code or databases.

## Current Server Layout

Production path:

```text
/data1/long_play_project
```

Important project directories:

```text
/data1/long_play_project/data/raw
/data1/long_play_project/data/exports
/data1/long_play_project/logs
```

PostgreSQL data is stored in the Docker named volume:

```text
long_play_project_postgres_data
```

Do not delete `data/raw`, `data/exports`, `logs`, or the PostgreSQL volume during routine updates.

## Daily Commands

```bash
cd /data1/long_play_project
docker compose ps
docker compose logs app --tail=200
docker compose run --rm app python scripts/health_report.py
docker compose run --rm app python scripts/operational_report.py
docker compose run --rm app python scripts/quality_summary.py
docker compose run --rm app python scripts/backup.py --dry-run
```

## Updating Code

```bash
cd /data1/long_play_project
git pull
docker compose build app
docker compose up -d app
docker compose ps
docker compose logs app --tail=100
docker compose run --rm app python scripts/health_report.py
docker compose run --rm app python scripts/operational_report.py
docker compose run --rm app python scripts/quality_summary.py
```

Only the app container needs rebuilding for Python code changes. Do not recreate or remove the PostgreSQL volume unless there is an explicit database maintenance plan.

## Current Data Scope

Phase 2 collects only `current_price_source` current prices. At this stage, empty `fx_rates`, `commodity_benchmarks`, `weather_observations`, `news_items`, `daily_product_features`, and `dataset_exports` tables are expected and should not be treated as deployment failures.

Phase 3 starts with CBR FX; additional FX sources and commodity benchmarks will follow later. Phase 4 will add feature building and dataset export workflows. Do not add those sources or change the scheduler during diagnostics cleanup.

Check quality status with:

```bash
docker compose run --rm app python scripts/quality_summary.py
```

`pass` and `skip` are successful quality statuses. Any other status is reported as problematic; if none exist, the CLI prints `quality checks ok`.

Diagnostic CSV exports for these rows should be named `quality_checks_problematic.csv`, not `quality_checks_failed.csv`.

## CBR FX Deployment

`cbr_fx` collects official CBR XML daily rates for USD/RUB, EUR/RUB, and CNY/RUB. It writes raw XML to `data/raw/cbr_fx`, normalized rows to `fx_rates`, and quality checks to `data_quality_checks`.

Manual run after deploy:

```bash
docker compose run --rm app python scripts/run_collector.py cbr_fx
docker compose run --rm app python scripts/run_collector.py cbr_fx --date 2026-05-25
docker compose run --rm app python scripts/run_collector.py cbr_fx --from-date 2026-05-20 --to-date 2026-05-25
```

Backfill ranges are inclusive and safe to repeat. Existing `(source_id, base_currency, quote_currency, observed_at)` rows are skipped and reported as `skipped_existing`.

Check stored rates:

```bash
docker compose exec -T postgres psql -U collector -d commodity_dataset -c "
SELECT base_currency, quote_currency, rate, observed_at, created_at
FROM fx_rates
ORDER BY created_at DESC
LIMIT 20;
"
```

The CBR FX scheduler remains disabled unless explicitly enabled in `.env`:

```env
CBR_FX_SCHEDULER_ENABLED=false
CBR_FX_SCHEDULE_TIME=10:00
```

Enable it only after a successful manual run/backfill:

```env
CBR_FX_SCHEDULER_ENABLED=true
CBR_FX_SCHEDULE_TIME=10:00
```

`CURRENT_PRICE_SCHEDULER_ENABLED` and `CURRENT_PRICE_SCHEDULE_TIMES` are independent and should remain unchanged.

Check for duplicates:

```bash
docker compose exec -T postgres psql -U collector -d commodity_dataset -c "
SELECT base_currency, quote_currency, observed_at, COUNT(*)
FROM fx_rates
GROUP BY base_currency, quote_currency, observed_at
HAVING COUNT(*) > 1;
"
```

## Daily Features Deployment

Phase 3.2 adds manual daily feature building. It reads `price_observations` and CBR `fx_rates`, then upserts one row per `(product_id, feature_date)` into `daily_product_features`. `feature_date` uses `SCHEDULE_TIMEZONE`; FX uses the latest official CBR rate with `observed_at <= feature_date`, so weekends use the last available CBR date and never future FX.

After deploying code and applying migrations, build all currently available features:

```bash
docker compose run --rm app alembic upgrade head
docker compose run --rm app python scripts/build_features.py daily
```

Build an explicit inclusive range:

```bash
docker compose run --rm app python scripts/build_features.py daily --from-date 2026-05-20 --to-date 2026-05-25
```

Check output and duplicate safety:

```bash
docker compose exec -T postgres psql -U collector -d commodity_dataset -c "
SELECT *
FROM daily_product_features
ORDER BY feature_date DESC, product_id
LIMIT 20;
"

docker compose exec -T postgres psql -U collector -d commodity_dataset -c "
SELECT product_id, feature_date, COUNT(*)
FROM daily_product_features
GROUP BY product_id, feature_date
HAVING COUNT(*) > 1;
"
```

There is no automatic feature scheduler in Phase 3.2. Features are built manually until the output is observed in production. This is not an ML model and does not add news, weather, ECB, or other sources.

## Price Instrument Discovery

Phase 4.0 discovery is manual and read-only. It is used to verify missing current-price product candidates before any production collector change.

```bash
docker compose run --rm app python scripts/discover_price_instruments.py
```

Outputs are limited to:

```text
diagnostics/discovery/PRICE_INSTRUMENT_DISCOVERY_REPORT.md
diagnostics/discovery/price_instrument_candidates.json
```

The discovery command must not be scheduled. It does not write to PostgreSQL, does not save production `raw_responses`, does not touch raw collector data, and does not change `CURRENT_PRICE_SCHEDULE_TIMES`.

Only candidates marked `ready_to_add` should be considered for a later Phase 4.1 production config change. Candidates marked `not_found` need a separate source review instead of guessed codes.

Phase 4.1 adds only the confirmed `soybean_meal` candidate to `current_price_source`:

```text
product_code=soybean_meal
external_code=JO_165938
endpoint=https://api.jijinhao.com/quoteCenter/realTime.htm
parser_type=json
price_path=JO_165938.q5
```

Do not add `sunflower_oil` or `sunflower_meal` until reliable instruments are confirmed.

## Checking The Collector

Manual run:

```bash
docker compose run --rm app python scripts/run_collector.py current_price_source
docker compose run --rm app python scripts/operational_report.py
```

Expected healthy result:

```text
status=success
records_found=3
records_written=3
errors_count=0
```

Raw files should appear under:

```text
data/raw/current_price_source/{yyyy}/{mm}/{dd}/{collector_run_id}/
```

## Checking The Production Scheduler

Production `.env` should use:

```env
CURRENT_PRICE_SCHEDULER_ENABLED=true
CURRENT_PRICE_SCHEDULE_TIMES=09:00,18:00
CURRENT_PRICE_TEST_INTERVAL_SECONDS=
```

Check scheduler registration:

```bash
docker compose logs app --tail=200
```

The logs should show `current_price_source_0900` and `current_price_source_1800`. The test interval job should not be present in normal production mode.

## Test Scheduler Mode

Use only for a short verification window:

```env
CURRENT_PRICE_TEST_INTERVAL_SECONDS=300
```

After testing, set it back to an empty value and recreate the app container:

```bash
docker compose up -d app
```

## Backup Dry Run

```bash
docker compose run --rm app python scripts/backup.py --dry-run
```

The script prints the planned `pg_dump`, raw-data backup, exports backup, and verification steps. It does not delete or overwrite source data.

## Directory Ownership

The app container runs as non-root `appuser` by default. The image build args default to UID/GID `1000`, matching the `dmitriy` user on the current server:

```env
APP_UID=1000
APP_GID=1000
```

If bind-mounted paths are not writable, fix only project-owned directories:

```bash
chown -R dmitriy:dmitriy /data1/long_play_project/logs
chown -R dmitriy:dmitriy /data1/long_play_project/data
```

Do not change ownership of `/data1` itself and do not touch other projects.

## PostgreSQL Password Rotation

For an existing PostgreSQL Docker volume, do not change only `.env`. The safe sequence is:

1. Generate a strong password outside git.
2. Apply it inside PostgreSQL with `ALTER USER collector WITH PASSWORD '<new-password>';`.
3. Update `DATABASE_URL` in `/data1/long_play_project/.env`.
4. Recreate only the app container.
5. Run `health_report.py` and `operational_report.py`.

Do not print the new password in command logs or reports. Do not commit `.env`.

## Do Not Touch During Routine Deploys

- Existing nginx configuration.
- Existing PM2 applications.
- SSL certificates.
- Firewall rules.
- Other systemd services.
- Other directories under `/data1`, `/data2`, `/opt`, or `/home`.
- `data/raw` source data.
- PostgreSQL Docker volume.
