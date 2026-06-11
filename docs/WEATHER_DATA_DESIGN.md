# Weather Data Design

## Executive Summary

Phase 6.3B is a design-only step for a future weather data layer. It does not
add an Alembic migration, does not change SQLAlchemy models, does not write
PostgreSQL rows, does not implement a collector, does not change schedulers,
and does not add ML targets.

The proposed layer has four future tables:

- `weather_regions`: stable crop-weather region metadata and coordinates.
- `weather_observations`: source-backed daily weather observations by region.
- `weather_daily_features`: precomputed rolling weather aggregates by
  region/date.
- `product_weather_region_weights`: an explicit mapping from products to
  weather regions.

Phase 6.3C should implement the schema only. Phase 6.3D should add the first
controlled/manual weather collector. Phase 6.3E should integrate weather
features and export columns only after as-of rules are reviewed.

Phase 6.3C implements SQLAlchemy metadata, Alembic revision
`0012_weather_schema`, idempotent source seeds for Open-Meteo and NASA POWER,
initial weather region seeds, and operational reporting for empty weather
tables. It still does not implement a weather collector, does not write weather
observation rows, does not register a scheduler, and does not add ML targets.

Phase 6.3D implements the first controlled/manual collector for Open-Meteo
Historical Weather API. It writes production raw evidence and normalized
`weather_observations`, but it still does not register a scheduler, does not
aggregate weather features, and does not add product-level weather export
columns.

Phase 6.3E implements local/manual aggregation from `weather_observations` into
`weather_daily_features`. It remains region-level feature engineering only:
product-level weather columns and export integration are deferred to a later
phase.

## Why Weather Matters For Agricultural Commodity Forecasting

Weather affects yield expectations, harvest timing, crop stress, export supply,
crush margins, and replacement demand. The current dataset already contains
current product prices, FX, historical bars, energy factors, and global
commodity benchmarks. Weather adds a crop-condition layer for oilseed supply
risk.

Useful signals include:

- precipitation deficits and excess rain;
- heat stress during growing and pod-fill periods;
- frost risk;
- accumulated temperature and growing degree days;
- drought proxies from precipitation, evapotranspiration, and soil moisture;
- regional weather aggregation across production/export regions.

The layer must be leakage-safe: future weather values must never enter features
for earlier `feature_date` rows.

## Current Commodity Families

Current products that motivate the first weather design:

- `soybean`: `soybean_oil`, `soybean_meal`;
- `rapeseed/canola`: `rapeseed_oil`, `rapeseed_meal`.

The first region set should focus on soybean regions in Brazil, the United
States, and Argentina, plus canola/rapeseed regions in Canada, Europe, and the
Black Sea area.

## First Source Decision

The first source prototype should be Open-Meteo Historical Weather API.

Reasons:

- no project secret or API key is needed for the first prototype;
- point-coordinate daily weather fits the initial centroid-region approach;
- response size is suitable for bounded regional/date windows;
- JSON/CSV access is simpler than gridded reanalysis files;
- Phase 6.3A classified it as the recommended first source.

Open-Meteo should still be reviewed for terms, attribution, and stable variable
names before production export use.

## Secondary Candidate

NASA POWER is the strongest second candidate. It can provide agroclimatology
variables such as radiation and evapotranspiration, also without an API key.
NASA POWER is useful either as a fallback source or as a complement when
Open-Meteo does not provide an agricultural variable needed by the feature
builder.

## Why Not Start With ERA5/Copernicus

ERA5/Copernicus is rich and valuable, but it is not the right first production
weather source.

Reasons:

- account/API workflow is more complex;
- NetCDF/GRIB/gridded payloads are much larger;
- spatial aggregation, storage, and retention policy need more design;
- first value can be proven faster with bounded point-source weather.

ERA5 should remain a later high-complexity candidate after the basic weather
schema, raw lineage, and feature integration are stable.

## Proposed Tables

The weather layer should be explicit and normalized instead of embedding raw
weather columns directly into `daily_product_features` at collection time.

Proposed tables:

