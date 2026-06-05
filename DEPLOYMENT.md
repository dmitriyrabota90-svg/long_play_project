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

Phase 3.2 adds daily feature building. It reads `price_observations` and CBR `fx_rates`, then upserts one row per `(product_id, feature_date)` into `daily_product_features`. `feature_date` uses `SCHEDULE_TIMEZONE`; FX uses the latest official CBR rate with `observed_at <= feature_date`, so weekends use the last available CBR date and never future FX.

Build all currently available features manually when needed:

```bash
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

Phase 5.2 adds an optional scheduler job for this derived-table refresh:

```env
FEATURE_BUILDER_SCHEDULER_ENABLED=false
FEATURE_BUILDER_SCHEDULE_TIME=19:30
```

Enable it only after current-price and CBR FX scheduled runs are healthy:

```env
FEATURE_BUILDER_SCHEDULER_ENABLED=true
FEATURE_BUILDER_SCHEDULE_TIME=19:30
```

The scheduler registers `daily_feature_builder` at the configured time in
`SCHEDULE_TIMEZONE`. The recommended production time is `19:30`, after the
18:00 current-price run and the 10:00 CBR FX run. It does not collect raw data,
does not run historical collectors, and does not export datasets.

This is not an ML model and does not add news, weather, ECB, or other sources.

### Calendar Feature Deployment

Phase 6.0 adds deterministic calendar/seasonality columns to
`daily_product_features` and the daily features export. After deploying Phase
6.0 code, apply the migration and refresh features:

```bash
docker compose run --rm app alembic upgrade head
docker compose run --rm app python scripts/build_features.py daily
```

The refresh fills existing rows through the normal upsert path. Calendar
features are derived only from `feature_date`; they do not call external APIs,
run collectors, create ML targets, or change scheduler behavior.

## Dataset Export Deployment

Phase 5.0 exports `daily_product_features` as controlled dataset artifacts. It
does not run collectors, change schedulers, run migrations, or train an ML
model.

Run a CSV export:

```bash
cd /data1/long_play_project
docker compose run --rm app python scripts/export_dataset.py --list
APP_GIT_COMMIT=$(git rev-parse HEAD) docker compose run --rm -e APP_GIT_COMMIT app \
  python scripts/export_dataset.py daily_features --format csv --output-dir data/exports
