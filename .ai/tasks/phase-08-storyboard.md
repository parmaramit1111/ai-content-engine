# Task 08 — Storyboard

- **Phase:** 08 Storyboard
- **Status:** ready
- **Goal:** Transform a validated script into a scene-level storyboard and visual prompt package.
- **Source of truth:** PRD FR-05 and FR-06; ARCHITECTURE §2 and §4.2.
- **Dependencies:** 07-content-brief

## Scope

Add the smallest application/domain slice required to validate scene-level storyboard data and prepare prompts for visual generation.

## Out of scope

- Calling Google Flow programmatically
- Asset downloading or media rendering
- Audio, captions, FFmpeg
- Publishing or analytics

## Acceptance criteria

1. Storyboard output preserves script scene ordering.
2. Each scene can carry usable visual direction/prompt information.
3. Scene-level validation rejects malformed output.
4. Visual generation remains provider-agnostic.
5. Google Flow remains human-in-the-loop.
6. Unit tests use fakes/mocks and make no external calls.

## Validation

Run the full test suite, Ruff, mypy, and `git diff --check`.

## Review focus

Check scene traceability, prompt quality, Flow boundary, and whether the implementation adds only the structures needed by the next phase.