| table | purpose |
| --- | --- |
| `weather_regions` | Stable crop-weather regions and representative coordinates. |
| `weather_observations` | Raw daily weather observations by source/region/date. |
| `weather_daily_features` | Rolling/weather stress aggregates by region/date. |
| `product_weather_region_weights` | Mapping from products to relevant weather regions and weights. |

This keeps source data, regional aggregation, and product-level joins separate.

## Region Model

Table: `weather_regions`

| field | type | nullable | purpose |
| --- | --- | --- | --- |
| `id` | integer primary key | no | Surrogate key. |
| `region_code` | string(100) | no | Stable internal code, e.g. `br_mato_grosso_soybean`. |
| `region_name` | string(255) | no | Human-readable region name. |
| `country` | string(100) | no | Country name. |
| `country_code` | string(2) | yes | ISO-like country code when useful. |
| `crop` | string(100) | no | Crop, e.g. `soybean`, `canola`, `rapeseed`. |
| `commodity_family` | string(100) | no | `soybean`, `rapeseed`, or future family. |
| `role` | string(100) | no | `production`, `export`, `processing`, `import_demand`, or combined documented role. |
| `priority` | string(32) | no | `high`, `medium`, or `later`. |
| `latitude` | numeric(10, 6) | no | Representative coordinate. |
| `longitude` | numeric(10, 6) | no | Representative coordinate. |
| `spatial_model` | string(64) | no | `point_proxy`, `centroid`, `multi_point_later`, or `grid_later`. |
| `aggregation_strategy` | string(100) | no | `single_point`, `mean_of_points_later`, or `weighted_region_later`. |
| `is_active` | boolean | no | Enables controlled retirement without deleting metadata. |
| `metadata_json` | JSONB | yes | Source notes, provenance, crop calendar hints, and future polygon references. |
| `created_at` | timestamptz | no | Insert time. |
| `updated_at` | timestamptz | no | Last update time. |

Recommended region codes:

- `br_mato_grosso_soybean`
- `br_parana_soybean`
- `us_iowa_soybean`
- `us_illinois_soybean`
- `ar_pampas_soybean`
- `ca_saskatchewan_canola`
- `ca_alberta_canola`
- `ca_manitoba_canola`
- `eu_france_rapeseed`
- `eu_germany_rapeseed`
- `eu_poland_rapeseed`
- `ua_black_sea_rapeseed`
- `cn_hubei_rapeseed`

Recommended unique constraint:

```text
UNIQUE(region_code)
```

Recommended indexes:

- `region_code`;
- `country, crop`;
- `commodity_family`;
- `is_active`;
- `priority`.

## Observation Model

Table: `weather_observations`

| field | type | nullable | purpose |
| --- | --- | --- | --- |
| `id` | integer primary key | no | Surrogate key. |
| `source_id` | FK to `sources.id` | no | Future weather source, e.g. `open_meteo_historical_weather`. |
| `raw_response_id` | FK to `raw_responses.id` | no | Raw response evidence. |
| `collector_run_id` | FK to `collector_runs.id` | no | Collector run that fetched the weather payload. |
| `region_id` | FK to `weather_regions.id` | no | Weather region. |
| `source_region_key` | string(255) | no | Source-specific coordinate, station, or grid key. |
| `observation_date` | date | no | Local date represented by the weather row. |
| `observed_at` | timestamptz | no | UTC timestamp representation of `observation_date`. |
| `fetched_at` | timestamptz | no | UTC time this system fetched the source payload. |
| `frequency` | string(32) | no | Initially `daily`; future controlled values can be added later. |
| `temperature_2m_mean` | numeric(18, 8) | yes | Daily mean temperature. |
| `temperature_2m_min` | numeric(18, 8) | yes | Daily minimum temperature. |
| `temperature_2m_max` | numeric(18, 8) | yes | Daily maximum temperature. |
| `precipitation_sum` | numeric(18, 8) | yes | Daily precipitation. |
| `snowfall_sum` | numeric(18, 8) | yes | Daily snowfall if source supports it. |
| `relative_humidity_mean` | numeric(18, 8) | yes | Daily mean relative humidity if available. |
| `wind_speed_mean` | numeric(18, 8) | yes | Daily mean wind speed. |
| `wind_speed_max` | numeric(18, 8) | yes | Daily max wind speed. |
| `soil_moisture` | numeric(18, 8) | yes | Source-specific soil moisture value. |
| `evapotranspiration` | numeric(18, 8) | yes | ET or ET0 value when available. |
| `shortwave_radiation` | numeric(18, 8) | yes | Daily radiation value. |
| `source_record_hash` | string(64) | no | Stable normalized-record hash for idempotency/change detection. |
| `source_payload_hash` | string(64) | no | Raw response SHA-256 copied from `raw_responses.sha256`. |
| `metadata_json` | JSONB | yes | Units, source variable names, model, station, grid, parser version. |
| `created_at` | timestamptz | no | Insert time. |
| `updated_at` | timestamptz | no | Last update time. |

