# Supply-Demand Global Basket Policy

## Scope

```text
product_code: soybean_oil
commodity_family: soybean_oil
policy_version: v1-draft
coverage_threshold: 0.80
source: USDA PSD oilseeds downloadable ZIP
review_window: 2021, 2022, 2023
```

This policy is a governance proposal for a future production rollout. It does
not seed weights, enable country baskets, rebuild features, run collectors, or
change production behavior.

Phase 6.9S discovery used source-data coverage: the selected concrete country
rows for a metric divided by all valid concrete country rows for the same
metric and reviewed marketing years. `WLD`, `R00`, world rows, and non-country
aggregate rows are not part of the country-basket denominator.

## Metric Tiers

### Tier A - Eligible For First Rollout

Tier A metrics have small enough baskets for a first reviewed rollout and reach
the 80% source-data coverage target without CA.

- `production_volume`
- `crush_volume`
- `domestic_consumption`
- `exports_volume`

### Tier B - Requires Explicit Review

Tier B metrics are economically useful but need manual review before rollout
because they require larger baskets, omit an expected core country, or have a
more sensitive interpretation.

- `food_use`
- `beginning_stocks`
- `ending_stocks`

### Tier C - Deferred

Tier C metrics must not be enabled in the first global basket rollout.

- `imports_volume`
- `stock_to_use_ratio`

`imports_volume` is deferred because the 80% basket requires 14 countries and
CA appears only in this metric. `stock_to_use_ratio` is deferred from direct
weighting permanently: it must be derived from approved aggregated components.

## Basket-Size Rule

The v1 governance rule is:

```text
4-7 countries: eligible for first rollout
8-10 countries: manual review required
>10 countries: deferred unless separately approved
```

This is not an immutable statistical truth. It is a practical first-production
control so the first country-basket rollout remains reviewable, explainable, and
bounded. A later policy version may change these limits after production
evidence and review.

## Metric Decisions

| metric | discovery country count | tier | CA selected | seed in first rollout | reason |
|---|---:|---|---|---|---|
| `production_volume` | 4 | A | no | yes, after approval | Reaches 80% with a compact basket. |
| `crush_volume` | 5 | A | no | yes, after approval | Reaches 80% with a compact basket. |
| `domestic_consumption` | 6 | A | no | yes, after approval | Reaches 80% within the first-rollout size rule. |
| `exports_volume` | 6 | A | no | yes, after approval | Reaches 80% within the first-rollout size rule. |
| `food_use` | 7 | B | no | no | Size is rollout-eligible, but the selected basket excludes AR and needs economic review. |
| `beginning_stocks` | 10 | B | no | no | Large stock basket; manual review required. |
| `ending_stocks` | 10 | B | no | no | Large stock basket; manual review required. |
| `imports_volume` | 14 | C | yes | no | Large, dispersed import basket; CA appears here only and separate policy is required. |
| `stock_to_use_ratio` | n/a | C | n/a | no | Derived ratio only; never directly weighted. |

## Phase 6.9U Local Tier A Config

Phase 6.9U converts the reviewed Tier A discovery result into explicit local
code config for `soybean_oil`. It does not seed DB rows, deploy production,
rebuild features, or resume CA probing. Runtime use still requires passing the
reviewed config deliberately to the supply-demand builder or a later approved
deployment step.

The first config version is `supply_demand_global_basket_v1` and uses the exact
Phase 6.9S minimum-prefix 80% coverage country sets and weights:

| metric | selected countries / weights | cumulative source coverage |
|---|---|---:|
| `production_volume` | `CH=0.30156174`, `US=0.20443230`, `BR=0.18026335`, `AR=0.11854805` | `0.80480543` |
| `crush_volume` | `CH=0.31002524`, `US=0.19838896`, `BR=0.17250566`, `AR=0.11500740`, `IN=0.03274302` | `0.82867026` |
| `domestic_consumption` | `CH=0.30853244`, `US=0.20406072`, `BR=0.14997310`, `IN=0.09387629`, `AR=0.03480292`, `MX=0.02218114` | `0.81342660` |
| `exports_volume` | `AR=0.43476831`, `BR=0.19273543`, `RS=0.06502242`, `BL=0.04597907`, `PA=0.04158445`, `US=0.03748879` | `0.81757848` |

