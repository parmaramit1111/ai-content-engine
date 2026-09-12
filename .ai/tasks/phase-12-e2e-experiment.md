# Task 12 — E2E MVP & Experiment

- **Phase:** 12 E2E MVP + Experiment
- **Status:** ready
- **Goal:** Prove the local workflow can produce the first 10–15 technical Shorts and record enough production and audience data to make a continue/pivot/stop decision.
- **Source of truth:** PRD §§10–17; ARCHITECTURE §§14, 16, 19 and 20.
- **Dependencies:** 11-review-package

## Scope

Connect the completed workflow into a usable CLI/file-based MVP, document the operating procedure, and provide experiment metadata/templates for production and analytics tracking.

## Out of scope

- Frontend
- Database
- Autonomous publishing
- Multi-platform automation
- Cloud deployment
- Analytics dashboard

## Acceptance criteria

1. The end-to-end workflow is executable locally from structured inputs to a reviewable final artifact.
2. Manual NotebookLM and Flow steps have clear handoff points.
3. Budget protection remains active for automated provider calls.
4. Human review remains mandatory before publication.
5. Production time, regeneration count, incremental AI cost, and audience metrics can be recorded.
6. The first 10–15 video experiment is documented as an operational procedure.
7. Results can be used to identify winning topics/hooks/formats and decide whether to continue, pivot, or stop.

## Validation

Run the full test suite, Ruff, mypy, and `git diff --check`. Perform one end-to-end local smoke run using non-sensitive/sample content.

## Review focus

Review the complete MVP against every PRD Definition-of-Done item. Reject unnecessary infrastructure and verify that the workflow is actually usable by a human operator.
