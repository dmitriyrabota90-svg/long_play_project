# Trade Import Export Data Design

## Executive Summary

Phase 6.5B is a design-only step for a future trade/import-export layer. It
does not add an Alembic migration, does not change SQLAlchemy models, does not
write PostgreSQL rows, does not implement a collector, does not change
schedulers, does not add ML targets, and does not add dataset targets.

The proposed layer has four future tables:

- `trade_commodity_codes`: HS/source commodity-code mappings and product-family
  metadata.
- `trade_flows`: normalized import/export rows by reporter, partner, commodity,
  flow direction, period, quantity, and value.
- `product_trade_code_weights`: explicit mapping from project products to
  trade codes and roles.
- `daily_trade_features`: product-level trade aggregates that can later be
  copied into `daily_product_features` and exported.

Phase 6.5C should implement the reviewed schema only. Phase 6.5D should add the
first controlled trade collector. Phase 6.5E should integrate trade features
and export columns only after as-of rules are reviewed.

## Why Trade/Import-Export Matters For Agricultural Commodity Price Forecasting

Trade flows describe physical availability, destination demand, export
competition, logistics pressure, and substitution effects. Soybean, soybean
oil, soybean meal, rapeseed/canola seed, rapeseed/canola oil, and
rapeseed/canola meal are traded through global supply chains. A price movement
can come from production shocks, but it can also come from China import demand,
Brazil/US/Argentina soybean export strength, Canada/EU/Ukraine rapeseed export
availability, or vegetable oil substitution.

Useful future signals include monthly import/export volumes, trade values,
average unit values, net export proxies, major exporter/importer shares,
rolling trade averages, year-over-year changes, reporting lag, and explicit
missing flags.

The layer must be leakage-safe. Monthly and annual trade rows are often
published after the period ends and can be revised later. A future dataset row
for a given feature date must know whether a trade row was published and
whether this system had fetched it by that date.

## Current Product Families

The current dataset motivates the first trade design around:

- `soybean`: soybean seed context for `soybean_oil` and `soybean_meal`;
- `soybean_oil`: direct oil trade and vegetable oil substitution context;
- `soybean_meal`: direct meal/oilcake trade and feed-demand context;
- `rapeseed/canola`: seed trade context for rapeseed oil and meal;
- `rapeseed/canola oil`: direct oil trade and vegetable oil substitution;
- `rapeseed/canola meal`: direct meal/oilcake trade and feed-demand context;
- broader `vegetable_oils`: palm oil and sunflower oil as context;
- grains and fertilizer as later indirect context.

## First Source Decision

The first source prototype should use UN Comtrade if API access, authentication,
and rate limits are workable.

Reasons:

- global bilateral trade coverage;
- HS commodity code support;
- import/export directions, quantities, values, reporter, and partner fields;
- monthly and annual routes may be available depending on endpoint/access;
- good fit for China import demand and major exporter proxy features;
- Phase 6.5A classified it as the recommended first source.

UN Comtrade still needs a bounded prototype before any production collector is
written. The first prototype should verify exact endpoint, auth behavior, rate
limits, response fields, code systems, monthly availability, and licensing
notes.

## First Prototype Scope

The first prototype should be intentionally narrow:

- source: UN Comtrade;
- frequency: monthly trade data if available;
- HS codes: `1201`, `1507`, `2304`, `1205`, `1514`, `2306`;
- reporters/exporters: Brazil, United States, Argentina, Canada, Ukraine, and
  EU/EU-member reporters where supported;
- importer/demand proxy: China;
- partners: world/all partners when supported, China as a selected partner, and
  EU/selected partners later;
- flows: import, export, and unknown/re-export variants only after mapping is
  reviewed;
- request policy: small windows, explicit timeout, no broad country/code
  crawling, and raw-response caching in the future collector.

## Why Not Start With Paid Or High-Complexity Customs Data

ITC Trade Map and national customs/statistics agencies can be valuable, but
they are not the right first production layer.

Reasons:

- paid/commercial sources require explicit license and API approval;
- national customs sites are heterogeneous by country, language, file format,
  revision policy, and publication calendar;
- broad scraping or portal automation creates operational and licensing risk;
- storage and deduplication are harder when every reporter has a different
  model;
- value can be proven faster with one global HS-code source.

These sources should remain later candidates after the shared schema is proven.

## HS And Source Commodity Mapping

Initial mapping:

| family | product_code | HS/source code | relevance | notes |
| --- | --- | --- | --- | --- |
| `soybean` |  | `1201` | direct | Soya beans; China import demand and Brazil/US/Argentina export proxy. |
| `soybean_oil` | `soybean_oil` | `1507` | direct | Soybean oil and fractions; subcodes can separate crude/refined. |
| `soybean_meal` | `soybean_meal` | `2304` | direct | Soybean oilcake/solid residues; feed-demand and crush-product proxy. |
| `rapeseed_canola` |  | `1205` | direct | Rape/colza seed; Canada/EU/Ukraine/China flows. |
| `rapeseed_oil` | `rapeseed_oil` | `1514` | direct | Rape/colza/mustard oil; mustard inclusion needs source-specific review. |
| `rapeseed_meal` | `rapeseed_meal` | `2306` | direct | Other vegetable oilcake; relevant subcodes must be verified. |
| `palm_oil` |  | `1511` | context | Substitute vegetable oil. |
| `sunflower_oil` |  | `1512` | context | Substitute vegetable oil, even without current-price instruments. |
| `wheat` |  | `1001` | context | Grain/feed and Black Sea context. |
| `maize_corn` |  | `1005` | context | Feed and biofuel context. |
| `fertilizer` |  | `3102/3103/3104/3105` | later | Input-cost context after core trade layer is proven. |

HS revisions and subcodes matter. The schema stores both generic HS mappings and
source-specific caveats so future collectors can preserve the original source
code and revision instead of forcing every source into a single generic label.

## Proposed Tables

| table | purpose |
| --- | --- |
| `trade_commodity_codes` | Stable source/HS commodity-code mapping metadata. |
| `trade_flows` | Normalized trade rows by reporter, partner, code, flow, and period. |
| `product_trade_code_weights` | Product-to-trade-code mappings for direct/context feature aggregation. |
| `daily_trade_features` | Precomputed product-level trade features for later joins into `daily_product_features`. |

The design keeps commodity-code metadata, source rows, product mappings, and
derived features separate.

## Commodity Code Model

Table: `trade_commodity_codes`

| field | type | nullable | purpose |
| --- | --- | --- | --- |
| `id` | integer primary key | no | Surrogate key. |
| `source_id` | FK to `sources.id` | yes | Source-specific code owner when applicable; nullable for generic HS mappings. |
| `code_system` | string(64) | no | `HS`, `UN_COMTRADE_HS`, `FAOSTAT_ITEM`, `USDA_FAS`, etc. |
| `commodity_code` | string(64) | no | Source or HS code, e.g. `1201`. |
| `commodity_name` | string(255) | no | Human-readable source commodity name. |
| `hs_code` | string(64) | yes | Generic HS code when available. |
| `hs_revision` | string(32) | no | HS revision/version or `generic` when not source-specific. |
| `commodity_family` | string(100) | no | `soybean`, `soybean_oil`, `rapeseed_meal`, etc. |
| `product_code` | string(100) | yes | Direct product mapping when one exists. |
| `relevance` | string(32) | no | `direct`, `context`, or `later`. |
| `unit_hint` | string(100) | yes | Expected physical quantity unit if known. |
| `is_active` | boolean | no | Allows retirement without deleting metadata. |
| `metadata_json` | JSONB | yes | Source-specific caveats, subcode notes, revision notes. |
| `created_at` | timestamptz | no | Insert time. |
| `updated_at` | timestamptz | no | Last update time. |

Recommended unique constraint:

```text
UNIQUE(code_system, commodity_code, hs_revision)
```

Recommended indexes:

- `commodity_family`;
- `product_code`;
- `hs_code`;
- `is_active`.

`source_id` is nullable because HS mappings can be generic and not tied to a
single source. `metadata_json` should store source-specific caveats instead of
creating many one-off columns.

## Trade Flow Model

Table: `trade_flows`

