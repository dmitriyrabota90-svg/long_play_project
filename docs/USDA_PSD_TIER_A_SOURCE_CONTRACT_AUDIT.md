# USDA PSD Tier A Source-Contract Audit

## Purpose

Phase 6.9V-P adds a pure local audit of the current USDA PSD oilseeds
downloadable ZIP against the reviewed Tier A `soybean_oil` basket contract.
The audit checks raw row availability and the existing local parser mappings.
It does not connect to PostgreSQL, invoke collector orchestration, use
`RawStore`, or write normalized observations.

The source URL is read from `DOWNLOADABLE_DATASET_ENDPOINT` in
`app/collectors/supply_demand/usda_psd_config.py`:

```text
https://apps.fas.usda.gov/psdonline/downloads/psd_oilseeds_csv.zip
```

This is a local source-contract audit against a current USDA PSD ZIP. It does
not prove production database inventory or execute a production backfill.

## Scope

The audit reads the reviewed Tier A configuration directly. The current scope
is `soybean_oil`, marketing years `2021`, `2022`, and `2023`:

| metric | approved countries |
|---|---|
| `production_volume` | `CH`, `US`, `BR`, `AR` |
| `crush_volume` | `CH`, `US`, `BR`, `AR`, `IN` |
| `domestic_consumption` | `CH`, `US`, `BR`, `IN`, `AR`, `MX` |
| `exports_volume` | `AR`, `BR`, `RS`, `BL`, `PA`, `US` |

The audit excludes CA, Tier B/C metrics, `imports_volume`, and direct
`stock_to_use_ratio` weighting.

## Status Contract

- `available`: the required raw row exists and the current pure mapping and
  value parser accept it.
- `missing_raw_row`: no raw row exists for the required identity.
- `expected_unsupported_metric`: an aggregate or detail row is intentionally
  outside the modeled feature contract; this is informational.
- `unexpected_mapping_gap`: the raw row exists but a current metric or country
  mapping is missing.
- `unexpected_parser_failure`: the raw row exists but its value cannot be
  normalized safely.

## Running Locally

Download is opt-in and the destination must resolve under `/tmp`:

```bash
python scripts/audit_usda_psd_tier_a_source_contract.py \
  --download-to /tmp/cdb-tier-a-usda-contract/psd_oilseeds_csv.zip \
  --output /tmp/cdb-tier-a-usda-contract/tier_a_source_contract.json \
  --product-code soybean_oil \
  --marketing-years 2021,2022,2023 \
  --format json
```

An already downloaded ZIP or extracted CSV may be audited with `--zip-path`
or `--csv-path`. Output is written only to the explicit `--output` path.
Markdown output uses `--format md`.

## Phase 6.9V-P Baseline

The 2026-06-21 local run audited the current `psd_oilseeds.csv` member from a
`3,838,477` byte ZIP:

- required matrix cells: `63`;
- available cells: `45`;
- missing raw rows: `0`;
- unexpected parser failures: `0`;
- unexpected metric mappings: `0`;
- country mapping gaps: `18`;
- expected unsupported raw detail/aggregate rows: `135`.

All required country/metric/year raw rows exist. The 18 blocked matrix cells
come from current country resolver gaps:

| country | affected Tier A metrics | affected years |
|---|---|---|
| `IN` | `crush_volume`, `domestic_consumption` | 2021-2023 |
| `MX` | `domestic_consumption` | 2021-2023 |
| `RS` | `exports_volume` | 2021-2023 |
| `BL` | `exports_volume` | 2021-2023 |
| `PA` | `exports_volume` | 2021-2023 |

The source-ready candidate country/year units are AR, BR, US, and CH for each
of 2021-2023, limited to the Tier A metrics required for each country. These
are proposals for a future bounded review. They are not claims that production
is missing rows and they do not authorize a backfill.

## Safety And Rollout

The audit module is deliberately independent of database sessions, collector
classes, and raw production storage.

The follow-up country-mapping review rechecked the same ZIP bytes
(`sha256=1aafe6c59700c954270662b63ff67f9f63c74209cda7557eefd1fc74f2525936`)
and confirmed these source identities:

| raw code | raw country name | project canonical code |
|---|---|---|
| `IN` | India | `IN` |
| `MX` | Mexico | `MX` |
| `RS` | Russia | `RS` |
| `BL` | Bolivia | `BL` |
| `PA` | Paraguay | `PA` |

These are USDA PSD source codes. The project preserves them as canonical
source-country codes instead of guessing ISO aliases. Only the exact raw
country names above are accepted as new aliases; for example, `RUS` remains
unsupported.

After adding the verified mappings, the same 63-cell Tier A contract has 63
available cells, zero mapping gaps, zero missing raw rows, and zero parser
failures. No codes remain unresolved in this bounded five-code review.

Any production action remains separate:

1. Compare the source-ready plan with a separate read-only production
   inventory export.
2. Approve bounded collection units explicitly before any production run.

Do not infer production readiness from this report alone.
