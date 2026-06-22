# commodity-dataset-builder

`commodity-dataset-builder` is a standalone long-running Python application for collecting, storing, normalizing, and exporting commodity-market data for future ML datasets focused on oils and meals.

This project is not a Telegram bot. It does not use a Telegram token, does not import Telegram bot code, and does not depend on any Telegram bot database.

## Current Scope

Implemented in this skeleton:

- Python application structure.
- PostgreSQL schema through SQLAlchemy and Alembic.
- Docker Compose with PostgreSQL and the app service.
- Environment-based settings via `pydantic-settings`.
- UTC datetime policy for application and database values.
- Console and file logging.
- Immutable raw storage helper.
- Hash helpers.
- Idempotent seed data for products and sources.
- Safe scheduler with controlled jobs for approved collectors.
- `current_price_source` collector for the first current-price instruments.
- CBR FX collector.
- Manual Jijinhao historical price collector for `historys`.
- Manual FRED energy collector.
- Manual World Bank Pink Sheet commodity benchmark collector.
- Manual Open-Meteo historical weather collector and weather feature builders.
- Manual GDELT news metadata collector.
- Rule-based commodity event extraction from stored news articles.
- Daily feature builder with price, FX, calendar, energy, benchmark, weather, and news/event features.
- Health-check helper.
- Dataset export v1 with manifest and SHA-256 checks.
- CLI scripts.
- Minimal pytest tests.

Not implemented yet:

- Sunflower product and fundamental collectors.
- Trade/import-export collectors.
- Automatic schedulers for historical, energy, benchmark, and weather collectors.
- Dataset target calculation.
- ML model training.
- FastAPI or any web service.
- Telegram integration.

## Architecture

```text
APScheduler
  -> collectors
  -> raw storage
  -> normalized PostgreSQL database
  -> data quality checks
  -> feature builder
  -> dataset exporter
  -> monitoring and backups
```

Every collected raw response must be stored immutably and linked to normalized records through `raw_response_id`. All data used for future features must carry `fetched_at` and either `observed_at` or `published_at` to prevent data leakage.

## Project Structure

```text
app/
  config/
  collectors/
  db/
  storage/
  features/
  exports/
  quality/
  scheduler/
  monitoring/
scripts/
tests/
data/
  raw/
  exports/
migrations/
```

## Environment

Copy the example file before running locally:

```bash
cp .env.example .env
```

Docker Compose also loads `.env.example` as safe defaults and lets a local `.env` override them.

Main settings:

```env
APP_ENV=local
LOG_LEVEL=INFO
DATABASE_URL=postgresql+psycopg2://collector:collector_password@postgres:5432/commodity_dataset
DATA_DIR=data
RAW_DATA_DIR=data/raw
EXPORT_DATA_DIR=data/exports
SCHEDULE_TIMEZONE=Europe/Moscow
CURRENT_PRICE_SCHEDULER_ENABLED=false
CURRENT_PRICE_SCHEDULE_TIMES=09:00,18:00
CURRENT_PRICE_TEST_INTERVAL_SECONDS=
CBR_FX_SCHEDULER_ENABLED=false
CBR_FX_SCHEDULE_TIME=10:00
FEATURE_BUILDER_SCHEDULER_ENABLED=false
FEATURE_BUILDER_SCHEDULE_TIME=19:30
LOG_MAX_BYTES=10485760
LOG_BACKUP_COUNT=10
APP_VERSION=0.1.0
```

All persisted application timestamps are UTC. `SCHEDULE_TIMEZONE` is used only to interpret wall-clock schedule times before converting `collection_slot` to UTC.

## Local Development

Install dependencies:

```bash
python -m venv .venv
.venv\\Scripts\\activate
pip install -e .[dev]
```

Run checks:

```bash
python -m compileall app scripts
pytest
```

## Docker Compose

Start PostgreSQL:

```bash
docker compose up -d postgres
```

Start the app scheduler:

```bash
docker compose up app
```

The PostgreSQL service is exposed only to the Docker network by default.

## PostgreSQL / Docker Verification

Use this sequence on the server or any machine with Docker daemon available:

```bash
docker compose config
docker compose up -d postgres
docker compose run --rm app alembic upgrade head
docker compose run --rm app python -m app.db.seed
docker compose run --rm app python scripts/run_collector.py current_price_source
docker compose run --rm app python scripts/health_report.py
docker compose run --rm app python scripts/operational_report.py
docker compose run --rm app python scripts/quality_summary.py
```

If `docker compose config` passes but `docker compose up` cannot connect to Docker, the code path has not failed; the Docker daemon is simply unavailable in that environment.

## Alembic Migrations

Run migrations:

```bash
alembic upgrade head
```

Create a future migration:

```bash
alembic revision --autogenerate -m "describe change"
```

The application does not silently recreate production tables. Schema changes must go through Alembic.

## Seed

Seed products and sources:

```bash
python -m app.db.seed
```

The seed is idempotent and can be run repeatedly.

## Scheduler

Run the safe scheduler skeleton:

```bash
python scripts/run_scheduler.py
```

Current jobs:

- `health_check`: hourly.
- `daily_quality_check`: daily at 03:00 in `SCHEDULE_TIMEZONE`.

No real collectors are scheduled yet.

The `current_price_source` job function exists in code but is not registered in the scheduler by default. Run it explicitly from CLI until the schedule is intentionally enabled.

## Current Price Collector

Run the first real price collector:

```bash
python scripts/run_collector.py current_price_source
python scripts/run_collector.py current_price_source --run-type manual
python scripts/run_collector.py current_price_source --run-type scheduled --collection-slot "2026-05-12T09:00:00+00:00"
```

It currently collects:

- `rapeseed_oil` from `JO_166042`, JSON response, price path `JO_166042.q5`.
- `soybean_oil` from `JO_165951`, CSV-like response, price index `3`.
- `rapeseed_meal` from `JO_166106`, CSV-like response, price index `3`.
- `soybean_meal` from `JO_165938`, JSON response, price path `JO_165938.q5`.

Instrument config lives in:

```text
app/collectors/prices/current_price_config.py
```

To add a new current-price instrument, add a `CurrentPriceInstrument` entry with `product_code`, `external_code`, `endpoint`, `params`, `parser_type`, `response_prefix`, `price_path` or `price_index`, `currency`, and `unit`.

The collector writes:

- run status to `collector_runs`;
- raw payload metadata to `raw_responses`;
- immutable raw files to `data/raw/current_price_source/{yyyy}/{mm}/{dd}/{collector_run_id}/{sha256}.txt`;
- normalized prices to `price_observations`;
- first quality checks to `data_quality_checks`.

`collection_slot` is the planned collection point for scheduled runs. Manual runs keep `observed_at=fetched_at`. Scheduled runs use `observed_at=collection_slot` while keeping `fetched_at` as the real fetch time. This prevents retry attempts a few minutes apart from creating extra time points for the same planned collection.

For safety, `--collection-slot` is required for `--run-type scheduled`; the CLI refuses to invent a slot.

The collector is idempotent for scheduled retries: the stable `source_record_hash` uses `collection_slot` for scheduled runs and `observed_at` for manual runs.

Source-specific schema checks now include:

- raw response is not empty;
- content type is expected;
- raw response size is not anomalous versus recent responses for the instrument;
- response prefix exists;
- JSON root contains the external code;
- JSON price path exists;
- CSV column count is greater than `price_index`;
- price is convertible.

Useful SQL checks:

```sql
select * from collector_runs order by started_at desc limit 5;
select * from raw_responses order by fetched_at desc limit 5;
select * from price_observations order by observed_at desc limit 20;
select * from data_quality_checks order by checked_at desc limit 20;
select product_id, source_id, observed_at, collection_slot, count(*)
from price_observations
group by product_id, source_id, observed_at, collection_slot
having count(*) > 1;
```

## Controlled Current Price Schedule

The current-price collector is not scheduled unless explicitly enabled:

```env
CURRENT_PRICE_SCHEDULER_ENABLED=false
CURRENT_PRICE_SCHEDULE_TIMES=09:00,18:00
CURRENT_PRICE_TEST_INTERVAL_SECONDS=
SCHEDULE_TIMEZONE=Europe/Moscow
```

When `CURRENT_PRICE_SCHEDULER_ENABLED=true`, the scheduler registers one cron job per configured `HH:MM` time. Each job passes `run_type="scheduled"` and a UTC `collection_slot` based on the configured scheduler timezone.

### Test Scheduler Mode

For a short operational test without waiting for `09:00` or `18:00`, set:

```env
CURRENT_PRICE_TEST_INTERVAL_SECONDS=300
```

This registers `current_price_source_test_interval` and runs the collector every 300 seconds. Keep it empty in production unless you are deliberately testing. No interval job is registered by default.

