# Energy Prices Design

## Executive Summary

Phase 6.1B is a design-only step for future energy and oil factor storage. It
does not add an Alembic migration, does not change SQLAlchemy models, does not
write PostgreSQL rows, does not implement a collector, and does not change any
scheduler.

The proposed table is `energy_prices`. It should store normalized energy-market
observations from future sources such as FRED/EIA-derived CSV, World Bank Pink
Sheet, and possibly EIA Open Data API. The first recommended future prototype is
FRED/EIA-derived CSV because Phase 6.1A marked it `ready_to_prototype` and it
can cover Brent crude oil, WTI crude oil, Henry Hub natural gas, and a US diesel
proxy without storing secrets.

## Phase 6.1A Findings

Phase 6.1A audited source candidates without touching production tables.

| source | status | role |
| --- | --- | --- |
| FRED EIA-derived CSV | `ready_to_prototype` | First daily/weekly prototype candidate. |
| World Bank Pink Sheet | `ready_to_prototype` | Monthly benchmark complement. |
| EIA Open Data API v2 | `needs_manual_check` | Official API, requires API key and route design. |
| Stooq public historical data | `needs_manual_check` | Possible fallback, terms/symbols need review. |
| Nasdaq Data Link | `needs_manual_check` | Dataset-specific access and licensing. |
| Yahoo/Investing/TradingEconomics-like endpoints | `high_risk` | Manual comparison only, not production collector design. |

Recommended first instruments:

| instrument_code | source id | category | unit | frequency |
| --- | --- | --- | --- | --- |
| `brent_crude_oil` | `DCOILBRENTEU` | `crude_oil` | `USD/barrel` | daily |
| `wti_crude_oil` | `DCOILWTICO` | `crude_oil` | `USD/barrel` | daily |
| `henry_hub_natural_gas` | `DHHNGSP` | `natural_gas` | `USD/MMBtu` | daily |
| `us_diesel_retail` | `GASDESW` | `diesel` | document source unit carefully | weekly proxy |

## Requirements

`energy_prices` must support:

- daily FRED/EIA-derived prices with missing weekends and holidays;
- weekly fuel proxy series;
- monthly World Bank Pink Sheet benchmarks;
- future EIA API series that may require an API key but should not require a
  different schema;
- raw-response evidence and collector-run traceability;
- future as-of joins into `daily_product_features`;
- idempotent inserts and safe detection of revised source values.

The table should not be used for ML targets. It is an external factor table.

## Proposed Table

Table: `energy_prices`

| field | type | nullable | purpose |
| --- | --- | --- | --- |
| `id` | integer primary key | no | Surrogate key. |
| `source_id` | FK to `sources.id` | no | Source row, initially expected `fred_energy_prices`. |
| `raw_response_id` | FK to `raw_responses.id` | no | Raw payload evidence used to parse the row. |
| `collector_run_id` | FK to `collector_runs.id` | no | Collector run that fetched the source payload. |
| `instrument_code` | string(100) | no | Local stable code, e.g. `brent_crude_oil`. |
| `instrument_name` | string(255) | no | Human-readable name. |
| `instrument_category` | string(100) | no | `crude_oil`, `natural_gas`, `diesel`, `energy_index`, etc. |
| `external_id` | string(100) | no | Source series id, e.g. `DCOILBRENTEU`. |
| `frequency` | string(32) | no | `daily`, `weekly`, `monthly`, or future controlled value. |
| `period_start` | date | no | Start date of the observation period. |
| `period_end` | date | no | End date of the observation period. |
| `observed_at` | timestamptz | no | UTC timestamp representation of the period. |
| `published_at` | timestamptz | yes | Source publication time if provided. |
| `fetched_at` | timestamptz | no | UTC time the collector fetched the raw response. |
| `value` | numeric(18, 8) | no | Original source value. |
| `currency` | string(16) | yes | Currency when applicable, e.g. `USD`; nullable for index series. |
| `unit` | string(100) | no | Original unit, e.g. `USD/barrel`. |
| `normalized_value` | numeric(18, 8) | yes | Future normalized value; initially can equal `value`. |
| `normalized_currency` | string(16) | yes | Future normalized currency; initially can equal `currency`. |
| `normalized_unit` | string(100) | yes | Future normalized unit; initially can equal `unit`. |
| `source_record_hash` | string(64) | no | Stable normalized-record hash for change detection. |
| `source_payload_hash` | string(64) | no | Raw response SHA-256, matching `raw_responses.sha256`. |
| `metadata_json` | JSON/JSONB | yes | Source-specific notes and parse metadata. |
| `created_at` | timestamptz | no | Insert time. |
| `updated_at` | timestamptz | no | Last update time. |