CA is absent from all Tier A metrics. It remains deferred with `imports_volume`.

The production seed currently maps `soybean_oil` supply-demand concepts under
commodity family `soybean`; the config records the artifact family
`soybean_oil` in provenance while using the runtime `soybean` key so the
builder can join to existing product/commodity mappings when explicitly
enabled.

## Coverage Rule At Feature Time

Approved country baskets should be used only when enough selected countries are
available for the feature date.

```text
minimum_available_approved_basket_weight: 0.75
```

If selected countries available at a feature date cover at least 75% of the
approved basket weight, the builder may aggregate available countries and
renormalize by available approved weights. The feature metadata must record:

- selected countries;
- available countries;
- missing selected countries;
- configured weights;
- applied renormalized weights;
- available approved basket weight;
- missing-country flag.

If available selected countries cover less than 75% of approved basket weight,
the metric must remain missing and the builder must record explicit provenance
and a missing flag. It must not silently fall back to the latest country row.

Phase 6.9U emits structured provenance decisions:

- `supply_demand_global_basket_v1`
- `supply_demand_global_basket_partial_weight`
- `supply_demand_global_basket_insufficient_weight`
- `supply_demand_real_wld`
- `supply_demand_latest_country_fallback`

## WLD Precedence

Real `WLD` rows override country baskets. If a valid world row exists for a
metric and feature date under the normal as-of rules, the builder should prefer
that row and should not aggregate country baskets for the same metric.

## Ratios

`stock_to_use_ratio` is never directly weighted. It may be derived only when the
required aggregated components satisfy their coverage rules:

```text
stock_to_use_ratio = aggregated_ending_stocks / aggregated_domestic_consumption
```

If either component is missing or below its approved coverage threshold, the
ratio must remain missing.

## Missing-Country Policy

Missing selected countries may renormalize only inside the coverage rule above.
For Tier A rollout metrics, renormalization is acceptable when the available
approved basket weight is at least 75%. Below that level, the metric must be
left missing.

Tier B and Tier C metrics should not be enabled until their own missing-country
policy is reviewed and documented.

## CA Policy

CA is not required for the first soybean-oil global basket rollout. It was not
selected for the Tier A metrics. CA appears only in `imports_volume`, which is a
Tier C deferred metric because it requires a 14-country basket and separate
policy review.

CA probing remains paused until the approved rollout policy explicitly requires
CA data.

## Rollout Plan

Required sequence:

```text
policy approved
-> proposed weights generated
-> reviewed seed/config implementation
-> local tests
-> production deploy
-> rebuild existing supply-demand features
-> validate global basket provenance/coverage
-> only then decide whether CA probe is required
```

Discovery output does not automatically become production configuration. A
separate implementation phase must convert approved country sets and weights
into explicit seed or versioned config data.

Phase 6.9V-L adds the local readiness audit documented in
`docs/SUPPLY_DEMAND_BASKET_READINESS_AUDIT.md`. It evaluates an explicit
inventory export per Tier A metric and marketing year and proposes only the
smallest missing approved-country set needed to reach the `0.75` runtime
threshold. A `local_fixture` audit is demonstration evidence only. Production
deployment/rebuild remains blocked until a separate read-only
`production_inventory_export` audit confirms readiness or an approved bounded
backfill plan is completed.

Phase 6.9V-P adds a separate local source-contract audit documented in
`docs/USDA_PSD_TIER_A_SOURCE_CONTRACT_AUDIT.md`. It verifies the reviewed Tier
A country/metric/year matrix against a current USDA PSD ZIP and the pure local
normalization rules. It does not inspect production inventory. Source-ready
candidate units from that audit are proposals only and must still be compared
with a read-only production inventory before any bounded collection is
approved.

## Open Review Items

- Confirm whether Tier A selected country sets should use exact Phase 6.9S
  country lists or a curated analyst list.
- Decide whether Tier B stock metrics should use a lower first-rollout target or
  wait for broader country collection.
- Define a separate import policy before enabling `imports_volume`.
- Decide where approved weights should live: PostgreSQL seed rows or a versioned
  config file.
