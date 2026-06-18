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

`pass`, `skip`, and `info` are successful quality statuses. Other statuses are
classified as active failures, known historical incidents, or expected
diagnostic incidents. The CLI returns `ok`, `ok_with_known_incidents`, or
`error`; old checks stay in the database and remain visible in the report.

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

Export v1 includes current snapshot, CBR FX, FRED energy, and World Bank
benchmark features already materialized in `daily_product_features`. It excludes
`historical_price_bars`, `historical_price_bar_revisions`, news, weather,
sunflower products, and ML targets.

After Phase 6.0, export v1 also includes deterministic calendar/seasonality
columns derived from `feature_date`.

## Energy Source Discovery Deployment

Phase 6.1A is a diagnostics-only audit for future energy/oil factor sources. It
does not run production collectors, write PostgreSQL rows, save production raw
responses, apply migrations, change schedulers, or train ML models.

Run it manually after deploying the tooling:

```bash
cd /data1/long_play_project
docker compose run --rm app python scripts/audit_energy_sources.py
```

Outputs are runtime diagnostics:

```text
diagnostics/energy_source_audit/ENERGY_SOURCE_AUDIT_REPORT.md
diagnostics/energy_source_audit/energy_source_candidates.json
```

Do not commit diagnostics artifacts. The recommended first future production
prototype is FRED/EIA-derived CSV for Brent, WTI, Henry Hub natural gas, and US
diesel proxy. EIA Open Data, World Bank Pink Sheet, Stooq, Nasdaq Data Link, and
unofficial finance endpoints require separate schema/access/licensing review
before any collector is added.

## Energy Prices Schema Design

Phase 6.1B adds only design artifacts for a future `energy_prices` table:

```text
docs/ENERGY_PRICES_DESIGN.md
docs/sql_drafts/0008_energy_prices_draft.sql
```

The SQL file is a draft only and must not be applied manually. This phase does
not run migrations, create the table, change SQLAlchemy models, write
PostgreSQL rows, run collectors, or change scheduler settings.

Expected next phases:

- Phase 6.1C: schema migration.
- Phase 6.1D: first controlled FRED energy collector.
- Phase 6.1E: energy features/export integration.

## Energy Prices Schema Deployment

Phase 6.1C adds the non-destructive Alembic revision `0008_energy_prices`.
Deploy it like other schema-only migrations:

```bash
cd /data1/long_play_project
git pull
docker compose build app
docker compose up -d app
docker compose run --rm app alembic upgrade head
docker compose run --rm app python -m app.db.seed
```

Expected verification:

```sql
SELECT * FROM alembic_version;
SELECT COUNT(*) AS energy_prices_count FROM energy_prices;
SELECT code, name, is_active FROM sources WHERE code = 'fred_energy_prices';
```

`energy_prices_count` should be `0` until the Phase 6.1D controlled FRED
collector is deployed and deliberately run. This schema deployment must not run
collectors, change schedulers, rebuild features, or export datasets.

## FRED Energy Prices Collector Deployment

Phase 6.1D adds `fred_energy_prices`, a manual-only collector for bounded FRED
CSV energy series. It uses source `fred_energy_prices`, stores raw CSV under
`data/raw/fred_energy_prices/...`, creates `raw_responses`, and writes
normalized rows to `energy_prices`. It has no scheduler.

Timeouts are controlled by:

```env
FRED_ENERGY_TIMEOUT_SECONDS=30
```

The collector passes `cosd/coed` to FRED when a date range is supplied and makes
only one retry for transient timeout/connection errors. Repeated failures should
be treated as source/network instability, not as a reason to loop aggressively.

Deploy reviewed code as usual:

```bash
cd /data1/long_play_project
git pull
docker compose build app
docker compose up -d app
docker compose ps
```

Run the first controlled range:

```bash
docker compose run --rm app python scripts/run_collector.py fred_energy_prices --from-date 2026-05-20 --to-date 2026-06-05
```

Run the same command once more to verify idempotency. The retry should report
`records_written=0`, `skipped_existing>0`, `conflicts_count=0`, and
`errors_count=0`.

The collector currently supports:

```text
DCOILBRENTEU  Brent crude oil           daily   USD/barrel
DCOILWTICO    WTI crude oil             daily   USD/barrel
DHHNGSP       Henry Hub natural gas     daily   USD/MMBtu
GASDESW       US diesel proxy           weekly  source_unit
```

