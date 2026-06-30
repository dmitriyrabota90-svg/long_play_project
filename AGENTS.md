# Commodity Dataset Builder Agent Guide

This file dispatches work to the smallest relevant project context. It is not a
replacement for code, tests, Git history, or validated production evidence.

## Source-Of-Truth Order

Use this precedence when facts disagree:

1. Code and tests.
2. Committed Git history.
3. Current production diagnostics.
4. Versioned design documents.
5. `docs/codex/CURRENT_STATE.md`.

Never infer production state from local code alone.

## Mandatory Read Order

For every new task:

1. Read `AGENTS.md`.
2. Read `docs/codex/CURRENT_STATE.md`.
3. Read `docs/codex/CONTEXT_INDEX.md`.
4. Read only the relevant area documents, code, and tests listed there.

Use `python scripts/codex_project_context.py --area <area>` for a bounded
summary before broad repository searches.

## Safety Rules

- Work local-first by default.
- Require explicit user approval for production access and deploys.
- Create and verify a fresh DB backup before intentional production DB writes.
- Do not run Alembic or seed unless explicitly approved.
- Treat deploy, collector probe, backfill, builder rebuild, and export as
  distinct operations with distinct approval scopes.
- Never use `git add .`; stage explicit files.
- Do not commit `.env`, diagnostics, raw/export data, logs, local databases,
  archives, temporary environments, or runtime artifacts.
- Do not claim production state without a read-only audit or validated
  production diagnostic.
- Source availability does not authorize a collector run or backfill.
- Preserve as-of and fetched-at boundaries; do not introduce future leakage.

## Domain Dispatch

| Area | Start here |
|---|---|
| Supply-demand / USDA PSD | `docs/codex/CONTEXT_INDEX.md#usda-psd-country-mappings` |
| Country baskets | `docs/codex/CONTEXT_INDEX.md#supply-demand-country-baskets` |
| Weather | `docs/WEATHER_DATA_DESIGN.md` |
| Prices / FX | `README.md`, `app/collectors/prices/`, `app/collectors/fx/` |
| Dataset export | `docs/DATASET_EXPORT.md` |
| Quality / incidents | `docs/codex/CONTEXT_INDEX.md#quality-and-incidents` |
| Production operations | `docs/codex/RUNBOOKS/` |
| Code review | `docs/codex/RUNBOOKS/safe-code-review.md` |

System architecture and durable decisions:

- `docs/codex/ARCHITECTURE_MAP.md`
- `docs/codex/DECISION_INDEX.md`
- `docs/SOURCE_TO_FEATURE_LINEAGE.md`
- `docs/LEAKAGE_AND_ASOF_AUDIT.md`

## Context Tools

Read-only context script:

```bash
python scripts/codex_project_context.py --area all
python scripts/codex_project_context.py --area mapping
python scripts/codex_project_context.py --area production
python scripts/codex_project_context.py --area review
```

Runbooks:

- `docs/codex/RUNBOOKS/production-readonly-audit.md`
- `docs/codex/RUNBOOKS/production-write-change.md`
- `docs/codex/RUNBOOKS/safe-code-review.md`

Reusable workflows are documented rather than auto-installed because
repository-local skill discovery is not confirmed in the current setup:

- `docs/codex/skills/supply-demand-safe-change.md`
- `docs/codex/skills/production-readonly-audit.md`
- `docs/codex/skills/safe-code-review.md`

## Maintenance

Update `docs/codex/CURRENT_STATE.md` manually after a validated production
change or a durable local milestone. Keep it concise and evidence-based. Do not
paste raw logs, SQL dumps, secrets, full diagnostics, or speculation into it.