Recommended unique constraint:

```text
UNIQUE(source_id, region_id, observation_date, frequency)
```

Do not include `source_record_hash` in the unique constraint. The hash is a
change detector, not part of row identity. Including it would allow duplicates
when a source revises a value for the same source/region/date/frequency.

First collector idempotency policy:

- same unique key and same hash: skip;
- same unique key and changed hash: write a quality warning and do not silently
  overwrite in the first weather collector;
- add a revisions table later only if real source mutability appears.

Recommended indexes:

- `region_id, observation_date`;
- `source_id, observation_date`;
- `fetched_at`;
- `raw_response_id`;
- `collector_run_id`;
- `source_record_hash`.

## Aggregation Model

Table: `weather_daily_features`

Purpose: precompute weather aggregations by region/date before product-level
joining. This avoids recalculating rolling windows repeatedly during dataset
export and keeps region-level missingness visible.

| field | type | nullable | purpose |
| --- | --- | --- | --- |
| `id` | integer primary key | no | Surrogate key. |
| `region_id` | FK to `weather_regions.id` | no | Region being aggregated. |
| `feature_date` | date | no | Date for which rolling features are available. |
| `temperature_7d_mean` | numeric(18, 8) | yes | Mean temperature over previous 7 days including `feature_date`. |
| `temperature_30d_mean` | numeric(18, 8) | yes | Mean temperature over previous 30 days including `feature_date`. |
| `temperature_min_7d` | numeric(18, 8) | yes | Minimum temperature over previous 7 days. |
| `temperature_max_7d` | numeric(18, 8) | yes | Maximum temperature over previous 7 days. |
| `precipitation_7d_sum` | numeric(18, 8) | yes | Rolling precipitation sum. |
| `precipitation_14d_sum` | numeric(18, 8) | yes | Rolling precipitation sum. |
| `precipitation_30d_sum` | numeric(18, 8) | yes | Rolling precipitation sum. |
| `heat_stress_days_7d` | integer | yes | Count of heat-stress days. |
| `heat_stress_days_30d` | integer | yes | Count of heat-stress days. |
| `frost_days_7d` | integer | yes | Count of frost days. |
| `frost_days_30d` | integer | yes | Count of frost days. |
| `drought_proxy_30d` | numeric(18, 8) | yes | Simple drought proxy from precipitation/ET/soil moisture. |
| `growing_degree_days_7d` | numeric(18, 8) | yes | Rolling GDD. |
| `growing_degree_days_30d` | numeric(18, 8) | yes | Rolling GDD. |
| `weather_as_of_date` | date | yes | Latest observation date used by the aggregate row. |
| `missing_flags` | JSONB | yes | Explicit missing variable/window flags. |
| `metadata_json` | JSONB | yes | Thresholds, base temperature, source coverage notes. |
| `created_at` | timestamptz | no | Insert time. |
| `updated_at` | timestamptz | no | Last update time. |

Recommended unique constraint:

```text
UNIQUE(region_id, feature_date)
```

Rolling windows must use only weather observations with
`observation_date <= feature_date`.