Verify:

```sql
SELECT instrument_code, instrument_category, frequency, COUNT(*) AS rows_count,
       MIN(period_start) AS first_period, MAX(period_start) AS last_period,
       MIN(value) AS min_value, MAX(value) AS max_value
FROM energy_prices
GROUP BY instrument_code, instrument_category, frequency
ORDER BY instrument_code;

SELECT source_id, instrument_code, frequency, period_start, period_end, COUNT(*)
FROM energy_prices
GROUP BY source_id, instrument_code, frequency, period_start, period_end
HAVING COUNT(*) > 1;

SELECT COUNT(*) AS rows_without_raw_response
FROM energy_prices
WHERE raw_response_id IS NULL;
```

Do not run `current_price_source`, `cbr_fx`, `jijinhao_historical_prices`,
feature rebuilds, migrations, or exports as part of this controlled energy
collector verification. Do not add an energy scheduler in Phase 6.1D.

## Energy Features Deployment

Phase 6.1E adds nullable energy feature columns to `daily_product_features`
through Alembic revision `0009_energy_features`. The migration does not move
data and does not run collectors. Deploy reviewed code, then apply the migration:

```bash
docker compose run --rm app alembic upgrade head
```

Rebuild daily features manually after the migration:

```bash
docker compose run --rm app python scripts/build_features.py daily
```

The feature builder uses only existing rows in `energy_prices`. For every
feature date it selects the latest FRED row with
`energy_prices.period_start <= feature_date`, so future energy values are not
used. Weekly diesel is forward-filled by the same rule. Missing energy values are
stored in `energy_missing_flags`; this is not a scheduler or health failure.

Check fill rates and leakage:

```sql
SELECT COUNT(*) AS rows_total,
       COUNT(energy_brent_usd_per_barrel) AS brent_filled,
       COUNT(energy_wti_usd_per_barrel) AS wti_filled,
       COUNT(energy_henry_hub_usd_mmbtu) AS henry_filled,
       COUNT(energy_diesel_proxy_value) AS diesel_filled,
       COUNT(energy_missing_flags) AS missing_flags_filled
FROM daily_product_features;

SELECT product_id, feature_date, energy_brent_as_of_date, energy_wti_as_of_date,
       energy_henry_hub_as_of_date, energy_diesel_as_of_date
FROM daily_product_features
WHERE energy_brent_as_of_date > feature_date
   OR energy_wti_as_of_date > feature_date
   OR energy_henry_hub_as_of_date > feature_date
   OR energy_diesel_as_of_date > feature_date;
```

Export v1 includes the energy columns after the rebuild:

```bash
APP_GIT_COMMIT=$(git rev-parse HEAD) docker compose run --rm -e APP_GIT_COMMIT app \
  python scripts/export_dataset.py daily_features --format csv --output-dir data/exports
```

Do not run energy collectors, current-price collectors, CBR FX, historical
collectors, or feature scheduler changes as part of this migration unless a
separate controlled step explicitly asks for it.

## Commodity Benchmark Source Audit

Phase 6.2A is local-only discovery for future global commodity benchmark
sources. It creates diagnostics artifacts only:

```bash
python scripts/audit_commodity_benchmarks.py
```

Outputs:

```text
diagnostics/commodity_benchmark_audit/COMMODITY_BENCHMARK_AUDIT_REPORT.md
diagnostics/commodity_benchmark_audit/commodity_benchmark_candidates.json
```

This phase does not write PostgreSQL rows, does not run collectors, does not add
migrations, does not change schedulers, and does not require production deploy.
The recommended next phase is schema design for `commodity_benchmarks`.

Phase 6.2B is that design-only step. It adds:

```text
docs/COMMODITY_BENCHMARKS_DESIGN.md
docs/sql_drafts/0010_commodity_benchmarks_draft.sql
```

Do not apply the SQL draft manually. It is not an Alembic migration and does not
change production. The next deployable step should be Phase 6.2C schema-only
implementation, followed later by Phase 6.2D controlled World Bank Pink Sheet
collection and Phase 6.2E benchmark feature/export integration.

