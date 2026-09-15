# Task 07 — Content Brief

- **Phase:** 07 Content Brief
- **Status:** ready
- **Goal:** Generate and validate a structured `ContentBrief` from a topic and verified research input.
- **Source of truth:** PRD FR-03; ARCHITECTURE §13 and §4.2.
- **Dependencies:** 06-research-input

## Scope

Add the application workflow and provider-facing prompt contract needed to generate a validated `ContentBrief` without coupling the application layer to Gemini.

The authoritative model shape for `ContentBrief` is defined in `docs/ARCHITECTURE.md` §13 (Domain Model),
not in the broader field list of PRD FR-03. The existing `ContentBrief` domain model must be reused as-is.
The fields `category`, `audience`, `difficulty`, and `hook` are intentionally associated with the `Topic`
entity (ARCHITECTURE §13 — Topic), not with `ContentBrief`. Do not add those fields to `ContentBrief`;
do not modify the existing domain model. If brief generation needs topic-level context, pull it from the
associated `Topic`, not by extending `ContentBrief`.

## Out of scope

- Storyboards
- Visual generation
- Media processing
- Publishing or analytics
- Direct Gemini SDK use in application services
- Persistence beyond existing MVP conventions

## Acceptance criteria

1. Required brief fields from PRD FR-03 are represented.
2. Provider output is parsed and validated before being returned.
3. Generation uses `TextGenerationProvider`, not `GeminiProvider` directly.
4. Invalid provider output produces an explicit actionable error.
5. Source references from research can flow into the brief.
6. No real API calls are required by unit tests.

## Validation

Run the full test suite, Ruff, mypy, and `git diff --check`.

## Review focus

Check schema completeness, provider abstraction, validation quality, prompt determinism, and absence of scope expansion.