### Production Scheduler Mode

For normal scheduled collection:

```env
CURRENT_PRICE_SCHEDULER_ENABLED=true
CURRENT_PRICE_SCHEDULE_TIMES=09:00,18:00
CURRENT_PRICE_TEST_INTERVAL_SECONDS=
SCHEDULE_TIMEZONE=Europe/Moscow
```

Start the scheduler:

```bash
python scripts/run_scheduler.py
```

The collector stores `fetched_at` as the real fetch time and `collection_slot` / `observed_at` as the scheduled UTC time.

## Current Price Health Report

Print the operational report:

```bash
python scripts/health_report.py
python scripts/health_report.py --freshness-hours 12
```

The report includes:

- latest successful `current_price_source` run;
- latest failed or partial run;
- `price_observations` count for the last 24 hours;
- problematic quality checks for the last 24 hours;
- products without a fresh price;
- raw storage status;
- database status.

## Operational Report

Use the wider operational report:

```bash
python scripts/operational_report.py
python scripts/operational_report.py --freshness-hours 12
```

It includes database status, app version, masked DB URL setting, collector run counts, latest success/partial/error runs, raw/price/problematic quality counts for the last 24 hours, stale products, and sizes of `data/raw`, `data/exports`, and `logs`.

## Data Collection Phases

The current Phase 2 MVP collects only `current_price_source` current prices. Empty `fx_rates`, `commodity_benchmarks`, `weather_observations`, `news_items`, `daily_product_features`, and `dataset_exports` tables are expected at this stage and are not a production error.

Planned phases:

- Phase 2: current price collection only.
- Phase 3: CBR FX first; additional FX sources and commodity benchmarks later.
- Phase 4: feature building and dataset export workflows.

Do not add FX/news/weather/features/export sources as part of diagnostics cleanup.

## Quality Summary

Use the quality summary CLI to review checks without treating `pass`, `skip`,
or `info` rows as failures:

```bash
python scripts/quality_summary.py
python scripts/quality_summary.py --limit 50
```

The CLI prints total checks, checks by status, checks by severity, problematic
checks, latest problematic checks, and classified incident buckets. Problematic
rows are split into `active_current_failure`, `known_historical_incident`, and
`expected_diagnostic_incident`.

Old checks are never deleted or hidden. Known historical incidents and expected
diagnostic probe failures remain visible in the report, but they no longer make
the operational conclusion look like a fresh active failure. Conclusions are:

- `ok`: no active or known problematic checks.
- `ok_with_known_incidents`: no active failures, but known historical or
  expected diagnostic incidents remain in the database.
- `error`: at least one fresh or unknown active problematic check exists.

When exporting problematic quality checks for diagnostics, use `quality_checks_problematic.csv`; the old `quality_checks_failed.csv` name is intentionally avoided because `pass` and `skip` are not failures.

## CBR FX Collector

Phase 3 adds the first FX source: `cbr_fx`, the official Central Bank of Russia XML daily rates endpoint. It collects USD/RUB, EUR/RUB, and CNY/RUB from `https://www.cbr.ru/scripts/XML_daily.asp`, stores the raw XML in `data/raw/cbr_fx/...`, writes normalized rates to `fx_rates`, and records quality checks in `data_quality_checks`.

Manual run:

```bash
python scripts/run_collector.py cbr_fx
python scripts/run_collector.py cbr_fx --date 2026-05-25
python scripts/run_collector.py cbr_fx --from-date 2026-05-20 --to-date 2026-05-25
```

Backfill ranges are inclusive. Each requested day stores its own raw XML response and uses the same idempotency check as normal runs, so repeating the command should increase `skipped_existing` instead of creating duplicate `fx_rates` rows.

The CBR XML value is normalized as `Value / Nominal`, so CNY with `Nominal=10` is stored as the RUB price of 1 CNY.

The CBR FX scheduler is controlled separately and is disabled by default:

```env
CBR_FX_SCHEDULER_ENABLED=false
CBR_FX_SCHEDULE_TIME=10:00
```

Set `CBR_FX_SCHEDULER_ENABLED=true` to collect CBR FX once per day at `CBR_FX_SCHEDULE_TIME` in `SCHEDULE_TIMEZONE`. This does not change `CURRENT_PRICE_SCHEDULER_ENABLED` or `CURRENT_PRICE_SCHEDULE_TIMES`.

To inspect data:

```sql
SELECT base_currency, quote_currency, rate, observed_at, created_at
FROM fx_rates
ORDER BY created_at DESC
LIMIT 20;

SELECT base_currency, quote_currency, observed_at, COUNT(*)
FROM fx_rates
GROUP BY base_currency, quote_currency, observed_at
HAVING COUNT(*) > 1;
```

## Log Rotation

Application logs use `RotatingFileHandler`:

```env
LOG_MAX_BYTES=10485760
LOG_BACKUP_COUNT=10
```

`logs/` is ignored by git. Rotated logs are operational artifacts and should be covered by server retention policy.

## Cleanup Dry Run

Show cleanup information:

```bash
python scripts/cleanup_operational.py --dry-run
```

The cleanup skeleton reports sizes and rotated log candidates. It does not delete raw data or exports. Raw data is the source of future datasets and must be managed through backup/retention policy, not casual cleanup.

## Backup Dry Run

Show the backup plan:

```bash
python scripts/backup.py --dry-run
```

The plan includes a `pg_dump` command, raw-data copy plan, exports copy plan, and verification checklist. It performs no actions by default.

## PostgreSQL Data Checks

With Docker PostgreSQL:

```bash
docker compose up -d postgres
alembic upgrade head
python -m app.db.seed
python scripts/run_collector.py current_price_source
python scripts/health_report.py
```

## Deployment Checklist

1. Install Docker and Docker Compose plugin.
2. Create `.env` from `.env.example`.
3. Keep `CURRENT_PRICE_TEST_INTERVAL_SECONDS` empty for production.
4. Run `docker compose config`.
5. Start PostgreSQL with `docker compose up -d postgres`.
6. Apply migrations with `docker compose run --rm app alembic upgrade head`.
7. Seed products and sources with `docker compose run --rm app python -m app.db.seed`.
8. Run one manual collector check.
9. Run `health_report.py` and `operational_report.py`.
10. Configure backups for PostgreSQL, `data/raw`, and `data/exports`.
11. Enable `CURRENT_PRICE_SCHEDULER_ENABLED=true` only after the manual check is healthy.

## Post-Deploy Checks

Run these checks after every server deploy:

```bash
docker compose ps
docker compose logs app --tail=200
docker compose run --rm app python scripts/operational_report.py
docker compose run --rm app python scripts/health_report.py
```

Verify the production scheduler from logs. It should register `current_price_source_0900` and `current_price_source_1800`. It should not register `current_price_source_test_interval` unless `CURRENT_PRICE_TEST_INTERVAL_SECONDS` is deliberately set for a short test.

Check raw storage:

```bash
find data/raw/current_price_source -type f | tail
du -h data/raw data/exports logs --max-depth=2
```

Check backup planning:

```bash
docker compose run --rm app python scripts/backup.py --dry-run
```

Safe code update flow:

```bash
git pull
docker compose build app
docker compose up -d app
docker compose ps
docker compose run --rm app python scripts/health_report.py
docker compose run --rm app python scripts/operational_report.py
```

If host bind-mounted `logs/` or `data/` are not writable by the app container, fix only those project directories. Do not change ownership of `/data1` or other projects. The app image runs as a non-root user by default, using `APP_UID` and `APP_GID` build args, both defaulting to `1000`.

### PostgreSQL Password Rotation

For an existing PostgreSQL Docker volume, changing only `.env` is not enough: the database user password stored inside PostgreSQL remains unchanged. The safe order is:

1. Generate a new password outside git.
2. Run a one-off SQL command against the running database: `ALTER USER collector WITH PASSWORD '<new-password>';`.
3. Update `DATABASE_URL` in the server `.env` to use the same password.
4. Recreate the app container with `docker compose up -d app`.
5. Run `health_report.py` and `operational_report.py`.

Do not commit production `.env` and do not print the new password in logs or reports.

## Health Check

Use the health helper from Python:

```bash
python -c "from app.monitoring.health import run_health_check; print(run_health_check())"
```

It checks:

- database connectivity;
- `data/raw`;
- `data/exports`;
- product count;
- source count;
- latest collector run, if any.

## Raw Storage

Raw payloads are stored under:

```text
data/raw/{source_code}/{yyyy}/{mm}/{dd}/{collector_run_id}/{sha256}.{ext}
```

Files are never overwritten. The SHA-256 hash is calculated from the original bytes.

## Dataset Export

Export the current daily feature table as dataset v1:

```bash
python scripts/export_dataset.py --list
python scripts/export_dataset.py daily_features
python scripts/export_dataset.py daily_features --from-date 2026-05-20 --to-date 2026-06-04
python scripts/export_dataset.py daily_features --format csv
python scripts/export_dataset.py daily_features --format parquet
python scripts/export_dataset.py daily_features --format both
```

The default format is CSV. Output files are written under:

```text
data/exports/daily_features_v1_YYYYMMDD_HHMMSS.csv
data/exports/daily_features_v1_YYYYMMDD_HHMMSS_manifest.json
```

Export v1 uses `daily_product_features` as stored and joins `products` for
`product_code` and `product_name`. It does not use `historical_price_bars`, does
not create ML targets, and does not add news. Export v1 includes World Bank
benchmark feature columns and Phase 6.3F product-level weather feature columns
already materialized in `daily_product_features`. Export payload files in
`data/exports/` are runtime artifacts and must not be committed. Set
`APP_GIT_COMMIT=$(git rev-parse HEAD)` when exporting from Docker so the
manifest records the deployed commit. See [docs/DATASET_EXPORT.md](docs/DATASET_EXPORT.md).

## Phase 6.1A Energy Source Discovery

Phase 6.1A is diagnostics-only source discovery for future energy/oil factors.
It audits candidate sources such as FRED/EIA-derived CSV, EIA Open Data, and
World Bank Pink Sheet without writing PostgreSQL rows, storing production raw
responses, running collectors, changing schedulers, or creating ML targets.

Run the static inventory:

```bash
python scripts/audit_energy_sources.py
```

Outputs are runtime diagnostics and must not be committed:

```text
diagnostics/energy_source_audit/ENERGY_SOURCE_AUDIT_REPORT.md
diagnostics/energy_source_audit/energy_source_candidates.json
```

Current recommendation: prototype daily/weekly energy factors first from
FRED/EIA-derived CSV series for Brent, WTI, Henry Hub natural gas, and US diesel
proxy. EIA Open Data needs API-key policy and route discovery before production;
unofficial finance/scraping endpoints are high risk.

## Phase 6.1B Energy Prices Schema Design

Phase 6.1B is design-only for the future `energy_prices` table. It adds the
proposal in [docs/ENERGY_PRICES_DESIGN.md](docs/ENERGY_PRICES_DESIGN.md) and a
draft SQL file in `docs/sql_drafts/0008_energy_prices_draft.sql`.

No migration is created in this phase, no SQLAlchemy model is added, no
production collector is implemented, and no PostgreSQL rows are written. The
proposed next steps are:

- Phase 6.1C: non-destructive schema migration.
- Phase 6.1D: first controlled/manual FRED energy collector.
- Phase 6.1E: energy feature integration and export update.

## Phase 6.1C Energy Prices Schema

Phase 6.1C creates schema-only support for `energy_prices`: SQLAlchemy metadata,
Alembic revision `0008_energy_prices`, idempotent source seed
`fred_energy_prices`, and operational report counts. The table is expected to be
empty immediately after migration.

This phase still does not implement a production energy collector, does not
write energy rows, does not change schedulers, and does not add energy columns
to `daily_product_features` or dataset export.

## Phase 6.1D FRED Energy Prices Collector

Phase 6.1D adds the first controlled/manual energy collector:
`fred_energy_prices`. It fetches bounded FRED CSV series, stores raw CSV through
the production `RawStore`, records `raw_responses`, and writes normalized rows
to `energy_prices`. It does not add a scheduler and does not change
`current_price_source`, `cbr_fx`, historical price collection, daily features,
exports, ML targets, or migrations.

Run all configured FRED series:

```bash
python scripts/run_collector.py fred_energy_prices --from-date 2026-05-20 --to-date 2026-06-05
```

Run one series:

```bash
python scripts/run_collector.py fred_energy_prices --series DCOILBRENTEU --from-date 2026-05-20 --to-date 2026-06-05
```

Configured series:

- `DCOILBRENTEU`: Brent crude oil, daily, `USD/barrel`.
- `DCOILWTICO`: WTI crude oil, daily, `USD/barrel`.
- `DHHNGSP`: Henry Hub natural gas, daily, `USD/MMBtu`.
- `GASDESW`: US diesel proxy, weekly, `source_unit`; source unit and exact
  period semantics must be verified before feature integration.

The collector skips FRED missing values such as `.`. Idempotency is by
`source_id + instrument_code + frequency + period_start + period_end`. Same hash
rows are counted as `skipped_existing`; changed hashes write
`energy_existing_record_hash_changed` and are not overwritten in Phase 6.1D.
When `--from-date/--to-date` is provided, the FRED request includes bounded
`cosd/coed` parameters. Network hardening is intentionally conservative:
`FRED_ENERGY_TIMEOUT_SECONDS` defaults to `30`, and the collector performs only
one retry for transient timeout/connection errors before returning a clear
per-series failure.

Check data:

```sql
SELECT instrument_code, instrument_category, frequency, COUNT(*) AS rows_count,
       MIN(period_start) AS first_period, MAX(period_start) AS last_period
FROM energy_prices
GROUP BY instrument_code, instrument_category, frequency
ORDER BY instrument_code;

SELECT source_id, instrument_code, frequency, period_start, period_end, COUNT(*)
FROM energy_prices
GROUP BY source_id, instrument_code, frequency, period_start, period_end
HAVING COUNT(*) > 1;
```

## Phase 6.1E Energy Features And Export Integration

Phase 6.1E adds nullable energy columns to `daily_product_features` through
Alembic revision `0009_energy_features` and extends the daily feature builder
and export v1. It uses only already-collected `energy_prices`; it does not run
energy collectors, change schedulers, add ML targets, or use historical bars.

Energy as-of logic is conservative: for each feature date, the builder uses the
latest FRED row with `energy_prices.period_start <= feature_date`. Brent, WTI,
and Henry Hub get current values plus 1-day and 7-day deltas. The weekly diesel
proxy is forward-filled by the same as-of rule and gets a 7-day delta. Missing
current energy series are recorded in `energy_missing_flags`; missing deltas
remain `NULL`.

After deploying and applying the migration, rebuild daily features manually:

```bash
python scripts/build_features.py daily
```

Export v1 then includes the energy columns in CSV/Parquet output and in the
manifest `columns` / `column_count` fields:

```bash
APP_GIT_COMMIT=$(git rev-parse HEAD) python scripts/export_dataset.py daily_features --format csv --output-dir data/exports
```

## Phase 3.2 Daily Features

Daily features turn raw daily price observations and official CBR FX rates into one row per product and local feature date. Dates are calculated in `SCHEDULE_TIMEZONE` (`Europe/Moscow` in production), and FX uses an as-of rule: for each feature date, the builder uses the latest USD/RUB, EUR/RUB, and CNY/RUB rate with `fx_rates.observed_at <= feature_date`. Weekend and holiday CBR gaps therefore use the last available official rate without looking into the future.

Build all available features:

```bash
python scripts/build_features.py daily
```

Build an explicit inclusive range:

```bash
python scripts/build_features.py daily --from-date 2026-05-20 --to-date 2026-05-25
```

The builder upserts by `(product_id, feature_date)`: repeated runs update changed rows, skip identical rows, and do not create duplicates. Rolling windows require full windows: 3 daily price points for `price_rolling_mean_3d`, and 7 daily price points for `price_rolling_mean_7d` / `price_rolling_std_7d`; otherwise the fields stay `NULL`.

Check the result:

```sql
SELECT *
FROM daily_product_features
ORDER BY feature_date DESC, product_id
LIMIT 20;

SELECT product_id, feature_date, COUNT(*)
FROM daily_product_features
GROUP BY product_id, feature_date
HAVING COUNT(*) > 1;
```

This is feature engineering only. It is not an ML model, and it does not add news, weather, ECB, or other external sources.

### Calendar And Seasonality Features

Phase 6.0 adds deterministic calendar features to `daily_product_features` and
the daily features export. These fields include year, month, quarter, ISO week,
day of year, ISO day of week (`Monday=1`, `Sunday=7`), month/quarter boundary
flags, cyclic sine/cosine encodings for day of year and month, and
`calendar_season` (`winter`, `spring`, `summer`, `autumn`).

Calendar features are produced by the normal daily feature builder and require
no external API. After deploying Phase 6.0, run Alembic and rebuild features:

```bash
alembic upgrade head
python scripts/build_features.py daily
```

### Daily Feature Scheduler

Phase 5.2 adds an optional scheduler job for refreshing `daily_product_features`.
It is disabled by default:

```env
FEATURE_BUILDER_SCHEDULER_ENABLED=false
FEATURE_BUILDER_SCHEDULE_TIME=19:30
```