| field | type | nullable | purpose |
| --- | --- | --- | --- |
| `id` | integer primary key | no | Surrogate key. |
| `source_id` | FK to `sources.id` | no | Trade source, e.g. future `un_comtrade`. |
| `raw_response_id` | FK to `raw_responses.id` | no | Raw response evidence. |
| `collector_run_id` | FK to `collector_runs.id` | no | Collector run that fetched the payload. |
| `trade_commodity_code_id` | FK to `trade_commodity_codes.id` | no | Mapped source/HS commodity code. |
| `source_record_id` | string(255) | yes | Source row ID when provided. |
| `reporter_code` | string(32) | no | Source reporter code. |
| `reporter_name` | string(255) | no | Reporter name. |
| `partner_code` | string(32) | no | Source partner code. |
| `partner_name` | string(255) | no | Partner name. |
| `flow_direction` | string(32) | no | `export`, `import`, `re_export`, `re_import`, or `unknown`. |
| `trade_period` | string(32) | no | Source period label, e.g. `2026-05`. |
| `period_start` | date | no | First date of the trade period. |
| `period_end` | date | no | Last date of the trade period. |
| `frequency` | string(32) | no | `monthly`, `annual`, `quarterly`, or `unknown`. |
| `quantity` | numeric(18, 8) | yes | Source quantity value. |
| `quantity_unit` | string(100) | yes | Source quantity unit. |
| `trade_value_usd` | numeric(18, 8) | yes | Trade value in USD if provided or normalized. |
| `trade_value_local` | numeric(18, 8) | yes | Local/source-currency trade value if provided. |
| `currency` | string(16) | yes | Currency for local/source value. |
| `unit_value_usd` | numeric(18, 8) | yes | Derived value per quantity unit when safe. |
| `net_weight_kg` | numeric(18, 8) | yes | Net weight when provided. |
| `gross_weight_kg` | numeric(18, 8) | yes | Gross weight when provided. |
| `published_at` | timestamptz | yes | Source publication timestamp if available. |
| `fetched_at` | timestamptz | no | UTC time this system fetched the source payload. |
| `source_record_hash` | string(64) | no | Stable normalized-record hash for change detection. |
| `source_payload_hash` | string(64) | no | Raw response SHA-256 copied from `raw_responses.sha256`. |
| `metadata_json` | JSONB | yes | Source fields, flags, estimation notes, code/revision details. |
| `created_at` | timestamptz | no | Insert time. |
| `updated_at` | timestamptz | no | Last update time. |

Allowed `flow_direction` values:

- `export`
- `import`
- `re_export`
- `re_import`
- `unknown`

Allowed `frequency` values:

- `monthly`
- `annual`
- `quarterly`
- `unknown`

Recommended unique constraint:

```text
UNIQUE(source_id, trade_commodity_code_id, reporter_code, partner_code, flow_direction, frequency, period_start, period_end)
```

`source_record_hash` must not be part of uniqueness. The hash detects source
revisions or changed rows for an existing identity. First collector behavior
should skip same-hash rows and write explicit warnings/revision records for
same-identity changed-hash rows; it must not silently overwrite.

Recommended indexes:

- `trade_commodity_code_id, period_start`;
- `reporter_code, period_start`;
- `partner_code, period_start`;
- `flow_direction, period_start`;
- `source_id, fetched_at`;
- `raw_response_id`;
- `collector_run_id`;
- `source_record_hash`.

## Product Trade Code Weights

Table: `product_trade_code_weights`

This table maps project products to source/HS trade codes. It supports direct
and context features without hiding the mapping in code.

| field | type | nullable | purpose |
| --- | --- | --- | --- |
| `id` | integer primary key | no | Surrogate key. |
| `product_id` | FK to `products.id` | no | Project product. |
| `trade_commodity_code_id` | FK to `trade_commodity_codes.id` | no | Trade commodity code. |
| `weight` | numeric(18, 8) | no | Aggregation weight, initially often `1.0`. |
| `relevance` | string(32) | no | `direct`, `context`, or `later`. |
| `role` | string(64) | no | `primary`, `seed_context`, `co_product_context`, `substitute_context`, etc. |
| `effective_from` | date | no | First effective mapping date. |
| `effective_to` | date | yes | Last effective mapping date if retired. |
| `is_active` | boolean | no | Enables controlled retirement. |
| `metadata_json` | JSONB | yes | Mapping rationale, country groups, source caveats. |
| `created_at` | timestamptz | no | Insert time. |
| `updated_at` | timestamptz | no | Last update time. |

Recommended unique constraint:

```text
UNIQUE(product_id, trade_commodity_code_id, role, effective_from)
```

Recommended indexes:

- `product_id, is_active`;
- `trade_commodity_code_id, is_active`;
- `effective_from, effective_to`.

Initial design:

- `soybean_oil` -> HS `1507` direct, HS `1201`/`2304` context;
- `soybean_meal` -> HS `2304` direct, HS `1201`/`1507` context;
- `rapeseed_oil` -> HS `1514` direct, HS `1205`/`2306` context;
- `rapeseed_meal` -> HS `2306` direct, HS `1205`/`1514` context.

