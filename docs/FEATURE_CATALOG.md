# Feature Catalog

Phase 6.6B documents the ML-ready shape of the `daily_features` export. This is
documentation and audit tooling only: no ML model, no targets, no collectors, no
scheduler changes, no production deploy, and no production database writes.

Production status values:

- `production-deployed`: collected or built in production before the latest local-only batch.
- `local-implemented-awaiting-server-batch`: implemented locally and needs Phase 6.6A server batch before production validation.
- `schema-only`: database schema exists, but production data collection or feature use is not complete.
- `collector-only`: collector exists, but derived features/export use is not complete.
- `future`: planned, not implemented.

## identity

Purpose: stable row identity, product identity, and dataset reproducibility.

Source tables: `daily_product_features`, `products`.

Source collectors/builders: `build_daily_features`, `export_daily_features`.

Frequency: daily row grain, one row per `product_code` and `feature_date`.

Expected ML value: keys for joins, grouping, train/validation splits, and
per-product modeling.

Leakage/as-of protection: identity fields do not use future data. `as_of_at`
records the latest current price observation used by the daily row.

Missingness policy: `product_code` and `feature_date` are required by export
validation; product metadata must be present for exported rows.

Production status: `production-deployed` for existing product rows;
`local-implemented-awaiting-server-batch` for latest trade-augmented export
documentation.

## price

Purpose: current market snapshot features from the confirmed Chinese
Jijinhao/Cngold instruments.

Source tables: `price_observations`, `daily_product_features`.

Source collectors/builders: `current_price_source`, `build_daily_features`.

Frequency: scheduled current snapshots, aggregated into daily features.

Expected ML value: primary target-side explanatory signal for recent price
level, intraday movement, and short rolling momentum.

Leakage/as-of protection: scheduled runs use `collection_slot` as
`observed_at`; daily features only use observations whose local feature date is
the row date. Quality checks include `daily_feature_no_future_price`.

Missingness policy: missing price is an error for a daily feature row; sparse
rolling windows remain `NULL` until full windows are available.

Production status: `production-deployed`.

## fx

Purpose: RUB exchange-rate context for CNY, USD, and EUR.

Source tables: `fx_rates`, `daily_product_features`.

Source collectors/builders: `cbr_fx`, `build_daily_features`.

Frequency: daily CBR official rates, with non-business-day forward fill by
as-of rule.

Expected ML value: exchange-rate pressure on RUB-denominated economics and
international commodity parity.

Leakage/as-of protection: `fx_as_of_date <= feature_date`; deltas use the
previous available official observation.

Missingness policy: missing CNY/RUB is a warning; missing USD/EUR values remain
nullable.

Production status: `production-deployed`.

## calendar

Purpose: deterministic seasonality and calendar position.

Source tables: derived from `feature_date`.

Source collectors/builders: `build_calendar_features`.

Frequency: daily deterministic features.

Expected ML value: seasonal effects, monthly/quarterly cycles, and calendar
boundaries.

Leakage/as-of protection: deterministic from row date; no external source.

Missingness policy: should be fully populated for every daily feature row.

Production status: `production-deployed`.

## energy

Purpose: related energy-market context for oils, meals, freight, fuel, and
input-cost proxies.

Source tables: `energy_prices`, `daily_product_features`.

Source collectors/builders: `fred_energy_prices`, `build_daily_features`.

Frequency: source-dependent daily/weekly FRED series, forward-filled by
`period_start <= feature_date`.

Expected ML value: crude oil, gas, and diesel proxies can explain biofuel,
transport, and input-cost channels.

Leakage/as-of protection: `energy_as_of_date` and per-series as-of dates must be
`<= feature_date`; quality checks include `daily_feature_no_future_energy`.

Missingness policy: absent series are recorded in `energy_missing_flags`.

Production status: `production-deployed` or recently deployed depending on
server batch freshness.

## benchmarks

Purpose: global commodity benchmark context from World Bank Pink Sheet.

Source tables: `commodity_benchmarks`, `daily_product_features`.

Source collectors/builders: `world_bank_pink_sheet`, `build_daily_features`.

Frequency: monthly benchmarks forward-filled daily.

Expected ML value: global commodity price level and cross-market context for
soybean oil, soybeans, palm oil, maize, wheat, and fertilizer.

Leakage/as-of protection: `benchmark_as_of_date <= feature_date`; per-benchmark
as-of columns are checked by `daily_feature_no_future_benchmark`.

Missingness policy: absent benchmark families are recorded in
`benchmark_missing_flags`.

Production status: `production-deployed` or awaiting server refresh depending
on latest server batch.

## weather

