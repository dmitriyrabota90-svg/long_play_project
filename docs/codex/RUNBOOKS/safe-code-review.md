# Safe Code Review

Review only. Do not patch, commit, deploy, or access production unless a
separate request explicitly changes the scope.

## Read Order

1. `AGENTS.md`
2. `docs/codex/CURRENT_STATE.md`
3. `docs/codex/CONTEXT_INDEX.md`
4. Relevant design contract
5. Relevant module and focused tests
6. Diff and nearby ownership boundaries

## Review Dimensions

- behavioral correctness and regressions;
- architecture and ownership boundaries;
- as-of/fetched-at leakage safety;
- idempotency and uniqueness;
- parser validation and malformed input handling;
- error handling and partial-failure semantics;
- transaction/flush/rollback boundaries;
- raw evidence and normalized-row linkage;
- quality check status/severity/details semantics;
- configuration defaults and disabled-by-default operations;
- scheduler/deploy/migration/seed implications;
- test coverage for happy, edge, negative, and invariant paths;
- operational blast radius and rollback clarity.

## Evidence Rules

- Ground every finding in a file/line or reproducible test.
- Distinguish confirmed defects from open questions and residual risk.
- Do not claim production impact from local code alone.
- Do not weaken tests to make a change pass.
- Do not broaden repository search until the context index is insufficient.

## Output Order

1. Findings ordered by severity.
2. Open questions/assumptions.
3. Brief change summary.
4. Tests run and tests not run.
5. Residual operational risk.

If there are no findings, say so explicitly and identify remaining test or
production-validation gaps.

Reusable workflow: `docs/codex/skills/safe-code-review.md`.
