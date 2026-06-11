# Supply Demand Production Stocks Design

## Executive Summary

Phase 6.7B is a design-only step for a future supply-demand / production-stocks
layer. It does not add an Alembic migration, does not change SQLAlchemy models,
does not write PostgreSQL rows, does not implement a collector, does not change
schedulers, does not add ML targets, and does not add dataset targets.

The proposed layer has five future tables:

- `supply_demand_commodities`: source and project mappings for official
  commodity/metric concepts.
- `supply_demand_observations`: normalized production, consumption, stocks,
  area, yield, crush, import, and export observations by source release.
- `supply_demand_revisions`: audit rows when the same observation identity
  changes value/hash across report vintages.
- `product_supply_demand_weights`: explicit mapping from project products to
  direct/context official supply-demand concepts.
- `daily_supply_demand_features`: product-level daily as-of-safe supply-demand
  features for later copying into `daily_product_features` and export.

Phase 6.7C should implement the reviewed schema only. Phase 6.7D should add the
first controlled USDA PSD collector/prototype. Phase 6.7E should integrate
supply-demand features and export columns only after source, revision, and
as-of rules are reviewed.

## Why Supply-Demand / Production-Stocks Matter For Agricultural Commodity Price Forecasting

Official supply-demand balances describe physical availability and expected
tightness. For oilseed and meal markets, current price snapshots explain what
the market trades today, while production, crush, stocks, exports, imports,
area, and yield explain why price regimes change.

Useful future signals include:

- production volume and production forecast revisions;
- domestic consumption, food use, feed use, and industrial use;
- crush/processing volume that links seeds to oil and meal supply;
- imports, exports, and regional availability;
- beginning stocks, ending stocks, and stock-to-use ratio;
- planted area, harvested area, and yield;
- forecast month, marketing year, report publication date, reporting lag, and
  explicit missing flags.

The layer must be leakage-safe. Report data is often monthly, annual, or
marketing-year based, can describe a future crop year, and can be revised in
later releases. A future dataset row must know which report vintage was
published and fetched by the feature date.

## Current Product Families

The first design is motivated by current production products and close context:

- `soybean`: upstream seed balance and crush context for soybean oil and meal.
- `soybean_oil`: direct oil production, use, trade, and stocks.
- `soybean_meal`: direct meal production, feed use, trade, and stocks.
- `rapeseed/canola`: upstream seed balance and crush context for rapeseed oil
  and meal.
- `rapeseed/canola oil`: direct oil production, use, trade, and stocks.
- `rapeseed/canola meal`: direct meal production, feed use, trade, and stocks.
- `vegetable_oils`: palm oil and sunflowerseed oil as broader substitution
  context after the core layer is proven.

## First Source Decision

The first source prototype should use USDA PSD / FAS PSD Online.

Reasons:

- official global production, supply, and distribution balances;
- strong fit for soybeans, soybean oil, soybean meal, rapeseed/canola,
  rapeseed oil, and rapeseed meal;
- one source can cover production, consumption, crush, trade, and stocks;
- monthly release/vintage behavior is exactly the kind of as-of policy this
  layer needs to model;
- Phase 6.7A classified USDA PSD / FAS PSD Online as the recommended first
  source.

The PSD route still needs a bounded prototype before any production collector is
written. The prototype should verify exact endpoints/download format,
commodity/attribute codes, publication metadata, report vintage behavior,
country coverage, units, and license/citation requirements.

## First Prototype Scope

The first prototype should be intentionally narrow:

- source: USDA PSD / FAS PSD Online;
- commodity concepts: soybeans, soybean oil, soybean meal, rapeseed/canola,
  rapeseed oil, and rapeseed meal;
- metric concepts: production, domestic consumption/use, crush, imports,
  exports, beginning stocks, ending stocks, area, and yield where available;
- geography: world aggregate and a small set of high-value countries/regions
  only after PSD country codes are verified;
- time model: report month/year, marketing year, report publication date, and
  fetched_at must be captured before feature integration;
- request policy: small bounded probes, explicit timeouts, no broad catalog
  crawling, and no production DB writes in the prototype phase.

