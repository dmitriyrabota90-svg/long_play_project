# Leakage And As-Of Audit

Phase 6.6B records the leakage policy for the `daily_features` export. This is
not an ML model and does not add targets. The audit is local-only and does not
run collectors, migrations, schedulers, production feature builders, or server
commands.

## General Rule

No feature may use source data known after feature_date. Every feature group
must either be deterministic from `feature_date` or carry an explicit as-of
policy that prevents future information from entering a row.

## Price / Current Data

Current market features come from `price_observations`. Manual runs use fetch
time as the observation time; scheduled current-price runs use the configured
`collection_slot` as `observed_at` so retries do not create extra artificial
time points.

Leakage controls:

- row date is derived from `observed_at` in the configured local timezone;
- same-day price aggregations use observations assigned to that feature date;
- rolling windows use prior/current daily last prices only;
- `as_of_at` records the latest price observation used;
- quality checks include `daily_feature_no_future_price`.

Known limitation: current snapshots are not the same as official daily close
bars. Historical bars remain a separate table and are not mixed into the
current-price feature logic.

## FX

CBR FX features come from `fx_rates` and currently include USD/RUB, EUR/RUB,
and CNY/RUB.

Leakage controls:

- feature builder uses the latest official rate with observed date not after
  the feature date;
- weekend/holiday gaps use the latest available rate without looking forward;
- `fx_as_of_date <= feature_date`;
- quality checks include `daily_feature_no_future_fx`.

Known caveat: CBR publication timing can differ from the nominal rate date.
Future publication-aware exports may add stricter fetched/published cutoffs.

## Energy

Energy features come from `energy_prices` and include Brent, WTI, Henry Hub, and
a diesel proxy.

Leakage controls:

- energy values use source periods not after `feature_date`;
- per-series as-of columns are `energy_brent_as_of_date`,
  `energy_wti_as_of_date`, `energy_henry_hub_as_of_date`, and
  `energy_diesel_as_of_date`;
- aggregate `energy_as_of_date <= feature_date`;
- quality checks include `daily_feature_no_future_energy`.

Missingness is represented in `energy_missing_flags`.

## Commodity Benchmarks

Global commodity benchmarks come from World Bank Pink Sheet monthly data:
soybean oil, soybeans, palm oil, maize, wheat, and fertilizer index.

Leakage controls:

- monthly benchmark values use `period_start <= feature_date`;
- product daily features forward-fill monthly context by benchmark period;
- `benchmark_as_of_date <= feature_date`;
- per-series benchmark as-of columns are also checked;
- quality checks include `daily_feature_no_future_benchmark`.

Known limitation: Phase 6.2E style benchmark logic is period-based. Future
publication-aware modes may also enforce source `published_at` or `fetched_at`
cutoffs.

Missingness is represented in `benchmark_missing_flags`.

## Weather

Weather features come from Open-Meteo regional historical observations,
regional daily rolling aggregates, and product-region weights.

Leakage controls:

- `weather_observations.observation_date <= feature_date`;
- rolling windows are past-only;
- `weather_daily_features.feature_date <= product feature_date`;
- `weather_as_of_date <= feature_date`;
- active/effective product-region weights only;
- quality checks include `daily_feature_no_future_weather`.

Missingness and partial coverage are represented in `weather_missing_flags` and
`weather_regions_used`.

## News / Events

News and event features come from GDELT articles and deterministic rule-based
event extraction.

Leakage controls:

- article `published_at <= feature_date`;
- event dates and publication dates are aggregated only for past/current
  windows;
- `news_as_of_date <= feature_date`;
- strict mode should also consider `fetched_at <= feature_date` when simulating
  as-collected production;
- no future event extraction is allowed;
- quality checks include `daily_feature_no_future_news`.

Missingness is represented in `news_missing_flags`.

## Trade

Trade features come from UN Comtrade monthly `trade_flows`, HS-code mappings,
and `product_trade_code_weights`.

Leakage controls:

- `period_start <= feature_date`;
- `period_end <= feature_date`;
- source availability uses `published_at` date when present, otherwise
  `fetched_at` date;
- availability date must be `<= feature_date`;
- `trade_as_of_date <= feature_date`;
- `reporting_lag_days` records the gap between feature date and latest eligible
  trade source availability;
- monthly trade is forward-filled daily only after publication/fetch
  eligibility.

Missingness is represented in `trade_missing_flags`.

Known limitation: latest local trade feature/export integration is awaiting
server batch 6.6A before production export validation.

## Export

The export manifest should record:

- `git_commit`, preferably from `APP_GIT_COMMIT` when running inside Docker;
- source tables and included/excluded source notes;
- row count, column count, product list, feature-date range;
- file paths, sizes, and SHA-256 hashes;
- leakage note and known limitations.

Export modes to keep distinct in future work:

- `production_snapshot`: export current production database state;
- `historical_backfill`: export after controlled backfilled sources;
- `as_collected`: simulate only data that had been fetched by each date;
- `publication_aware`: enforce published/fetched availability for all slower
  sources.

## Known Limitations

- Some backfilled layers need explicit export mode labels before serious model
  training.
- Server batch 6.6A is still pending for the latest local trade feature/export
  integration.
- Sparse data is expected until collectors and derived builders are run for
  enough history.
- No target columns exist yet; target design must be a separate, audited phase.
- ML training should wait for production export validation and a documented
  train/validation split strategy.
