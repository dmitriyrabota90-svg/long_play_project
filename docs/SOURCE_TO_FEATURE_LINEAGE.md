# Source To Feature Lineage

This matrix documents how raw sources flow into normalized tables, derived
feature tables, and the final `daily_features` export. It is a local
documentation artifact for Phase 6.6B and does not trigger collection,
migrations, exports, or server deployment.

| raw source | collector/script | raw table/artifact | normalized table | derived feature table | final export columns/groups | refresh mode | current production status |
|---|---|---|---|---|---|---|---|
| Jijinhao/Cngold current price API | `current_price_source` via `scripts/run_collector.py` and scheduler | `raw_responses`, `data/raw/current_price_source/...` | `price_observations` | `daily_product_features` | price group: `price_last`, `price_first`, min/max, deltas, rolling windows, `as_of_at` | scheduled in production for current snapshots | production-deployed |
| CBR FX XML daily endpoint | `cbr_fx` via `scripts/run_collector.py` and scheduler | `raw_responses`, `data/raw/cbr_fx/...` | `fx_rates` | `daily_product_features` | fx group: `cny_rub`, `usd_rub`, `eur_rub`, deltas, `fx_as_of_date` | scheduled in production | production-deployed |
| Jijinhao/Cngold historical `historys.htm` | `jijinhao_historical_prices` manual collector | `raw_responses`, `data/raw/jijinhao_historical_prices/...` | `historical_price_bars`, `historical_price_bar_revisions` | not used by `daily_product_features` yet | excluded from `daily_features`; documented in manifest excluded sources | manual/backfill only | production-deployed table/collector, not final feature source |
| FRED energy API | `fred_energy_prices` via `scripts/run_collector.py` | `raw_responses`, `data/raw/fred_energy_prices/...` | `energy_prices` | `daily_product_features` | energy group: Brent, WTI, Henry Hub, diesel proxy, deltas, as-of dates, `energy_missing_flags` | manual/scheduled depending deployment runbook | production-deployed or awaiting server freshness |
| World Bank Pink Sheet | `world_bank_pink_sheet` via `scripts/run_collector.py` | `raw_responses`, `data/raw/world_bank_pink_sheet/...` | `commodity_benchmarks` | `daily_product_features` | benchmarks group: soybean oil, soybeans, palm oil, maize, wheat, fertilizer index, deltas, as-of dates, `benchmark_missing_flags` | manual/scheduled depending deployment runbook | production-deployed or awaiting server freshness |
| Open-Meteo archive API | `open_meteo_historical` via `scripts/run_collector.py` | `raw_responses`, `data/raw/open_meteo_historical/...` | `weather_observations` | `weather_daily_features`, then `daily_product_features` | weather group: weighted temperature, precipitation, heat/frost stress, drought proxy, GDD, `weather_as_of_date`, `weather_regions_used`, `weather_missing_flags` | manual/backfill first, later scheduler decision | production-deployed or awaiting server freshness |
| GDELT | `gdelt_news` via `scripts/run_collector.py` | `raw_responses`, `data/raw/gdelt_news/...` | `news_articles` | `commodity_events`, `daily_news_features`, then `daily_product_features` | news_events group: news counts, event counts, category counts, directional counts, sentiment proxy, `news_as_of_date`, `news_missing_flags` | manual/controlled, scheduler decision separate | production-deployed or awaiting server freshness |
| Rule-based news event extraction | `scripts/extract_news_events.py` | no external raw source; reads `news_articles` | `commodity_events` | `daily_news_features`, then `daily_product_features` | event category and sentiment columns in news_events group | manual derived builder | production-deployed or awaiting server freshness |
| UN Comtrade trade API | `un_comtrade` via `scripts/run_collector.py` | `raw_responses`, `data/raw/un_comtrade/...` | `trade_flows`, `trade_commodity_codes`, `product_trade_code_weights` | `daily_trade_features`, then `daily_product_features` | trade group: export/import volumes, values, unit values, China/major reporter proxies, YoY, `trade_as_of_date`, `reporting_lag_days`, `trade_missing_flags` | manual controlled collection; `trade_daily` local builder | local-implemented-awaiting-server-batch for final daily/export integration |
| Daily feature builder | `python scripts/build_features.py daily` | reads normalized tables | `daily_product_features` | `daily_product_features` | identity, price, fx, calendar, energy, benchmarks, weather, news_events, trade groups | manual/scheduled for core daily features depending deployment | production-deployed for earlier groups; trade integration awaiting server batch |
| Weather daily builder | `python scripts/build_features.py weather_daily` | reads `weather_observations` | `weather_daily_features` | `daily_product_features` after daily build | weather group | manual/backfill first | production-deployed or awaiting server freshness |
| News daily builder | `python scripts/build_features.py news_daily` | reads `news_articles`, `commodity_events` | `daily_news_features` | `daily_product_features` after daily build | news_events group | manual/backfill first | production-deployed or awaiting server freshness |
| Trade daily builder | `python scripts/build_features.py trade_daily` | reads `trade_flows`, `product_trade_code_weights` | `daily_trade_features` | `daily_product_features` after daily build | trade group | local-only currently; server batch pending | local-implemented-awaiting-server-batch |
| Dataset export | `python scripts/export_dataset.py daily_features` | reads `daily_product_features`, `products` | file artifacts under `data/exports/` | CSV/Parquet plus JSON manifest | all documented export columns in `DATASET_DICTIONARY.md` | manual file export | local trade columns implemented; production export validation pending |

## Notes

- Raw payload evidence lives in `raw_responses` and immutable files under
  `data/raw/...` for production collectors.
- Diagnostic scripts can write under `diagnostics/...`, but those artifacts are
  not production raw evidence and must not be committed.
- `daily_features` export manifests include `git_commit`, file hashes, column
  list, row count, product list, feature-date range, included sources, excluded
  sources, and leakage notes.
- Production server batch 6.6A is still pending for the latest local trade
  feature/export integration.