## Why Not Start With WASDE PDF Parsing Or Country-Specific High-Complexity Sources

WASDE, CONAB Brazil, Argentina official sources, Statistics Canada, Eurostat,
AMIS, and IGC can be valuable, but they are not the best first production
schema driver.

Reasons:

- WASDE is high-value but PDF/text table extraction is more brittle than a
  structured PSD route.
- Country-specific sources vary by language, file type, release calendar,
  geography, and revision policy.
- Commercial or subscription routes such as IGC require explicit licensing.
- Broad scraping would increase operational, storage, and licensing risk.
- A single global PSD-style source is a cleaner way to prove the schema,
  release/vintage model, and as-of policy.

These sources should remain later candidates after the shared schema is
reviewed and one bounded source path is proven.

## Metric Taxonomy

| metric_name | metric_group | expected_frequency | unit | source_candidates | ML value | as-of risk | revision risk |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `production_volume` | production | monthly report / marketing year / annual | source physical unit, normalized later to metric tons where safe | USDA PSD, WASDE, FAOSTAT, NASS, CONAB, Canada | High supply anchor. | Medium: report vintage and publication date are required. | High for forecasts and estimates. |
| `production_forecast_revision` | production | per report vintage | same as production or normalized diff | USDA PSD, WASDE, CONAB | High expectation-change signal. | Medium: must compare only prior known vintages. | High by definition. |
| `domestic_consumption` | consumption_use | monthly report / marketing year / annual | source physical unit | USDA PSD, WASDE, FAOSTAT, AMIS | High direct demand feature. | Medium. | Medium to high. |
| `food_use` | consumption_use | monthly report / marketing year / annual | source physical unit | PSD where available, FAOSTAT food balances | Medium for oil demand composition. | Medium. | Medium. |
| `feed_use` | consumption_use | monthly report / marketing year / annual | source physical unit | PSD/WASDE/FAOSTAT where available | High for meal demand. | Medium. | Medium. |
| `industrial_use` | consumption_use | monthly report / marketing year / annual | source physical unit | PSD/WASDE where available | Medium for biofuel/industrial oil demand. | Medium. | Medium. |
| `crush_volume` | processing | monthly report / marketing year | source physical unit | USDA PSD, WASDE, Canada, Argentina, CONAB | High link from seed to oil/meal supply. | Medium. | High in crop-cycle estimates. |
| `processing_volume` | processing | monthly report / marketing year | source physical unit | USDA PSD, national sources | Medium fallback for non-crush processing labels. | Medium. | Medium. |
| `exports_volume` | trade | monthly report / marketing year / annual | source physical unit | PSD, WASDE, FAOSTAT, AMIS | High availability and demand signal. | Medium: report forecasts differ from trade actuals. | Medium to high. |
| `imports_volume` | trade | monthly report / marketing year / annual | source physical unit | PSD, WASDE, FAOSTAT, AMIS | High for China/import demand proxies. | Medium. | Medium to high. |
| `beginning_stocks` | stocks | monthly report / marketing year | source physical unit | PSD, WASDE, AMIS | Medium carry-in availability signal. | Medium. | High when prior years revise. |
| `ending_stocks` | stocks | monthly report / marketing year | source physical unit | PSD, WASDE, AMIS | High tightness signal. | Medium. | High. |
| `stock_to_use_ratio` | stocks | derived per report vintage | ratio/percent | derived from PSD/WASDE observations | High normalized tightness signal. | Medium: derived inputs must be as-of-safe. | High if stocks or use revise. |
| `planted_area` | area_yield | seasonal / annual | hectares or acres, normalized later | NASS, PSD, FAOSTAT, CONAB, Canada, Eurostat | Medium to high early supply potential. | High: estimates evolve through crop season. | High. |
| `harvested_area` | area_yield | seasonal / annual | hectares or acres, normalized later | NASS, PSD, FAOSTAT, CONAB, Canada, Eurostat | Medium realized production denominator. | High. | High. |
| `yield` | area_yield | seasonal / annual | source yield unit, normalized later | NASS, PSD, FAOSTAT, CONAB, Canada, Eurostat | High crop-size expectation signal. | High. | High. |
| `forecast_month` | report_metadata | monthly | YYYY-MM or integer month/year pair | PSD, WASDE | Medium vintage identity and seasonality. | Low if stored directly. | Low. |
| `marketing_year` | report_metadata | annual marketing year | source marketing-year label | PSD, WASDE, FAOSTAT | High join key and feature context. | Medium: not equivalent to feature date. | Medium. |
| `report_publication_date` | report_metadata | per release | date/timestamp | PSD, WASDE, NASS, FAOSTAT | High leakage guard. | Low if captured; high if missing. | Low. |
| `reporting_lag_days` | report_metadata | derived daily/monthly | days | derived | Medium data freshness/uncertainty signal. | Low when calculated from publication date. | Low. |