When enabled, the scheduler registers `daily_feature_builder` at
`FEATURE_BUILDER_SCHEDULE_TIME` in `SCHEDULE_TIMEZONE`. The recommended
production time is `19:30`, after the 18:00 current-price run and the 10:00 CBR
FX run. This job only refreshes derived feature rows; it does not collect raw
data and does not export datasets.

## Adding a Collector

1. Add a class under `app/collectors/`.
2. Inherit from `BaseCollector`.
3. Store every raw response through `RawStore`.
4. Insert a `collector_runs` row for every run.
5. Insert a `raw_responses` row for every fetched payload.
6. Normalize data into dedicated tables with `raw_response_id`.
7. Add data quality checks before scheduling the collector.

Collectors must not use future data to build features. Feature availability must be controlled through `fetched_at`, `published_at`, and `as_of_at`.

## Phase 4.0 Price Instrument Discovery

Phase 4.0 is a read-only discovery step for missing product instruments. It does not add products to `CURRENT_PRICE_INSTRUMENTS`, does not write to `price_observations`, does not write to production `raw_responses`, and is not registered in any scheduler.

Run the built-in discovery:

```bash
python scripts/discover_price_instruments.py
```

The script writes concise diagnostics only:

```text
diagnostics/discovery/PRICE_INSTRUMENT_DISCOVERY_REPORT.md
diagnostics/discovery/price_instrument_candidates.json
```

You can probe a single candidate without changing production config:

```bash
python scripts/discover_price_instruments.py \
  --product-code soybean_meal \
  --title "Соевый шрот" \
  --endpoint "https://api.jijinhao.com/quoteCenter/realTime.htm" \
  --external-code JO_165938 \
  --parser-type json \
  --expected-keyword 豆粕
```

Discovery statuses mean:

- `ready_to_add`: the candidate parsed and matched the expected product name, but still needs Phase 4.1 confirmation before production use.
- `needs_manual_check`: a possible source exists, but the current parser/config is not reliable enough.
- `not_found`: no reliable current-source instrument was found; do not guess.

## Phase 4.1 Soybean Meal

Phase 4.1 promotes only the confirmed discovery candidate for `soybean_meal` into the production current-price instrument config:

- external code: `JO_165938`
- endpoint: `https://api.jijinhao.com/quoteCenter/realTime.htm`
- parser type: `json`
- response prefix: `var quote_json = `
- price path: `JO_165938.q5`

`sunflower_oil` and `sunflower_meal` are intentionally not added because reliable Jijinhao/Cngold instruments have not been found.

## Phase 4.2 Chinese Source Capability Audit

Phase 4.2 maps what the Cngold/Jijinhao source can provide beyond the currently collected instruments. It is read-only: it writes only diagnostic artifacts, does not write PostgreSQL rows, does not save production `raw_responses`, and does not run production collectors.

```bash
python scripts/audit_chinese_source.py --mode inventory
python scripts/audit_chinese_source.py --mode check-known
python scripts/audit_chinese_source.py --mode search-keywords
```

Outputs:

```text
diagnostics/chinese_source_audit/CHINESE_SOURCE_CAPABILITY_REPORT.md
diagnostics/chinese_source_audit/chinese_source_capabilities.json
```

`inventory` is static source mapping. `check-known` performs a small number of bounded HTTP probes against confirmed current quote endpoints and the compact `quoteCenter/historys.htm` history endpoint. `search-keywords` is intentionally `not_supported` to avoid crawler-like behavior.

Current Phase 4.2 recommendation: consider a separate historical daily OHLC prototype for already confirmed instruments before adding news, broad catalogs, or new commodity families.

## Phase 4.3 Historical Price Probe

Phase 4.3 probes historical Jijinhao/Cngold endpoints for the already confirmed production instruments only:

- `rapeseed_oil` / `JO_166042`
- `soybean_oil` / `JO_165951`
- `rapeseed_meal` / `JO_166106`
- `soybean_meal` / `JO_165938`

It is diagnostics-only. It does not write to PostgreSQL, does not create production `raw_responses`, does not update `daily_product_features`, and is not a production collector.

Run bounded probes:

```bash
python scripts/probe_historical_prices.py --endpoint historys --all-confirmed --days 30
python scripts/probe_historical_prices.py --endpoint kdata --all-confirmed --days 30
python scripts/probe_historical_prices.py --endpoint historys --product-code soybean_meal --days 30
```

Supported endpoint aliases:

- `historys` -> `https://api.jijinhao.com/quoteCenter/historys.htm`
- `kdata` -> `https://api.jijinhao.com/sQuoteCenter/kDataList.htm`
- `today_min` -> `https://api.jijinhao.com/sQuoteCenter/todayMin.htm`
- `four_days_min` -> `https://api.jijinhao.com/sQuoteCenter/fourDaysMin.htm`

Outputs:

```text
diagnostics/historical_price_probe/HISTORICAL_PRICE_PROBE_REPORT.md
diagnostics/historical_price_probe/historical_price_probe_results.json
diagnostics/historical_price_probe/historical_price_comparison.csv
diagnostics/historical_price_probe/raw/
```

Raw diagnostic responses are saved only under `diagnostics/historical_price_probe/raw/`, not under production `data/raw/`. If database access is available, the probe performs read-only comparison against existing `price_observations` for overlapping dates.

This phase does not decide the production schema. A future historical collector should be a separate phase after choosing whether to use a dedicated `historical_price_bars` table or explicit `observation_type` / OHLC fields.

## Phase 4.4 Historical Price Bars Design

Phase 4.4 is design-only. It documents how future historical daily bars should be stored without implementing a production historical collector or creating an Alembic migration.

Design document:

```text
docs/HISTORICAL_PRICE_BARS_DESIGN.md
```

Draft SQL, not to apply:

```text
docs/sql_drafts/0005_historical_price_bars_draft.sql
```

The design recommends a separate `historical_price_bars` table linked to `raw_responses`, because historical bars have a different as-of/leakage profile from current snapshot rows in `price_observations`. The first future collector candidate should use compact `quoteCenter/historys.htm`; `kDataList.htm` remains later/manual-check due to larger payloads.

## Phase 4.5 Historical Price Bars Schema

Phase 4.5 implements schema-only support for `historical_price_bars`:

- SQLAlchemy model: `HistoricalPriceBar`.
- Alembic revision: `0005_historical_price_bars`.
- Idempotent seed source: `jijinhao_historical_prices`.
- Operational report count/last-date fields for historical bars.

The table is expected to be empty immediately after migration. No production historical collector exists yet, daily features do not read `historical_price_bars`, and historical bars must not be mixed into `price_observations`.

## Phase 4.6 Manual Jijinhao Historical Price Collector

Phase 4.6 adds the first controlled production historical collector, `jijinhao_historical_prices`. It supports only the compact `quoteCenter/historys.htm` endpoint and writes normalized rows into `historical_price_bars`. It is manual/backfill only and is not registered in the scheduler.

Run all confirmed instruments:

```bash
python scripts/run_collector.py jijinhao_historical_prices --endpoint historys --days 30
```

Run one product:

```bash
python scripts/run_collector.py jijinhao_historical_prices --endpoint historys --product-code soybean_meal --days 30
```

Run as a backfill-labeled collector run:

```bash
python scripts/run_collector.py jijinhao_historical_prices --endpoint historys --days 30 --run-type backfill
```

Phase 4.6 deliberately rejects `kdata` for production collection:

```bash
python scripts/run_collector.py jijinhao_historical_prices --endpoint kdata --days 30
```

Expected output includes `run_id`, `status`, `endpoint_alias`, `products_processed`, `records_found`, `records_written`, `skipped_existing`, `updated_existing`, `revisions_written`, `conflicts_count`, and `errors_count`.

The collector stores raw evidence through the production `RawStore` under:

```text
data/raw/jijinhao_historical_prices/{yyyy}/{mm}/{dd}/{collector_run_id}/{sha256}.txt
```

It creates `collector_runs`, `raw_responses`, `historical_price_bars`, and quality checks. It does not write to `price_observations`, does not rebuild `daily_product_features`, and does not change `current_price_source` or `cbr_fx` behavior.

Idempotency is by `(product_id, source_id, endpoint_alias, bar_timeframe, bar_date)`. If the existing row has the same `source_record_hash`, the row is counted as `skipped_existing`.

## Phase 4.6C Mutable Latest Historical Bar Revisions

Phase 4.6C adds an audit trail for source revisions. Jijinhao can revise the latest daily historical bar after an initial fetch, so `historical_price_bars` stores the latest accepted version while `historical_price_bar_revisions` preserves the previous and incoming values, raw-response links, hashes, changed fields, and field-level diff.