## Daily Trade Features

Table: `daily_trade_features`

This table stores precomputed product-level trade aggregates. Monthly trade
rows can be forward-filled to daily feature dates only after publication/fetch
eligibility is satisfied.

| field | type | nullable | purpose |
| --- | --- | --- | --- |
| `id` | integer primary key | no | Surrogate key. |
| `product_id` | FK to `products.id` | no | Project product. |
| `feature_date` | date | no | Product feature date. |
| `export_volume_1m` | numeric(18, 8) | yes | Latest eligible 1-month export volume proxy. |
| `export_volume_3m_avg` | numeric(18, 8) | yes | Eligible 3-month average export volume. |
| `export_volume_12m_sum` | numeric(18, 8) | yes | Eligible 12-month export volume sum. |
| `import_volume_1m` | numeric(18, 8) | yes | Latest eligible 1-month import volume proxy. |
| `import_volume_3m_avg` | numeric(18, 8) | yes | Eligible 3-month average import volume. |
| `import_volume_12m_sum` | numeric(18, 8) | yes | Eligible 12-month import volume sum. |
| `net_export_volume_1m` | numeric(18, 8) | yes | Export minus import proxy. |
| `export_value_usd_1m` | numeric(18, 8) | yes | Latest eligible export value in USD. |
| `import_value_usd_1m` | numeric(18, 8) | yes | Latest eligible import value in USD. |
| `average_export_unit_value_usd` | numeric(18, 8) | yes | Export value divided by quantity when safe. |
| `average_import_unit_value_usd` | numeric(18, 8) | yes | Import value divided by quantity when safe. |
| `china_import_volume_1m` | numeric(18, 8) | yes | China import demand proxy. |
| `major_exporter_volume_1m` | numeric(18, 8) | yes | Major exporter group volume proxy. |
| `major_importer_volume_1m` | numeric(18, 8) | yes | Major importer group volume proxy. |
| `trade_balance_proxy` | numeric(18, 8) | yes | Product-level balance proxy. |
| `trade_yoy_change` | numeric(18, 8) | yes | Year-over-year trade change where enough history exists. |
| `trade_as_of_date` | date | yes | Latest eligible publication/fetch date represented by features. |
| `reporting_lag_days` | integer | yes | Lag between trade period end and as-of date. |
| `missing_flags` | JSONB | yes | Missing source/code/country/window flags. |
| `metadata_json` | JSONB | yes | Source mix, country groups, periods, mapping version. |
| `created_at` | timestamptz | no | Insert time. |
| `updated_at` | timestamptz | no | Last update time. |

Recommended unique constraint:

```text
UNIQUE(product_id, feature_date)
```

Recommended indexes:

- `product_id, feature_date`;
- `feature_date`;
- `trade_as_of_date`.

## Source Seeds Design

Future source seed candidates:

| code | name | category/type | active |
| --- | --- | --- | --- |
| `un_comtrade` | UN Comtrade | trade | true |
| `faostat_trade` | FAOSTAT Trade / Crops and Livestock Products | trade/context | true |
| `usda_fas_trade` | USDA FAS / GATS / PSD Trade Data | official_agriculture_trade | true |
| `world_bank_wits` | World Bank WITS | trade | later or true after manual check |

Phase 6.5B does not change `app/db/seed.py`. Source seeds should be reviewed
and added in Phase 6.5C or the first collector phase.

## Source And Raw Lineage

Every future production trade row must link to:

- `sources.id` through `source_id`;
- `collector_runs.id` through `collector_run_id`;
- `raw_responses.id` through `raw_response_id`;
- the raw payload SHA-256 through `source_payload_hash`;
- a normalized row hash through `source_record_hash`.

Diagnostics artifacts from Phase 6.5A are not production raw evidence. A future
collector must store source API/file responses through the normal `RawStore`,
create `raw_responses`, and only then insert normalized `trade_flows`.

## Deduplication And Idempotency Policy

Recommended trade flow identity:

```text
source_id
trade_commodity_code_id
reporter_code
partner_code
flow_direction
frequency
period_start
period_end
```

First collector policy:

- same identity and same `source_record_hash`: skip;
- same identity and changed `source_record_hash`: write explicit quality
  warning/revision policy and do not silently overwrite;
- malformed rows: write quality diagnostics and fail/partial-success according
  to collector policy;
