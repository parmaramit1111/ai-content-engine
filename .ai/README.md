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

## Coding-agent workflow

**Primary setup:** VS Code + Claude Code in the integrated terminal, launched from the repository root.

Claude Code is the primary coding agent for this project now that a Claude Code subscription is available. The repository remains the durable source of truth; a separate Claude Desktop Project is not required for coding work.

Other coding agents may be used for comparison or experimentation, but they must follow the same task contracts, validation rules, architecture boundaries, and Git approval gates.

## Operating model

```text
Task Contract
     ↓
 Investigate
     ↓
  Implement
     ↓
  Validate
     ↓
 Self-review
     ↓
Human approval
     ↓
   Commit
     ↓
    Push
     ↓
   Merge
```

Within a task, the coding agent may iterate on confirmed implementation or validation failures. It must not silently expand the task into future milestones.

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
- Repository state, task contracts, and committed code are the durable context for future coding-agent sessions.

The framework is designed incrementally so the development process can evolve without becoming a second application to maintain.