Phase 6.2C adds Alembic revision `0010_commodity_benchmarks`, the
`CommodityBenchmark` SQLAlchemy model, idempotent `world_bank_pink_sheet` and
`fao_price_indices` source seeds, and operational report counts. The initial
schema already included a small `commodity_benchmarks` skeleton table; this
migration expands it to the reviewed benchmark schema. After a later approved
deploy, the table should still be empty until a controlled collector is run. Do
not run benchmark collectors in Phase 6.2C; Phase 6.2D is the future controlled
World Bank collector.

Phase 6.2D implements that controlled `world_bank_pink_sheet` collector. It is
manual-only and has no scheduler. It downloads the official World Bank Pink
Sheet monthly XLSX, stores raw evidence in `data/raw/world_bank_pink_sheet/...`,
writes one `raw_responses` row per run, and writes normalized monthly benchmark
rows into `commodity_benchmarks`.

```bash
docker compose run --rm app python scripts/run_collector.py world_bank_pink_sheet --benchmark world_bank_soybean_oil --from-date 2024-01-01 --to-date 2026-06-01
docker compose run --rm app python scripts/run_collector.py world_bank_pink_sheet --from-date 2024-01-01 --to-date 2026-06-01
```

Supported benchmark codes are `world_bank_soybean_oil`, `world_bank_soybeans`,
`world_bank_palm_oil`, `world_bank_maize`, `world_bank_wheat`, and
`world_bank_fertilizer_index`. Re-running the same source data skips existing
rows; changed values for an existing business key produce
`commodity_benchmark_existing_record_hash_changed` and are not overwritten in
Phase 6.2D. Phase 6.2D itself does not add a benchmark scheduler, daily feature
integration, or ML targets.

Phase 6.2E adds nullable World Bank benchmark columns to
`daily_product_features` through Alembic revision `0011_benchmark_features`.
The migration does not run collectors and does not move existing data. Deploy
reviewed code, then apply the migration:

```bash
docker compose run --rm app alembic upgrade head
```

Rebuild daily features manually after the migration:

```bash
docker compose run --rm app python scripts/build_features.py daily
```

The feature builder uses only existing rows in `commodity_benchmarks`. For every
feature date it selects the latest monthly World Bank row with
`commodity_benchmarks.period_start <= feature_date`, forward-fills values, and
computes 1-month and 3-month deltas by calendar month. Missing configured
benchmark series are stored in `benchmark_missing_flags`; this is not a
scheduler or health failure.

Check benchmark fill rates and leakage:

```sql
SELECT COUNT(*) AS rows_total,
       COUNT(benchmark_soybean_oil_value) AS soybean_oil_filled,
       COUNT(benchmark_soybeans_value) AS soybeans_filled,
       COUNT(benchmark_palm_oil_value) AS palm_oil_filled,
       COUNT(benchmark_maize_value) AS maize_filled,
       COUNT(benchmark_wheat_value) AS wheat_filled,
       COUNT(benchmark_fertilizer_index_value) AS fertilizer_filled,
       COUNT(benchmark_missing_flags) AS missing_flags_filled
FROM daily_product_features;

SELECT product_id, feature_date, benchmark_soybean_oil_as_of_date,
       benchmark_soybeans_as_of_date, benchmark_palm_oil_as_of_date,
       benchmark_maize_as_of_date, benchmark_wheat_as_of_date,
       benchmark_fertilizer_index_as_of_date
FROM daily_product_features
WHERE benchmark_soybean_oil_as_of_date > feature_date
   OR benchmark_soybeans_as_of_date > feature_date
   OR benchmark_palm_oil_as_of_date > feature_date
   OR benchmark_maize_as_of_date > feature_date
   OR benchmark_wheat_as_of_date > feature_date
   OR benchmark_fertilizer_index_as_of_date > feature_date;
```

Export v1 includes benchmark columns after the rebuild:

```bash
APP_GIT_COMMIT=$(git rev-parse HEAD) docker compose run --rm -e APP_GIT_COMMIT app \
  python scripts/export_dataset.py daily_features --format csv --output-dir data/exports
```

Do not run current-price collectors, CBR FX, historical collectors, benchmark
collectors, or scheduler changes as part of this migration unless a separate
controlled step explicitly asks for it.

## Weather Source And Region Audit

Phase 6.3A is local-only discovery for future weather regions and source
candidates. It creates diagnostics artifacts only:

```bash
python scripts/audit_weather_sources.py
```

Outputs:

```text
diagnostics/weather_source_audit/WEATHER_SOURCE_AUDIT_REPORT.md
diagnostics/weather_source_audit/weather_source_candidates.json
```

This phase does not write PostgreSQL rows, does not run collectors, does not add
migrations, does not change schedulers, does not use production `RawStore`, and
does not require production deploy. The recommended next phase is weather schema
design for `weather_regions`, `weather_observations`, and future weather-derived
daily feature tables. Later phases should implement schema, then a controlled
Open-Meteo prototype, then feature/export integration.

Phase 6.3B is that design-only step. It adds:

```text
docs/WEATHER_DATA_DESIGN.md
docs/sql_drafts/0012_weather_schema_draft.sql
```

Do not apply the SQL draft manually. It is not an Alembic migration and does not
change production. The next deployable step should be Phase 6.3C schema-only
implementation, followed later by Phase 6.3D controlled Open-Meteo collection
and Phase 6.3E weather feature/export integration.

Phase 6.3C adds Alembic revision `0012_weather_schema`, weather SQLAlchemy
models, Open-Meteo/NASA source seeds, initial weather region seeds, and
operational report counts. It is still schema-only: do not run weather
collectors, do not add a weather scheduler, and do not expect
`weather_observations` or `weather_daily_features` to contain rows until later
controlled phases. The next steps are Phase 6.3D controlled Open-Meteo
collection, Phase 6.3E weather aggregation/features, and Phase 6.3F product
daily dataset/export integration.

Phase 6.3D adds a manual-only Open-Meteo Historical Weather collector:

```bash
docker compose run --rm app python scripts/run_collector.py open_meteo_historical_weather \
  --region br_mato_grosso_soybean \
  --from-date 2026-05-01 \
  --to-date 2026-05-10
```

For a small all-region check:

```bash
docker compose run --rm app python scripts/run_collector.py open_meteo_historical_weather \
  --from-date 2026-05-01 \
  --to-date 2026-05-03
```

This collector writes raw evidence through `RawStore`, normalized rows to
`weather_observations`, and quality checks. It is capped at 45 inclusive days
per manual run, skips exact duplicate rows, and warns without overwrite on
changed existing hashes. It has no scheduler, does not rebuild daily features,
does not write weather-derived product features, and does not add ML targets.
The next safe step is Phase 6.3E weather daily aggregation from
`weather_observations`.

Phase 6.3E adds local/manual aggregation from `weather_observations` into
`weather_daily_features`:

```bash
docker compose run --rm app python scripts/build_features.py weather_daily
docker compose run --rm app python scripts/build_features.py weather_daily \
  --region br_mato_grosso_soybean \
  --from-date 2026-05-01 \
  --to-date 2026-05-10
```

The aggregation is idempotent by `(region_id, feature_date)`, records missing
early-window flags, and uses no future observations. It does not run collectors,
does not add a weather scheduler, does not rebuild product daily features, and
does not add ML targets. Product-level weather feature/export integration is a
later Phase 6.3F decision.

Phase 6.3F adds product-level weather columns to `daily_product_features`
through Alembic revision `0013_weather_features`, seeds first-version
equal product-region weather weights, and includes those weather columns in
the `daily_features` export. Apply this migration only during a reviewed
deploy:

```bash
docker compose run --rm app alembic upgrade head
docker compose run --rm app python -m app.db.seed
docker compose run --rm app python scripts/build_features.py weather_daily
docker compose run --rm app python scripts/build_features.py daily
APP_GIT_COMMIT=$(git rev-parse HEAD) docker compose run --rm -e APP_GIT_COMMIT app \
  python scripts/export_dataset.py daily_features --format csv --output-dir data/exports
```

The product weather fields are nullable. The builder uses only active/effective
`product_weather_region_weights`, only `weather_daily_features.feature_date <=
feature_date`, and only weather rows whose `weather_as_of_date <= feature_date`.
Partial or absent regional coverage is recorded in `weather_missing_flags`.
Phase 6.3F does not add a weather scheduler, does not run weather collectors
automatically, does not change current price/FX/energy/benchmark collectors,
and does not add ML targets.

## News And Event Source Audit

Phase 6.4A is local-only discovery/design for future news and event sources. It
creates diagnostics artifacts only:

```bash
python scripts/audit_news_sources.py
```

Outputs:

```text
diagnostics/news_source_audit/NEWS_SOURCE_AUDIT_REPORT.md
diagnostics/news_source_audit/news_source_candidates.json
```

This phase does not write PostgreSQL rows, does not run collectors, does not add
migrations, does not change schedulers, does not use production `RawStore`, and
does not require production deploy. It also does not add ML targets or an
NLP/LLM classifier. The recommended next phase is news/events schema design for
future `news_articles`, `commodity_events`, and `daily_news_features` tables or
feature layers. Later phases should implement schema, then a controlled
official-report/GDELT metadata prototype, then event labeling and feature/export
integration.

Phase 6.4B is that design-only step. It adds:

```text
docs/NEWS_EVENTS_DESIGN.md
docs/sql_drafts/0014_news_events_schema_draft.sql
```

Do not apply the SQL draft manually. It is not an Alembic migration and does not
change production. The next deployable step should be Phase 6.4C schema-only
implementation, followed later by Phase 6.4D controlled GDELT/official-report
collection, Phase 6.4E rule-based event extraction, and Phase 6.4F news/event
feature/export integration. Phase 6.4B does not add collectors, schedulers, ML
targets, or NLP/LLM classifiers.

Phase 6.4C adds Alembic revision `0014_news_events_schema`, SQLAlchemy models
for `news_articles`, `commodity_events`, and `daily_news_features`, idempotent
source seeds for `gdelt_2_1`, `usda_reports`, `fao_news_releases`, and
`world_bank_commodity_releases`, and operational report counts. It is still
schema-only: do not run news collectors, do not add a news scheduler, and do
not expect the news/event tables to contain rows until later controlled phases.
The next steps are Phase 6.4D controlled GDELT/news collection, Phase 6.4E
rule-based event extraction, and Phase 6.4F daily feature/export integration.

Phase 6.4D adds a manual-only GDELT DOC article metadata collector named
`gdelt_news`. It writes raw API responses through `RawStore`, links
`raw_responses`, and inserts normalized article metadata into `news_articles`.
It does not write `commodity_events`, does not build `daily_news_features`, does
not add a scheduler, and does not add ML/NLP/LLM classification.

Run only small controlled windows:

```bash
docker compose run --rm app python scripts/run_collector.py gdelt_news \
  --query-key soybean \
  --from-date 2026-06-01 \
  --to-date 2026-06-03 \
  --maxrecords 25
```

Supported query presets are `soybean`, `rapeseed_canola`, `vegetable_oils`, and
`grain_oilseed_policy`. The first collector limits one request to 7 inclusive
days and `maxrecords <= 100`. Same identity with unchanged metadata is skipped;
changed metadata creates `news_existing_article_hash_changed` quality warnings
and is not overwritten.

Useful checks after a controlled run:

```sql
SELECT source_name, language, COUNT(*) AS rows_count,
       MIN(published_at) AS first_published_at,
       MAX(published_at) AS last_published_at
FROM news_articles
GROUP BY source_name, language
ORDER BY rows_count DESC, source_name;

SELECT source_id, article_hash, COUNT(*)
FROM news_articles
GROUP BY source_id, article_hash
HAVING COUNT(*) > 1;

SELECT COUNT(*) AS rows_without_raw_response
FROM news_articles
WHERE raw_response_id IS NULL;
```

The next steps are Phase 6.4E rule-based event extraction from `news_articles`
and Phase 6.4F daily feature/export integration. Do not add a news scheduler or
ML classifier during Phase 6.4D rollout.

Phase 6.4E adds a deterministic local/manual extractor from existing
`news_articles` into `commodity_events`. It does not call GDELT or any external
news API, does not fetch article bodies, does not build `daily_news_features`,
does not add a scheduler, and does not use ML/NLP/LLM classification.

Dry-run a bounded date window:

```bash
docker compose run --rm app python scripts/extract_news_events.py \
  --from-date 2026-06-01 \
  --to-date 2026-06-03 \
  --dry-run
```

Write deterministic events for a source/date window:

```bash
docker compose run --rm app python scripts/extract_news_events.py \
  --from-date 2026-06-01 \
  --to-date 2026-06-03 \
  --source gdelt_2_1
```

Inspect results:

