# Commodity Benchmarks Design

## Executive Summary

Phase 6.2B is a design-only step for a future `commodity_benchmarks`
storage layer. It does not add an Alembic migration, does not change
SQLAlchemy models, does not write PostgreSQL rows, does not implement a
collector, does not change schedulers, and does not add ML targets.
Phase 6.2C implements schema-only support: SQLAlchemy metadata, Alembic
revision `0010_commodity_benchmarks`, idempotent source seed readiness, and
operational reporting for an empty `commodity_benchmarks` table. The initial
schema already had a small `commodity_benchmarks` skeleton; Phase 6.2C expands
that existing table non-destructively instead of recreating it.

The proposed table is `commodity_benchmarks`. It should store global benchmark
prices and indices from sources such as World Bank Pink Sheet and FAO Food Price
Index data. These benchmarks are lower-frequency context features for future
agricultural price forecasting datasets, not replacements for current local
price snapshots.

## Why Global Commodity Benchmarks Matter

The project currently stores local/current commodity prices, FX, historical
bars, and energy factors. Global benchmark data adds a broader market-regime
layer:

- vegetable oil and oilseed substitution pressure;
- grain and feed market context;
- fertilizer and input-cost pressure;
- global commodity cycle signals;
- stable monthly context for future features and dataset exports.

These data should improve future ML dataset quality only if they are joined with
strict as-of rules. The design therefore treats publication and fetch timing as
first-class fields.

## First Source Decision

The first production prototype should be World Bank Pink Sheet.

Reasons:

- broad monthly commodity coverage;
- useful agriculture, oils, grains, fertilizers, and energy benchmarks;
- no project-specific secret or API key for the first prototype;
- stable source identity and publication process;
- Phase 6.2A classified it as `ready_to_prototype`.

First World Bank benchmark candidates:

| benchmark_code | external_id placeholder | category | commodity_family | frequency | unit notes | ML value |
| --- | --- | --- | --- | --- | --- | --- |
| `world_bank_soybean_oil` | Pink Sheet soybean oil series | `vegetable_oil` | `soybean` | monthly | likely USD/metric ton; confirm workbook column | direct oil benchmark |
| `world_bank_soybeans` | Pink Sheet soybeans series | `oilseed` | `soybean` | monthly | likely USD/metric ton; confirm workbook column | oilseed anchor for oil and meal |
| `world_bank_palm_oil` | Pink Sheet palm oil series | `vegetable_oil` | `palm` | monthly | likely USD/metric ton; confirm workbook column | substitute oil benchmark |
| `world_bank_maize` | Pink Sheet maize series | `grain` | `corn` | monthly | likely USD/metric ton; confirm workbook column | feed and biofuel context |
| `world_bank_wheat` | Pink Sheet wheat series | `grain` | `wheat` | monthly | likely USD/metric ton; confirm workbook column | broad grain market regime |
| `world_bank_fertilizer_index` | Pink Sheet fertilizer index | `fertilizer` | `fertilizer` | monthly | index value; no currency | input-cost pressure |

## Additional Source

FAO indices are a useful second monthly index layer.

First FAO candidates:

| benchmark_code | external_id placeholder | category | commodity_family | frequency | unit notes | ML value |
| --- | --- | --- | --- | --- | --- | --- |
| `fao_vegetable_oils_index` | FAO vegetable oils index | `food_index` | `vegetable_oils` | monthly | index value, base period must be recorded | direct vegetable oils market regime |
| `fao_cereals_index` | FAO cereals index | `food_index` | `cereals` | monthly | index value, base period must be recorded | grain market regime |
| `fao_food_price_index` | FAO Food Price Index | `food_index` | `food` | monthly | index value, optional first wave | broad food inflation regime |

FAO should be prototyped only after the exact machine-readable file or stable
download path is confirmed.

## Why Not Use High-Risk Web Scraping First

Nasdaq Data Link, Stooq, Yahoo-like, Investing-like, and other unofficial
endpoints are not good first production sources for this layer.

Reasons:

- licensing and redistribution terms may be unclear or commercial;
- endpoints and symbols can change without warning;
- broad crawling would create operational and legal risk;
- values may be adjusted, delayed, or mixed across contract types;
- this project requires raw evidence, stable source metadata, and reproducible
  as-of joins.

These sources can remain manual-check candidates, but they should not drive the
first `commodity_benchmarks` collector.

## Proposed Table

Table: `commodity_benchmarks`

