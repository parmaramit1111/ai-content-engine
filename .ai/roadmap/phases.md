# MVP Development Roadmap

This roadmap converts the PRD and architecture into small, reviewable development phases.

The roadmap is a planning contract for coding agents. It does not replace `docs/PRD.md` or `docs/ARCHITECTURE.md`; those remain the source of truth.

## Operating rules

- Complete phases in dependency order unless a task explicitly states otherwise.
- A phase is complete only when its completion gate passes.
- Passing tests alone is insufficient; scope, architecture, and acceptance criteria must also pass review.
- Human review remains required before commits during the initial validation period.
- Do not implement future phases opportunistically.
- Do not introduce a frontend, database, cloud infrastructure, autonomous publishing, or undocumented external-service API integration for MVP.
- Prefer the smallest implementation that satisfies the current phase.
- Preserve provider boundaries and quota/budget safety.

## Completed phases

### Phase 01 — Repository Foundation

**Status:** Complete

Established the Python project structure, domain foundation, dependency/tooling baseline, and initial tests.

**Gate:** Foundation exists and quality checks pass.

### Phase 02 — Budget & Quota Safety

**Status:** Complete

Established provider budget models, warning/hard-stop policy, reserve protection, usage tracking, and multi-dimensional Gemini request/token handling.

**Gate:** Automated provider work cannot silently exceed configured local safety budgets or enable paid fallback.

### Phase 03 — Configuration

**Status:** Complete

Established environment configuration and externalized budget configuration through YAML.

**Gate:** Runtime settings, secrets, and budget configuration are separated and validated.

### Phase 04 — Gemini Provider

**Status:** Complete

Established the provider abstraction and Gemini implementation with usage accounting and provider-specific error handling.

**Gate:** Gemini works behind `TextGenerationProvider`; application code remains provider-agnostic.

### Phase 05 — Content Generation

**Status:** Complete

Established the first content-generation vertical slice: `ContentBrief` → `ScriptService` → `TextGenerationProvider` → structured JSON → validated `Script`/`Scene` objects.

**Gate:** A valid brief can produce a validated script without persistence or Gemini-specific dependencies in the application layer.

## Remaining MVP phases

### Phase 06 — Research & Input Handling

**Objective:** Establish a structured, human-in-the-loop research workflow that can capture source-grounded material for a content topic.

**PRD alignment:** FR-01 Topic Management, FR-02 Research; NotebookLM remains human-in-the-loop.

**Likely task areas:**

- Define the minimum research data model.
- Capture key facts, terminology, examples, caveats, primary sources, and visual concepts.
- Support manual NotebookLM output/source-set recording.
- Support official documentation and primary-source references.
- Validate research completeness and source references.
- Keep research provider abstractions only where a real programmatic dependency exists.

**Dependencies:** Phase 05.

**Completion gate:** Research can be represented, validated, and supplied to the next workflow stage without pretending to automate NotebookLM.

### Phase 07 — Content Brief Generation

**Objective:** Turn validated topic/research input into a structured `ContentBrief` suitable for script generation.

**PRD alignment:** FR-03 Content Brief; Gemini is the programmatic generation provider.

**Likely task areas:**

- Define/validate brief input contract.
- Build provider-agnostic brief-generation service.
- Generate structured brief fields: topic, category, audience, difficulty, hook, problem, core explanation, example, takeaway, CTA, sources, estimated duration, visual style.
- Validate source attribution and required fields.
- Enforce sensible duration/format constraints.
- Reuse existing Gemini provider and budget protection.

**Dependencies:** Phase 06.

**Completion gate:** Valid research/topic input can produce a validated `ContentBrief` through the provider abstraction.

### Phase 08 — Storyboard & Visual Planning

**Objective:** Convert a validated script into scene-level visual planning suitable for manual Google Flow generation.

**PRD alignment:** FR-05 Storyboard and FR-06 Visual Generation.

**Likely task areas:**

- Define storyboard representation.
- Generate/validate scene-level visual directions.
- Keep narration, duration, on-screen text, and visual direction aligned.
- Produce a visual prompt package suitable for human use in Google Flow.
- Avoid undocumented or unstable Flow API assumptions.

**Dependencies:** Phase 05; Phase 07 is expected for the full end-to-end path.

**Completion gate:** A validated script can produce a validated scene-level storyboard/visual prompt package that can be used manually in Flow.