- never include `source_record_hash` in the unique constraint because that would
  allow duplicate identities when a source revises a row.

## Revision And Change Detection Policy

Trade data can be revised after publication. `source_record_hash` should be
computed from normalized business fields such as quantity, values, weights,
reporter/partner, flow direction, period, and source flags. Technical fields
such as `fetched_at`, `raw_response_id`, and `collector_run_id` should not make
an unchanged business row look revised.

Phase 6.5D can initially record changed-hash warnings and refuse silent
overwrites. A revisions table can be added later if real revisions appear
regularly and the project needs versioned audit history.

## As-Of And Leakage Policy

For realistic ML simulation:

- use only rows with `published_at <= feature_date`;
- strict `as_collected` mode also requires `fetched_at <= feature_date`;
- monthly and annual trade rows have reporting lag and should not be available
  at the start of their period;
- backfilled trade rows must not be treated as known on past feature dates
  unless `historical_backfill_allowed` mode is explicitly selected;
- revisions must be detected by `source_record_hash`;
- future month trade data must never be used for earlier feature dates;
- `trade_as_of_date` must be less than or equal to `feature_date`.

If a source has no reliable `published_at`, the safe default is `fetched_at`
availability.

## Reporting Lag Policy

Trade feature builders should calculate `reporting_lag_days` from the source
period end to the availability date used for the feature. For monthly rows this
usually means:

```text
reporting_lag_days = trade_as_of_date - period_end
```

Publication-aware mode can use `published_at`. Strict as-collected mode should
use `fetched_at`. Missing or unknown publication dates must be represented in
`missing_flags` and metadata.

## Units And Normalization Policy

Store original source units and values in `trade_flows`. Do not discard source
quantity units, source currency, or source flags.

Normalization rules:

- quantities should preserve source units and optionally normalize weights to
  kilograms/metric tons when source data supports it;
- USD values should use source-provided USD fields when available;
- local/source-currency values should be stored separately from USD;
- `unit_value_usd` should be derived only when quantity and value are both
  present, positive, and compatible;
- `metadata_json` should record conversion decisions and unavailable fields.

## Country Reporter Partner Policy

First reporter/partner groups:

- core exporter/reporters: Brazil, United States, Argentina, Canada, Ukraine;
- European Union / France / Germany / Poland if the source supports EU and
  member-state reporting cleanly;
- China as importer/demand proxy;
- world/all partners where the source supports aggregate partner rows;
- selected partners only after the first prototype proves identity and
  deduplication behavior.

Country code systems differ by source. Future schema and collectors should
preserve source country codes and names, and later add normalized country groups
only after the source-specific semantics are reviewed.

Avoid double-counting:

- do not sum world/all-partner aggregate rows together with individual partner
  rows for the same reporter/flow/period;
- do not sum EU aggregate rows with member-state rows without an explicit
  grouping policy;
- store country-group assumptions in feature metadata.

## Future Feature Integration Into Daily Product Features

The first trade feature layer should remain separate from `daily_product_features`.
After controlled validation, `daily_product_features` can receive nullable
columns copied from `daily_trade_features`.

Candidate product-level features:

- `export_volume_1m`;
- `export_volume_3m_avg`;
- `import_volume_1m`;
- `import_volume_3m_avg`;
- `net_export_volume_1m`;
- `china_import_volume_1m`;
- `major_exporter_volume_1m`;
- `average_export_unit_value_usd`;
- `trade_yoy_change`;
- `reporting_lag_days`;
- `trade_as_of_date`;
- `trade_missing_flags`.

Rules:

- product-level mapping uses `product_trade_code_weights`;
- rolling windows use only periods known as-of the feature date;
- monthly trade can be forward-filled daily after publication/fetch
  eligibility;
- missing flags must be explicit.

## Future Export Integration

Export v1 should not include trade columns until:

- trade schema is implemented;
- at least one controlled source collector is validated;
- `daily_trade_features` are built with tested as-of rules;
- feature columns are nullable and carry `trade_as_of_date` plus missing flags;
- export manifests include the updated schema/version metadata.

## Non-Goals

- No migration in Phase 6.5B.
- No Alembic revision in Phase 6.5B.
- No SQLAlchemy model changes in Phase 6.5B.
- No collector in Phase 6.5B.
- No DB writes in Phase 6.5B.
- No scheduler changes in Phase 6.5B.
- No production deploy in Phase 6.5B.
- No ML in Phase 6.5B.
- No targets in Phase 6.5B.
