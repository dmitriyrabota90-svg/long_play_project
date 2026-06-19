# Supply-Demand Country Aggregation Design

## Executive Summary

Phase 6.9O showed that the current supply-demand daily builder uses a representative-country fallback: it prefers `WLD` rows and otherwise selects the latest eligible country row for each product/metric. This made `soybean_oil` features switch from BR to AR when AR became the newest country-level observation, even though BR remained stored and economically relevant.

Phase 6.9P introduces a local-only country-aware aggregation design. The production database schema does not need to change yet because `daily_supply_demand_features.metadata_json` already carries structured provenance and `product_supply_demand_weights` remains the metric mapping layer.

Phase 6.9Q adds the reviewed country-weight methodology and a local proposal generator. Production weights remain disabled until a generated proposal is reviewed and converted into explicit config or seed data.

Phase 6.9S adds coverage-driven global basket discovery. The global basket
configuration is not equivalent to the current production fallback: it is an
explicit reviewed country set per metric, selected by source-data coverage, and
it remains inactive until approved country sets and weights are explicitly
seeded or configured.

Phase 6.9T defines the first draft production governance policy in
`docs/SUPPLY_DEMAND_GLOBAL_BASKET_POLICY.md`. The policy separates metrics that
are eligible for first rollout from metrics requiring review or deferral; it
does not enable production baskets by itself.

## Current Limitation

The current fallback policy is collection-order sensitive:

- `WLD` is preferred when real world rows exist.
- If no `WLD` exists, one latest country row is selected.
- Stored country rows that are not latest are ignored.
- Product features can change when a new country is collected, even if that country should be only one part of a product-level basket.

This is acceptable for a diagnostic representative signal, but not for product-level supply-demand features intended to represent a country basket.

## Target Semantics

The target policy is:

1. Preserve `WLD` priority when a real world row exists.
2. If no `WLD` row exists and a country basket is configured for the product and commodity family, aggregate country rows with explicit weights.
3. If no basket is configured, retain the existing latest-country fallback for backward compatibility.
4. Keep metric mapping weights separate from country aggregation weights.

The selected policy should be written to feature metadata so downstream export and audit code can see whether values came from `WLD`, a configured basket, or the legacy latest-country fallback.

## Country Weight Model

Country weights are keyed by:

```text
product_code + commodity_family + country_code
```

The metric mapping layer remains `product_supply_demand_weights`:

```text
product -> supply_demand_commodity/metric -> metric mapping weight
```

The country aggregation layer is separate:

```text
product + commodity_family -> country_code -> country basket weight
```

For Phase 6.9P/6.9Q, real production weights are intentionally not seeded. US, BR, AR, and CA weights require an approved economic basis, such as historical metric share, production share, trade exposure, or analyst-defined relevance. Tests use explicit sample weights only to validate behavior.

The companion methodology document is `docs/SUPPLY_DEMAND_COUNTRY_WEIGHT_METHODOLOGY.md`. It defines metric-specific historical-share proposals and the no-leakage rule for generating candidate weights.

## Additive And Derived Metrics

Country baskets are applied only to additive metrics:

- `production_volume`
- `beginning_stocks`
- `ending_stocks`
- `imports_volume`
- `exports_volume`
- `domestic_consumption`
- `crush_volume`
- `food_use`

Ratios are not averaged directly. `stock_to_use_ratio` should be derived after aggregation from:

```text
aggregated ending_stocks / aggregated domestic_consumption
```

If the source has a `WLD` ratio row, the builder may keep using it under the `WLD` priority rule. If the builder is using a country basket, it should not average country-level ratio rows.

## As-Of And Leakage Rule

Each selected country row must satisfy the existing availability condition:

```text
availability_date <= feature_date
```

Availability date is:

1. `report_published_at` date;
2. else `published_at` date;
3. else `fetched_at` date.

For a country basket, `supply_demand_as_of_date` is the maximum availability date among selected country inputs. This is conservative: the feature is marked as available only when all selected rows used in the computed value were actually available.

## Missing-Country Behavior

The initial policy is partial-basket renormalization with explicit provenance:

- If some configured countries are missing but at least one configured country has an eligible row, aggregate available countries and renormalize by available country weights.
- Write missing configured countries into `metadata_json`.
- Add a missing flag so the feature is visibly incomplete.
- If no configured country has an eligible row, the metric remains missing.

This avoids silent replacement by the newest country while still allowing bounded feature generation during staged data collection.

## Provenance

Feature metadata should include:

- selected country policy;
- per-metric selection mode;
- selected countries;
- configured countries;
- missing configured countries;
- applied weights;
- whether weights were renormalized;
- used observation ids.

No new schema is required for this first local-only phase because `daily_supply_demand_features.metadata_json` already stores structured JSON.

## Rollout Plan

1. Implement configurable country basket support in the local builder.
2. Generate a local proposal with the Phase 6.9Q/6.9S proposal generator.
3. Keep the default active production basket empty until weights and the global basket policy are reviewed and approved.
4. Add tests with explicit sample US/BR/AR/CA weights.
5. After weight approval, decide whether to persist country weights in a new table or keep a versioned config file.
6. Rebuild supply-demand features in a controlled production phase only after the country-weight policy is approved.
7. Resume bounded CA probing only after the reviewed US+BR+AR basket is validated.

## Open Questions

- Should weights represent production share, export relevance, import exposure, or a blend?
- Should CA be included for soybean oil directly or only as a context country?
- Should each metric have separate country weights, or should one commodity-family basket apply to all additive metrics?
- Should country weights be stored in PostgreSQL later for operational editability and auditability?
