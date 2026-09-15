# Task 09 — Visual Asset Preparation

- **Phase:** 09 Visual Asset Preparation
- **Status:** ready
- **Goal:** Define and validate the asset package needed to bring human-generated Google Flow clips into the local workflow.
- **Source of truth:** PRD FR-06; ARCHITECTURE §6 and §16.
- **Dependencies:** 08-storyboard

## Scope

Add asset metadata/ingestion preparation sufficient to associate imported visual clips with storyboard scenes and content IDs.

## Out of scope

- Programmatic Google Flow integration
- Automated video generation
- Large media storage in Git
- Audio synthesis
- Captioning or FFmpeg assembly

## Acceptance criteria

1. Imported assets have explicit metadata and source information.
2. Assets can be associated with content/scene context.
3. Local generated media remains outside normal Git tracking.
4. The workflow does not pretend to inspect Flow account usage automatically.
5. Validation catches missing or invalid asset metadata.

## Validation

Run the full test suite, Ruff, mypy, and `git diff --check`.

## Review focus

Check artifact boundaries, traceability, media-file handling, Flow human-in-the-loop constraints, and repository cleanliness.
