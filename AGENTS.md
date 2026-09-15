# AGENTS.md — Repository Guide for Coding Agents

This repository is developed primarily with **Claude Code**, normally launched from the integrated terminal in VS Code. Other coding agents may be used, but the repository workflow and source-of-truth rules apply to all agents.

## Source of truth

Read these before implementing a non-trivial task:

1. `docs/PRD.md` — product requirements and MVP boundaries
2. `docs/ARCHITECTURE.md` — technical architecture and integration boundaries
3. `.ai/tasks/<task>.md` — exact task scope and acceptance criteria
4. `.ai/prompts/implement.md` — implementation workflow

The repository is the source of truth. Do not depend on a separate Claude Desktop Project or hidden conversation state for project requirements.

## Recommended development environment

Use VS Code as the development workspace and run Claude Code from the repository root in the integrated terminal:

```bash
cd /path/to/ai-content-engine
claude
```

Claude Code should operate on the active Git branch and use the repository files as its durable context.

## Development lifecycle

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

Within a single task, an agent may investigate failures and make focused fixes, then rerun validation. It must not silently expand into future phases.

## Git rules

- Work on a dedicated feature branch for implementation tasks.
- Keep unrelated work out of the task branch.
- Do not commit or push during implementation/validation unless the user explicitly approves the completed task.
- Do not merge until the completed commit has been verified.
- Never force-push or rewrite shared history unless explicitly authorized.
- Before committing, inspect `git status`, `git diff`, and the changed-file list.

## Development setup

Install dev dependencies:

```bash
pip install -e ".[dev]"
```

## Commands

### Run tests

```bash
pytest
```

### Lint

```bash
ruff check src/ tests/
```

### Format

```bash
ruff format src/ tests/
```

### Type check

```bash
mypy src/
```

### Diff validation

```bash
git diff --check
```

### Run the standard checks

```bash
ruff check src/ tests/ && mypy src/ && pytest && git diff --check
```

## Repository hygiene

Never commit:

- secrets or API keys
- private/user data
- generated media
- local agent state under `.ai/state/`
- caches or environment-specific files
- unrelated changes

Human-in-the-loop services such as NotebookLM and Google Flow must not be represented as automated integrations without a documented, supported interface.
