# Task 06 — Research & Input

- **Phase:** 06 Research & Input
- **Status:** ready
- **Goal:** Represent research notes and verified source references needed to create a content brief.
- **Source of truth:** PRD §6, FR-02; ARCHITECTURE §8 and §13.
- **Dependencies:** 05-content-generation

## Scope

Add the smallest domain/application slice required to capture research notes, source references,
verification state, and the handoff into later brief generation.

Research is associated with a `Topic` (see ARCHITECTURE §13 — Topic and PRD FR-01). The research
model must reference or embed the topic it supports without replacing the `Topic` entity.

**Minimum required fields** (must be represented and validated):

- `key_facts` — list of factual points gathered during research
- `terminology` — list of domain terms and definitions
- `examples` — list of concrete examples
- `caveats` — list of known limitations or edge cases
- `primary_sources` — list of source references (URLs or identifiers)
- `visual_concepts` — list of visual directions tied to the topic

`Topic.source_refs` must be preserved as the existing source-reference field; do not duplicate
or replace it unnecessarily. The research model may reference `source_refs` or extend it, but
must not duplicate it as a separate source-of-truth.

**Optional future metadata** (not required for Phase 06 completion):

- NotebookLM session ID/name
- Notes on which sources were used in NotebookLM
- Confidence scores per fact
- Researcher annotations

## Out of scope

- NotebookLM API integration
- Unofficial NotebookLM automation
- New provider abstractions without a concrete need
- Persistent database
- Storyboard, media, publishing, or analytics work
- Any assumption about undocumented or provider-side NotebookLM quotas, account access, or
  programmatic usage limits

## Acceptance criteria

1. Research data has a validated structured representation following the minimum field set above.
2. Primary/source references can be recorded and linked to a Topic.
3. Human verification status is explicit.
4. NotebookLM remains human-in-the-loop; no programmatic NotebookLM API integration.
5. The design does not claim access to provider-side NotebookLM quotas.
6. Existing domain/provider boundaries remain intact.
7. The research model distinguishes required minimum fields from optional future metadata.

## Validation

Run the repository test suite, Ruff, mypy, and `git diff --check`.

## Review focus

Check scope discipline, source attribution, human-in-the-loop boundaries, and compatibility with the existing `ContentBrief` and `ScriptService` flow.
