# Dataset Export V1

## What Export V1 Is

Phase 5.0 adds a controlled dataset export for `daily_product_features`.
It produces file artifacts for analysis; it does not train an ML model, create
targets, add new sources, or change production collectors.

## Source Tables

Export v1 reads:

- `daily_product_features`
- `products`
- `commodity_benchmarks` through the feature builder
- `weather_daily_features` and `product_weather_region_weights` through the
  feature builder
- `daily_trade_features`, `trade_flows`, `product_trade_code_weights`, and
  `trade_commodity_codes` through the feature builder
- `daily_supply_demand_features`, `supply_demand_observations`, and
  `product_supply_demand_weights` through the feature builder

It does not write PostgreSQL metadata in Phase 5.0 or Phase 6.3F. The JSON
manifest beside the export file is the export metadata source.

## Row Grain

One row equals one `product_code` and one `feature_date`.

## Columns

The CSV includes:

- `product_code`
- `product_name`
- `feature_date`
- calendar and seasonality fields: year, month, quarter, ISO week, day of
  year, ISO day of week, month/quarter boundary flags, cyclic day/month
  encodings, and season
- `feature_version`
- `as_of_at`
- daily price fields: first, last, min, max, observation count, 1-day deltas,
  intraday deltas, and rolling 3-day/7-day features
- CBR FX fields: `cny_rub`, `usd_rub`, `eur_rub`, their 1-day deltas, and
  `fx_as_of_date`
- FRED energy fields: Brent, WTI, Henry Hub, and diesel proxy values; 1-day and
  7-day deltas where supported; per-series energy as-of dates; and
  `energy_missing_flags`
- World Bank benchmark fields: soybean oil, soybeans, palm oil, maize, wheat,
  and fertilizer index values; 1-month and 3-month deltas; per-benchmark
  as-of dates; `benchmark_as_of_date`; and `benchmark_missing_flags`
- product-level weather fields: weighted 7/30-day temperature features,
  7/14/30-day precipitation sums, heat/frost stress counts, drought proxy,
  growing degree days, `weather_as_of_date`, `weather_regions_used`, and
  `weather_missing_flags`
- product-level news/event fields: 1/7/30-day article and event counts,
  7-day bullish/bearish/mixed event counts, 30-day event-category counts,
  `sentiment_proxy_7d`, `news_as_of_date`, and `news_missing_flags`
- product-level trade fields: 1-month export/import volume and value proxies,
  3-month averages, 12-month sums, net export/trade balance proxy,
  China/major-reporter volume proxies, unit values, YoY change,
  `trade_as_of_date`, `reporting_lag_days`, and `trade_missing_flags`
- product-level supply-demand fields: production, domestic consumption, food
  and feed use, crush, exports/imports, beginning/ending stocks,
  stock-to-use, area/yield, forecast revisions, report vintage metadata,
  `supply_demand_as_of_date`, `supply_demand_reporting_lag_days`, and
  `supply_demand_missing_flags`
- `created_at`
- `updated_at`

`features_json` is not exported in v1 because the export is an explicit tabular
schema.

Calendar fields are deterministic and require no external API. Day of week uses
ISO convention (`Monday=1`, `Sunday=7`). Cyclic fields use sine/cosine encodings
for day of year and month. Seasons are `winter` for December-February, `spring`
for March-May, `summer` for June-August, and `autumn` for September-November.

## Data Types

Dates and timestamps are exported as ISO strings. Numeric fields are exported as
decimal strings to avoid binary floating-point drift in CSV consumers.

## Date Range

By default, all available feature dates are exported. Use inclusive filters when
needed:

```bash
python scripts/export_dataset.py daily_features --from-date 2026-05-20 --to-date 2026-06-04
```

## Products Included

The export includes products that have rows in `daily_product_features`.
Currently this is expected to include the production current-price products:

- `rapeseed_oil`
- `soybean_oil`
- `rapeseed_meal`
- `soybean_meal`

## Sources Included

Export v1 includes only sources already materialized into
`daily_product_features`:

- `current_price_source` snapshots through the daily feature builder
- CBR FX rates through the daily feature builder
- FRED energy prices through the daily feature builder
- World Bank Pink Sheet commodity benchmarks through the daily feature builder
- Open-Meteo region-level weather aggregates through
  `product_weather_region_weights`
- rule-based `commodity_events` and `daily_news_features` through the daily
  feature builder
- UN Comtrade monthly trade flows through `daily_trade_features` and
  `product_trade_code_weights`
- USDA PSD supply-demand observations through `daily_supply_demand_features`
  and `product_supply_demand_weights`

The USDA PSD collector source contract is the direct downloadable oilseeds ZIP
(`https://apps.fas.usda.gov/psdonline/downloads/psd_oilseeds_csv.zip`).
Metadata-only PSD API responses are rejected before normalization and are not
valid export inputs.
The direct ZIP is country-level. Current controlled USDA PSD probes should use
concrete country codes such as `US`, `BR`, `AR`, `CA`, or `CH`. `WLD`/`World`
rows are not present in the ZIP and are not synthesized. Reviewed country
baskets supply product-level aggregation under explicit as-of and coverage
rules.
Country-aware aggregation exists in the local feature builder. The Phase 6.9Q
proposal generator creates review artifacts only; generated weight proposals
are not export inputs until converted into reviewed config and rebuilt through
the normal feature pipeline.
Phase 6.9U adds a local reviewed Tier A `soybean_oil` basket config for
`production_volume`, `crush_volume`, `domestic_consumption`, and
`exports_volume` under `supply_demand_global_basket_v1`. The config preserves
real `WLD` precedence, requires at least `0.75` available approved basket
weight at feature time, and records basket provenance in
`daily_supply_demand_features.metadata_json`. It is not a production export
input until deployed and rebuilt explicitly; Tier B/C metrics and CA remain
deferred.
Phase 6.9X makes this reviewed Tier A config the default local builder input,
so the ordinary `supply_demand_daily` command needs no config injection. This
does not activate Tier B/C metrics or change production before deployment.
Expected skipped USDA PSD rows, such as aggregate totals and currently
unmodeled detail splits, are diagnostics only and do not become export columns.
Supported metric rows must still normalize into `daily_supply_demand_features`
before they can appear in `daily_features` exports.

