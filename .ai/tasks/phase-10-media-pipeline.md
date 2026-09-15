# Task 10 — Audio, Captions & FFmpeg

- **Phase:** 10 Audio + Captions + FFmpeg
- **Status:** ready
- **Goal:** Assemble imported visual clips, narration/audio, and reviewed captions into a publish-ready 9:16 MP4 using deterministic local tooling.
- **Source of truth:** PRD FR-07, FR-08, FR-09; ARCHITECTURE §3 and §12.
- **Dependencies:** 09-visual-assets

## Scope

Implement a small media pipeline around FFmpeg that can normalize clips, combine ordered scenes with audio, and add reviewed captions/subtitles.

## Out of scope

- AI video generation
- Automated Flow calls
- Automated publishing
- Advanced editing suite
- Frontend
- Cloud media infrastructure

## Acceptance criteria

1. Input clips can be ordered by scene.
2. Output is normalized to 9:16 vertical format.
3. Audio can be incorporated.
4. Reviewed captions/subtitles can be incorporated.
5. FFmpeg failures are explicit and actionable.
6. Tests do not require large generated media files or external services.
7. The pipeline is deterministic enough to be exercised with small fixtures.

## Validation

Run the full test suite, Ruff, mypy, and `git diff --check`. Where practical, include a small local FFmpeg smoke test.

## Review focus

Check subprocess safety, path handling, deterministic assembly, caption timing, artifact handling, and scope discipline.