```sql
SELECT event_category, commodity_family, COUNT(*) AS rows_count,
       MIN(event_date) AS first_event_date,
       MAX(event_date) AS last_event_date
FROM commodity_events
GROUP BY event_category, commodity_family
ORDER BY event_category, commodity_family;

SELECT source_id, news_article_id, event_category, commodity_family,
       country, region, event_date, extraction_method, COUNT(*)
FROM commodity_events
GROUP BY source_id, news_article_id, event_category, commodity_family,
         country, region, event_date, extraction_method
HAVING COUNT(*) > 1;
```

The extractor writes quality checks for article text, category/family detection,
event date, confidence, source text hash, inserts, and rule-hash conflicts.
Existing events are never overwritten silently. Phase 6.4E still does not update
export v1 or `daily_product_features`; that is reserved for Phase 6.4F.

Phase 6.4F adds local/manual daily news/event feature aggregation and export
integration. It reads already stored `news_articles` and `commodity_events`;
it does not call GDELT, does not run news collectors, does not add a scheduler,
and does not use ML/NLP/LLM classification.

Build product-level news/event aggregates:

```bash
docker compose run --rm app python scripts/build_features.py news_daily
docker compose run --rm app python scripts/build_features.py news_daily \
  --from-date 2026-06-01 \
  --to-date 2026-06-10
```

Then rebuild daily product features when the news aggregates should appear in
export v1:

```bash
docker compose run --rm app python scripts/build_features.py daily
```

Useful checks:

```sql
SELECT p.code, dnf.feature_date, dnf.news_count_7d, dnf.event_count_7d,
       dnf.sentiment_proxy_7d, dnf.news_as_of_date, dnf.missing_flags
FROM daily_news_features dnf
JOIN products p ON p.id = dnf.product_id
ORDER BY dnf.feature_date DESC, p.code
LIMIT 40;

SELECT product_id, feature_date, news_as_of_date
FROM daily_news_features
WHERE news_as_of_date > feature_date
LIMIT 20;
```

Export v1 now includes nullable product-level news/event columns. Missing or
partial coverage is normal early in rollout and is recorded through
`news_missing_flags`.

## Trade Import Export Source Audit

Phase 6.5A is local-only discovery/design for future trade/import-export
sources and HS/source-code mappings. It creates diagnostics artifacts only:

```bash
python scripts/audit_trade_sources.py
```

Outputs:

```text
diagnostics/trade_source_audit/TRADE_SOURCE_AUDIT_REPORT.md
diagnostics/trade_source_audit/trade_source_candidates.json
```

This phase does not write PostgreSQL rows, does not run collectors, does not add
migrations, does not change schedulers, does not use production `RawStore`, and
does not require production deploy. It also does not add ML targets. The
recommended next phase is Phase 6.5B trade/import-export schema design for
future `trade_commodity_codes`, `trade_flows`, and trade feature tables. Later
phases should implement schema, then a controlled narrow UN Comtrade prototype,
then trade feature/export integration.

Phase 6.5B is that design-only step. It adds:

```text
docs/TRADE_DATA_DESIGN.md
docs/sql_drafts/0016_trade_schema_draft.sql
```

Do not apply the SQL draft manually. It is not an Alembic migration and does not
change production. The proposed future tables are `trade_commodity_codes`,
`trade_flows`, `product_trade_code_weights`, and `daily_trade_features`.
Planned next steps are Phase 6.5C schema-only implementation, Phase 6.5D a
controlled narrow UN Comtrade collector, and Phase 6.5E trade feature/export
integration. Phase 6.5B does not add collectors, schedulers, DB writes, ML
targets, or dataset targets.

Phase 6.5C adds Alembic revision `0016_trade_schema`, SQLAlchemy models for
`trade_commodity_codes`, `trade_flows`, `product_trade_code_weights`, and
`daily_trade_features`, idempotent source seeds for UN Comtrade, FAOSTAT trade,
USDA FAS trade, and World Bank WITS, plus core HS code seeds and direct
product-code weights. It is still schema-only: do not run trade collectors, do
not add a trade scheduler, and do not expect `trade_flows` or
`daily_trade_features` to contain rows until later controlled phases.

After a reviewed deploy of Phase 6.5C, apply the migration and seed only:

```bash
docker compose run --rm app alembic upgrade head
docker compose run --rm app python -m app.db.seed
```

The next steps are Phase 6.5D controlled UN Comtrade collection and Phase 6.5E
trade feature/export integration.

