# Daily slice provenance v1

## Lifecycle

`build_daily_features` selects `price_day.last` once. The same in-memory
`PriceObservation` object supplies both `price_last` and the immutable
`daily_slice_revisions` record. No second lookup by price/date is used.

The main builder transaction writes the mutable daily feature, a build run, and
one immutable revision per processed slice. Each revision stores a reconstructable
JSON content snapshot plus its content SHA, exact selected observation/raw IDs
when available, copied Decimal price, observed/fetched/collection timestamps,
and provider publication timestamp only when the source supplied it.

`readiness_confirmed_at` is intentionally null in that transaction. For the
normal builder path, a new transaction confirms the revision only after the
first transaction has committed. An explicit-session caller receives pending
revision IDs and must invoke `confirm_readiness_after_commit` after its own
successful commit. Confirmation is idempotent and never rewrites an existing
timestamp.

## Failure cases

- Rollback removes both feature changes and pending revisions, so it cannot
  produce READY evidence.
- A crash after commit but before confirmation leaves an immutable pending
  revision, not a false READY record; a later confirmation retry is idempotent.
- A rebuild creates a new build run/revision even for unchanged content; prior
  revisions and their readiness timestamps remain unchanged.
- Legacy rows receive no fabricated provenance. Missing raw evidence is null;
  missing provider timestamp remains `UNKNOWN`, not fresh.

## Evidence export and target audit

`scripts/export_dataset.py daily_slice_evidence --output-dir <dir>` writes an
explicit JSON sidecar plus manifest. The export records its schema, coverage,
export time, content-input hash, and output SHA. Export time is not readiness.
The target-audit runner accepts `--evidence <sidecar>` and accepts a pair only
when the sidecar unambiguously matches product/source/code/Decimal price, the
current slice has confirmed readiness, and a future provider publication
timestamp proves it followed that cutoff. A local ID, fetched time, or equal
price alone never proves source freshness.

## Production rollout and rollback

The additive migrations were applied during the approved 2026-10-02 production
rollout of `cdb-v1-rc-20261001-01`, after a verified database backup. A bounded
builder run and evidence export passed. This does not establish provider-time
freshness for records whose provider timestamp remains unknown. Rollback was
not performed; if needed, disable evidence consumers first and apply the
Alembic downgrade only under a separately approved database change plan.