## Commodity-Region Mapping Design

Weather regions should not be blindly joined to every product. Soybean products
need soybean regions; rapeseed products need canola/rapeseed regions. A mapping
layer also lets later phases encode production/export importance.

Future table: `product_weather_region_weights`

| field | type | nullable | purpose |
| --- | --- | --- | --- |
| `id` | integer primary key | no | Surrogate key. |
| `product_id` | FK to `products.id` | no | Commodity product. |
| `region_id` | FK to `weather_regions.id` | no | Relevant weather region. |
| `weight` | numeric(18, 8) | no | Product-region weight; first version can use equal weights. |
| `role` | string(100) | no | `production`, `export`, `processing`, or `import_demand`. |
| `effective_from` | date | no | Start date for the mapping. |
| `effective_to` | date | yes | End date; nullable for active mapping. |
| `is_active` | boolean | no | Enables controlled retirement. |
| `metadata_json` | JSONB | yes | Weight source, assumptions, and notes. |
| `created_at` | timestamptz | no | Insert time. |
| `updated_at` | timestamptz | no | Last update time. |

Recommended first policy:

- soybean oil and soybean meal use high-priority soybean regions;
- rapeseed oil and rapeseed meal use high-priority canola/rapeseed regions;
- first version can use equal weights across high-priority regions;
- future versions can weight by production/export share.

## Source And Raw Lineage

Every production `weather_observations` row must link to:

- `sources.id` through `source_id`;
- `collector_runs.id` through `collector_run_id`;
- `raw_responses.id` through `raw_response_id`;
- the raw payload SHA-256 through `source_payload_hash`.

Diagnostics artifacts from Phase 6.3A are not production raw evidence. A future
collector must store weather source responses through the normal `RawStore` and
create `raw_responses` before inserting normalized weather rows.

## Date Alignment And As-Of/Leakage Policy

Weather features must be aligned by date and availability.

Rules:

- for a commodity `feature_date`, use only weather with
  `observation_date <= feature_date`;
- rolling windows use only past days and the current feature date;
- no future leakage is allowed from later weather observations;
- `fetched_at` controls availability in realistic as-collected simulations;
- historical backfill can be allowed only in an explicitly named research mode;
- `weather_as_of_date` should record the latest weather observation used;
- missing or partial weather coverage must be represented in `missing_flags`.

If weather for 2026-05-20 is fetched on 2026-06-01, a real-time simulation for
2026-05-21 must not treat that value as available unless the export mode
explicitly allows historical backfill.

## Units And Normalization Policy

Store source values in normalized project columns, but preserve source unit
notes in `metadata_json`.

Recommended conventions:

- temperature: Celsius;
- precipitation and snowfall: millimeters per day;
- wind speed: meters per second or kilometers per hour, explicitly recorded;
- radiation: source unit recorded, likely MJ/m2 or W/m2-derived daily value;
- evapotranspiration: millimeters per day;
- soil moisture: source-defined unit and depth must be recorded.

If a source uses different units, conversion must happen before inserting
`weather_observations`, and the conversion must be documented and tested.

## Missingness Policy

Weather data will be incomplete for some variables, regions, or dates. Missing
values should be explicit rather than silently filled.

Policy:

- nullable metric columns are allowed because sources differ in coverage;
- missing windows should set `missing_flags` in `weather_daily_features`;
- product-level weather features should carry a `weather_missing_flags` field;
- do not forward-fill precipitation or stress counts without a specific design;
- temperature short gaps may be handled later, but not in Phase 6.3B.

## Rate Limit And Storage Policy

First prototype scope should stay bounded:

- source: Open-Meteo Historical Weather API;
- spatial model: centroid point proxies;
- regions: initial high-priority regions from Phase 6.3A;
- frequency: daily;
- date windows: controlled ranges;
- HTTP timeout and user-agent required in the later collector;
- raw responses stored once per source request via `RawStore`;
- no broad weather crawling.

NASA POWER can be added after Open-Meteo if the source variables or terms make
it useful. ERA5/Copernicus should wait for explicit storage and gridded
aggregation design.