## Product-To-Official-Commodity Mapping

| product/family | official commodity concepts | relevance | notes/risk |
| --- | --- | --- | --- |
| `soybean` | Soybeans production, crush, exports, imports, beginning stocks, ending stocks, stock-to-use | context | Upstream seed balance drives soybean oil and soybean meal supply. |
| `soybean_oil` | Soybean Oil production, domestic consumption, food/industrial use, exports, imports, ending stocks | direct | Direct balance item for current product. |
| `soybean_meal` | Soybean Meal production, feed use, exports, imports, ending stocks | direct | Direct meal/feed balance item. |
| `rapeseed_canola` | Rapeseed/Canola production, crush, exports, imports, stocks, stock-to-use | context | Source naming varies by rapeseed/canola/country. |
| `rapeseed_oil` | Rapeseed/Canola Oil production, domestic consumption, exports, imports, ending stocks | direct | Direct product concept; official name needs source-specific mapping. |
| `rapeseed_meal` | Rapeseed/Canola Meal production, feed use, exports, imports, ending stocks | direct | Direct meal concept; official labels need manual check. |
| `palm_oil` | Palm Oil production, use, exports, imports, ending stocks | context | Substitute vegetable oil after core products are proven. |
| `sunflowerseed_oil` | Sunflowerseed Oil production, use, exports, imports, ending stocks | later | Useful later, but current-price production instruments are not confirmed. |
| `corn` | Corn production, feed use, exports, imports, ending stocks | context | Feed/biofuel competition context for meal demand. |

## Proposed Tables

| table | purpose |
| --- | --- |
| `supply_demand_commodities` | Source/project commodity and metric mapping. |
| `supply_demand_observations` | Normalized official balance observations with raw/source lineage. |
| `supply_demand_revisions` | Audit trail for changed observation values/hashes. |
| `product_supply_demand_weights` | Product-level direct/context mapping to official concepts. |
| `daily_supply_demand_features` | Daily product-level derived feature table for later integration. |

The design keeps source mapping, raw observations, revisions, product weights,
and daily derived features separate. Do not write these values into
`daily_product_features` at collection time.

## Supply Demand Commodity Model

Table: `supply_demand_commodities`

| field | type | nullable | purpose |
| --- | --- | --- | --- |
| `id` | integer primary key | no | Surrogate key. |
| `source_id` | FK to `sources.id` | yes | Source owner when mapping is source-specific. |
| `source_commodity_code` | string(100) | yes | Source commodity code when available. |
| `source_commodity_name` | string(255) | no | Source commodity name. |
| `source_metric_code` | string(100) | yes | Source metric/attribute code when available. |
| `source_metric_name` | string(255) | no | Source metric/attribute name. |
| `commodity_family` | string(100) | no | Project family such as `soybean_oil`. |
| `product_code` | string(100) | yes | Direct project product code if one exists. |
| `metric_name` | string(100) | no | Normalized metric name. |
| `metric_group` | string(100) | no | Normalized metric group. |
| `unit_hint` | string(100) | yes | Expected source/normalized unit hint. |
| `frequency` | string(64) | no | Expected source frequency. |
| `relevance` | string(32) | no | `direct`, `context`, or `later`. |
| `is_active` | boolean | no | Enables retirement without deletion. |
| `metadata_json` | JSONB | yes | Source caveats, marketing-year semantics, unit notes. |
| `created_at` | timestamptz | no | Insert time. |
| `updated_at` | timestamptz | no | Last update time. |

