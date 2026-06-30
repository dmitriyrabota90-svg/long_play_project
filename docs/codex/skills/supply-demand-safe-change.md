# Supply-Demand Safe Change

Use for USDA PSD parsing, country mappings, basket policy, readiness, or daily
supply-demand feature changes.

## Read Order

1. `AGENTS.md`
2. `docs/codex/CURRENT_STATE.md`
3. Relevant section in `docs/codex/CONTEXT_INDEX.md`
4. `docs/SUPPLY_DEMAND_GLOBAL_BASKET_POLICY.md`
5. Focused code and tests only

## Guardrails

- Preserve WLD precedence and as-of eligibility.
- Tier A is limited to production, crush, domestic consumption, and exports.
- Tier B/C remain deferred unless explicitly approved.
- Do not change reviewed weights as part of parser/mapping work.
- Separate source-contract readiness from production inventory and feature
  readiness.
- Do not run collectors, builders, deploys, seed, or migrations by default.
- Source-ready candidates are not backfill authorization.

## Focused Validation

Start with:

```bash
pytest -q tests/test_usda_psd_collector.py \
  tests/test_usda_psd_tier_a_source_contract.py \
  tests/test_daily_supply_demand_features.py \
  tests/test_supply_demand_basket_readiness.py
```

Then run the full suite if code changes pass focused tests. Report whether
weights, scheduler, schema, collectors, or production were untouched.