## Future Feature Integration Into `daily_product_features`

Phase 6.3B does not change `daily_product_features`.

Future product-level fields may include:

- `weather_soybean_precipitation_30d_weighted`;
- `weather_soybean_temperature_30d_weighted`;
- `weather_soybean_heat_stress_days_30d`;
- `weather_rapeseed_precipitation_30d_weighted`;
- `weather_rapeseed_frost_days_30d`;
- `weather_drought_proxy_30d`;
- `weather_as_of_date`;
- `weather_missing_flags`.

Feature builder rule:

1. Build or read `weather_daily_features` by region/date.
2. Join product to regions through `product_weather_region_weights`.
3. Use only region features with `feature_date <= product feature_date`.
4. Weight region values according to the mapping table.
5. Write explicit missing flags when region coverage is incomplete.

## Future Export Integration

Dataset export v1 should not include weather fields until Phase 6.3E explicitly
adds them to `daily_product_features` and documents the as-of policy.

When weather export integration is added, the manifest should list:

- source tables: `weather_regions`, `weather_observations`,
  `weather_daily_features`, and `product_weather_region_weights`;
- first source: `open_meteo_historical_weather`;
- region mapping version;
- whether historical backfill was allowed.

No weather-derived targets should be created.

## Source Seed Design

Phase 6.3B does not change seed data. Future source seeds:

```text
code: open_meteo_historical_weather
name: Open-Meteo Historical Weather API
source_type/category: weather
is_active: true
```

```text
code: nasa_power_weather
name: NASA POWER Weather / Agroclimatology
source_type/category: weather
is_active: true
```

The first production collector should seed only the source it uses unless a
later phase explicitly approves both.

## Migration Plan For Later Phases

Phase 6.3C should add:

- SQLAlchemy metadata for `weather_regions`, `weather_observations`,
  `weather_daily_features`, and `product_weather_region_weights`;
- a non-destructive Alembic migration;
- idempotent seed readiness for `open_meteo_historical_weather`;
- operational report counts for empty weather tables.

Phase 6.3C must not write weather data rows or register a scheduler.

## Phase 6.3C Schema Implementation

Phase 6.3C adds:

- `WeatherRegion`;
- `WeatherObservation`;
- `WeatherDailyFeature`;
- `ProductWeatherRegionWeight`;
- Alembic revision `0012_weather_schema`;
- source seeds for `open_meteo_historical_weather` and `nasa_power_weather`;
- 14 first-version point-proxy weather region seeds;
- operational report sections for weather regions, observations, daily
  features, and product-region weights.

The existing early `weather_observations` skeleton from the initial schema is
expanded to the reviewed model. Legacy skeleton columns are left nullable for
compatibility, while future collector inserts should use the new region-linked
columns.

Phase 6.3C does not create a collector, does not run collectors, does not write
weather observations, does not change schedulers, and does not add weather
columns to `daily_product_features`.

## Phase 6.3D Open-Meteo Collector

Phase 6.3D adds a manual-only collector named
`open_meteo_historical_weather`. It uses Open-Meteo Historical Weather API:

```text
https://archive-api.open-meteo.com/v1/archive
```

The collector accepts an explicit date range and an optional seeded
`weather_regions.region_code`. If no region is supplied, it collects active
regions; longer windows are limited to high/medium priority regions. A single
manual run is capped at 45 inclusive days.

Example one-region run:

```bash
python scripts/run_collector.py open_meteo_historical_weather \
  --region br_mato_grosso_soybean \
  --from-date 2026-05-01 \
  --to-date 2026-05-10
```

Example small all-region run:

```bash
python scripts/run_collector.py open_meteo_historical_weather \
  --from-date 2026-05-01 \
  --to-date 2026-05-03
```

Requested daily variables:

- `temperature_2m_mean`;
- `temperature_2m_min`;
- `temperature_2m_max`;
- `precipitation_sum`;
- `rain_sum`;
- `snowfall_sum`;
- `relative_humidity_2m_mean`;
- `wind_speed_10m_mean`;
- `wind_speed_10m_max`;
- `shortwave_radiation_sum`;
- `et0_fao_evapotranspiration`.