Purpose: agronomic weather context from regional historical observations and
product-region weights.

Source tables: `weather_observations`, `weather_daily_features`,
`product_weather_region_weights`, `daily_product_features`.

Source collectors/builders: `open_meteo_historical`, `build_weather_daily_features`,
`build_daily_features`.

Frequency: daily regional observations, rolling regional aggregates, and
product-weighted daily features.

Expected ML value: temperature, precipitation, heat/frost stress, drought proxy,
and growing degree days can capture supply-side stress.

Leakage/as-of protection: region features use past-only windows and
`weather_as_of_date <= feature_date`; product features copy only eligible
region rows.

Missingness policy: missing or partial regional coverage is represented in
`weather_missing_flags` and `weather_regions_used`.

Production status: `production-deployed` for implemented weather stack;
server freshness depends on pending Phase 6.6A.

## news_events

Purpose: deterministic news/event context from GDELT and rule-based event
classification.

Source tables: `news_articles`, `commodity_events`, `daily_news_features`,
`daily_product_features`.

Source collectors/builders: `gdelt_news`, `extract_news_events`,
`build_news_daily_features`, `build_daily_features`.

Frequency: article/event timestamps aggregated into 1/7/30-day daily features.

Expected ML value: policy, logistics, weather-disaster, crop-report, energy,
demand, and supply-chain event counts can explain shocks not visible in price
or weather alone.

Leakage/as-of protection: article/event publication dates are constrained by
feature date; strict future modes should also enforce fetched-at cutoffs.

Missingness policy: absent articles, absent events, or partial source coverage
are recorded in `news_missing_flags`.

Production status: `production-deployed` or awaiting latest server batch
depending on deployment state.

## trade

Purpose: import/export context from monthly trade flows and product HS-code
weights.

Source tables: `trade_flows`, `trade_commodity_codes`,
`product_trade_code_weights`, `daily_trade_features`, `daily_product_features`.

Source collectors/builders: `un_comtrade`, `build_trade_daily_features`,
`build_daily_features`.

Frequency: monthly trade flows transformed into daily, forward-filled features
after source availability.

Expected ML value: export/import volumes, net export pressure, China import
proxy, major exporter/importer proxy, unit values, YoY change, and reporting
lag can capture demand/supply trade context.

Leakage/as-of protection: `period_start`, `period_end`, and
`published_at`/`fetched_at` availability must be `<= feature_date`.
Product-level rows require `trade_as_of_date <= feature_date`.

Missingness policy: missing mappings, missing flows, incomplete rolling windows,
missing reporter proxies, and missing YoY history are represented in
`trade_missing_flags`.

Production status: `local-implemented-awaiting-server-batch` for
`build_trade_daily_features` and export integration; UN Comtrade collector was
implemented earlier as controlled manual collection.

## supply_demand

Purpose: official production, consumption, crush, trade-balance, stock, area,
yield, and forecast-revision context from USDA PSD-style supply-demand
observations.

Source tables: `supply_demand_observations`, `supply_demand_commodities`,
`product_supply_demand_weights`, `daily_supply_demand_features`,
`daily_product_features`.

Source collectors/builders: `usda_psd`, `build_supply_demand_daily_features`,
`build_daily_features`.

Frequency: monthly report vintages and marketing-year balances transformed into
daily, forward-filled product features after source availability.

Expected ML value: production, crush/use, imports/exports, ending stocks,
stock-to-use, area/yield, and forecast revisions can explain fundamental
supply-demand tightness beyond current prices and trade actuals.

Leakage/as-of protection: `report_published_at`, `published_at`, or `fetched_at`
is reduced to `supply_demand_as_of_date`; product-level rows require
`supply_demand_as_of_date <= feature_date`. Forecast revisions compare only
previous eligible report vintages.

Missingness policy: missing product mappings, absent observations, missing
core metrics, missing revisions, missing publication dates, and area/yield gaps
are represented in `supply_demand_missing_flags`.

Production status: `local-implemented-awaiting-server-batch` for
`build_supply_demand_daily_features`, `daily_product_features` integration, and
export columns. The USDA PSD collector exists from the previous phase, but this
feature batch still needs local verification and a later server batch.

## Raw And Source Lineage

Raw/source lineage fields are not exported as row columns except the manifest
metadata (`git_commit`, source notes, files, SHA-256, row count, column count,
product list, and feature-date range). Normalized source tables retain
`raw_response_id`, `collector_run_id`, hashes, fetched timestamps, and source
metadata for auditability.

Production status: `production-deployed` for existing collectors; latest
trade and supply-demand feature/export documentation is
`local-implemented-awaiting-server-batch`.
