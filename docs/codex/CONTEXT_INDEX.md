# Context Index

Use this matrix to select two to five primary files before broad searches.

## USDA PSD Country Mappings

- When: parser country gaps, source labels, bounded mapping changes.
- Read first: `docs/USDA_PSD_TIER_A_SOURCE_CONTRACT_AUDIT.md`.
- Code: `app/collectors/supply_demand/usda_psd_config.py`,
  `app/audits/usda_psd_tier_a_source_contract.py`.
- Tests: `tests/test_usda_psd_collector.py`,
  `tests/test_usda_psd_tier_a_source_contract.py`.
- Safe checks: compileall, source-contract fixture tests, local ZIP audit.
- Workflow: `docs/codex/skills/supply-demand-safe-change.md`.

## Supply-Demand Country Baskets

- When: weights, WLD precedence, partial coverage, provenance.
- Read first: `docs/SUPPLY_DEMAND_GLOBAL_BASKET_POLICY.md`.
- Code: `app/features/supply_demand_basket_config.py`,
  `app/features/supply_demand_daily.py`.
- Tests: `tests/test_daily_supply_demand_features.py`,
  `tests/test_supply_demand_basket_readiness.py`.
- Safe checks: focused supply-demand tests; no builder by default.
- Workflow: `docs/codex/skills/supply-demand-safe-change.md`.

## Readiness Audit

- When: source readiness or production inventory readiness is questioned.
- Read first: `docs/SUPPLY_DEMAND_BASKET_READINESS_AUDIT.md`.
- Code: `app/audits/supply_demand_basket_readiness.py`,
  `app/audits/usda_psd_tier_a_source_contract.py`.
- Tests: `tests/test_supply_demand_basket_readiness.py`,
  `tests/test_usda_psd_tier_a_source_contract.py`.
- Safe checks: local fixture/source audit with output under `/tmp`.
- Production runbook: `docs/codex/RUNBOOKS/production-readonly-audit.md`.

## Production Deploy / Write Workflow

- When: deploy, migration, seed, collector, backfill, rebuild, export.
- Read first: `docs/codex/RUNBOOKS/production-write-change.md`.
- Code: operation-specific module plus `app/operations/backup.py`.
- Tests: operation-specific tests and `tests/test_operational_tools.py`.
- Safe local checks: compileall, full pytest, Compose config.
- Production runbook: `docs/codex/RUNBOOKS/production-write-change.md`.

## Production Read-Only Audit

- When: validating HEAD, schema, inventory, scheduler, quality, or isolation.
- Read first: `docs/codex/RUNBOOKS/production-readonly-audit.md`.
- Code: `app/monitoring/operational_report.py`,
  `app/monitoring/quality_summary.py`.
- Tests: `tests/test_operational_tools.py`, `tests/test_quality_summary.py`.
- Safe local checks: validate SQL/export scope before SSH approval.
- Workflow: `docs/codex/skills/production-readonly-audit.md`.

## Dataset Export

- When: export columns, manifest, checksums, reproducibility, leakage.
- Read first: `docs/DATASET_EXPORT.md`.
- Code: `app/exports/daily_features_export.py`,
  `scripts/export_dataset.py`.
- Tests: `tests/test_dataset_export.py`,
  `tests/test_dataset_readiness_audit.py`.
- Safe checks: tests only unless export execution is explicitly requested.
- Related: `docs/LEAKAGE_AND_ASOF_AUDIT.md`.

## Quality And Incidents

- When: quality summary is warning/error or a collector reports skips/failures.
- Read first: `docs/codex/CURRENT_STATE.md`.
- Code: `app/monitoring/quality_summary.py`, `app/quality/checks.py`.
- Tests: `tests/test_quality_summary.py`.
- Safe checks: classify current failures separately from historical and
  expected diagnostic incidents.
- Production runbook: `docs/codex/RUNBOOKS/production-readonly-audit.md`.

## Safe Code Review

- When: review, architecture audit, regression or operational risk assessment.
- Read first: `docs/codex/RUNBOOKS/safe-code-review.md`.
- Code/tests: select from the relevant area above.
- Safe checks: diff inspection and tests; no edits or production access.
- Workflow: `docs/codex/skills/safe-code-review.md`.

## Prices / FX And Weather

- Prices/FX: `app/collectors/prices/`, `app/collectors/fx/`,
  `tests/test_current_price_source.py`, `tests/test_cbr_fx.py`.
- Weather: `docs/WEATHER_DATA_DESIGN.md`,
  `app/collectors/weather/`, `app/features/weather_daily.py`.
- Use area-specific tests before any broad suite.
