# Claude Code Instructions

## Project

AI Content Engine — a Phase 1 validation project for an AI-assisted technical short-form content production workflow.

Read these files before making architectural or implementation decisions:

1. `docs/PRD.md`
2. `docs/ARCHITECTURE.md`
3. `README.md`

## Working Principles

- Build the smallest correct solution that satisfies the current milestone.
- Do not implement speculative features.
- Keep the MVP CLI-first.
- Keep the core application independent from the CLI and any future frontend.
- Prefer simple local files over a database until a real requirement appears.
- Prefer free/low-cost services during validation.
- Keep provider-specific code behind small interfaces.
- Never commit secrets.
- Do not add dependencies without a clear reason.
- Preserve backward compatibility for existing content schemas when practical.

## Frontend

There is intentionally **no frontend in the initial MVP**.

The architecture must leave room for a future basic web frontend. Do not create React, Next.js, or other frontend code unless the current task explicitly requires it.

If a frontend is introduced later, it must consume the application/API layer rather than duplicate business logic.

## AI Providers

Google services are part of the experiment, but the domain must not become tightly coupled to a vendor-specific implementation.

Google Flow may initially be a human-in-the-loop asset-generation step. Do not invent an undocumented Flow API.

For Gemini/API integrations:

- Keep credentials in environment variables.
- Make provider failures explicit.
- Validate structured outputs with Pydantic.
- Never log secrets or full sensitive provider payloads.

## Media

Use FFmpeg as the primary media-processing foundation.

Do not commit generated large media files to Git unless intentionally selected as a small public fixture/example.

Validate paths and avoid unsafe shell construction.

## Content Quality

Technical accuracy is more important than generation speed.

Generated content must pass human review before publication.

Do not silently invent facts, sources, benchmarks, or technical claims.

Prefer primary sources and official documentation when factual accuracy matters.

## Code Quality

Use:

- Python 3.12+
- Type hints
- Pydantic for structured models
- pytest for tests
- Ruff for formatting/linting

Keep functions focused and modules cohesive.

Do not introduce a framework merely for convention.

## Testing

Every meaningful feature should include appropriate tests.

Before declaring a task complete, run the relevant tests and quality checks.

For external AI calls, use mocks/fixtures in normal automated tests.

## Git Workflow

The repository uses:

- `main` — stable/public branch.
- `development` — active integration branch.
- Feature branches for substantial changes.

Do not rewrite shared history.

Keep commits focused and use clear conventional-style messages where practical.

Do not commit directly to `main` for normal development.

## Documentation

Update documentation when behavior or architecture changes.

Important architectural decisions belong in `docs/decisions/`.

Do not duplicate the complete PRD in code comments.

## Implementation Workflow

For a non-trivial task:

1. Read the relevant requirements.
2. Inspect existing code before editing.
3. State the implementation approach briefly.
4. Make the smallest coherent change.
5. Add/update tests.
6. Run validation.
7. Review the diff for unnecessary complexity.
8. Update documentation if needed.

## Do Not

- Build a frontend prematurely.
- Add a database prematurely.
- Add a queue/job system prematurely.
- Add Kubernetes/cloud infrastructure to the MVP.
- Create autonomous publishing.
- Store secrets in source control.
- Generate fake analytics.
- Treat AI-generated output as automatically correct.
- Over-engineer provider abstractions.

## Definition of Done

A feature is complete when:

- Requirements are satisfied.
- Code is readable and typed.
- Tests cover meaningful behavior.
- Relevant checks pass.
- No secrets or unnecessary generated artifacts are committed.
- Documentation is updated where necessary.
