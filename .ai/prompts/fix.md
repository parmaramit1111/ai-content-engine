# Fix Prompt

Fix only the blockers identified by the latest validation/review for the assigned task.

## Instructions

1. Read the task contract and the latest validation/review report.
2. Confirm each reported blocker against the current code before changing anything.
3. Fix only confirmed blockers within the task's scope.
4. Preserve existing public behavior unless the blocker requires a change.
5. Do not add speculative refactors, future-phase features, or new provider integrations.
6. Re-run focused tests, then the full relevant validation suite.
7. Run Ruff, mypy, and `git diff --check` where configured.
8. Do not commit or push.

## Completion report

Return:

- blockers addressed
- files changed
- tests/checks run and results
- remaining blockers
- confirmation that no unrelated changes, secrets, generated media, or local state were added
- confirmation that no commit or push was performed