Phase 6.5E adds Alembic revision `0017_trade_features`, the
`trade_daily` feature builder, product-level trade columns in
`daily_product_features`, and export/operational-report integration.

Local/manual commands:

```bash
python scripts/build_features.py trade_daily
python scripts/build_features.py trade_daily --product soybean_oil --from-date 2026-06-01 --to-date 2026-06-30
python scripts/build_features.py daily
python scripts/export_dataset.py daily_features --format csv --output-dir data/exports
```

After a reviewed server deploy, apply migrations before rebuilding features:

```bash
docker compose run --rm app alembic upgrade head
docker compose run --rm app python scripts/build_features.py trade_daily
docker compose run --rm app python scripts/build_features.py daily
```

These are manual commands only. Phase 6.5E does not add a trade scheduler, does
not run collectors automatically, does not add ML, and does not create targets.
Export artifacts remain runtime files under `data/exports/` and must not be
committed.

Phase 6.6B is local-only dataset readiness documentation and audit tooling. It
adds the feature catalog, dataset dictionary, source-to-feature lineage,
leakage/as-of audit, ML-ready audit template, and a local diagnostics script:

```bash
python scripts/audit_dataset_readiness.py
```

The script writes only:

```text
diagnostics/dataset_readiness/DATASET_READINESS_AUDIT_REPORT.md
diagnostics/dataset_readiness/dataset_readiness_audit.json
```

Do not deploy Phase 6.6B by itself as a production validation step. Server batch
6.6A is still required before final production export validation: reviewed pull
on the server, pending migrations, controlled derived builders, health/quality
reports, and a checked `daily_features` export. Phase 6.6B does not run
collectors, does not add scheduler jobs, does not add ML, and does not add
targets.

Phase 6.7A is local-only supply-demand / production-stocks source discovery for
future official balance features. It uses a static curated registry, performs no
HTTP requests, and writes only diagnostics artifacts:

```bash
python scripts/audit_supply_demand_sources.py
```

Outputs:

```text
diagnostics/supply_demand_source_audit/SUPPLY_DEMAND_SOURCE_AUDIT_REPORT.md
diagnostics/supply_demand_source_audit/supply_demand_source_candidates.json
```

The recommended first source to investigate is USDA PSD / FAS PSD Online, with a
bounded soybean/rapeseed oilseed-oil-meal prototype. Phase 6.7A does not need
server deploy, migrations, production DB writes, collector runs, scheduler
changes, ML, or targets. The next step is Phase 6.7B schema/as-of design before
any production supply-demand collector.

Phase 6.7B is that design-only schema step. It adds:

```text
docs/SUPPLY_DEMAND_DESIGN.md
docs/sql_drafts/0018_supply_demand_schema_draft.sql
```

Do not apply the SQL draft manually. It is not an Alembic migration and does not
change production. The proposed future tables are `supply_demand_commodities`,
`supply_demand_observations`, `supply_demand_revisions`,
`product_supply_demand_weights`, and `daily_supply_demand_features`. Planned
next steps are Phase 6.7C schema-only implementation, Phase 6.7D a controlled
USDA PSD collector/prototype, and Phase 6.7E supply-demand feature/export
integration. Phase 6.7B does not add collectors, schedulers, DB writes, ML
targets, or dataset targets.

Phase 6.7C implements the reviewed schema through Alembic revision
`0018_supply_demand_schema`. It adds only new supply-demand tables, source
seeds, conservative mapping seeds, product mapping weights, operational-report
counts, and tests. It does not add a collector, scheduler job, feature builder,
export columns, ML, or targets.

After a reviewed deploy, apply the schema with normal Alembic flow and then run
the idempotent seed. The new tables are expected to be empty except for mapping
tables until Phase 6.7D adds a controlled USDA PSD prototype.

Phase 6.7D adds that controlled/manual `usda_psd` collector. It is not
scheduled. It writes raw evidence, `raw_responses`, quality checks, and
normalized `supply_demand_observations`; it does not rebuild
`daily_product_features`, does not change exports, and does not add ML targets.

Phase 6.9E uses the direct USDA PSD downloadable oilseeds ZIP contract:

```text
https://apps.fas.usda.gov/psdonline/downloads/psd_oilseeds_csv.zip
```