Controlled updates are allowed only when a changed row is the latest `MAX(bar_date)` for its `(product_id, source_id, endpoint_alias, bar_timeframe)` series. The collector writes a `historical_latest_bar_updated` quality record and increments `updated_existing` / `revisions_written`. If an older closed bar changes, the collector does not overwrite it: it records an `immutable_old_bar_conflict` revision, writes `historical_old_bar_hash_changed`, and increments `conflicts_count`.

There is still no historical scheduler. Daily features still read only `price_observations` plus `fx_rates`; they do not consume `historical_price_bars`.

Check stored bars:

```sql
SELECT p.code, hpb.endpoint_alias, hpb.bar_timeframe, hpb.bar_date, hpb.price, hpb.close_price, hpb.currency, hpb.unit, hpb.fetched_at
FROM historical_price_bars hpb
JOIN products p ON p.id = hpb.product_id
ORDER BY hpb.created_at DESC
LIMIT 20;

SELECT product_id, source_id, endpoint_alias, bar_timeframe, bar_date, COUNT(*)
FROM historical_price_bars
GROUP BY product_id, source_id, endpoint_alias, bar_timeframe, bar_date
HAVING COUNT(*) > 1;
```

Daily features still use `price_observations` plus `fx_rates`; historical bars are not consumed by feature building yet.

## Backup Skeleton

Current backup script only prints the planned steps:

```bash
python scripts/backup.py
```

Future implementation should include PostgreSQL dumps, raw-data backups, export backups, checksum verification, and retention policy.

## Phase 5.0 Daily Features Dataset Export

Phase 5.0 adds controlled file export for `daily_product_features`:

```bash
APP_GIT_COMMIT=$(git rev-parse HEAD) python scripts/export_dataset.py daily_features --format csv --output-dir data/exports
```

The export grain is one row per `product_code` and `feature_date`. The manifest
records the Git commit, row count, column count, product list, date range,
source-table notes, excluded sources, file sizes, and SHA-256 hashes. Historical
bars and revision rows remain excluded from feature export v1.

Phase 6.0 extends this export with deterministic calendar/seasonality columns.
These are derived from `feature_date`; they do not require new external sources
and are not model targets.

This is not ML model training and does not create targets.

## Phase 6.1A Energy/Oil Source Audit

Phase 6.1A adds a diagnostics-only inventory for future energy/oil factors:

```bash
python scripts/audit_energy_sources.py
```

The command writes only `diagnostics/energy_source_audit/*`, does not touch
PostgreSQL, does not use production `RawStore`, does not run collectors, and
does not change scheduler settings. The first recommended future prototype is a
FRED/EIA-derived CSV collector for Brent, WTI, Henry Hub natural gas, and US
diesel proxy, after a separate schema design phase.

Phase 6.1B documents that schema design in
[docs/ENERGY_PRICES_DESIGN.md](docs/ENERGY_PRICES_DESIGN.md). It is still
design-only: the draft SQL is not an Alembic migration, `energy_prices` is not
created yet, and daily feature export does not use energy data.

Phase 6.1C implements the empty `energy_prices` schema and the
`fred_energy_prices` source seed only. The first controlled FRED collector is a
later phase.

Phase 6.1D implements the manual-only `fred_energy_prices` collector. Phase
6.1E integrates those collected rows into `daily_product_features` and export v1
with strict `period_start <= feature_date` as-of logic. It does not add an
energy scheduler, does not rebuild features automatically, and does not create
ML targets.

## Phase 6.2A Commodity Benchmark Source Audit

Phase 6.2A is a local diagnostics-only inventory for future global commodity
benchmark sources such as World Bank Pink Sheet, FAO indices, USDA/WASDE/PSD,
and selected FRED commodity proxies.

```bash
python scripts/audit_commodity_benchmarks.py
```

The command writes only `diagnostics/commodity_benchmark_audit/*`. It does not
write PostgreSQL rows, does not use production `RawStore`, does not run
collectors, does not change schedulers, and does not require production deploy.
Current recommendation: design a `commodity_benchmarks` schema first, then
prototype World Bank Pink Sheet as the first controlled monthly benchmark
collector.

Phase 6.2B documents that schema design in
[docs/COMMODITY_BENCHMARKS_DESIGN.md](docs/COMMODITY_BENCHMARKS_DESIGN.md) and
adds a draft SQL file at
`docs/sql_drafts/0010_commodity_benchmarks_draft.sql`. It is design-only: no
migration, no SQLAlchemy model changes, no collector, no scheduler changes, no
DB writes, no ML, and no targets. Planned next steps are Phase 6.2C schema
implementation, Phase 6.2D a controlled World Bank Pink Sheet collector, and
Phase 6.2E benchmark feature/export integration.

Phase 6.2C implements schema-only support for `commodity_benchmarks`: SQLAlchemy
metadata, Alembic revision `0010_commodity_benchmarks`, idempotent source seeds
for `world_bank_pink_sheet` and `fao_price_indices`, and operational report
counts for an empty table. It still does not implement a benchmark collector,
does not write benchmark rows, does not change schedulers, and does not add ML
targets.

Phase 6.2D adds the first manual-only `world_bank_pink_sheet` collector. It
downloads the official World Bank Pink Sheet monthly historical XLSX, stores the
raw workbook through `RawStore`, writes `raw_responses`, and inserts normalized
monthly rows into `commodity_benchmarks`.

```bash
python scripts/run_collector.py world_bank_pink_sheet
python scripts/run_collector.py world_bank_pink_sheet --benchmark world_bank_soybean_oil --from-date 2024-01-01 --to-date 2026-06-01
```

Supported benchmark codes are `world_bank_soybean_oil`, `world_bank_soybeans`,
`world_bank_palm_oil`, `world_bank_maize`, `world_bank_wheat`, and
`world_bank_fertilizer_index`. Date filters use `period_start`; monthly
`observed_at` is the calendar month end. The collector is idempotent by
`source_id + benchmark_code + frequency + period_start + period_end`; same-hash
rows are skipped, changed hashes create a warning and are not overwritten in
Phase 6.2D. No benchmark scheduler is registered, and no ML targets are
created.

Phase 6.2E integrates the collected World Bank benchmark rows into
`daily_product_features` and export v1 through nullable columns. The feature
builder forward-fills the latest monthly benchmark row with
`commodity_benchmarks.period_start <= feature_date`, creates 1-month and
3-month deltas using calendar-month lookbacks, records per-series as-of dates,
and writes `benchmark_missing_flags` when a configured series is unavailable.
This phase adds Alembic revision `0011_benchmark_features`, but it does not run
benchmark collectors, add a benchmark scheduler, rebuild features
automatically, or create ML targets.

After deploying and applying the migration, rebuild features manually:

```bash
python scripts/build_features.py daily
APP_GIT_COMMIT=$(git rev-parse HEAD) python scripts/export_dataset.py daily_features --format csv --output-dir data/exports
```

## Phase 6.3A Weather Source And Region Audit

Phase 6.3A is a local diagnostics-only inventory for future weather features
for soybean and rapeseed/canola product families.

```bash
python scripts/audit_weather_sources.py
```

The command writes only:

```text
diagnostics/weather_source_audit/WEATHER_SOURCE_AUDIT_REPORT.md
diagnostics/weather_source_audit/weather_source_candidates.json
```

It does not write PostgreSQL rows, does not use production `RawStore`, does not
run collectors, does not add migrations, does not change schedulers, and does
not create ML targets. The first recommended source for a later controlled
prototype is Open-Meteo Historical Weather API with high-priority centroid
regions for Brazil, US, Argentina, Canada, and Ukraine/Black Sea crop-weather
signals.

Planned next steps are Phase 6.3B weather schema design, Phase 6.3C schema
implementation, Phase 6.3D first controlled weather collector, and Phase 6.3E
weather feature/export integration.

Phase 6.3B documents the future weather schema in
[docs/WEATHER_DATA_DESIGN.md](docs/WEATHER_DATA_DESIGN.md) and adds a draft SQL
file at `docs/sql_drafts/0012_weather_schema_draft.sql`. It is design-only: no
Alembic migration, no SQLAlchemy model changes, no collector, no scheduler
changes, no DB writes, no ML, and no targets. Planned next steps are Phase 6.3C
schema-only implementation, Phase 6.3D a controlled Open-Meteo weather
collector, and Phase 6.3E weather feature/export integration.

Phase 6.3C implements schema-only support for the weather layer: SQLAlchemy
metadata, Alembic revision `0012_weather_schema`, idempotent source seeds for
`open_meteo_historical_weather` and `nasa_power_weather`, 14 initial weather
region seeds, and operational report counts. It does not implement a weather
collector, does not write weather observation rows, does not change schedulers,
and does not add ML targets. Planned next steps are Phase 6.3D first controlled
Open-Meteo collector, Phase 6.3E weather daily aggregation/features, and Phase
6.3F weather integration into the product daily dataset/export.