`source_id` can be nullable because generic mapping may be created before a
source-specific mapping. USDA PSD mappings should later be source-specific.

Recommended unique constraint:

```text
UNIQUE(source_id, source_commodity_code, source_metric_code, metric_name)
```

Recommended indexes:

- `commodity_family`;
- `product_code`;
- `metric_name`;
- `metric_group`;
- `is_active`.

## Supply Demand Observation Model

Table: `supply_demand_observations`

| field | type | nullable | purpose |
| --- | --- | --- | --- |
| `id` | integer primary key | no | Surrogate key. |
| `source_id` | FK to `sources.id` | no | Supply-demand source, e.g. future `usda_psd`. |
| `raw_response_id` | FK to `raw_responses.id` | no | Raw response evidence. |
| `collector_run_id` | FK to `collector_runs.id` | no | Collector run that fetched the payload. |
| `supply_demand_commodity_id` | FK to `supply_demand_commodities.id` | no | Normalized commodity/metric mapping. |
| `source_record_id` | string(255) | yes | Source row ID when provided. |
| `country_code` | string(32) | no | Source country/region code or `WORLD`. |
| `country_name` | string(255) | no | Source country/region name. |
| `region_code` | string(64) | yes | Optional region/subregion code. |
| `region_name` | string(255) | yes | Optional region/subregion name. |
| `marketing_year` | string(32) | no | Source marketing-year label. |
| `marketing_year_start` | date | yes | Estimated/known start date. |
| `marketing_year_end` | date | yes | Estimated/known end date. |
| `report_month` | integer | no | Report/vintage month. |
| `report_year` | integer | no | Report/vintage year. |
| `report_published_at` | timestamptz | yes | Source publication timestamp/date. |
| `observed_period_start` | date | yes | Period represented by the value. |
| `observed_period_end` | date | yes | End of period represented by the value. |
| `frequency` | string(32) | no | `monthly_report`, `marketing_year`, `annual`, `quarterly`, or `unknown`. |
| `estimate_type` | string(32) | no | `actual`, `estimate`, `forecast`, `projection`, or `unknown`. |
| `metric_value` | numeric(18, 8) | no | Normalized metric value in `metric_unit`. |
| `metric_unit` | string(100) | no | Unit for metric value. |
| `value_usd` | numeric(18, 8) | yes | Optional value in USD if source provides monetary rows later. |
| `is_forecast` | boolean | no | True for forecast/projection rows. |
| `is_revision` | boolean | no | True when row was detected as changed from prior version. |
| `published_at` | timestamptz | yes | Availability timestamp used by feature builders. |
| `fetched_at` | timestamptz | no | UTC time this system fetched the payload. |
| `source_record_hash` | string(64) | no | Stable normalized-record hash for change detection. |
| `source_payload_hash` | string(64) | no | Raw response SHA-256 copied from `raw_responses.sha256`. |
| `metadata_json` | JSONB | yes | Source fields, units, parser version, caveats. |
| `created_at` | timestamptz | no | Insert time. |
| `updated_at` | timestamptz | no | Last update time. |

Allowed `estimate_type` values:

- `actual`
- `estimate`
- `forecast`
- `projection`
- `unknown`

Allowed `frequency` values:

- `monthly_report`
- `marketing_year`
- `annual`
- `quarterly`
- `unknown`

Recommended unique constraint:

```text
UNIQUE(source_id, supply_demand_commodity_id, country_code, marketing_year, report_year, report_month, estimate_type)
```

`source_record_hash` must not be part of uniqueness. It detects changed
estimates/revisions for an existing observation identity.

Recommended indexes:

- `supply_demand_commodity_id, marketing_year`;
- `country_code, marketing_year`;
- `report_published_at`;
- `published_at`;
- `fetched_at`;
- `raw_response_id`;
- `collector_run_id`;
- `source_record_hash`.

## Supply Demand Revision Model

Table: `supply_demand_revisions`

Purpose: preserve old and new values when the same observation identity changes.

