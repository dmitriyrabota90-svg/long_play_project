# Production Read-Only Audit Workflow

Use only with explicit SSH/read-only production approval.

1. Read `docs/codex/RUNBOOKS/production-readonly-audit.md`.
2. State expected HEAD, schema, project path, tables, columns, and row bounds.
3. Permit only Git/status/service reads, catalog inspection, and `SELECT`.
4. Prefer bounded CSV streamed over SSH to local `/tmp`; avoid server files.
5. Validate CSV headers, scope, counts, and absence of secret/unrelated fields.
6. Stop on HEAD/status/schema mismatch, any write, or scope expansion.
7. Run local pure audit helpers only after validating the export.
8. Report evidence and limitations; never infer a backfill requirement.

Do not run deploy, migration, seed, collector, builder, export, restart, or
cleanup. Do not print full `.env`, credentials, raw payloads, or unrelated
project state.
