# Validate Prompt

Validate the current implementation of one `.ai/tasks/` task without making implementation changes.

## Instructions

1. Read the task contract and its PRD/architecture references.
2. Inspect the current diff and surrounding implementation.
3. Run the repository's relevant automated tests.
4. Run Ruff, mypy, and `git diff --check` where configured.
5. Check for secrets, generated media, caches, local state, or unrelated files.
6. Verify provider boundaries, human-in-the-loop constraints, budget/quota safety, and artifact handling where relevant.
7. Check acceptance criteria individually; do not infer success from tests alone.
8. Do not modify files, commit, or push.

## Report

Return a concise validation report with:

- checks run and results
- acceptance criteria: PASS/FAIL per item
- scope/architecture findings
- security/repository hygiene findings
- blockers
- recommended next action
