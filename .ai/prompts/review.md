# Review Prompt

Review an implemented task as an architecture and scope reviewer. Do not assume that passing tests means the task passes.

## Review order

1. Read the task contract.
2. Read the referenced PRD and architecture sections.
3. Inspect the complete diff, not only newly added tests.
4. Verify every acceptance criterion.
5. Check compatibility with existing domain models and provider abstractions.
6. Look for unnecessary complexity, duplicated abstractions, hidden coupling, and future-scope leakage.
7. Check error handling and validation behavior.
8. Check secrets, generated artifacts, path handling, external calls, and repository hygiene.
9. Check human-in-the-loop boundaries and budget/quota safeguards where applicable.
10. Decide `PASS`, `PASS WITH NOTES`, or `FAIL`.

## Review standard

- A test failure is a blocker unless clearly unrelated and documented.
- Missing acceptance criteria are blockers.
- Architecture violations are blockers unless explicitly justified by the task.
- Minor cleanup that does not affect correctness may be noted without blocking.
- Do not request speculative abstractions or future features.

## Report

Return:

- verdict
- findings ordered by severity
- acceptance-criteria assessment
- architecture assessment
- test/quality assessment
- required fixes, if any
- optional follow-ups that are explicitly outside the current task