| field | type | nullable | purpose |
| --- | --- | --- | --- |
| `id` | integer primary key | no | Surrogate key. |
| `source_id` | FK to `sources.id` | no | Source row, e.g. future `world_bank_pink_sheet`. |
| `raw_response_id` | FK to `raw_responses.id` | no | Raw workbook/file evidence. |
| `collector_run_id` | FK to `collector_runs.id` | no | Collector run that fetched and parsed the source. |
| `benchmark_code` | string(100) | no | Stable internal code, e.g. `world_bank_soybean_oil`. |
| `external_id` | string(255) | no | Source-specific sheet/series/column identifier. |
| `benchmark_name` | string(255) | no | Human-readable benchmark name. |
| `benchmark_category` | string(100) | no | `oilseed`, `vegetable_oil`, `grain`, `fertilizer`, `food_index`, etc. |
| `commodity_family` | string(100) | no | `soybean`, `palm`, `corn`, `wheat`, `fertilizer`, `vegetable_oils`, etc. |
| `geography` | string(100) | no | `global`, `world`, `source_specific`, or later region code. |
| `frequency` | string(32) | no | Initially `monthly`; future `daily`/`weekly` allowed by controlled design. |
| `period_start` | date | no | First date of the value period. |
| `period_end` | date | no | Last date of the value period. |
| `observed_at` | timestamptz | no | Representative timestamp for query consistency. |
| `published_at` | timestamptz | yes | Source publication time if available. |
| `fetched_at` | timestamptz | no | Time this system fetched the raw source. |
| `value` | numeric(18, 8) | no | Original source value. |
| `currency` | string(16) | yes | Currency when applicable; nullable for index series. |
| `unit` | string(100) | no | Original source unit or index base label. |
| `normalized_value` | numeric(18, 8) | yes | Future normalized value; initially can equal `value`. |
| `normalized_currency` | string(16) | yes | Future normalized currency; nullable or `INDEX` for index series. |
| `normalized_unit` | string(100) | yes | Future normalized unit or index label. |
| `source_record_hash` | string(64) | no | Stable normalized-record hash for idempotency/change detection. |
| `source_payload_hash` | string(64) | no | Raw response SHA-256 copied from `raw_responses.sha256`. |
| `metadata_json` | JSON/JSONB | yes | Source-specific sheet, column, unit, citation, and publication notes. |
| `created_at` | timestamptz | no | Insert time. |
| `updated_at` | timestamptz | no | Last update time. |

## Source And Raw Lineage

Every production benchmark row must link to:

- `sources.id` through `source_id`;
- `collector_runs.id` through `collector_run_id`;
- `raw_responses.id` through `raw_response_id`;
- the raw payload SHA-256 through `source_payload_hash`.

Diagnostics artifacts from Phase 6.2A are not production raw evidence. A future
collector must store the World Bank/FAO source file through the normal `RawStore`
and create `raw_responses` before inserting normalized benchmark rows.

## Frequency Handling

Monthly is the first supported production frequency because World Bank and FAO
are monthly benchmark sources.

Period rules:

- monthly: `period_start` is the first day of the month and `period_end` is the
  last day of the month;
- daily later: `period_start = period_end`;
- weekly later: source-defined week start and week end.

The schema intentionally includes `frequency` to avoid mixing monthly index
values with daily or weekly market prices.

## Period Semantics

Use `period_start` and `period_end` for the actual source period.

Use `observed_at` as a representative timestamp for compatibility with existing
as-of query patterns. Recommended rule:

- monthly benchmark: `observed_at` = start of `period_end` in UTC;
- daily benchmark later: `observed_at` = start of `period_start` in UTC;
- weekly benchmark later: `observed_at` = start of `period_end` in UTC.

Do not use `observed_at` alone to decide whether the value was available to the
model. Availability must use `published_at` and/or `fetched_at`.

## As-Of And Leakage Policy

Monthly benchmark values can be published after the month ends. A May benchmark
must not be used for feature dates before it was available.

Future export/feature modes:

- `as_collected`: value can be used only when `fetched_at <= feature_as_of_at`;
- `publication_aware`: use `published_at <= feature_as_of_at` when the source
  provides publication time, while retaining `fetched_at` for audit;
- `historical_backfill_allowed`: allowed only for research/backfill analysis,
  not realistic simulation.

The default production feature policy should be `as_collected` until reliable
publication timestamps are implemented.

## Units And Normalization Policy

Store original source values in `value`, `currency`, and `unit`.

Store normalized values separately:

- physical prices can initially copy original value/currency/unit;
- index series can use `normalized_currency = NULL` or `INDEX` by convention;
- `metadata_json` should record index base year/base period;
- unit conversions must be explicit and tested before feature integration.

Do not compare index values and physical USD prices without an explicit feature
design.

## Unique Constraint And Idempotency

Recommended unique constraint:

```text
UNIQUE(source_id, benchmark_code, frequency, period_start, period_end)
```

Rationale:

- one source owns its own benchmark semantics;
- one internal benchmark code represents one feature-grade series;
- frequency prevents collisions between monthly/daily variants;
- period dates identify the benchmark period;
- one current accepted value should exist per source/benchmark/frequency/period.

Do not include `source_record_hash` in the unique constraint. The hash is a
change detector, not an identity component.

First collector policy:

- same key and same hash: skip;
- same key and changed hash: write quality warning
  `commodity_benchmark_existing_record_hash_changed`;
- no silent overwrite in the first collector;
- do not add a revisions table until real World Bank/FAO mutable behavior is
  observed.

## Mutable Or Revised Benchmark Policy

World Bank or FAO may revise historical values. Phase 6.2B does not design a
revision table as mandatory because mutability has not yet been observed in
production.

Recommended first behavior:

- detect changed hashes;
- write a quality warning with old/new values and source hashes;
- do not overwrite silently;
- decide on a revision layer later if real revisions occur.

## Indexes

Recommended PostgreSQL-safe names:

```text
ix_commodity_bench_source_benchmark_period
  (source_id, benchmark_code, period_start, period_end)

ix_commodity_bench_benchmark_observed
  (benchmark_code, observed_at)

ix_commodity_bench_category_observed
  (benchmark_category, observed_at)

ix_commodity_bench_family_observed
  (commodity_family, observed_at)

ix_commodity_bench_fetched_at
  (fetched_at)

ix_commodity_bench_raw_response_id
  (raw_response_id)

ix_commodity_bench_collector_run_id
  (collector_run_id)

ix_commodity_bench_source_record_hash
  (source_record_hash)
```

If migration tooling reports identifier length issues, shorten names while
preserving meaning, for example `ix_cmd_bench_src_code_period`.

## Source Seeding Design

Phase 6.2B does not change seed data.
Phase 6.2C adds idempotent seeds for the first two benchmark source candidates.

Future source seed candidates:

```text
code: world_bank_pink_sheet
name: World Bank Pink Sheet
source_type: commodity_benchmark
base_url: https://www.worldbank.org/en/research/commodity-markets
is_active: true
frequency: monthly, stored in source metadata if a metadata field exists later
```

```text
code: fao_price_indices
name: FAO Food Price Indices
source_type: commodity_benchmark
base_url: https://www.fao.org/worldfoodsituation/foodpricesindex/en/
is_active: true
frequency: monthly, stored in source metadata if a metadata field exists later
```

## Future Feature Integration

Do not change `daily_product_features` in Phase 6.2B.

Future feature examples:

- `benchmark_soybean_oil_value`
- `benchmark_soybean_oil_delta_1m`
- `benchmark_soybean_oil_delta_3m`
- `benchmark_soybeans_value`
- `benchmark_palm_oil_value`
- `benchmark_maize_value`
- `benchmark_wheat_value`
- `benchmark_fertilizer_index`
- `fao_vegetable_oils_index`
- `fao_cereals_index`
- `benchmark_as_of_date`
- `benchmark_missing_flags`

Rules:

- monthly values may be forward-filled only after the value is available under
  the chosen as-of mode;
- missing benchmark series should produce explicit missing flags;
- no future leakage;
- unit and index-base metadata must be documented in the export data dictionary.

## Future Export Integration

Dataset export should include benchmark columns only after:

- schema is implemented;
- at least one controlled collector is working;
- feature builder has explicit benchmark as-of logic;
- export manifest lists benchmark source tables and limitations.

Exports must not include benchmark-derived targets in this phase family.

## Future Phases

- Phase 6.2C: schema-only implementation for `commodity_benchmarks`.
- Phase 6.2D: first controlled/manual World Bank Pink Sheet collector.
- Phase 6.2E: benchmark feature and export integration with leakage-safe as-of
  policy.

## Non-Goals

- No migration in Phase 6.2B.
- No collector writes benchmark rows in Phase 6.2C.
- No DB writes in Phase 6.2B.
- No benchmark data rows in Phase 6.2C.
- No scheduler changes in Phase 6.2C.
- No ML model.
- No targets.