Phase 6.3D adds the first manual-only Open-Meteo Historical Weather collector.
It uses the seeded `weather_regions`, bounded date ranges, production
`RawStore`, `raw_responses`, `weather_observations`, and weather quality checks.
It does not add a scheduler, does not change `daily_product_features`, and does
not create ML targets.

Run one region:

```bash
python scripts/run_collector.py open_meteo_historical_weather \
  --region br_mato_grosso_soybean \
  --from-date 2026-05-01 \
  --to-date 2026-05-10
```

Run all active regions for a small controlled range:

```bash
python scripts/run_collector.py open_meteo_historical_weather \
  --from-date 2026-05-01 \
  --to-date 2026-05-03
```

The collector currently limits one manual run to 45 inclusive days. Same
`source_id + region_id + observation_date + frequency` rows with the same
`source_record_hash` are skipped; changed hashes create
`weather_existing_observation_hash_changed` warnings and are not overwritten in
Phase 6.3D. Missing optional Open-Meteo variables are stored as `NULL` and
listed in `metadata_json`.

Phase 6.3E builds region-level weather aggregates from `weather_observations`
into `weather_daily_features`. It is a derived-feature step only: it does not
run weather collectors, does not change schedulers, does not modify product
daily features, and does not add ML targets.

```bash
python scripts/build_features.py weather_daily
python scripts/build_features.py weather_daily \
  --region br_mato_grosso_soybean \
  --from-date 2026-05-01 \
  --to-date 2026-05-10
```

The builder uses only `observation_date <= feature_date`, computes 7/14/30-day
rolling aggregates, heat-stress days at `temperature_2m_max >= 30C`, frost days
at `temperature_2m_min <= 0C`, first-version drought proxy as
`precipitation_30d_sum`, and growing degree days with base `10C` for soybean
regions and `5C` for rapeseed/canola regions. Incomplete early windows are
recorded in `missing_flags`.

Phase 6.3F integrates region-level weather aggregates into product-level
`daily_product_features` and the `daily_features` export. It adds Alembic
revision `0013_weather_features` with nullable product-weather columns,
idempotent equal-weight `product_weather_region_weights` seeds for soybean and
rapeseed/canola products, and leakage-safe weighted aggregation in
`python scripts/build_features.py daily`.

```bash
python -m app.db.seed
python scripts/build_features.py weather_daily
python scripts/build_features.py daily
APP_GIT_COMMIT=$(git rev-parse HEAD) python scripts/export_dataset.py daily_features --format csv --output-dir data/exports
```

The first version maps soybean products to Brazil, US, and Argentina soybean
regions, and rapeseed/canola products to Canada, France, and Ukraine/Black Sea
regions. Weights are equal within each product family and marked with
`role=production_weather_proxy`. The daily feature builder uses only active
weights effective for the product `feature_date`, only
`weather_daily_features.feature_date <= feature_date`, and only weather rows
whose `weather_as_of_date <= feature_date`. Missing or partial regional
coverage is recorded in `weather_missing_flags`; product weather columns remain
nullable.

Phase 6.3F is still not an ML phase. It does not add targets, does not add a
weather scheduler, does not run weather collectors automatically, and does not
change current price, FX, energy, benchmark, or historical collectors.

## Phase 6.4A News And Event Source Audit

Phase 6.4A is a local diagnostics-only inventory for future news and event
features. It maps event categories for agricultural commodity prices and reviews
candidate sources such as GDELT, official USDA/FAO/World Bank report releases,
ReliefWeb disaster feeds, Google News RSS-style search feeds, and paid news
APIs.

```bash
python scripts/audit_news_sources.py
```

The command writes only:

```text
diagnostics/news_source_audit/NEWS_SOURCE_AUDIT_REPORT.md
diagnostics/news_source_audit/news_source_candidates.json
```

It does not write PostgreSQL rows, does not use production `RawStore`, does not
run collectors, does not add migrations, does not change schedulers, does not
add ML targets, and does not add an NLP/LLM classifier. The recommended first
source for a later bounded prototype is GDELT 2.1 metadata, paired with a
low-noise official report/release event layer for USDA WASDE/PSD, FAO, and
World Bank releases.

Planned next steps are Phase 6.4B news/events schema design, Phase 6.4C schema
implementation, Phase 6.4D a first controlled news/report collector, Phase
6.4E rule-based event labeling, and Phase 6.4F daily news/event feature and
export integration.

Phase 6.4B documents the future news/events schema in
[docs/NEWS_EVENTS_DESIGN.md](docs/NEWS_EVENTS_DESIGN.md) and adds a draft SQL
file at `docs/sql_drafts/0014_news_events_schema_draft.sql`. It is design-only:
no Alembic migration, no SQLAlchemy model changes, no collector, no scheduler
changes, no DB writes, no ML, no targets, and no NLP/LLM classifier. Planned
next steps are Phase 6.4C schema-only implementation, Phase 6.4D a first
controlled GDELT/official-report collector, Phase 6.4E rule-based event
extraction, and Phase 6.4F daily news/event feature and export integration.

Phase 6.4C implements schema-only support for `news_articles`,
`commodity_events`, and `daily_news_features` through Alembic revision
`0014_news_events_schema`, SQLAlchemy metadata, idempotent seeds for
`gdelt_2_1`, `usda_reports`, `fao_news_releases`, and
`world_bank_commodity_releases`, and operational report counts. The new tables
are expected to be empty until a controlled news/report collector is added in a
later phase. Phase 6.4C does not add a collector, does not write news rows, does
not register a scheduler, does not add ML targets, and does not add an NLP/LLM
classifier.

Phase 6.4D adds the first manual-only GDELT news collector. It stores bounded
GDELT DOC article metadata in `news_articles`, stores raw evidence through the
normal `RawStore`/`raw_responses` path, and writes news-specific quality checks.
It does not write `commodity_events`, does not build `daily_news_features`, does
not add a scheduler, does not add ML targets, and does not add an NLP/LLM
classifier.

Run a small preset query:

```bash
python scripts/run_collector.py gdelt_news \
  --query-key soybean \
  --from-date 2026-06-01 \
  --to-date 2026-06-03 \
  --maxrecords 25
```

Run a bounded custom query:

```bash
python scripts/run_collector.py gdelt_news \
  --query "soybean oil export ban" \
  --from-date 2026-06-01 \
  --to-date 2026-06-03 \
  --maxrecords 25
```

Supported query presets are `soybean`, `rapeseed_canola`, `vegetable_oils`, and
`grain_oilseed_policy`. Phase 6.4D limits one request to 7 inclusive days and
`maxrecords <= 100`. Re-running the same source result skips unchanged articles;
same identity with changed metadata creates `news_existing_article_hash_changed`
quality warnings and is not overwritten in this phase.

Phase 6.4E adds deterministic rule-based event extraction from already stored
`news_articles` into `commodity_events`. It does not call GDELT or any external
news API, does not fetch article bodies, does not use ML/NLP/LLM classifiers,
does not build `daily_news_features`, and does not add a scheduler.

```bash
python scripts/extract_news_events.py --from-date 2026-06-01 --to-date 2026-06-03 --dry-run
python scripts/extract_news_events.py --from-date 2026-06-01 --to-date 2026-06-03 --source gdelt_2_1
python scripts/extract_news_events.py --from-date 2026-06-01 --to-date 2026-06-03 --article-id 123
```

The rule taxonomy covers `export_restriction`, `import_policy`,
`war_logistics_disruption`, `weather_disaster`, `crop_report`,
`biofuel_policy`, `energy_shock`, `currency_macro`, `demand_shock`, and
`supply_chain`. Commodity families are currently `soybean`, `rapeseed`,
`vegetable_oils`, `grains`, and `fertilizer_energy`.

Extraction is conservative and versioned with `extraction_method=keyword_rule`
and `extraction_version=news_event_rules_v1`. Re-running the same unchanged
article skips existing events. If the same event identity would be produced
from changed article text or rule output, the extractor writes
`commodity_event_existing_rule_hash_changed` as a warning and does not overwrite
the existing event.

Phase 6.4F builds product-level daily news/event aggregates and integrates them
into `daily_product_features` and export v1. It reads existing `news_articles`
and `commodity_events`; it does not call GDELT, does not run collectors, does
not add a scheduler, and does not add ML/NLP/LLM classification.

```bash
python scripts/build_features.py news_daily
python scripts/build_features.py news_daily --from-date 2026-06-01 --to-date 2026-06-10
python scripts/build_features.py news_daily --product soybean_oil --from-date 2026-06-01 --to-date 2026-06-10
python scripts/build_features.py daily
```

