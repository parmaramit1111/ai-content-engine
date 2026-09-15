# Task 11 — Human Review & Packaging

- **Phase:** 11 Human Review + Packaging
- **Status:** ready
- **Goal:** Provide a structured human review gate and package validated content artifacts for manual publication.
- **Source of truth:** PRD FR-10 and FR-11; ARCHITECTURE §14, §18 and §19.
- **Dependencies:** 10-media-pipeline

## Scope

Implement review checklist/data and packaging metadata so a completed video can be reviewed, approved, rejected, and prepared for manual YouTube Shorts publication.

## Out of scope

- Automatic publishing
- YouTube API integration
- Analytics dashboard
- Automated approval
- Social-platform automation

## Acceptance criteria

1. Review covers technical accuracy, sources, clarity, hook, pacing, visual relevance, AI artifacts, captions, brand consistency, and copyright/licensing concerns.
2. Approval is explicit and human-controlled.
3. A rejected item can record actionable review findings.
4. Packaging identifies the final artifact and relevant metadata.
5. The workflow never publishes automatically.

## Validation

Run the full test suite, Ruff, mypy, and `git diff --check`.

## Review focus

Check that human approval is a real gate, review findings are actionable, and no publishing/API scope has leaked into the MVP.
