# Supply-Demand Country Weight Methodology

## Executive Summary

Phase 6.9P added a country-aware aggregation engine, but production country weights remain disabled. Phase 6.9Q defines a reviewed methodology and a local proposal generator for country weights. The generator is read-only with respect to project databases: it reads explicit JSON input and writes a proposal JSON to a caller-provided path.

The goal is to avoid arbitrary weights. Equal weights, collection-order fallbacks, or silently invented production baskets are not acceptable for supply-demand features.

## Target Scope

Initial supported target:

```text
product_code: soybean_oil
commodity_family: soybean_oil
candidate countries: US, BR, AR, CA
```

CA is not automatically included in production weights. Its inclusion depends on calculated historical share, source-data coverage, missing-data review, and explicit human approval.

## Weight Logic

Weights are metric-specific. One shared country weight across all metrics is not used.

Additive metrics supported for weight proposals:

- `production_volume`
- `beginning_stocks`
- `ending_stocks`
- `imports_volume`
- `exports_volume`
- `domestic_consumption`
- `crush_volume`
- `food_use`

For each metric and target effective date:

```text
country_weight(metric, country)
=
sum(country metric values over selected completed marketing years)
/
sum(candidate basket metric values over selected completed marketing years)
```

The selected completed marketing years are the previous `N` completed marketing years ending at the explicit `completed_marketing_year`. `N` is a required parameter. No production default is inferred. Examples and tests use `N=3`.

## No-Leakage Rule

A source row may contribute to a proposed weight only when:

```text
source_as_of_date <= weight_effective_as_of_date
```

If multiple source rows exist for the same metric/country/marketing year, the generator uses the latest row whose source as-of date is not later than the effective date. Revised or collected-later information is excluded.

Each proposal retains:

- `weight_effective_as_of_date`
- `input_marketing_years`
- `available_marketing_years`
- `maximum_source_as_of_date`
- `source_as_of_coverage`

## Candidate-Basket Coverage

The generator input should include all available country rows for each metric/year, not only US/BR/AR/CA. Non-basket countries are used in the coverage denominator.

```text
basket_coverage_weight
=
sum(values from included basket countries)
/
sum(values from all valid available countries)
```

This is source-data coverage. It is not guaranteed global market coverage unless the input source itself is complete and reviewed.

## Country Inclusion Policy

No production threshold is hard-coded.

The proposal generator accepts an optional `--minimum-share` parameter. If it is omitted, every candidate country remains visible and included when it has historical data. If it is provided, countries below the threshold are marked as excluded from the proposal while still being reported for review.

Human review is required before enabling weights in production.

## Ratios

The generator does not calculate direct country weights for `stock_to_use_ratio`.

The daily feature builder should continue deriving ratio values after aggregation:

```text
aggregated_ending_stocks / aggregated_domestic_consumption
```

## Missing Data

The proposal generator reports missing data explicitly and does not fill values.

The output includes:

- `missing_country_years`
- `missing_metrics`
- `available_marketing_years`
- `source_as_of_coverage`

Missing years can still produce a partial-history proposal row, but that row requires review before production use.

## Proposal Generator

Example:

```bash
python scripts/propose_supply_demand_country_weights.py \
  --input /tmp/historical_supply_demand.json \
  --output /tmp/soybean_oil_weight_proposal.json \
  --product-code soybean_oil \
  --commodity-family soybean_oil \
  --effective-as-of-date 2024-01-15 \
  --completed-marketing-year 2022 \
  --lookback-years 3 \
  --candidate-countries US,BR,AR,CA
```

Input rows must have fields equivalent to:

```text
product_code
commodity_family
country_code
metric_code
marketing_year
value
source_as_of_date
```

The output is a proposal artifact, not production configuration. Generated proposal files should not be committed unless they are deliberately curated documentation fixtures.

## Rollout Policy

Required sequence:

```text
proposal generator
-> reviewed country-weight configuration
-> explicit seed/config implementation
-> deploy aggregation engine and weights
-> rebuild existing supply-demand features
-> validate US+BR+AR basket
-> only then controlled CA probe
```

Until this sequence is approved and executed, production behavior remains unchanged: no production country weights are seeded and CA probe remains paused.