## Sources Excluded

Export v1 intentionally excludes:

- `historical_price_bars`
- `historical_price_bar_revisions`
- sunflower products
- ML targets and model outputs

## As-Of And Leakage Policy

Export v1 uses `daily_product_features` exactly as stored. The current feature
builder uses current snapshot prices, CBR FX, FRED energy prices, World Bank
benchmark rows, and product-level weather aggregates with as-of logic. Energy
values use the latest
`energy_prices.period_start <= feature_date`; weekly diesel is forward-filled by
the same rule. World Bank benchmark values use the latest
`commodity_benchmarks.period_start <= feature_date`, are forward-filled as
monthly context features, and include explicit per-series as-of dates. Weather
values use active/effective product-region weights and only
`weather_daily_features.feature_date <= product feature_date` with
`weather_as_of_date <= product feature_date`. News/event values use
`daily_news_features.feature_date <= product feature_date` with
`news_as_of_date <= product feature_date`. Trade values use
`daily_trade_features.feature_date <= product feature_date` with
`trade_as_of_date <= product feature_date`; monthly data is forward-filled only
after source publication/fetch availability. Supply-demand values use
`daily_supply_demand_features.feature_date <= product feature_date` with
`supply_demand_as_of_date <= product feature_date`; official report vintages
are forward-filled only after publication/fetch availability. Historical bars
are not consumed by daily features yet, so the export cannot accidentally treat
historical backfill as if it was available in the past.

Phase 6.9I keeps that rule unchanged. It only aligns the
`supply_demand_daily` default build window with newly available official report
as-of dates, so a report fetched on `2026-06-16` can populate `2026-06-16` and
later feature rows while `2026-06-15` and earlier remain empty. Rows before the
report as-of date are marked with
`supply_demand_observations_after_feature_date_window` in supply-demand missing
metadata.

## Known Limitations

- No labels or ML targets are included.
- Historical OHLC bars are excluded from features v1.
- Energy features depend on the currently collected FRED window; missing current
  series are recorded in `energy_missing_flags`.
- Benchmark features are monthly and forward-filled by `period_start`; future
  export modes may add stricter `published_at` or `fetched_at` cutoffs.
- Weather features use first-version equal product-region weights and centroid
  region proxies. Missing or partial regional coverage is recorded in
  `weather_missing_flags`.
- News/event features are rule-based keyword aggregates, not semantic
  NLP/LLM/ML classifications. Missing or partial source coverage is recorded in
  `news_missing_flags`.
- Trade features are monthly aggregates and may lag source publication. Missing
  mappings, missing flows, incomplete rolling windows, and unavailable reporter
  proxies are recorded in `trade_missing_flags`.
- Supply-demand features are monthly/marketing-year report aggregates and may
  lag source publication. Missing mappings, missing official metrics, missing
  revisions, and missing publication dates are recorded in
  `supply_demand_missing_flags`.
- Sunflower products are not implemented.
- This is a controlled file export, not a public API or dashboard.

## Run Locally

```bash
python scripts/export_dataset.py --list
python scripts/export_dataset.py daily_features
python scripts/export_dataset.py daily_features --format csv
python scripts/export_dataset.py daily_features --format parquet
python scripts/export_dataset.py daily_features --format both
python scripts/export_dataset.py daily_features --output-dir data/exports
```

For reproducible manifests, pass the Git commit explicitly when exporting from
an environment that does not include `.git`:

```bash
APP_GIT_COMMIT=$(git rev-parse HEAD) python scripts/export_dataset.py daily_features
```

If `APP_GIT_COMMIT` is not set, the exporter tries `git rev-parse HEAD`; if that
also fails, the manifest records `git_commit` as `unknown`.

Parquet requires `pyarrow` or `fastparquet`. The project includes `pyarrow`; if
neither engine is available, the CLI exits with a clear error.

## Run On Server

```bash
cd /data1/long_play_project
APP_GIT_COMMIT=$(git rev-parse HEAD) docker compose run --rm -e APP_GIT_COMMIT app \
  python scripts/export_dataset.py daily_features --format csv --output-dir data/exports
```

Export payloads are runtime artifacts under `data/exports/` and must not be
committed.

## Validate Output

The CLI validates:

- positive row count
- no duplicate `(product_code, feature_date)`
- non-empty `product_code`
- non-empty `feature_date`
- valid feature date range
- output paths stay under `data/exports`
- CSV can be read back
- manifest row count matches the file
- SHA-256 is calculated
- manifest does not contain secret markers

The manifest contains row count, column count, product list, feature-date range,
source notes, excluded sources, file paths, file sizes, and SHA-256 hashes.