| field | type | nullable | purpose |
| --- | --- | --- | --- |
| `id` | integer primary key | no | Surrogate key. |
| `supply_demand_observation_id` | FK to `supply_demand_observations.id` | no | Observation being revised. |
| `revision_number` | integer | no | Monotonic number per observation. |
| `old_metric_value` | numeric(18, 8) | yes | Previous value. |
| `new_metric_value` | numeric(18, 8) | yes | Incoming value. |
| `old_source_record_hash` | string(64) | no | Previous normalized hash. |
| `new_source_record_hash` | string(64) | no | Incoming normalized hash. |
| `revision_reason` | string(64) | no | Reason category. |
| `detected_at` | timestamptz | no | Time collector detected the change. |
| `metadata_json` | JSONB | yes | Field-level diff and policy decision. |
| `created_at` | timestamptz | no | Insert time. |

Recommended unique constraint:

```text
UNIQUE(supply_demand_observation_id, revision_number)
```

Recommended revision reasons:

- `source_revision`
- `report_restatement`
- `corrected_estimate`
- `parser_change`
- `unknown`

## Product Supply Demand Weights Model

Table: `product_supply_demand_weights`

Purpose: map project products to official commodity/metric concepts and allow
direct/context/later aggregation.

| field | type | nullable | purpose |
| --- | --- | --- | --- |
| `id` | integer primary key | no | Surrogate key. |
| `product_id` | FK to `products.id` | no | Project product. |
| `supply_demand_commodity_id` | FK to `supply_demand_commodities.id` | no | Official concept. |
| `weight` | numeric(18, 8) | no | Aggregation weight. |
| `relevance` | string(32) | no | `direct`, `context`, or `later`. |
| `role` | string(64) | no | `direct_balance`, `seed_context`, `substitute_context`, etc. |
| `effective_from` | date | no | Start of mapping validity. |
| `effective_to` | date | yes | End of mapping validity. |
| `is_active` | boolean | no | Enables retirement without deletion. |
| `metadata_json` | JSONB | yes | Rationale and source-specific notes. |
| `created_at` | timestamptz | no | Insert time. |
| `updated_at` | timestamptz | no | Last update time. |

Recommended unique constraint:

```text
UNIQUE(product_id, supply_demand_commodity_id, role, effective_from)
```

Initial design:

- `soybean_oil`: soybean oil production/consumption/exports/imports direct;
  soybean crush context.
- `soybean_meal`: soybean meal production/feed use/exports/imports direct;
  soybean crush context.
- `rapeseed_oil`: rapeseed/canola oil production/consumption/exports/imports
  direct; rapeseed/canola crush context.
- `rapeseed_meal`: rapeseed/canola meal production/feed use/exports/imports
  direct; rapeseed/canola crush context.

## Daily Supply Demand Feature Model

Table: `daily_supply_demand_features`

Purpose: precomputed product-level supply-demand features. This table is not a
collector output table. It is a future feature-builder output that can later be
copied into `daily_product_features`.

| field | type | nullable | purpose |
| --- | --- | --- | --- |
| `id` | integer primary key | no | Surrogate key. |
| `product_id` | FK to `products.id` | no | Project product. |
| `feature_date` | date | no | Feature date. |
| `production_volume` | numeric(18, 8) | yes | Latest as-of production value. |
| `domestic_consumption` | numeric(18, 8) | yes | Latest as-of domestic use. |
| `food_use` | numeric(18, 8) | yes | Latest as-of food use. |
| `feed_use` | numeric(18, 8) | yes | Latest as-of feed use. |
| `crush_volume` | numeric(18, 8) | yes | Latest as-of crush/processing value. |
| `exports_volume` | numeric(18, 8) | yes | Latest as-of exports value. |
| `imports_volume` | numeric(18, 8) | yes | Latest as-of imports value. |
| `beginning_stocks` | numeric(18, 8) | yes | Latest as-of beginning stocks. |
| `ending_stocks` | numeric(18, 8) | yes | Latest as-of ending stocks. |
| `stock_to_use_ratio` | numeric(18, 8) | yes | Derived tightness ratio. |
| `planted_area` | numeric(18, 8) | yes | Latest as-of planted area. |
| `harvested_area` | numeric(18, 8) | yes | Latest as-of harvested area. |
| `yield_value` | numeric(18, 8) | yes | Latest as-of yield. |
| `production_forecast_revision` | numeric(18, 8) | yes | Revision delta. |
| `ending_stocks_revision` | numeric(18, 8) | yes | Revision delta. |
| `stock_to_use_revision` | numeric(18, 8) | yes | Revision delta. |
| `forecast_month` | integer | yes | Report forecast month. |
| `marketing_year` | string(32) | yes | Source marketing-year label. |
| `report_published_at` | timestamptz | yes | Report vintage used. |
| `supply_demand_as_of_date` | date | yes | Feature availability date. |
| `reporting_lag_days` | integer | yes | Lag between report date and feature date. |
| `missing_flags` | JSONB | yes | Explicit missingness flags. |
| `metadata_json` | JSONB | yes | Builder details and selected observation IDs. |
| `created_at` | timestamptz | no | Insert time. |
| `updated_at` | timestamptz | no | Last update time. |