### Source Code Denormalization

Do not store a separate `source_code` column in `energy_prices`. Existing
project tables normally link normalized rows to `sources` by `source_id`.
Keeping the same style avoids drift between a denormalized `source_code` string
and the authoritative `sources.code` value.

## Field Decisions

### `raw_response_id`

Use `NOT NULL` for production rows. Every external response in this project
needs raw evidence, and energy prices should follow the same rule as production
collector tables. Diagnostics-only artifacts from Phase 6.1A are not production
raw evidence.

### `collector_run_id`

Use `NOT NULL` for production rows. A future energy collector should create a
`collector_runs` row before fetching source payloads, and every parsed
`energy_prices` row should link back to that run.

### `period_start`, `period_end`, and `observed_at`

Use `period_start` and `period_end` as dates to support mixed frequencies:

- daily: both dates are the same;
- weekly: full source week or documented source period;
- monthly: first and last day of the month.

Keep `observed_at` as `TIMESTAMP WITH TIME ZONE` for consistency with other
project tables and as-of query patterns. For date-only source rows, set
`observed_at` to the start of `period_start` in UTC unless the source provides a
more precise timestamp.

### `metadata_json`

Use `JSONB` on PostgreSQL. Suggested keys:

- `series_id`
- `endpoint`
- `source_units`
- `source_frequency`
- `seasonal_adjustment`
- `source_notes`
- `parser_version`
- `missing_value_marker`

## Unique Constraint And Idempotency

Recommended unique constraint:

```text
UNIQUE(source_id, instrument_code, frequency, period_start, period_end)
```

Recommended name:

```text
uq_energy_prices_source_instrument_frequency_period
```

Rationale:

- a source owns its own series semantics;
- `instrument_code` identifies the local feature-grade series;
- `frequency` prevents collisions if a source exposes daily and monthly
  variants of a similar instrument;
- `period_start` and `period_end` support daily, weekly, and monthly rows;
- one current accepted value should exist for a source/instrument/frequency
  period.

Do not include `source_record_hash` in the unique constraint. If a source later
revises a value, including the hash would allow duplicate rows for the same
period. Use `source_record_hash` as a change detector instead.

First collector idempotency policy:

- same unique key and same hash: skip;
- same unique key and changed hash: write quality warning
  `energy_existing_record_hash_changed`;
- do not silently overwrite in the first production collector;
- add a revisions table later only if real source mutability is observed.

## Indexes

Recommended index names use short PostgreSQL-safe identifiers:

```text
ix_energy_prices_source_instrument_period
  (source_id, instrument_code, period_start, period_end)

ix_energy_prices_instrument_observed
  (instrument_code, observed_at)

ix_energy_prices_category_observed
  (instrument_category, observed_at)

ix_energy_prices_fetched_at
  (fetched_at)

ix_energy_prices_raw_response_id
  (raw_response_id)

ix_energy_prices_collector_run_id
  (collector_run_id)

ix_energy_prices_source_record_hash
  (source_record_hash)
```

## Source Seeding Design

Future source seed:

```text
code: fred_energy_prices
name: FRED Energy Prices
type/category: energy benchmark / external factor
base_url: https://fred.stlouisfed.org/graph/fredgraph.csv
is_active: true
```

Phase 6.1B does not change `app/db/seed.py`. Seeding should happen in the
schema/collector phase after the table design is accepted.

Future instrument config:

| instrument_code | external_id | name | category | unit | frequency |
| --- | --- | --- | --- | --- | --- |
| `brent_crude_oil` | `DCOILBRENTEU` | Crude Oil Prices: Brent - Europe | `crude_oil` | `USD/barrel` | daily |
| `wti_crude_oil` | `DCOILWTICO` | Crude Oil Prices: West Texas Intermediate | `crude_oil` | `USD/barrel` | daily |
| `henry_hub_natural_gas` | `DHHNGSP` | Henry Hub Natural Gas Spot Price | `natural_gas` | `USD/MMBtu` | daily |
| `us_diesel_retail` | `GASDESW` | US diesel sales price proxy | `diesel` | source unit requires confirmation | weekly |