`news_daily` writes `daily_news_features` with 1/7/30-day article and event
counts, 7-day direction counts, 30-day event-category counts,
`sentiment_proxy_7d`, `news_as_of_date`, `missing_flags`, and metadata. The
daily product builder copies those fields into nullable `daily_product_features`
columns only when `news_as_of_date <= feature_date`; otherwise it leaves values
empty and records `news_missing_flags`.

## Phase 6.5A Trade Import Export Source Audit

Phase 6.5A is a local diagnostics-only inventory for future trade/import-export
features. It maps initial HS codes for soybean, soybean oil, soybean meal,
rapeseed/canola seed, rapeseed oil, rapeseed meal, and context commodities, and
evaluates candidate sources such as UN Comtrade, FAOSTAT, USDA FAS/GATS/PSD,
World Bank WITS, ITC Trade Map, Eurostat Comext, and national customs/stat
agencies.

```bash
python scripts/audit_trade_sources.py
```

Outputs:

```text
diagnostics/trade_source_audit/TRADE_SOURCE_AUDIT_REPORT.md
diagnostics/trade_source_audit/trade_source_candidates.json
```

This phase writes diagnostics only. It does not write PostgreSQL rows, does not
create a collector, does not use production `RawStore`, does not add migrations,
does not change schedulers, does not add ML targets, and performs no live API
probing. Current recommendation: use UN Comtrade as the first bounded prototype
candidate after schema design, with FAOSTAT as slower annual context and
USDA/FAS routes needing manual verification.

## Phase 6.5B Trade Import Export Schema Design

Phase 6.5B documents the future trade/import-export schema in
[docs/TRADE_DATA_DESIGN.md](docs/TRADE_DATA_DESIGN.md) and adds a draft SQL
file at `docs/sql_drafts/0016_trade_schema_draft.sql`. It is design-only: no
Alembic migration, no SQLAlchemy model changes, no collector, no scheduler
changes, no DB writes, no ML, and no targets.

The proposed future tables are `trade_commodity_codes`, `trade_flows`,
`product_trade_code_weights`, and `daily_trade_features`. The first future
collector candidate remains a narrow UN Comtrade monthly prototype for selected
HS codes and reporter/partner groups. Planned next steps are Phase 6.5C schema
implementation, Phase 6.5D first controlled UN Comtrade collector, and Phase
6.5E trade feature/export integration.

Phase 6.5C implements schema-only support for the trade/import-export layer:
SQLAlchemy metadata, Alembic revision `0016_trade_schema`, idempotent source
seeds for `un_comtrade`, `faostat_trade`, `usda_fas_trade`, and
`world_bank_wits`, core HS code seeds, direct first-version
`product_trade_code_weights`, and operational report counts. It does not add a
collector, does not write `trade_flows`, does not build `daily_trade_features`,
does not register a scheduler, and does not add ML targets.

Phase 6.5D adds the first controlled manual trade collector, `un_comtrade`.
It writes raw API payloads through `RawStore`, stores raw metadata in
`raw_responses`, and normalizes rows into `trade_flows`. It is manual-only and
has no scheduler.

```bash
python scripts/run_collector.py un_comtrade \
  --hs-code 1507 \
  --from-period 2024-01 \
  --to-period 2024-03 \
  --reporter BRA \
  --partner WLD \
  --flow export \
  --maxrecords 100
```

Supported first-pass HS codes are `1201`, `1507`, `2304`, `1205`, `1514`, and
`2306`. Supported controlled reporter/partner codes are `BRA`, `USA`, `ARG`,
`CAN`, `CHN`, and `WLD`; `WLD` is allowed only as partner. Phase 6.5D limits one
request to 3 monthly periods and `maxrecords <= 500`. Re-running unchanged rows
skips them. Same identity with changed normalized values writes
`trade_existing_flow_hash_changed` and does not overwrite in this phase.

`daily_trade_features`, dataset exports, ML targets, and scheduler integration
are intentionally not added in Phase 6.5D.

Phase 6.5E adds the daily trade feature layer and export integration. It builds
nullable `daily_trade_features` from monthly `trade_flows`, then the normal
daily product feature builder copies as-of-safe trade values into
`daily_product_features`.

```bash
python scripts/build_features.py trade_daily
python scripts/build_features.py trade_daily --product soybean_oil --from-date 2026-06-01 --to-date 2026-06-30
python scripts/build_features.py daily
```

The daily trade builder uses `product_trade_code_weights`, monthly
`trade_flows`, and strict availability dates (`published_at` date, falling back
to `fetched_at` date) so `trade_as_of_date` is never later than the feature
date. Export v1 now includes nullable trade columns such as `export_volume_1m`,
`import_volume_1m`, `net_export_volume_1m`, `trade_as_of_date`,
`reporting_lag_days`, and `trade_missing_flags`.

Phase 6.5E does not add ML targets, does not add scheduler jobs, and does not
run collectors by itself.

## Phase 6.6B Dataset Readiness Audit

Phase 6.6B is local-only documentation and audit tooling for the future
ML-ready `daily_features` dataset. It does not train ML, does not add targets,
does not run collectors, does not touch production PostgreSQL, and does not
change schedulers.

New dataset readiness docs:

- [docs/FEATURE_CATALOG.md](docs/FEATURE_CATALOG.md)
- [docs/DATASET_DICTIONARY.md](docs/DATASET_DICTIONARY.md)
- [docs/SOURCE_TO_FEATURE_LINEAGE.md](docs/SOURCE_TO_FEATURE_LINEAGE.md)
- [docs/LEAKAGE_AND_ASOF_AUDIT.md](docs/LEAKAGE_AND_ASOF_AUDIT.md)
- [docs/ML_READY_DATASET_AUDIT.md](docs/ML_READY_DATASET_AUDIT.md)

Run the local audit:

```bash
python scripts/audit_dataset_readiness.py
```

The script reads the export schema and docs, then writes diagnostics only:

```text
diagnostics/dataset_readiness/DATASET_READINESS_AUDIT_REPORT.md
diagnostics/dataset_readiness/dataset_readiness_audit.json
```

Diagnostics artifacts are runtime files and should not be committed.

## Phase 6.7A Supply-Demand Source Audit

Phase 6.7A is local-only diagnostics and source discovery for future
supply-demand, production, stocks, area, yield, crush, and official balance
features. It does not run collectors, does not write PostgreSQL rows, does not
create migrations, does not change schedulers, and does not add ML targets.

Run the local audit:

```bash
python scripts/audit_supply_demand_sources.py
```

The script uses a static curated registry and performs no HTTP requests. It
writes diagnostics only:

```text
diagnostics/supply_demand_source_audit/SUPPLY_DEMAND_SOURCE_AUDIT_REPORT.md
diagnostics/supply_demand_source_audit/supply_demand_source_candidates.json
```

The current recommended first source to investigate is USDA PSD / FAS PSD
Online, with a bounded oilseed/oil/meal prototype for soybeans, soybean oil,
soybean meal, rapeseed/canola, rapeseed oil, and rapeseed meal. FAOSTAT is a
reasonable annual context prototype later; WASDE, NASS, AMIS, Eurostat, IGC,
CONAB, Argentina, and Canada sources require source-specific manual checks or
licensing decisions before production automation.

Diagnostics artifacts are runtime files and should not be committed.

## Phase 6.7B Supply-Demand Schema Design

Phase 6.7B is design-only. It documents the future supply-demand /
production-stocks schema and SQL draft without changing SQLAlchemy models,
without creating an Alembic migration, without writing PostgreSQL rows, without
adding collectors, and without changing schedulers.

Design artifacts:

```text
docs/SUPPLY_DEMAND_DESIGN.md
docs/sql_drafts/0018_supply_demand_schema_draft.sql
```

The proposed future tables are `supply_demand_commodities`,
`supply_demand_observations`, `supply_demand_revisions`,
`product_supply_demand_weights`, and `daily_supply_demand_features`.
The first future source remains USDA PSD / FAS PSD Online. Do not apply the SQL
draft manually; Phase 6.7C should implement the reviewed schema through Alembic.

## Phase 6.7C Supply-Demand Schema

Phase 6.7C implements the reviewed supply-demand / production-stocks schema
only. It adds SQLAlchemy models, Alembic revision
`0018_supply_demand_schema`, idempotent source seeds, conservative
commodity/metric mapping seeds, direct product mapping weights, and
operational-report counts.

Created tables:

```text
supply_demand_commodities
supply_demand_observations
supply_demand_revisions
product_supply_demand_weights
daily_supply_demand_features
```

The seeded mappings intentionally mark exact USDA PSD codes as
`needs_verification`. Phase 6.7C does not implement a collector, does not write
observation rows, does not change `daily_product_features`, and does not change
exports or scheduler jobs.

## Phase 6.7D USDA PSD Collector