The controlled live probe downloads that ZIP, stores it through `RawStore`,
extracts the CSV, and normalizes only the reviewed soybean/rapeseed oil and
meal commodity codes. The `PSDOnlineApi/api/downloadableData/GetDatasetContents`
route is intentionally not used because it returns downloadable dataset
metadata, not PSD data rows. The discovered `api/query/RunQuery` POST endpoint
is not used in this hotfix.
The direct ZIP is country-level. Use concrete USDA PSD country codes such as
`US`, `BR`, `AR`, `CA`, and `CH` for controlled probes. `WLD`/`World` rows are
not present in the ZIP and are not synthesized from country rows; explicit world
aggregation is deferred until aggregation rules and coverage policy are
designed.

Supported USDA PSD metrics are production, domestic consumption, food use, feed
use, crush, exports, imports, beginning stocks, ending stocks, stock-to-use,
planted area, harvested area, and yield. Known PSD aggregate/detail rows that
are not current feature inputs are expected skipped rows, not active collector
failures, as long as supported rows are normalized. Real malformed rows, mapping
gaps for supported metrics, and unknown unsupported metrics still require
review. Do not start broad backfill until skip-reason summaries are understood.

Use a reviewed fixture for local validation:

```bash
python scripts/run_collector.py usda_psd \
  --commodity-family soybean_oil \
  --from-marketing-year 2023 \
  --to-marketing-year 2023 \
  --country US \
  --fixture-file tests/fixtures/usda_psd/oilseeds_sample.csv
```

Use `--live-probe` only after tests pass and a fresh controlled production
probe has been explicitly approved:

```bash
python scripts/run_collector.py usda_psd \
  --commodity-family soybean_oil \
  --from-marketing-year 2023 \
  --to-marketing-year 2023 \
  --country US \
  --maxrecords 100 \
  --live-probe
```

Operational safety limits are fixed in code: maximum three marketing years per
run, default `--maxrecords=100`, hard `--maxrecords=500`, and no scheduler
registration. If an existing observation identity changes hash, the collector
writes `supply_demand_existing_observation_hash_changed` and does not silently
overwrite.

Phase 6.7E adds local daily supply-demand feature/export integration. It is not
a collector deploy by itself and it does not add scheduler jobs or ML targets.
After the reviewed code is deployed later, the controlled server sequence should
run the migration, then:

```bash
python scripts/build_features.py supply_demand_daily
python scripts/build_features.py daily
python scripts/export_dataset.py daily_features --format csv --output-dir data/exports
```

`supply_demand_daily` reads `supply_demand_observations` and
`product_supply_demand_weights`, writes `daily_supply_demand_features`, and the
regular daily builder copies only rows with
`supply_demand_as_of_date <= feature_date` into `daily_product_features`.
If a newly fetched report has an as-of date later than the current product
feature window, `supply_demand_daily` extends its default range to that first
safe as-of date and marks earlier rows with
`supply_demand_observations_after_feature_date_window` rather than backfilling
future information.
Expected nullable export fields include production/use/crush/trade/stocks,
stock-to-use, area/yield, forecast revisions, `supply_demand_as_of_date`,
`supply_demand_reporting_lag_days`, and `supply_demand_missing_flags`.

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

## UN Comtrade Collector Rollout

Phase 6.5D adds a manual-only `un_comtrade` collector. It is not scheduled and
must be run only in controlled, narrow windows after the `0016_trade_schema`
migration and seed have been applied.

Example controlled command:

```bash
docker compose run --rm app python scripts/run_collector.py un_comtrade \
  --hs-code 1507 \
  --from-period 2024-01 \
  --to-period 2024-01 \
  --reporter BRA \
  --partner WLD \
  --flow export \
  --maxrecords 100
```

Phase 6.5D supports only HS codes `1201`, `1507`, `2304`, `1205`, `1514`, and
`2306`, a maximum of 3 monthly periods per request, and bounded
`maxrecords <= 500`. Raw responses are stored under `data/raw/un_comtrade/...`
and normalized rows are written to `trade_flows`. Re-run the same command to
verify idempotency; unchanged rows should be skipped, and changed rows should
create `trade_existing_flow_hash_changed` warnings without overwriting.

Do not add a scheduler for `un_comtrade` in this phase. Do not build trade
features or export trade columns until Phase 6.5E defines the as-of policy.

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