## Raw Storage Design

Future production collector source code:

```text
fred_energy_prices
```

Raw path:

```text
data/raw/fred_energy_prices/{yyyy}/{mm}/{dd}/{collector_run_id}/{sha256}.csv
```

Each fetched CSV response should create one `raw_responses` row. Parsed
`energy_prices` rows must point to the `raw_response_id` and copy the raw
payload SHA-256 into `source_payload_hash`.

## As-Of And Leakage Policy

`observed_at` and `period_start` are not enough for ML-safe features.

Rules:

- `fetched_at` records when this system actually obtained the data.
- `published_at` records when the source says the value became available, if
  the source provides that information.
- `as_collected` mode must filter by `fetched_at <= feature_as_of_at`.
- `publication_aware` mode may use `published_at` when available, with
  `fetched_at` still preserved for audit.
- historical backfill must not be treated as known in the past unless an export
  mode explicitly allows historical backfill.
- monthly World Bank values may be forward-filled only after the allowed as-of
  timestamp.

This policy mirrors the existing project rule that raw evidence and collection
time are required to avoid future-data leakage.

## Future Feature Integration

Phase 6.1B does not change `daily_product_features`.

Future energy feature columns could include:

- `brent_usd_per_barrel`
- `brent_delta_1d`
- `brent_delta_7d`
- `wti_usd_per_barrel`
- `wti_delta_1d`
- `henry_hub_usd_mmbtu`
- `diesel_proxy`
- `energy_as_of_date`
- `energy_missing_flags`

Feature builder rules:

- join the latest energy observation available on or before `feature_date`;
- also respect as-of availability through `fetched_at` or `published_at`;
- leave missing values explicit instead of inventing data;
- handle weekly/monthly values through documented forward-fill windows;
- do not mix energy features into export v1 until Phase 6.1E explicitly
  updates the feature/export contract.

## Quality Checks

Future collector checks:

Raw checks:

- `energy_raw_response_non_empty`
- `energy_content_type_expected`
- `energy_response_size_within_limit`
- `energy_parser_success`

Data checks:

- `energy_instrument_present`
- `energy_period_present`
- `energy_value_present`
- `energy_value_numeric`
- `energy_fetched_at_present`
- `energy_source_record_hash_present`
- `energy_no_duplicate_source_instrument_period`
- `energy_no_future_observed_at`
- `energy_existing_record_hash_changed`

For missing source values such as holiday gaps, the parser should skip missing
value markers and record parser statistics rather than inserting null prices.

## Operational Limits

First FRED prototype limits:

- bounded date ranges;
- one small CSV request for the first four series or one request per series;
- explicit timeout and user agent;
- no secrets;
- no scheduler until manual run and idempotency are verified;
- no broad source discovery from production collector code.

World Bank Pink Sheet should use low-frequency workbook downloads and separate
monthly parsing tests.

EIA Open Data API should not be implemented until API-key storage, route
selection, and rate-limit policy are agreed.

## Migration Plan For Next Phase

Phase 6.1C should:

1. Add SQLAlchemy model `EnergyPrice`.
2. Add non-destructive Alembic migration creating only `energy_prices`.
3. Add constraints and indexes from this design.
4. Optionally add idempotent source seed `fred_energy_prices`.
5. Keep the new table empty after migration.
6. Update operational reports to show count/latest observed date without
   treating an empty table as an error.

## Production Rollout Plan

1. Phase 6.1C: schema-only migration.
2. Phase 6.1D: first controlled/manual FRED CSV collector for the four selected
   instruments.
3. Phase 6.1E: energy feature integration and dataset export update.
4. Later: World Bank monthly benchmark collector.
5. Later/manual-check: EIA API collector if API-key policy is approved.

## Open Questions

- Confirm exact unit and semantics for `GASDESW`.
- Decide whether first FRED collector requests combined CSV or one CSV per
  series.
- Verify FRED citation and usage requirements for stored/exported datasets.
- Decide whether source revisions need an `energy_price_revisions` table after
  observing real data changes.
- Decide whether World Bank monthly values should share `energy_prices` or a
  broader `commodity_benchmarks` table once benchmark design resumes.
