# Task Contracts

Task files are the executable backlog for the AI-assisted development framework.

## Contract

Each task must define:

- `id` — stable task identifier.
- `phase` — roadmap phase.
- `title` — concise task name.
- `status` — `ready`, `in_progress`, `blocked`, or `done`.
- `goal` — one concrete outcome.
- `source_of_truth` — PRD/architecture sections that govern the task.
- `scope` — what the agent may change.
- `out_of_scope` — explicit boundaries.
- `dependencies` — completed task IDs required first.
- `acceptance_criteria` — observable completion conditions.
- `validation` — required tests and quality checks.
- `review_focus` — architectural and scope concerns.

## Execution rule

One task should produce one small, reviewable vertical slice whenever practical. The implementation agent must not commit or push unless the task explicitly says so. Human approval remains the gate before commit.

## Lifecycle

```text
ready
  ↓
in_progress
  ↓
validate
  ↓
review
  ├── fail → fix → validate → review
  └── pass → human approval → commit
```

Task files should describe the desired outcome, not prescribe every implementation detail. Agents may choose implementation details within the stated architecture and scope.
