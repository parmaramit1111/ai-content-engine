# AI-Assisted Development Framework

This directory contains the version-controlled framework used to execute the project's development tasks with coding agents.

## Purpose

The framework keeps implementation work small, reviewable, and aligned with `docs/PRD.md` and `docs/ARCHITECTURE.md`.

Planned structure:

```text
.ai/
├── roadmap/      Phase and milestone definitions
├── tasks/        Small implementation task contracts
├── prompts/      Reusable implement/review/validate/fix prompts
└── state/        Local agent execution state (not committed)
```

## Operating model

```text
Task
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
```

The framework is intentionally lightweight. It is not a separate workflow engine, database, or autonomous deployment system.

## Rules

- `docs/PRD.md` and `docs/ARCHITECTURE.md` remain the project source of truth.
- Tasks must have explicit scope and acceptance criteria.
- Passing tests alone does not mean a task passes; scope and architecture must also pass review.
- Coding agents must not silently expand a task into future milestones.
- Human approval remains required before committing changes during the initial validation period.
- Secrets, API keys, generated media, and local execution state must never be committed.

The framework will be designed incrementally before the remaining MVP implementation tasks are added.
