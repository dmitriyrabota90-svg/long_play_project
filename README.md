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
- failed quality checks for the last 24 hours;
- products without a fresh price;
- raw storage status;
- database status.

## Operational Report

Use the wider operational report:

```bash
python scripts/operational_report.py
python scripts/operational_report.py --freshness-hours 12
```

It includes database status, app version, DB URL setting, collector run counts, latest success/partial/error runs, raw/price/quality counts for the last 24 hours, stale products, and sizes of `data/raw`, `data/exports`, and `logs`.

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

Create a skeleton export manifest:

```bash
python scripts/export_dataset.py
```

This creates:

```text
data/exports/{timestamp}/dataset_manifest.json
```

Real CSV and Parquet exports will be added later.

## Adding a Collector

1. Add a class under `app/collectors/`.
2. Inherit from `BaseCollector`.
3. Store every raw response through `RawStore`.
4. Insert a `collector_runs` row for every run.
5. Insert a `raw_responses` row for every fetched payload.
6. Normalize data into dedicated tables with `raw_response_id`.
7. Add data quality checks before scheduling the collector.

Collectors must not use future data to build features. Feature availability must be controlled through `fetched_at`, `published_at`, and `as_of_at`.

## Backup Skeleton

Current backup script only prints the planned steps:

```bash
python scripts/backup.py
```

Future implementation should include PostgreSQL dumps, raw-data backups, export backups, checksum verification, and retention policy.

## Next Phase

The next phase is to harden the current-price collector in production: observe live failures, add source-specific schema-change checks, then decide whether to schedule it automatically.