Phase 6.7D adds the first controlled/manual USDA PSD supply-demand collector:
`usda_psd`. It writes raw evidence through `RawStore`, records
`raw_responses`, and writes normalized rows to `supply_demand_observations`.
It does not add scheduler jobs, does not change `daily_product_features`, does
not change exports, and does not add ML targets.

The first implementation is intentionally conservative:

- supported commodity families: `soybean`, `soybean_oil`, `soybean_meal`,
  `rapeseed_canola`, `rapeseed_canola_oil`, `rapeseed_canola_meal`;
- supported concrete USDA PSD ZIP country codes: `US`, `BR`, `AR`, `CA`,
  `CH`, plus `EU` where present; `WLD` is accepted only as an explicit
  no-world-row request and is not synthesized from country rows;
- max marketing-year window: 3 years;
- default `--maxrecords`: 100, hard cap 500;
- source schema status: `needs_verification`.

Phase 6.9E uses the direct USDA PSD downloadable oilseeds ZIP contract:

```text
https://apps.fas.usda.gov/psdonline/downloads/psd_oilseeds_csv.zip
```

`--live-probe` fetches that bounded ZIP, stores it as raw evidence, and parses
the CSV inside it. The `PSDOnlineApi/api/downloadableData/GetDatasetContents`
route is intentionally not used because production validation showed it returns
downloadable dataset metadata, not PSD data rows. The discovered
`api/query/RunQuery` POST endpoint remains unused in this first collector.
Production validation also showed the direct ZIP is country-level: it has rows
for concrete USDA country codes such as `US`, `BR`, `AR`, `CA`, and `CH`, but
does not contain `WLD`, `R00`, or `World` aggregate rows. `WLD` therefore does
not fabricate data; world aggregation is deferred until the country set, metric
aggregation rules, stock-to-use formula, unit normalization, coverage policy,
and as-of behavior are explicitly designed.

Reviewed downloadable commodity codes:

- `4232000` -> `soybean_oil`
- `0813100` -> `soybean_meal`
- `4239100` -> `rapeseed_oil`
- `0813600` -> `rapeseed_meal`

Supported USDA PSD metrics are production, domestic consumption, food use, feed
use, crush, exports, imports, beginning stocks, ending stocks, stock-to-use,
planted area, harvested area, and yield. Phase 6.9K treats known PSD aggregate
or detail rows that are not current feature inputs, such as `total_supply`,
`total_distribution`, `industrial_dom._cons.`, `feed_waste_dom._cons.`, and
`extr._rate,_999.9999`, as expected skipped rows when supported rows are also
normalized. Invalid rows for supported metrics remain malformed-row warnings.
Review skip-reason summaries before starting any broad supply-demand backfill.

Run against a reviewed local fixture:

```bash
python scripts/run_collector.py usda_psd \
  --commodity-family soybean_oil \
  --from-marketing-year 2023 \
  --to-marketing-year 2023 \
  --country US \
  --fixture-file tests/fixtures/usda_psd/oilseeds_sample.csv
```

Opt in to a bounded live probe only when the USDA PSD endpoint contract has
been manually reviewed:

```bash
python scripts/run_collector.py usda_psd \
  --commodity-family soybean_oil \
  --from-marketing-year 2023 \
  --to-marketing-year 2023 \
  --country US \
  --maxrecords 100 \
  --live-probe
```

The collector rejects scheduled runs. Duplicate rows are idempotent. If an
existing identity is found with a changed `source_record_hash`, the collector
writes a quality warning and does not overwrite the stored observation.

## Phase 6.7E Daily Supply-Demand Features

Phase 6.7E adds the local daily supply-demand feature layer and export
integration. It builds nullable `daily_supply_demand_features` from
`supply_demand_observations` and `product_supply_demand_weights`, then the
normal daily product feature builder copies as-of-safe supply-demand values into
`daily_product_features`.

```bash
python scripts/build_features.py supply_demand_daily
python scripts/build_features.py supply_demand_daily --product soybean_oil --from-date 2026-06-01 --to-date 2026-06-30
python scripts/build_features.py daily
```

The supply-demand daily builder uses `report_published_at` date, falling back
to `published_at` date and then `fetched_at` date, so
`supply_demand_as_of_date` is never later than the feature date. Forecast
revision fields compare only previous eligible report vintages. Export v1 now
includes nullable supply-demand columns such as `production_volume`,
`domestic_consumption`, `ending_stocks`, `stock_to_use_ratio`,
`production_forecast_revision`, `supply_demand_as_of_date`,
`supply_demand_reporting_lag_days`, and `supply_demand_missing_flags`.

Phase 6.9I keeps strict as-of behavior and aligns the default
`supply_demand_daily` build window with newly available supply-demand report
dates. If a USDA report is fetched on `2026-06-16`, feature dates before that
day remain empty and are marked with
`supply_demand_observations_after_feature_date_window`; the `2026-06-16` row
and later rows may safely use the observation.

Phase 6.9P adds a country-aware aggregation engine: real `WLD` rows still have
priority, and additive country rows can be aggregated only when an explicit
country basket is configured. Phase 6.9Q adds a local proposal generator for
reviewed country weights. Phase 6.9S/6.9T adds global basket discovery and a
draft governance policy in `docs/SUPPLY_DEMAND_GLOBAL_BASKET_POLICY.md`.
Country weights remain disabled unless they are part of reviewed config; CA
probing remains paused.

Phase 6.9U adds a local reviewed Tier A `soybean_oil` basket config:

- enabled metrics in config: `production_volume`, `crush_volume`,
  `domestic_consumption`, `exports_volume`;
- policy version: `supply_demand_global_basket_v1`;
- runtime availability threshold: `0.75` of approved selected basket weight;
- real `WLD` rows still override baskets;
- Tier B/C metrics, direct `stock_to_use_ratio` weighting, CA probing, seed
  data, production rebuild, and scheduler changes remain deferred.

The config is explicit in code and tested locally, but production export values
do not change until a later approved deploy and feature rebuild.

Phase 6.9X makes the reviewed Tier A config the default for the ordinary local
command `python scripts/build_features.py supply_demand_daily`. No CLI option
or environment variable is required. WLD precedence, partial/insufficient
coverage rules, and explicit overrides remain intact; Tier B/C metrics and CA
remain disabled. Production is unchanged until a separate approved deploy and
rebuild.

Phase 6.9V-L adds a pure local readiness audit and bounded plan generator:

```bash
python scripts/audit_supply_demand_basket_readiness.py \
  --input /tmp/supply_demand_inventory.json \
  --output /tmp/tier_a_readiness.json \
  --product-code soybean_oil \
  --commodity-family soybean_oil \
  --audit-as-of-date 2026-06-19 \
  --required-marketing-years 2023 \
  --audit-scope local_fixture \
  --format json
```

It has no DB access and does not run collection. `local_fixture` is synthetic
only; production deployment remains blocked until a later read-only
`production_inventory_export` audit confirms coverage or yields an approved
bounded backfill plan. See
[`docs/SUPPLY_DEMAND_BASKET_READINESS_AUDIT.md`](docs/SUPPLY_DEMAND_BASKET_READINESS_AUDIT.md).

Phase 6.9V-P adds a pure local Tier A source-contract audit for the current
USDA PSD oilseeds ZIP:

```bash
python scripts/audit_usda_psd_tier_a_source_contract.py \
  --zip-path /tmp/cdb-tier-a-usda-contract/psd_oilseeds_csv.zip \
  --output /tmp/cdb-tier-a-usda-contract/tier_a_source_contract.json \
  --product-code soybean_oil \
  --marketing-years 2021,2022,2023 \
  --format json
```

It checks raw availability and current pure parser mappings only. It has no DB
or collector orchestration access, excludes CA and Tier B/C metrics, and does
not prove production inventory or authorize a backfill. See
[`docs/USDA_PSD_TIER_A_SOURCE_CONTRACT_AUDIT.md`](docs/USDA_PSD_TIER_A_SOURCE_CONTRACT_AUDIT.md).

```bash
python scripts/propose_supply_demand_country_weights.py \
  --input /tmp/historical_supply_demand.json \
  --output /tmp/soybean_oil_weight_proposal.json \
  --product-code soybean_oil \
  --commodity-family soybean_oil \
  --effective-as-of-date 2024-01-15 \
  --completed-marketing-year 2022 \
  --lookback-years 3 \
  --candidate-countries US,BR,AR,CA
```

Generated proposal files are runtime artifacts and should not be committed.

Phase 6.7E does not add ML targets, does not add scheduler jobs, and does not
run collectors by itself. Server execution remains a later controlled batch.

## Next Phase

After Phase 6.7E, the next recommended step is a controlled server batch:
deploy the local code, apply the migration, run `supply_demand_daily`, rebuild
daily features, export `daily_features`, and validate reports. Do not start ML
or target engineering before that production export is checked.