Recommended unique constraint:

```text
UNIQUE(product_id, feature_date)
```

Recommended indexes:

- `product_id, feature_date`;
- `feature_date`;
- `supply_demand_as_of_date`;
- `marketing_year`.

## Source/Raw Lineage

Future production collectors must use normal production raw evidence:

- store raw payloads through `RawStore`;
- insert `raw_responses`;
- link normalized `supply_demand_observations` through `raw_response_id`;
- record collector run metadata through `collector_runs`;
- copy `raw_responses.sha256` into `source_payload_hash`;
- create stable `source_record_hash` from normalized row identity/value fields.

Diagnostics artifacts from Phase 6.7A and the SQL draft from Phase 6.7B are not
production raw evidence.

## Deduplication/Idempotency Policy

- Same observation identity plus same `source_record_hash`: skip.
- Same observation identity plus changed `source_record_hash`: do not silently
  overwrite.
- The first controlled collector may warn and avoid overwrite until revision
  policy is implemented.
- A revision-aware collector should create `supply_demand_revisions`, preserve
  old/new values, and update the main observation only according to a reviewed
  policy.
- Raw evidence must be retained for every source response.

The observation unique key should model source identity and report vintage, not
record hash:

```text
source_id + supply_demand_commodity_id + country_code + marketing_year + report_year + report_month + estimate_type
```

## Revision/Change Detection Policy

Official supply-demand rows can change because of source revisions, corrected
estimates, report restatements, or parser changes. Revisions are expected and
should become explicit data, not silent mutation.

Recommended first policy:

- same key and same hash: skip;
- same key and changed hash: write quality warning and stop short of overwrite
  until `supply_demand_revisions` is implemented;
- after revisions are implemented: write old/new value and hash to
  `supply_demand_revisions`, then update the main row only if the source policy
  allows latest-known value storage;
- feature builders should select the latest known-as-of estimate, not the latest
  estimate available today.

## As-Of/Leakage Policy

Rules:

- Use only estimates/reports with `report_published_at <= feature_date`.
- In strict `as_collected` mode, also require `fetched_at <= feature_date`.
- `supply_demand_as_of_date <= feature_date` must hold in daily features.
- Marketing year is not the feature date.
- Forecasts for future marketing years may be known if published before
  `feature_date`, but they must be labeled `is_forecast=true`.
- Later PSD/WASDE revisions must not overwrite past feature values silently.
- Historical backfill must be labeled by export/feature mode:
  `historical_backfill_allowed`, `publication_aware`, or `as_collected`.
- Do not use future WASDE/PSD revisions for earlier features.

## Marketing Year Policy

Marketing-year labels are source-specific and must not be treated as calendar
dates. Store the source label in `marketing_year`, plus optional
`marketing_year_start` and `marketing_year_end` when the source or a reviewed
mapping provides them.

Daily features should forward-fill a report's marketing-year value only after
the report is published/fetched and only while that value is still the latest
known-as-of value for the selected product mapping.

## Forecast Vs Actual Policy

