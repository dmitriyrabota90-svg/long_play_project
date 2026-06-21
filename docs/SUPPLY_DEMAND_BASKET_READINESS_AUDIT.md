# Supply-Demand Basket Readiness Audit

## Purpose

Phase 6.9V-L adds a pure local audit for the reviewed Tier A `soybean_oil`
country baskets. The tool reads an explicit normalized-observation inventory
file, evaluates whether each required metric/year can satisfy the reviewed
basket policy, and writes a bounded advisory collection plan.

The audit does not open PostgreSQL, create a DB session, use `RawStore`, call a
collector, run a feature builder, or infer production state from prior reports.

## Input Inventory

JSON input may be a list or an object containing `observations` or `inventory`.
Each record requires:

```text
product_code
commodity_family
metric_code
country_code
marketing_year
source_as_of_date
```

`source_as_of_date` must use `YYYY-MM-DD`. Values are not required because this
phase audits presence and availability, not feature values. The reviewed
`soybean_oil` artifact family and the existing runtime family alias `soybean`
are both accepted.

## CLI

```bash
python scripts/audit_supply_demand_basket_readiness.py \
  --input /tmp/supply_demand_inventory.json \
  --output /tmp/tier_a_readiness.json \
  --product-code soybean_oil \
  --commodity-family soybean_oil \
  --audit-as-of-date 2026-06-19 \
  --required-marketing-years 2023 \
  --audit-scope local_fixture \
  --format json
```

Supported output formats are `json`, `csv`, and `md`. The output path is always
explicit. `audit_scope` is either:

- `local_fixture`: default; synthetic/demo input that makes no production claim;
- `production_inventory_export`: a future read-only production inventory export.

## Readiness Statuses

| status | meaning |
|---|---|
| `real_wld_available` | An eligible real world row exists for the metric/year; no country plan is needed. |
| `basket_ready_full` | Every approved country is available by the audit as-of date. |
| `basket_ready_partial` | Some countries are missing, but available approved basket weight is at least `0.75`. |
| `basket_insufficient_weight` | Some eligible inventory exists, but approved available weight is below `0.75`. |
| `missing_inventory` | No eligible inventory row exists for the metric/year. |

Future rows where `source_as_of_date > audit_as_of_date` are ignored and listed
under `source_as_of_coverage.future_rows_ignored`.

## WLD Precedence

A real eligible `WLD`/world row overrides country-basket requirements for its
metric and marketing year. The audit does not synthesize WLD from country rows.

## Approved Weight Rule

The reviewed discovery weights sum to the selected source-coverage prefix, not
necessarily `1.0`. Runtime availability is therefore:

```text
sum(available selected-country weights) / sum(all approved selected-country weights)
```

At least `0.75` is required. Full and sufficient partial baskets produce no
collection plan. Below the threshold, the audit ranks missing approved
countries by configured weight descending and selects the smallest prefix that
would reach `0.75` for that metric/year.

## Bounded Collection Plan

The consolidated plan groups selected missing units by:

```text
country_code + marketing_year
```

It records the Tier A metrics requiring that unit, maximum normalized approved
weight impact, deterministic priority, and reason. A missing row for one
marketing year never satisfies another year. Tier B/C metrics and CA cannot
enter the Tier A plan because they are absent from the reviewed Tier A config.

The tool does not invent or execute production collection commands.

## Production Boundary

A local fixture report demonstrates logic only. It does not describe or prove
current production database coverage. Production readiness requires a later
read-only normalized-observation inventory export labeled
`production_inventory_export`, followed by review of the generated bounded
plan. Deployment and feature rebuild remain blocked until that audit or an
approved bounded backfill is completed.
