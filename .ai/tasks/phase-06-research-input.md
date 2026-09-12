# Task 06 — Research & Input

- **Phase:** 06 Research & Input
- **Status:** ready
- **Goal:** Represent research notes and verified source references needed to create a content brief.
- **Source of truth:** PRD §6, FR-02; ARCHITECTURE §8 and §13.
- **Dependencies:** 05-content-generation

## Scope

Add the smallest domain/application slice required to capture research notes, source references, verification state, and the handoff into later brief generation.

## Out of scope

- NotebookLM API integration
- Unofficial NotebookLM automation
- New provider abstractions without a concrete need
- Persistent database
- Storyboard, media, publishing, or analytics work

## Acceptance criteria

1. Research data has a validated structured representation.
2. Primary/source references can be recorded.
3. Human verification status is explicit.
4. NotebookLM remains human-in-the-loop.
5. The design does not claim access to provider-side NotebookLM quotas.
6. Existing domain/provider boundaries remain intact.

## Validation

Run the repository test suite, Ruff, mypy, and `git diff --check`.

## Review focus

Check scope discipline, source attribution, human-in-the-loop boundaries, and compatibility with the existing `ContentBrief` and `ScriptService` flow.
