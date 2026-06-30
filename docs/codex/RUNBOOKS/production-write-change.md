# Production Write Change

Production writes are exceptional and require explicit scope.

## Required Gate

```text
explicit approval
-> preflight
-> expected commit gate
-> fresh DB backup
-> minimal deploy
-> operation-specific validation
-> stop gate
-> diagnostics
-> final state check
```

## Procedure

1. Confirm the approved operation separately:
   - deploy;
   - migration;
   - seed;
   - collector/probe;
   - backfill;
   - builder rebuild;
   - dataset export.
2. Confirm local tests, pushed commit, expected production predecessor, and
   rollback boundary.
3. Preflight server HEAD, tracked status, services, schema, storage, and
   baseline table counts.
4. Stop if HEAD/status/schema differs from the approved plan.
5. Create a fresh timestamped PostgreSQL backup inside the approved backup
   path. Record file size and SHA-256.
6. Deploy only the expected commit with the minimum required service action.
7. Run Alembic or seed only when explicitly included in approval.
8. Execute only the approved operation with bounded products/dates/records.
9. Validate operation-specific invariants: counts, duplicates, raw linkage,
   as-of boundaries, quality checks, and idempotency where applicable.
10. Stop before expanding scope if any write count, conflict, parser error,
    schema result, or provenance differs from expectation.
11. Save concise diagnostics outside Git.
12. Recheck HEAD, schema, services, table counts, quality, scheduler settings,
    and tracked status.

## Separation Rules

- A deploy does not authorize a migration.
- A migration does not authorize seed or collection.
- A collector probe does not authorize a backfill.
- A backfill does not authorize a feature rebuild.
- A feature rebuild does not authorize export.
- Source readiness does not authorize any production operation.

Never recreate the PostgreSQL volume, delete raw data, or modify unrelated
nginx/PM2/systemd/firewall services as part of this workflow.
