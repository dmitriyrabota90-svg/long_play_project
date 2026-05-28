# Historical Price Bars Design

## Executive Summary

Phase 4.4 is a design-only step for storing historical daily price bars from Jijinhao/Cngold. It does not implement a production collector, does not add an Alembic migration, and does not write historical rows to PostgreSQL.

The recommended model is a separate `historical_price_bars` table linked to `products`, `sources`, `collector_runs`, and `raw_responses`. Historical bars should not be mixed into `price_observations`, because `price_observations` currently represents current snapshots collected manually or by schedule and is already used by the daily feature builder.

The first production candidate should use `quoteCenter/historys.htm` with strict limits. `sQuoteCenter/kDataList.htm` remains useful for later investigation, but it is not the first production source because Phase 4.3 showed much larger payloads.

## Phase 4.3 Findings

The diagnostics-only Phase 4.3 probe checked the four confirmed production instruments:

| product_code | external_code |
| --- | --- |
| `rapeseed_oil` | `JO_166042` |
| `soybean_oil` | `JO_165951` |
| `rapeseed_meal` | `JO_166106` |
| `soybean_meal` | `JO_165938` |

`historys` results:

- 4/4 instruments parsed.
- 30 rows per instrument.
- Payload size was about 3.2 KB per instrument.
- The endpoint exposed date-like rows with provisional `open`, `high`, `low`, `close`, `price`, and `volume` mapping.
- q-field semantics still need final manual confirmation before production writes.

`kdata` results:

- 4/4 instruments parsed.
- 30 rows per instrument.
- Payload size was about 0.97-1.48 MB per instrument.
- It appears to contain richer OHLC history, but response size and pagination behavior require separate controls.

Production DB counts did not change during Phase 4.3 diagnostics, confirming the probe stayed outside production normalized tables.

## Why Separate Table

`price_observations` currently stores current snapshot prices:

- Manual runs use `observed_at=fetched_at`.
- Scheduled runs use `observed_at=collection_slot`.
- Idempotency is built around the current snapshot record hash.
- `daily_product_features` derives current daily features from these rows.

Historical bars have a different meaning:

- A row can describe a past `bar_date` while being fetched today.
- Rows may include OHLC and volume, not just a single current price.
- Backfilled historical data has a different leakage profile from as-collected snapshots.
- A daily close from history should not silently replace the latest current snapshot used by existing features.

Therefore, historical bars should not be written into `price_observations` unless the schema is later redesigned with an explicit `observation_type` and OHLC fields. The safer first step is a dedicated `historical_price_bars` table.

## Proposed Table Schema

Table: `historical_price_bars`

| field | type | nullable | purpose |
| --- | --- | --- | --- |
| `id` | integer primary key | no | Surrogate key. |
| `product_id` | FK to `products.id` | no | Product the bar belongs to. |
| `source_id` | FK to `sources.id` | no | Source row, recommended code `jijinhao_historical_prices`. |
| `raw_response_id` | FK to `raw_responses.id` | no | Raw payload evidence used to parse the bar. |
| `collector_run_id` | FK to `collector_runs.id` | no | Collector run that fetched the raw payload. |
| `external_code` | string(100) | no | Jijinhao code such as `JO_165938`. |
| `endpoint_alias` | string(50) | no | Endpoint family, initially `historys`; later possibly `kdata`. |
| `bar_date` | date | no | Calendar date of the historical bar. |
| `bar_timeframe` | string(50) | no | `daily`, `intraday`, or `unknown`; first production target is `daily`. |
| `open_price` | numeric(18, 6) | yes | Daily open when available. |
| `high_price` | numeric(18, 6) | yes | Daily high when available. |
| `low_price` | numeric(18, 6) | yes | Daily low when available. |
| `close_price` | numeric(18, 6) | yes | Daily close when available. |
| `price` | numeric(18, 6) | yes | Single price value for endpoints without full OHLC; for `historys`, this can mirror provisional close. |
| `volume` | numeric(24, 6) | yes | Volume if present. Optional because not every endpoint may provide it reliably. |
| `currency` | string(16) | no | Expected `CNY` for current Jijinhao instruments. |
| `unit` | string(100) | no | Expected `metric_ton` for current products. |
| `observed_at` | timestamptz | no | Timestamp representing the bar in UTC; for daily bars, start of `bar_date` UTC unless source gives a better timestamp. |
| `published_at` | timestamptz | yes | Source publication timestamp if available. `NULL` for `historys` until proven otherwise. |
| `fetched_at` | timestamptz | no | Actual UTC time the historical response was fetched. |
| `source_record_hash` | string(64) | no | Stable per-bar idempotency hash. |
| `source_payload_hash` | string(64) | no | SHA-256 of the full raw response, same value as `raw_responses.sha256`. |
| `created_at` | timestamptz | no | Insert time. |
| `updated_at` | timestamptz | no | Update time when a bar is refreshed. |

