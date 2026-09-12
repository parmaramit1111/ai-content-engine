# AI-Assisted Development Framework

This directory contains the version-controlled framework used to execute the project's development tasks with coding agents.

## Purpose

The framework keeps implementation work small, reviewable, and aligned with `docs/PRD.md` and `docs/ARCHITECTURE.md`.

## Structure

```text
.ai/
├── roadmap/      Phase and milestone definitions
├── tasks/        Small implementation task contracts
├── prompts/      Reusable implement/review/validate/fix prompts
└── state/        Local agent execution state (not committed)
```

## Current status

- Phases 01–05 are complete in the development plan.
- Phases 06–12 have explicit task contracts under `.ai/tasks/`.
- Generic implementation, validation, review, and fix prompts are available under `.ai/prompts/`.
- The next implementation task is **Phase 06 — Research & Input**.

## Operating model

```text
Task Contract
     ↓
  Implement
     ↓
  Validate
     ↓
   Review
   ├── Fail → Fix → Validate → Review
   └── Pass
          ↓
    Human approval
          ↓
       Commit
          ↓
        Push
```

The framework is intentionally lightweight. It is not a separate workflow engine, database, or autonomous deployment system.

## Rules

- `docs/PRD.md` and `docs/ARCHITECTURE.md` remain the project source of truth.
- Existing implementation, domain models, provider interfaces, configuration, and budget controls must be inspected before adding replacements.
- Tasks must have explicit scope, dependencies, and acceptance criteria.
- Passing tests alone does not mean a task passes; scope and architecture must also pass review.
- Coding agents must not silently expand a task into future milestones.
- Coding agents must not commit or push unless explicitly instructed after human review.
- Provider-specific implementations must remain behind existing provider abstractions where those abstractions apply.
- External services that are intentionally human-in-the-loop must not be represented as automated integrations without a documented, supported interface.
- Secrets, API keys, generated media, and local execution state must never be committed.

The framework is designed incrementally so the development process can evolve without becoming a second application to maintain.
