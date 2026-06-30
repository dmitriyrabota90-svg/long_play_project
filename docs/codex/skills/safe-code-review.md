# Safe Code Review Workflow

Use for review-only requests.

## Process

1. Read `AGENTS.md`, `CURRENT_STATE.md`, and the relevant context-index entry.
2. Select the smallest module/test/design set.
3. Review correctness, architecture, as-of safety, idempotency, failures,
   transactions, quality semantics, defaults, and operational risk.
4. Run only safe local tests needed to validate a finding.
5. Do not edit code or access production unless separately instructed.

## Finding Standard

Every finding needs:

- severity;
- file and line;
- concrete behavior/risk;
- evidence or reproduction;
- smallest safe remediation direction.

## Final Report

```text
Findings (highest severity first)
Open questions / assumptions
Change summary
Validation performed
Residual risks
```

If no issue is found, state that clearly and list remaining validation gaps.
