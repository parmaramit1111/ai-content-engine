# Claude Code Session Start

Use this prompt when starting a new Claude Code session for work in `ai-content-engine`.

```text
You are working in the ai-content-engine repository.

Start by establishing repository state before making any changes.

1. Confirm the repository root.
2. Run `git status`.
3. Run `git branch --show-current`.
4. Inspect recent commits with `git log -5 --oneline`.
5. Read `AGENTS.md`.
6. Read the active task contract under `.ai/tasks/`.
7. Read the relevant sections of `docs/PRD.md` and `docs/ARCHITECTURE.md`.
8. Inspect the existing implementation and tests relevant to the task.
9. Summarize your understanding of:
   - the current branch/state
   - the task goal
   - the task boundaries
   - existing components to reuse
   - files you expect may need to change
10. Do not modify files, commit, or push during this initial investigation.

After the investigation, wait for the implementation instruction unless the user has already explicitly asked you to implement the assigned task.
```

## Notes

- Use the repository as the durable source of truth.
- VS Code is the recommended workspace; Claude Code should normally run from its integrated terminal at the repository root.
- A separate Claude Desktop Project is not required for repository coding.
- Start a fresh Claude Code session at logical checkpoints rather than carrying an oversized context indefinitely.