## Field Definitions

`bar_date` is the market date of the bar. For daily history this is the primary analytical date.

`bar_timeframe` distinguishes daily bars from future intraday bars. The first production collector should only write `daily`. Intraday endpoints should remain diagnostics-only until a separate storage plan exists.

`observed_at` is a timestamp representation of the bar. For daily bars it should be `bar_date 00:00:00+00:00` unless the source provides a precise timestamp with clear semantics.

`fetched_at` is when the collector obtained the response. This field is mandatory for leakage control.

`published_at` is optional because Phase 4.3 did not prove that Jijinhao exposes a publication timestamp for the historical rows.

`source_record_hash` should be computed from normalized stable fields:

```text
source_code
product_code
external_code
endpoint_alias
bar_timeframe
bar_date
open_price
high_price
low_price
close_price
price
volume
currency
unit
```

`source_payload_hash` should copy the raw response SHA-256. It lets audits quickly connect a parsed record to the exact payload version.

## Unique Constraints And Indexes

Recommended first unique constraint:

```text
UNIQUE(product_id, source_id, endpoint_alias, bar_timeframe, bar_date)
```

Implemented name in Phase 4.5: `uq_hist_bars_product_source_endpoint_timeframe_date` (shortened to avoid PostgreSQL identifier-length issues).

This is preferable to including `source_record_hash` in the uniqueness constraint. If the source later revises a historical bar, a unique constraint that includes the hash would allow duplicate bars for the same product/date/endpoint. The desired behavior is upsert by product/source/endpoint/timeframe/date, then update values and `updated_at` if the normalized record changed.

Keep `source_record_hash` as a non-unique change detector and audit field. If the hash changes for an existing unique key, update the row and optionally write a quality warning or revision metric.

Recommended indexes:

```text
ix_hist_bars_product_bar_date
  (product_id, bar_date)

ix_hist_bars_source_fetched_at
  (source_id, fetched_at)

ix_hist_bars_product_source_timeframe_date
  (product_id, source_id, bar_timeframe, bar_date)

ix_hist_bars_raw_response_id
  (raw_response_id)

ix_hist_bars_collector_run_id
  (collector_run_id)
```

Optional later index for export workloads:

```text
ix_hist_bars_timeframe_bar_date
  (bar_timeframe, bar_date)
```

## Raw Storage Design

Recommended new source code:

```text
jijinhao_historical_prices
```

Production raw responses should use the existing `RawStore`:

```text
data/raw/jijinhao_historical_prices/{yyyy}/{mm}/{dd}/{collector_run_id}/{sha256}.txt
```

Where:

- `yyyy/mm/dd` comes from `fetched_at`.
- `collector_run_id` is the historical collector run.
- `sha256` is the raw payload hash.

Each fetched payload should create a `raw_responses` row with:

- `source_id`
- `collector_run_id`
- `fetched_at`
- `url`
- `method`
- `status_code`
- `content_type`
- `storage_path`
- `sha256`
- `bytes_size`
- `parser_version`

Each `historical_price_bars` row should point to the corresponding `raw_response_id`. Phase 4.3 diagnostics raw files are not production raw evidence and should not be referenced by normalized rows.

## Collector Design

Future collector name:

```text
jijinhao_historical_prices_collector
```

Future source code:

```text
jijinhao_historical_prices
```

Endpoint priority:

1. `quoteCenter/historys.htm`
   - First production candidate.
   - Compact payloads around 3.2 KB per instrument for 30 rows.
   - Safer for manual/backfill runs.
   - q-field semantics still need a final confirmation step.
2. `sQuoteCenter/kDataList.htm`
   - Later/manual-check only.
   - Payloads around 0.97-1.48 MB per instrument for 30 rows in Phase 4.3.
   - Requires max response bytes, pagination/window limits, timeout controls, and storage monitoring.

Implemented Phase 4.6 CLI:

```bash
python scripts/run_collector.py jijinhao_historical_prices --endpoint historys --days 30
python scripts/run_collector.py jijinhao_historical_prices --product-code soybean_meal --endpoint historys --days 30
python scripts/run_collector.py jijinhao_historical_prices --endpoint historys --days 30 --run-type backfill
```

Run types:

- `manual`
- `backfill`

Scheduler:

- Do not enable a scheduler in the first production phase.
- Use manual/backfill runs until schema, idempotency, and quality checks are proven.

Phase 4.6 production behavior:

