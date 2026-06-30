# Architecture Map

## Data Flow

```text
external sources
  -> collector request
  -> immutable raw evidence + raw_responses
  -> normalized source-owned tables
  -> domain daily feature tables
  -> daily_product_features
  -> versioned dataset export + manifest/checksum
```

Detailed lineage: `docs/SOURCE_TO_FEATURE_LINEAGE.md`.

## Ownership Boundaries

### Collection And Raw Evidence

- Collectors: `app/collectors/`
- Shared collector lifecycle: `app/collectors/base.py`
- Immutable raw files: `app/storage/raw_store.py`
- Content/source hashes: `app/storage/hashes.py`
- Run/evidence metadata: `collector_runs`, `raw_responses`

Every normalized external record must retain raw evidence linkage. Diagnostic
downloads are not production raw evidence.

### Normalized Source Tables

- Current snapshots: `price_observations`
- FX: `fx_rates`
- Historical bars: `historical_price_bars`
- Weather: `weather_observations`
- News/events: `news_articles`, `commodity_events`
- Trade: `trade_flows`
- Supply-demand: `supply_demand_observations`

Schema ownership is in `app/db/models.py` and `migrations/versions/`.

### Daily Domain Features

- Supply-demand: `app/features/supply_demand_daily.py`
- Weather: `app/features/weather_daily.py`
- News: `app/features/news_daily.py`
- Trade: `app/features/trade_daily.py`
- Product integration: `app/features/daily.py`

Domain feature tables retain domain-specific as-of and provenance fields.
`daily_product_features` integrates them; it must not erase availability
boundaries.

### Export

- Export implementation: `app/exports/daily_features_export.py`
- CLI: `scripts/export_dataset.py`
- Contract: `docs/DATASET_EXPORT.md`
- Tests: `tests/test_dataset_export.py`

Exports are runtime artifacts. Manifests record schema, row/date coverage,
source tables, Git commit, and file checksums.

## As-Of And Leakage Boundary

An observation's market/report period is not its availability time. Feature
eligibility must use the best available publication timestamp and fall back to
`fetched_at` only under the documented contract. A historical record fetched
today must not appear in an earlier real-time simulation.

Canonical review: `docs/LEAKAGE_AND_ASOF_AUDIT.md`.

Tests anchor this boundary in:

- `tests/test_daily_features.py`
- `tests/test_daily_supply_demand_features.py`
- `tests/test_dataset_export.py`

## Supply-Demand Selection

Selection order:

1. Use an eligible real `WLD` observation when present.
2. Otherwise use the approved metric-specific country basket.
3. For reviewed Tier A baskets, allow partial renormalization only at approved
   available weight `>= 0.75`.
4. Keep the metric missing below threshold; do not silently select the latest
   country.
5. Legacy latest-country fallback applies only where no basket is configured.

Tier A metrics are production, crush, domestic consumption, and exports.
Tier B/C remain deferred.

Canonical policy: `docs/SUPPLY_DEMAND_GLOBAL_BASKET_POLICY.md`.

## Three Different Readiness Claims

- Source availability: raw source rows exist and pure parsing succeeds.
- Production inventory: normalized production rows exist and are eligible.
- Feature readiness: enough eligible observations satisfy as-of and basket
  coverage rules for a feature date.

None implies the next. A source-ready candidate is not backfill authorization.

## Main Project Surfaces

| Surface | Location |
|---|---|
| Configuration | `app/config/` |
| Database | `app/db/`, `migrations/versions/` |
| Collectors | `app/collectors/` |
| Audits/discovery | `app/audits/`, `app/discovery/` |
| Features | `app/features/` |
| Export | `app/exports/` |
| Quality/monitoring | `app/quality/`, `app/monitoring/` |
| Operations | `app/operations/` |
| Scheduler | `app/scheduler/` |
| CLIs | `scripts/` |
| Contracts | `docs/` |
| Regression anchors | `tests/` |

## Test Anchors By Layer

- Collector/raw lifecycle: `tests/test_raw_store.py` and collector tests.
- Schema/migrations: `tests/test_*_schema.py`.
- Supply-demand parsing: `tests/test_usda_psd_collector.py`.
- Basket policy: `tests/test_daily_supply_demand_features.py`.
- Readiness: `tests/test_supply_demand_basket_readiness.py`.
- Integration/export: `tests/test_daily_features.py`,
  `tests/test_dataset_export.py`.
- Operations/quality: `tests/test_operational_tools.py`,
  `tests/test_quality_summary.py`.
