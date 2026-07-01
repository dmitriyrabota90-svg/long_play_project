# Current Project State

Manually maintained snapshot. Validate time-sensitive production claims with a
read-only audit before relying on them.

Last reviewed: `2026-07-01`

## Snapshot

- Local branch: `main`
- Local baseline for Phase 7.2:
  `dd483fe4e7f16c6c75c4c10ae6b09269822b205d`
- Production HEAD: `dd483fe4e7f16c6c75c4c10ae6b09269822b205d`
- Production Alembic revision: `0019_supply_demand_features`
- Current local phase: Phase 7.2 strict USDA country identity coherence
  validation.
- Mapping commit `c48b8e7` is deployed. The Phase 7.2 coherence fix is
  local-only until a separate approved deploy.

## Production Baseline

Tier A global basket v1 is deployed and validated for `soybean_oil`.

Tier A metrics:

- `production_volume`
- `crush_volume`
- `domestic_consumption`
- `exports_volume`

Semantics:

- A real eligible `WLD` row takes precedence over country aggregation.
- No current WLD supply-demand rows were observed in the validated production
  inventory.
- Country baskets use explicit metric-specific approved weights.
- Partial baskets may renormalize only when available approved weight is at
  least `0.75`.
- Provenance records selected, missing, and applied countries/weights.
- Tier B/C metrics remain deferred.

Latest validated production export:

- Manifest: `daily_features_v1_20260625_084259_manifest.json`
- Rows: `140`
- Columns: `166`
- Feature dates: `2026-05-20` through `2026-06-25`
- CSV SHA-256:
  `1ed248a656a2017af0c1540d4ba96c1ac76979c25726fa040b657feba587bc86`
- Manifest Git commit: `5fb3221a8680341d6b1bc2923e12ee36b82eebc0`

Latest relevant verified backup:

- File:
  `commodity_dataset_before_tier_a_default_wiring_rebuild_20260625_112958.dump`
- SHA-256:
  `b343feb89999b2b273cf41687d5af571c4d2db7ed31a4519b415744db7acc2e7`

Production scheduler values:

```text
CURRENT_PRICE_SCHEDULER_ENABLED=true
CURRENT_PRICE_SCHEDULE_TIMES=09:00,18:00
CBR_FX_SCHEDULER_ENABLED=true
CBR_FX_SCHEDULE_TIME=10:00
FEATURE_BUILDER_SCHEDULER_ENABLED=true
FEATURE_BUILDER_SCHEDULE_TIME=19:30
```

## Known Quality Condition

The latest validated run had no new problematic checks in the preceding 24
hours. The overall quality conclusion may remain `error` because old pre-fix
USDA diagnostic incidents remain stored. Distinguish historical incidents from
new active failures before changing code or data.

## Country Mapping And Coherence State

Deployed commit `c48b8e7` verifies and maps these USDA PSD source codes:

- `IN=India`
- `MX=Mexico`
- `RS=Russia`
- `BL=Bolivia`
- `PA=Paraguay`

The local Phase 7.2 parser resolves raw code and name independently and rejects
contradictory known identities as `country_identity_mismatch` before metric or
numeric parsing. A current local ZIP revalidation reports `63/63` available
Tier A cells and zero unexpected coherence issues. The fix is not deployed and
does not authorize collection or backfill.

## Next Recommended Work

1. Review and separately deploy the Phase 7.2 coherence fix.
2. Keep USDA collection/backfill prohibited until that deploy is validated.
3. Obtain separate bounded approval before any collector run or backfill.
4. Address strict `as_collected` mode separately; it is outside Phase 7.2.

## Maintenance Contract

Update this file only after committed local milestones or validated production
checks. Do not add raw command output, complete diagnostics, secrets, guesses,
or claims that have not passed the source-of-truth precedence in `AGENTS.md`.
