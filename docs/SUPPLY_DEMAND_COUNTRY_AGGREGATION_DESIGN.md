# Supply-Demand Country Aggregation Design

## Executive Summary

Phase 6.9O showed that the current supply-demand daily builder uses a representative-country fallback: it prefers `WLD` rows and otherwise selects the latest eligible country row for each product/metric. This made `soybean_oil` features switch from BR to AR when AR became the newest country-level observation, even though BR remained stored and economically relevant.

Phase 6.9P introduces a local-only country-aware aggregation design. The production database schema does not need to change yet because `daily_supply_demand_features.metadata_json` already carries structured provenance and `product_supply_demand_weights` remains the metric mapping layer.

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

For Phase 6.9P, real production weights are intentionally not seeded. US, BR, AR, and CA weights require an approved economic basis, such as production share, trade exposure, or analyst-defined relevance. Tests use explicit sample weights only to validate behavior.

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
2. Keep the default active production basket empty until weights are approved.
3. Add tests with explicit sample US/BR/AR/CA weights.
4. After weight approval, decide whether to persist country weights in a new table or keep a versioned config file.
5. Rebuild supply-demand features in a controlled production phase only after the country-weight policy is approved.

## Open Questions

- Should weights represent production share, export relevance, import exposure, or a blend?
- Should CA be included for soybean oil directly or only as a context country?
- Should each metric have separate country weights, or should one commodity-family basket apply to all additive metrics?
- Should country weights be stored in PostgreSQL later for operational editability and auditability?
