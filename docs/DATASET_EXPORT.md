# Dataset Export V1

## What Export V1 Is

Phase 5.0 adds a controlled dataset export for `daily_product_features`.
It produces file artifacts for analysis; it does not train an ML model, create
targets, add new sources, or change production collectors.

## Source Tables

Export v1 reads:

- `daily_product_features`
- `products`

It does not write PostgreSQL metadata in Phase 5.0. The JSON manifest beside
the export file is the export metadata source.

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

## Sources Excluded

Export v1 intentionally excludes:

- `historical_price_bars`
- `historical_price_bar_revisions`
- news
- weather
- commodity benchmarks
- sunflower products
- ML targets and model outputs

## As-Of And Leakage Policy

Export v1 uses `daily_product_features` exactly as stored. The current feature
builder uses current snapshot prices and CBR FX with its existing as-of logic.
Historical bars are not consumed by daily features yet, so the export cannot
accidentally treat historical backfill as if it was available in the past.

## Known Limitations

- No labels or ML targets are included.
- Historical OHLC bars are excluded from features v1.
- News, weather, benchmarks, and sunflower products are not implemented.
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