### Phase 09 — Visual Asset Ingestion & Preparation

**Objective:** Make Flow-generated clips and other visual assets usable by the local production workflow.

**PRD alignment:** FR-06 Visual Generation; Flow remains human-in-the-loop.

**Likely task areas:**

- Define minimal asset metadata required by production.
- Import locally generated/Flow-generated clips.
- Validate file existence, media type, duration, dimensions, and scene association where practical.
- Track manually entered Flow credit usage when applicable.
- Keep generated media out of Git by default.
- Prepare assets for deterministic assembly.

**Dependencies:** Phase 08.

**Completion gate:** Human-generated visual clips can be safely imported, validated, associated with scenes, and prepared for assembly.

### Phase 10 — Audio, Captions & Video Assembly

**Objective:** Produce a publish-ready 9:16 MP4 from prepared visual assets and audio/captions.

**PRD alignment:** FR-07 Audio, FR-08 Video Assembly, FR-09 Captions.

**Likely task areas:**

- Define audio input contract.
- Support human/local/provider-generated narration without coupling the core workflow to one TTS vendor.
- Generate or ingest captions.
- Validate caption terminology and timing.
- Build FFmpeg-based deterministic assembly.
- Support clip ordering, audio, captions, basic transitions, aspect-ratio normalization, and final MP4 output.
- Fail clearly on missing/incompatible media.

**Dependencies:** Phase 09.

**Completion gate:** Given valid scenes/assets/audio/captions, the system can deterministically produce a valid 9:16 publish-ready MP4.

### Phase 11 — Human Review, Packaging & Publication Metadata

**Objective:** Establish the final human-controlled quality gate and package metadata needed for manual YouTube Shorts publication.

**PRD alignment:** FR-10 Human Review, FR-11 Publishing.

**Likely task areas:**

- Define the human review checklist.
- Validate technical accuracy, source correctness, clarity, hook, pacing, visual relevance, AI artifacts, captions, brand consistency, and licensing concerns.
- Record approval/rejection and review findings.
- Record publication metadata without automating YouTube publishing.
- Provide a final content package for manual publication.

**Dependencies:** Phase 10.

**Completion gate:** A completed video cannot be considered publish-ready until the human review gate passes, and all publication metadata can be recorded.

### Phase 12 — End-to-End MVP & Experiment Validation

**Objective:** Prove that the complete workflow can repeatedly produce the initial 10–15 video validation batch and capture the information needed to decide whether to continue.

**PRD alignment:** MVP Definition of Done, Validation Plan, Metrics, Success Criteria.

**Likely task areas:**

- Connect the full workflow end to end.
- Add small composable CLI commands where needed.
- Add end-to-end/integration tests using fakes/fixtures; no real provider calls in automated tests.
- Measure production time, regeneration cycles, incremental cost, and workflow errors.
- Define lightweight analytics metadata capture.
- Produce the first 10–15 videos across the planned categories.
- Record audience and production metrics.
- Document experiment results and lessons learned.

**Dependencies:** Phases 06–11.

**Completion gate:** The team can repeatedly run the local workflow, produce the initial validation batch, record metrics, and document whether the Phase 1 hypothesis has enough evidence to continue, pivot, or stop.

## Dependency graph

```text
Phase 01 Foundation          ✅
        ↓
Phase 02 Budget              ✅
        ↓
Phase 03 Configuration       ✅
        ↓
Phase 04 Gemini Provider     ✅
        ↓
Phase 05 Content Generation  ✅
        ↓
Phase 06 Research/Input
        ↓
Phase 07 Content Brief
        ↓
Phase 08 Storyboard
        ↓
Phase 09 Asset Preparation
        ↓
Phase 10 Audio/Captions/FFmpeg
        ↓
Phase 11 Human Review/Packaging
        ↓
Phase 12 E2E MVP/Experiment
```

Phases 06–08 may contain narrowly scoped technical tasks that can be developed independently when their explicit dependencies are satisfied, but the end-to-end content path follows the order above.

## Global phase completion gate

A phase may be marked complete only when all of the following are true:

- Task acceptance criteria pass.
- Automated tests pass.
- Ruff passes.
- Type checking passes where configured.
- `git diff --check` passes.
- Scope review passes.
- Architecture review passes.
- No secrets, private data, generated media, or unrelated changes are included.
- Human approval is obtained before commit during the initial validation period.