```

`APP_GIT_COMMIT` is copied into the manifest. If it is not provided, the
exporter falls back to `git rev-parse HEAD`, then to `unknown` when `.git` is not
available inside the runtime environment.

Optional filters are inclusive:

```bash
docker compose run --rm app python scripts/export_dataset.py daily_features --from-date 2026-05-20 --to-date 2026-06-04
```

The command writes:

```text
data/exports/daily_features_v1_YYYYMMDD_HHMMSS.csv
data/exports/daily_features_v1_YYYYMMDD_HHMMSS_manifest.json
```

These files are runtime artifacts and must not be committed. Validate the latest
manifest and CSV after export:

```bash
latest_manifest=$(ls -1t data/exports/*manifest*.json | head -1)
python -m json.tool "$latest_manifest" | sed -n "1,220p"

latest_csv=$(ls -1t data/exports/*.csv | head -1)
python - <<PY
import csv
from pathlib import Path
p = Path("$latest_csv")
with p.open("r", encoding="utf-8", newline="") as f:
    reader = csv.reader(f)
    header = next(reader)
    rows = sum(1 for _ in reader)
print({"file": str(p), "columns": len(header), "rows": rows})
PY
```

Export v1 includes current snapshot and CBR FX features already materialized in
`daily_product_features`. It excludes `historical_price_bars`,
`historical_price_bar_revisions`, news, weather, benchmarks, sunflower products,
and ML targets.

After Phase 6.0, export v1 also includes deterministic calendar/seasonality
columns derived from `feature_date`.

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

## Chinese Source Capability Audit

Phase 4.2 audit tooling is read-only and writes only diagnostics:

```bash
docker compose run --rm app python scripts/audit_chinese_source.py --mode inventory
docker compose run --rm app python scripts/audit_chinese_source.py --mode check-known
docker compose run --rm app python scripts/audit_chinese_source.py --mode search-keywords
```

Outputs:

```text
diagnostics/chinese_source_audit/CHINESE_SOURCE_CAPABILITY_REPORT.md
diagnostics/chinese_source_audit/chinese_source_capabilities.json
```

`check-known` runs only bounded probes against confirmed quote/history endpoints. It must not be scheduled and must not write to PostgreSQL. `search-keywords` currently reports `not_supported`; do not replace it with broad crawling.

## Checking The Collector

Manual run:

```bash
docker compose run --rm app python scripts/run_collector.py current_price_source
docker compose run --rm app python scripts/operational_report.py
```

Expected healthy result:

```text
status=success
records_found=4
records_written=4
errors_count=0
```

Raw files should appear under:

```text
data/raw/current_price_source/{yyyy}/{mm}/{dd}/{collector_run_id}/
```

## Historical Price Probe

Phase 4.3 historical probing is diagnostics-only. It must not be scheduled and must not write to PostgreSQL production tables or production `data/raw/`.

Run bounded checks after deploy when investigating historical Jijinhao/Cngold endpoints:

```bash
docker compose run --rm app python scripts/probe_historical_prices.py --endpoint historys --all-confirmed --days 30
docker compose run --rm app python scripts/probe_historical_prices.py --endpoint kdata --all-confirmed --days 30
docker compose run --rm app python scripts/probe_historical_prices.py --endpoint historys --product-code soybean_meal --days 30
```

Outputs:

```text
diagnostics/historical_price_probe/HISTORICAL_PRICE_PROBE_REPORT.md
diagnostics/historical_price_probe/historical_price_probe_results.json
diagnostics/historical_price_probe/historical_price_comparison.csv
diagnostics/historical_price_probe/raw/
```

The probe can run read-only SELECT comparisons against `price_observations` when the database is available. It does not create `raw_responses`, does not update `daily_product_features`, and is not a production historical collector. Production historical collection requires a later schema/design decision, preferably a dedicated historical bars model or explicit `observation_type` plus OHLC fields.

## Historical Price Bars Design

Phase 4.4 is documentation-only. It does not create a migration and does not change production schema.

Read before implementing any historical collector:

```text
docs/HISTORICAL_PRICE_BARS_DESIGN.md
docs/sql_drafts/0005_historical_price_bars_draft.sql
```

The draft SQL is explicitly marked `DRAFT ONLY. DO NOT APPLY.` Future rollout should first add an Alembic migration and tests, then run a manual/backfill collector with scheduler disabled.

## Historical Price Bars Schema

Phase 4.5 adds the `historical_price_bars` table and the seed source `jijinhao_historical_prices`. After deploying this phase, apply migrations normally:

```bash
docker compose run --rm app alembic upgrade head
```

The expected immediate table count is zero:

```sql
SELECT COUNT(*) AS historical_price_bars_count FROM historical_price_bars;
```

This is intentional for Phase 4.5. `daily_product_features` continues to use `price_observations` plus `fx_rates`.

## Manual Historical Price Collector

Phase 4.6 adds a controlled manual/backfill collector for compact Jijinhao history rows. It supports only `quoteCenter/historys.htm`; `kDataList.htm` remains diagnostics-only and must not be used by the production collector yet.

After deployment, run the idempotent seed so the source row exists:

```bash
docker compose run --rm app python -m app.db.seed
```

Run one product first:

```bash
docker compose run --rm app python scripts/run_collector.py jijinhao_historical_prices --endpoint historys --product-code soybean_meal --days 30
```

If that run is healthy, run all confirmed products:

```bash
docker compose run --rm app python scripts/run_collector.py jijinhao_historical_prices --endpoint historys --days 30
```

Then run the same all-products command again to verify idempotency. An unchanged retry should report `records_written=0`, `skipped_existing` near the number of existing bars, `updated_existing=0`, `revisions_written=0`, `conflicts_count=0`, and `errors_count=0`.

Check output:

```bash
docker compose exec -T postgres psql -U collector -d commodity_dataset -c "
SELECT p.code, COUNT(*) AS rows_count, MIN(hpb.bar_date) AS first_bar_date, MAX(hpb.bar_date) AS last_bar_date
FROM historical_price_bars hpb
JOIN products p ON p.id = hpb.product_id
GROUP BY p.code
ORDER BY p.code;
"

docker compose exec -T postgres psql -U collector -d commodity_dataset -c "
SELECT product_id, source_id, endpoint_alias, bar_timeframe, bar_date, COUNT(*)
FROM historical_price_bars
GROUP BY product_id, source_id, endpoint_alias, bar_timeframe, bar_date
HAVING COUNT(*) > 1;
"

docker compose exec -T postgres psql -U collector -d commodity_dataset -c "
SELECT COUNT(*) AS rows_without_raw_response
FROM historical_price_bars
WHERE raw_response_id IS NULL;
"
```

There is no scheduler for `jijinhao_historical_prices` in Phase 4.6. Do not rebuild daily features as part of this collector rollout; feature builder source selection will be a later phase.

## Historical Mutable Latest Bar Revisions

Phase 4.6C adds Alembic revision `0006_historical_bar_revisions` and table `historical_price_bar_revisions`. Apply the migration after deploying reviewed code:

```bash
docker compose run --rm app alembic upgrade head
```

Jijinhao may revise the latest daily bar. The collector permits a controlled update only for the current `MAX(bar_date)` of the same product, source, endpoint, and timeframe. Before updating the main row, it writes a revision containing old/new values, raw-response links, hashes, `changed_fields`, and `diff_json`. Older changed bars are not overwritten silently: they remain conflicts requiring review.

After migration, run one manual historical retry and verify:

```sql
SELECT COUNT(*) FROM historical_price_bar_revisions;
SELECT id, historical_price_bar_id, revision_reason, revision_number, changed_fields, created_at
FROM historical_price_bar_revisions
ORDER BY created_at DESC
LIMIT 20;
```

The historical collector remains manual-only. Do not add a scheduler and do not rebuild daily features during this rollout.

## Checking The Production Scheduler

Production `.env` should use:

```env
CURRENT_PRICE_SCHEDULER_ENABLED=true
CURRENT_PRICE_SCHEDULE_TIMES=09:00,18:00
CURRENT_PRICE_TEST_INTERVAL_SECONDS=
CBR_FX_SCHEDULER_ENABLED=true
CBR_FX_SCHEDULE_TIME=10:00
FEATURE_BUILDER_SCHEDULER_ENABLED=true
FEATURE_BUILDER_SCHEDULE_TIME=19:30
```

Check scheduler registration:

```bash
docker compose logs app --tail=200
```

The logs should show `current_price_source_0900`, `current_price_source_1800`,
`cbr_fx_daily`, and, when enabled, `daily_feature_builder`. The test interval
job should not be present in normal production mode.

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
