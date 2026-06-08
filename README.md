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
- Safe scheduler skeleton with health and quality-check placeholder jobs.
- `current_price_source` collector for the first current-price instruments.
- Health-check helper.
- Dataset export manifest skeleton.
- CLI scripts.
- Minimal pytest tests.

Not implemented yet:

- News, weather, FX, benchmark, and fundamental collectors.
- Feature builder logic.
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

Use the quality summary CLI to review checks without treating `pass` or `skip` rows as failures:

```bash
python scripts/quality_summary.py
python scripts/quality_summary.py --limit 50
```

The CLI prints total checks, checks by status, checks by severity, problematic checks, latest problematic checks, and a conclusion of `ok`, `warning`, or `error`. Statuses `pass` and `skip` are successful; any other status is considered problematic. When the problematic count is zero, the output includes `quality checks ok`.

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
not create ML targets, and does not add news, weather, or benchmarks. Export
payload files in `data/exports/` are runtime artifacts and must not be
committed. Set `APP_GIT_COMMIT=$(git rev-parse HEAD)` when exporting from
Docker so the manifest records the deployed commit. See
[docs/DATASET_EXPORT.md](docs/DATASET_EXPORT.md).

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

Next step after controlled runs: Phase 6.1E should decide how energy factors
join into features and exports without changing historical as-of semantics.

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

## Next Phase

The next phase is to let collection continue for a few days, audit the exported
feature dataset, and then decide whether the daily feature builder needs its own
controlled scheduler.