- Only `historys` is accepted by the production collector.
- `kdata` is rejected with a CLI error and remains diagnostics-only.
- Raw payloads are stored through `RawStore` and linked through `raw_responses`.
- Parsed rows are written only to `historical_price_bars`.
- `price_observations` and `daily_product_features` are not changed by the collector.
- Existing rows with matching `source_record_hash` are skipped.
- Existing rows with a changed `source_record_hash` create a `historical_existing_bar_hash_changed` warning and are not overwritten silently in Phase 4.6.

## Quality Checks

Raw response checks:

- `historical_raw_response_non_empty`
- `historical_content_type_expected`
- `historical_response_size_within_limit`
- `historical_parser_success`

Data checks:

- `historical_bar_date_present`
- `historical_price_present`
- `historical_price_positive`
- `historical_ohlc_consistent`
- `historical_no_duplicate_product_date`
- `historical_no_future_observed_at`
- `historical_fetched_at_present`
- `historical_source_record_hash_present`
- `historical_existing_bar_hash_changed`

OHLC consistency:

- `high_price >= low_price`
- `high_price >= open_price`
- `high_price >= close_price`
- `low_price <= open_price`
- `low_price <= close_price`

If an endpoint provides only a single `price` without OHLC, OHLC-specific checks should be `skip`, not `fail`.

## As-Of And Leakage Policy

Historical backfill data must not be treated as if it was available on the original `bar_date`.

Rules:

1. `bar_date` / `observed_at` represent the market value date.
2. `fetched_at` represents when the application actually obtained the data.
3. If a bar for `2026-05-01` is fetched on `2026-05-28`, it must not be available to an as-of simulation for dates before `2026-05-28`.
4. Dataset export should eventually support explicit modes:
   - `as_collected`
   - `historical_backfill_allowed`
5. Feature builders must filter by `fetched_at <= as_of_at` in real-time simulation mode.
6. Offline historical analysis may use backfilled bars, but that mode must be labeled and separated from leakage-safe as-collected datasets.

## Feature Builder Impact

Near term:

- Do not change `daily_product_features`.
- Continue building current daily features from `price_observations` and `fx_rates`.

Future options:

- `current_snapshot_features`: existing behavior based on scheduled/current snapshots.
- `historical_bar_features`: daily bars from `historical_price_bars`.
- `hybrid_features`: explicit configured combination of current snapshots and historical bars.

Risks:

- Replacing current snapshot `price_last` with historical close will change time series semantics.
- Using backfilled historical bars without a `fetched_at` cutoff creates data leakage.
- A product/date can have both current snapshots and historical bars; source selection must be explicit.

## Operational Limits

Initial `historys` limits:

- Endpoint alias: `historys`.
- Safe initial window: `days=30`.
- Max products per run: the four confirmed production instruments.
- Timeout: start with 15-20 seconds.
- Retry policy: low retries, no aggressive loops.
- Response size guard: start with a conservative max such as 100 KB per instrument.

Initial `kdata` limits if investigated later:

- Not the first production endpoint.
- Require max response bytes before parsing, e.g. 2 MB per instrument initially.
- Require pagination/window controls.
- Require timeout controls.
- Require storage growth monitoring.
- Avoid broad runs until payload behavior is fully understood.

## Migration Plan For Next Phase

Phase 4.5 was schema-only/schema-plus-tests:

1. Add SQLAlchemy model `HistoricalPriceBar`.
2. Add Alembic migration for `historical_price_bars`. Phase 4.5 implements this as revision `0005_historical_price_bars`.
3. Add seed row for source `jijinhao_historical_prices`.
4. Do not enable scheduler.

Phase 4.6 adds the first manual production collector:

1. Reuse the Phase 4.3 parser for `historys` rows.
2. Write production raw evidence through `RawStore`.
3. Insert `collector_runs`, `raw_responses`, and `historical_price_bars` rows.
4. Add parser, idempotency, conflict, raw linkage, and quality check tests.
5. Keep scheduler disabled.

## Production Rollout Plan

1. Apply migration after review. Done in Phase 4.5.
2. Run source seed. Required before Phase 4.6 server run if the source row is not present yet.
3. Run a single manual historical collector for one product with `days=30`.
4. Verify `collector_runs`, `raw_responses`, and `historical_price_bars`.
5. Verify duplicates and quality checks.
6. Run all four confirmed products manually.
7. Run the all-products command again to verify idempotency.
8. Compare bars against current snapshots for overlapping dates in a later analysis step.
9. Keep feature builder unchanged until explicit feature-source mode is implemented.

## Open Questions

- Confirm final q-field semantics for `historys.htm`: whether `q1/q2/q3/q4/q60` always map to open/close/high/low/volume for all four instruments.
- Decide whether historical source should update existing bars when values change, or store revisions in a separate future audit table.
- Decide exact max response size limits after a few more controlled diagnostics.
- Decide whether `observed_at` should always be UTC midnight or derived from source timestamps when available.
- Decide whether dataset export should expose historical bars before feature builder uses them.