Use `estimate_type` and `is_forecast` to separate actuals, estimates,
forecasts, projections, and unknown source rows.

- Forecast rows can describe future marketing years and still be valid features
  if the report was already published by `feature_date`.
- Actual rows are not automatically safer; they can still be revised later.
- Feature/export consumers should be able to distinguish forecast-derived
  features from actual-derived features.

## Units And Normalization Policy

Store source units in `metric_unit` and mapping hints in `unit_hint`. Normalize
only when the source unit and conversion are unambiguous.

Recommended initial policy:

- keep source physical units in observations;
- record source unit names and parser notes in `metadata_json`;
- derive normalized metric-ton features only after unit mapping tests exist;
- do not mix acres/hectares or short tons/metric tons without explicit
  conversion metadata;
- keep `value_usd` optional for later monetary rows, not core PSD balance rows.

## Country/Geography Policy

PSD and official balance sources may use countries, regions, world aggregates,
and special groups. Store both `country_code`/`country_name` and optional
`region_code`/`region_name`.

Recommended first scope:

- start with `WORLD` and a small set of manually reviewed countries;
- avoid aggregating regions and countries together unless the mapping says so;
- document China/import demand, Brazil/US/Argentina soybean supply, and
  Canada/EU/Ukraine rapeseed/canola context as later product-weight decisions;
- never infer geography from product name alone.

## Source Seed Design

Phase 6.7B does not change seed data. Future seed candidates:

| source code | name | category/type | active policy |
| --- | --- | --- | --- |
| `usda_psd` | USDA PSD / FAS PSD Online | `supply_demand` | active first source after prototype. |
| `usda_wasde` | USDA WASDE | `official_report` | active later/manual after PDF/text policy. |
| `faostat_supply_demand` | FAOSTAT Production / Food Balance | `supply_demand_context` | active later context source. |
| `usda_nass_quickstats` | USDA NASS Quick Stats | `area_yield_production` | active later/manual after API key policy. |

No source seed is added in Phase 6.7B.

## Future Feature Integration Into `daily_product_features`

Nearest-term behavior:

- no change to `daily_product_features` in Phase 6.7B;
- no supply-demand columns are added yet;
- no feature builder is implemented yet.

Future behavior:

- build `daily_supply_demand_features` first;
- copy selected nullable columns into `daily_product_features` only after
  schema and as-of policy are implemented;
- use `product_supply_demand_weights` to map official concepts to products;
- forward-fill report/marketing-year rows daily only after publication/fetch;
- keep `missing_flags` explicit;
- add revision-aware features later, not during initial collection.

Candidate future product-level columns:

- `production_volume`
- `domestic_consumption`
- `crush_volume`
- `exports_volume`
- `imports_volume`
- `ending_stocks`
- `stock_to_use_ratio`
- `planted_area`
- `harvested_area`
- `yield_value`
- `production_forecast_revision`
- `ending_stocks_revision`
- `stock_to_use_revision`
- `reporting_lag_days`
- `supply_demand_as_of_date`
- `supply_demand_missing_flags`

## Future Export Integration

Export v1 should not add supply-demand columns until Phase 6.7E or later. When
added, export columns should be nullable, documented in `DATASET_DICTIONARY.md`,
and linked in `SOURCE_TO_FEATURE_LINEAGE.md`.

Future export manifests should preserve:

- source code and release/vintage metadata;
- feature-mode flag: `as_collected`, `publication_aware`, or
  `historical_backfill_allowed`;
- data completeness/missing flags.

## Future Phases

- Phase 6.7C: supply-demand schema-only implementation and tests.
- Phase 6.7D: first controlled USDA PSD collector/prototype.
- Phase 6.7E: supply-demand daily features and export integration.

## Non-Goals

- No migration in Phase 6.7B.
- No Alembic revision in Phase 6.7B.
- No SQLAlchemy model changes in Phase 6.7B.
- No collector in Phase 6.7B.
- No DB writes in Phase 6.7B.
- No scheduler changes in Phase 6.7B.
- No ML in Phase 6.7B.
- No targets in Phase 6.7B.
- No production deploy in Phase 6.7B.
