# Implement Prompt

You are implementing one task from `.ai/tasks/` in the `ai-content-engine` repository.

## Instructions

1. Read the assigned task contract completely.
2. Read the referenced sections of `docs/PRD.md` and `docs/ARCHITECTURE.md` before changing code.
3. Inspect the existing implementation and tests first. Reuse existing domain models, interfaces, configuration, budget controls, and utilities where appropriate.
4. Implement only the task's stated scope and acceptance criteria.
5. Prefer the smallest composable design that fits the existing architecture.
6. Do not introduce a provider-specific dependency into an application/domain interface when an existing abstraction already covers the need.
7. Do not invent undocumented external APIs, quotas, account access, or automation capabilities.
8. Keep human-in-the-loop boundaries explicit.
9. Never add secrets, API keys, private data, generated media, local agent state, caches, or environment-specific files to Git.
10. Do not modify `README.md`, PRD, architecture, or unrelated components unless the task explicitly requires it.
11. Add or update focused tests for behavior introduced by the task. External provider calls must be mocked/faked in automated tests.
12. Before adding or relying on tests, verify that required test dependencies (e.g. `pytest-asyncio`)
    are declared in `pyproject.toml`. The documented dev installation (`pip install -e ".[dev]"`)
    must be sufficient to run the repository test suite.
13. Do not commit or push. Stop after implementation and validation and report the results.

## Required validation

Run, as applicable to the repository configuration:

- test suite
- Ruff
- mypy
- `git diff --check`

If a required check cannot run, report the exact reason instead of treating the task as complete.

## Completion report

Return:

- files changed
- implementation summary
- tests/checks run and results
- acceptance criteria status
- any limitations or follow-up concerns
- confirmation that no commit or push was performed
