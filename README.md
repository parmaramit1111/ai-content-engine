# AI Content Engine

AI-assisted content production engine for creating, validating, and publishing practical technical short-form videos.

> **Phase 1:** Validate whether we can turn real software/AI engineering knowledge into useful visual content efficiently and at very low incremental cost.

## Why this project?

This is both a side-hustle experiment and an engineering portfolio project.

The goal is not simply to generate AI videos. We are building a disciplined workflow around:

- Research
- Structured content generation
- Storyboarding
- AI video generation
- Media processing
- Human review
- Publishing
- Analytics
- Iteration

The project is designed to demonstrate practical AI engineering rather than a collection of isolated AI demos.

## Current Status

**Phase 1 — Planning / Foundation**

The initial MVP is intentionally **CLI-first**.

There is no frontend or database in the first iteration.

A future basic web frontend is possible if the validated workflow justifies it.

## Architecture

```
Topic
  ↓
Research
  ↓
Content Brief
  ↓
Script
  ↓
Storyboard
  ↓
Visual Generation
  ↓
Audio / Captions
  ↓
FFmpeg
  ↓
Human Review
  ↓
YouTube Shorts
  ↓
Analytics
```

See:

- [Product Requirements](docs/PRD.md)
- [Architecture](docs/ARCHITECTURE.md)

These documents are the source of truth for product requirements and technical design. Claude Code should use them as the project specification when implementing the system.

## Technology Direction

- Python 3.12+
- Gemini / Google AI Studio
- NotebookLM
- Google Flow
- FFmpeg
- Pydantic
- pytest
- Ruff
- GitHub Actions
- Claude Code for development acceleration

The implementation will favor free/open-source tooling during validation.

## Repository Structure

```
docs/       Product and architecture documentation
src/        Python application
prompts/    Version-controlled AI prompts
content/    Content metadata and workflow artifacts
assets/     Local/generated media artifacts
tests/      Automated tests
```

Large generated media should not normally be committed to Git.

## Development

The active development branch is:

```text
development
```

The stable branch is:

```text
main
```

Development decisions should follow `docs/PRD.md` and `docs/ARCHITECTURE.md`.

## Validation Target

The first content batch is approximately **10–15 videos** across AI engineering, backend engineering, architecture, and engineering lessons.

We will evaluate:

- Audience engagement
- Retention
- Subscriber conversion
- Production time
- Regeneration effort
- Technical quality
- Visual quality
- Incremental cost

The goal is to learn quickly and decide whether the workflow deserves further investment.

## Public Repository

This repository is public intentionally.

It is meant to showcase:

- AI engineering
- Python/backend engineering
- Automation
- Prompt engineering
- Media processing
- Testing
- Architecture
- Experiment-driven product development

Never commit:

- API keys
- OAuth tokens
- Private analytics
- Sensitive datasets
- Confidential business information
- Unlicensed third-party media

## License

MIT License. See [LICENSE](LICENSE).

## Guiding Principle

> **Use AI to increase leverage, not to remove engineering judgment.**
