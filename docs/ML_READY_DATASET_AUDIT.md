# ML-Ready Dataset Audit

Phase 6.6B is a local-only documentation and audit step. It does not train a model,
does not add targets, does not deploy, does not run collectors, and does not
touch the production database.

## Executive Summary

The project now has a broad ML-ready dataset pipeline shape: current prices,
FX, calendar features, energy context, global commodity benchmarks, weather,
news/events, historical bars, trade/import-export, and supply-demand official
balance layers. The latest local trade and supply-demand feature/export
integration is implemented but server batch 6.6A is still pending, so
production export validation is pending.

The dataset is close to being suitable for first exploratory modeling later,
but not yet ready for serious model training because target design, final
production export validation, deeper source coverage, and longer
history/backfill checks are still missing.

## Dataset Pipeline Status

| layer | status | notes |
|---|---|---|
| current prices | production-deployed | Four Jijinhao/Cngold instruments feed `price_observations`. |
| historical bars | production-deployed table/collector | Stored separately in `historical_price_bars`; not used by export v1. |
| FX | production-deployed | CBR USD/RUB, EUR/RUB, CNY/RUB. |
| calendar/seasonality | production-deployed | Deterministic from `feature_date`. |
| energy | production-deployed or awaiting server freshness | FRED energy prices feed `daily_product_features`. |
| global commodity benchmarks | production-deployed or awaiting server freshness | World Bank Pink Sheet context. |
| weather | production-deployed or awaiting server freshness | Open-Meteo regional observations and weighted product features. |
| news/events | production-deployed or awaiting server freshness | GDELT plus rule-based event extraction. |
| trade/import-export | local-implemented-awaiting-server-batch | UN Comtrade collector exists; `trade_daily` and export integration need server batch. |
| supply-demand | local-implemented-awaiting-server-batch | USDA PSD collector exists; `supply_demand_daily` and export integration need server batch. |
| export v1 | local trade and supply-demand schema implemented | `daily_features` export includes nullable trade and supply-demand columns locally. |
| ML targets | future | Not designed or implemented. |

## Feature Group Readiness Table

| feature_group | readiness | enough for exploratory modeling later? | caution |
|---|---|---|---|
| identity | ready | yes | Do not model directly on unstable names. |
| price | ready | yes | Current snapshots are not official closes. |
| fx | ready | yes | Publication timing caveat remains for strict simulations. |
| calendar | ready | yes | Deterministic; no source risk. |
| energy | mostly ready | yes after production freshness check | Needs current server validation. |
| benchmarks | mostly ready | yes after production freshness check | Monthly values may need publication-aware mode later. |
| weather | mostly ready | yes after production freshness check | Regional proxy design should be monitored. |
| news_events | mostly ready | exploratory only | Rule-based, not semantic ML/NLP classification. |
| trade | local-ready, server pending | yes after server batch and validation | Sparse monthly data and reporting lag are expected. |
| supply_demand | local-ready, server pending | yes after server batch and validation | Monthly report vintages, sparse mappings, and revision semantics need monitoring. |
| historical bars | stored, not final-feature source | not in export v1 | Keep separate until explicit feature mode exists. |

## Export Readiness Table

| export | readiness | blockers |
|---|---|---|
| `daily_features` CSV | implemented | server batch 6.6A and production export validation pending |
| `daily_features` manifest | implemented | verify `APP_GIT_COMMIT` on production export |
| Parquet export | implemented if pyarrow/fastparquet available | environment-specific dependency |
| target export | future | target design not started |

## Data Quality Controls

Existing controls include:

- collector run status and counts;
- immutable raw response storage for collectors;
- source-specific parser/schema checks;
- uniqueness constraints on normalized tables;
- quality checks for current prices, FX, energy, benchmarks, weather, news, and
  historical bar mutations;
- export validation for duplicates, row count, date range, SHA-256, and secret
  markers.

## Missingness Controls

Missingness is explicit by group:

- `energy_missing_flags`;
- `benchmark_missing_flags`;
- `weather_missing_flags`;
- `news_missing_flags`;
- `trade_missing_flags`;
- `supply_demand_missing_flags`;
- nullable rolling windows until enough history exists.

Sparse data should not be interpreted as pipeline failure when a layer is
newly implemented, awaiting server batch, or still being backfilled.

## Leakage Controls

Leakage controls are documented in `LEAKAGE_AND_ASOF_AUDIT.md`. Critical rules:

- no source data known after `feature_date`;
- group as-of columns must be `<= feature_date`;
- trade uses publication/fetch availability and reporting lag;
- supply-demand uses report publication/fetch availability, report vintages,
  and `supply_demand_as_of_date`;
- historical bars are not mixed into current snapshot features;
- target columns do not exist yet.

## Known Gaps

- Supply-demand daily features are local-only until the server batch runs.
- Broader production/stocks/WASDE/FAOSTAT structured data is not implemented.
- More historical backfill and cross-source validation are needed.
- Scheduler integration for newer derived builders needs a separate reviewed
  phase.
- Server batch 6.6A has not been applied for latest local layers.
- Production export validation pending after server batch.
- No targets, train/validation split policy, or model evaluation protocol yet.

## Server Batch Dependency

Server batch 6.6A is still pending. It should deploy the latest local code,
apply any pending migrations, run controlled derived builders, validate
production reports, and produce a checked production export snapshot.

Until that happens, docs should label the latest trade and supply-demand
feature/export layers as `local-implemented-awaiting-server-batch`.

## Recommendation

1. Do server batch 6.6A first when the server is available.
2. Validate production data counts, quality checks, and the `daily_features`
   export manifest.
3. Only after production export validation, move to deeper supply-demand /
   production-stocks source expansion.
4. Do not start ML training or target engineering until target definition and
   leakage policy are designed as a separate phase.

What is enough for first exploratory modeling later:

- a validated production `daily_features` export;
- explicit feature dictionary and lineage;
- no target columns mixed into features;
- known sparse/missing flags.

What should not be used yet:

- unvalidated local-only trade or supply-demand columns from production assumptions;
- historical bars as if they were current snapshots;
- backfilled data without export mode labels;
- any future target/label concept not yet audited.