Mapped `weather_observations` fields:

- temperature mean/min/max;
- precipitation sum;
- snowfall sum;
- relative humidity mean;
- wind speed mean/max;
- evapotranspiration;
- shortwave radiation.

`rain_sum` is retained as source metadata for now. If optional variables are
missing or unsupported in a response, the collector stores `NULL` in the mapped
column and records the missing variable names in `metadata_json`.

Raw evidence policy:

- one Open-Meteo response is saved through `RawStore` per region request;
- every `weather_observations` row links to `raw_response_id` and
  `collector_run_id`;
- diagnostics artifacts are not production raw evidence.

Idempotency policy:

- business key:
  `source_id + region_id + observation_date + frequency`;
- same `source_record_hash`: skip;
- changed `source_record_hash`: write
  `weather_existing_observation_hash_changed`, increment conflicts, and do not
  overwrite in Phase 6.3D.

Quality checks include raw response presence, content type, daily arrays,
parsed rows, observation date, core values, source hash, raw linkage, and
changed-hash conflicts.

No weather scheduler is registered. `daily_product_features` and dataset export
do not use weather observations until a later explicit feature phase.

## Phase 6.3E Weather Daily Aggregation

Phase 6.3E adds a deterministic feature builder for `weather_daily_features`.
It reads `weather_observations` and upserts one row per
`region_id + feature_date`.

Run all active regions with observations:

```bash
python scripts/build_features.py weather_daily
```

Run one region and explicit inclusive date range:

```bash
python scripts/build_features.py weather_daily \
  --region br_mato_grosso_soybean \
  --from-date 2026-05-01 \
  --to-date 2026-05-10
```

Rolling windows:

- 7d: `feature_date - 6 days` through `feature_date`;
- 14d: `feature_date - 13 days` through `feature_date`;
- 30d: `feature_date - 29 days` through `feature_date`.

The builder uses only observations with `observation_date <= feature_date`.
`weather_as_of_date` is the latest observation date used in the feature row.
If an early row has less than a full rolling window, the builder computes from
available historical observations and records incomplete-window flags.

First-version thresholds and formulas:

- heat stress day: `temperature_2m_max >= 30C`;
- frost day: `temperature_2m_min <= 0C`;
- growing degree days: `max(0, temperature_2m_mean - base_temperature)`;
- soybean base temperature: `10C`;
- rapeseed/canola base temperature: `5C`;
- default base temperature: `10C`;
- drought proxy: `precipitation_30d_sum`, where lower values mean drier.

Missing flags are stored as JSON and may include:

- `missing_temperature`;
- `missing_precipitation`;
- `incomplete_7d_window`;
- `incomplete_14d_window`;
- `incomplete_30d_window`;
- `missing_region_observations`.

Quality checks verify region presence, feature date validity, observation
availability, no future observations, as-of safety, reasonable temperatures,
non-negative precipitation, non-negative GDD, and missing flag recording.

Phase 6.3E does not run weather collectors, does not register a scheduler, does
not change `daily_product_features`, does not add product-level weather export
columns, and does not create ML targets.

## Non-Goals

Historical Phase 6.3B design-only non-goals:

- No migration in Phase 6.3B.
- No SQLAlchemy model changes in Phase 6.3B.
- No collector in Phase 6.3B.
- No DB writes in Phase 6.3B.
- No scheduler changes.
- No ML model.
- No targets.

Current Phase 6.3D collector non-goals:

- No scheduler changes in Phase 6.3D.
- No automatic feature rebuild from weather rows.
- No product-level weather export integration yet.
- No ML model.
- No targets.
- No broad gridded weather storage or ERA5/Copernicus collector.

Current Phase 6.3E aggregation non-goals:

- No weather collector run as part of aggregation.
- No scheduler changes in Phase 6.3E.
- No product-level weather feature integration yet.
- No dataset export weather columns yet.
- No ML model.
- No targets.
