# Decision Index

This is a pointer index, not an ADR archive.

| Decision | Status | Why | Canonical detail |
|---|---|---|---|
| Local-first development | Active | Limits production blast radius and separates implementation from operations. | `AGENTS.md` |
| Explicit production write approval and fresh DB backup | Active | Makes intentional DB changes recoverable and scoped. | `docs/codex/RUNBOOKS/production-write-change.md` |
| As-of anti-leakage | Active | Prevents backfilled/future information from appearing historically available. | `docs/LEAKAGE_AND_ASOF_AUDIT.md` |
| Tier A global basket v1 | Deployed | Replaces collection-order fallback with reviewed metric-specific aggregation. | `docs/SUPPLY_DEMAND_GLOBAL_BASKET_POLICY.md` |
| Real WLD precedence | Active | Uses authoritative world rows instead of double aggregation when eligible. | `docs/SUPPLY_DEMAND_COUNTRY_AGGREGATION_DESIGN.md` |
| Minimum available approved basket weight `0.75` | Active | Allows bounded partial coverage without weak or silent substitution. | `docs/SUPPLY_DEMAND_GLOBAL_BASKET_POLICY.md` |
| Tier B/C deferral | Active | Avoids premature broad baskets and direct ratio weighting. | `docs/SUPPLY_DEMAND_GLOBAL_BASKET_POLICY.md` |
| Source-ready is not backfill authorization | Active | Separates source contract, production inventory, and operation approval. | `docs/USDA_PSD_TIER_A_SOURCE_CONTRACT_AUDIT.md` |
| Historical OHLC separated from snapshots | Active | Preserves semantics and leakage profile. | `docs/HISTORICAL_PRICE_BARS_DESIGN.md` |
| Runtime artifacts stay outside Git | Active | Keeps history reproducible and secret/data safe. | `AGENTS.md` |
