# Production Read-Only Audit

Use only after production read access is explicitly approved.

## Scope Contract

Allowed:

- read HEAD/status and container status;
- run `SELECT` queries;
- inspect schema/version;
- export a bounded inventory CSV to local `/tmp`;
- run local pure audits against that bounded export;
- read validated reports and selected scheduler keys.

Not allowed:

- deploy, pull, build, restart, migration, seed;
- collector, builder, export, cleanup, or backup execution;
- SQL writes or server temporary files unless explicitly approved;
- full `.env`, secrets, raw payloads, or unrelated project access.

## Sequence

1. Write down expected server, project path, HEAD, schema revision, query
   purpose, and output columns.
2. Validate SQL locally: every statement must be `SELECT`/catalog inspection.
3. Preflight production read-only:
   - current HEAD and tracked status;
   - Compose service status;
   - Alembic version via `SELECT`.
4. Inspect only the schema/tables needed for the question.
5. For inventory, select explicit columns and bounded rows. Prefer CSV emitted
   over SSH to a local `/tmp` path; do not create a server artifact.
6. Validate exported headers, row count, date/country/product scope, and that
   no secret or unrestricted metadata column is present.
7. Run the local readiness/audit tool against the local export.
8. Record evidence, limitations, and exact distinction between source
   availability, production inventory, and feature readiness.

## Stop Conditions

Stop immediately if:

- HEAD differs from the approved expected commit;
- tracked production changes exist;
- a command would write to DB/files or restart a service;
- query scope is broader than approved;
- required identifiers or schema differ;
- output includes secrets or unrelated data.

Do not "fix" production during an audit.

## Reporting

Report:

- HEAD, schema revision, service health;
- exact read-only scope and query dimensions;
- counts/ranges and audit result;
- mismatches and stop conditions;
- where the local diagnostic is stored;
- explicit confirmation that no production writes/actions occurred.

Reusable workflow: `docs/codex/skills/production-readonly-audit.md`.
