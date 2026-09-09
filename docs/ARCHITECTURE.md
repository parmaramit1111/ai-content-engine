# Architecture — AI Content Engine

## 1. Architecture Goals

The architecture must optimize for:

- Fast iteration.
- Low operating cost.
- Human control over generated content.
- Provider flexibility.
- Testability.
- Clear separation between domain logic and external AI/media tools.
- CLI-first MVP.
- Optional future frontend without a rewrite.
- Portfolio-quality engineering.

## 2. Architectural Approach

Use a lightweight layered architecture:

```
CLI / Future Web UI
        ↓
Application Services
        ↓
Domain Models + Workflow
        ↓
Provider Interfaces
   ┌────┼─────┐
   ↓    ↓     ↓
Gemini Flow  TTS
        ↓
 Media Pipeline
        ↓
   Local Artifacts
```

The core workflow must not depend directly on CLI commands or a future frontend.

## 3. Recommended Stack

### Runtime

- Python 3.12+
- uv for environment/package management if adopted during implementation.

### Application

- Pydantic / Pydantic Settings
- Python standard library where sufficient
- Typer or Click for CLI; prefer Typer unless implementation evidence suggests otherwise.

### AI

- Google Gemini / Google AI Studio for structured reasoning and generation.
- NotebookLM for source-grounded research during the content workflow.
- Google Flow for video generation.
- Provider adapters should isolate vendor-specific details.

### Media

- FFmpeg
- Python subprocess integration
- Optional MoviePy only where it meaningfully simplifies orchestration.

### Data

MVP:

- YAML/JSON/Markdown
- Git as version history
- Local filesystem for artifacts

Future:

- SQLite for a local content database.
- PostgreSQL only when a real multi-user/server requirement exists.

### Testing

- pytest
- Unit tests for domain/application logic.
- Integration tests for provider adapters where feasible.
- Snapshot/golden tests for structured prompt outputs where useful.

### Quality

- Ruff
- Formatting/linting through Ruff.
- Type checking with mypy or pyright if justified by project complexity.

### CI

GitHub Actions:

- Install dependencies
- Lint
- Type check if enabled
- Run tests

## 4. Project Structure

```
ai-content-engine/
├── README.md
├── CLAUDE.md
├── LICENSE
├── pyproject.toml
├── .gitignore
├── .env.example
│
├── docs/
│   ├── PRD.md
│   ├── ARCHITECTURE.md
│   └── decisions/
│
├── src/
│   └── content_engine/
│       ├── domain/
│       │   ├── models.py
│       │   └── enums.py
│       ├── application/
│       │   ├── topic_service.py
│       │   ├── research_service.py
│       │   ├── script_service.py
│       │   ├── storyboard_service.py
│       │   ├── production_service.py
│       │   └── validation_service.py
│       ├── providers/
│       │   ├── gemini/
│       │   ├── flow/
│       │   ├── tts/
│       │   └── research/
│       ├── media/
│       │   ├── ffmpeg.py
│       │   ├── captions.py
│       │   └── assembly.py
│       ├── storage/
│       │   └── filesystem.py
│       ├── config.py
│       └── cli.py
│
├── prompts/
│   ├── research/
│   ├── scripts/
│   ├── storyboard/
│   ├── visuals/
│   └── evaluation/
│
├── content/
│   ├── ideas/
│   ├── research/
│   ├── briefs/
│   ├── scripts/
│   ├── storyboards/
│   └── published/
│
├── assets/
│   ├── raw/
│   ├── generated/
│   ├── audio/
│   ├── subtitles/
│   └── final/
│
└── tests/
    ├── unit/
    └── integration/
```

Generated media should generally be ignored by Git. Keep only intentionally selected small/sample assets in the public repository.

## 5. Domain Model

Core entities:

### Topic

```text
id
title
category
audience
difficulty
hook
status
source_refs
created_at
updated_at
```

### ContentBrief

```text
topic
problem
core_explanation
example
takeaway
cta
sources
estimated_duration
visual_style
```

### Script

```text
id
brief_id
version
scenes[]
```

### Scene

```text
number
duration
narration
visual_prompt
onscreen_text
transition
```

### Asset

```text
id
type
path
source
provider
metadata
```

### Production

```text
script_id
assets
audio
captions
output_path
status
validation
```

## 6. Provider Abstraction

External services must sit behind small interfaces.

Conceptually:

```python
class TextGenerationProvider(Protocol):
    async def generate(...): ...

class ResearchProvider(Protocol):
    async def research(...): ...

class VideoProvider(Protocol):
    async def generate_scene(...): ...

class TTSProvider(Protocol):
    async def synthesize(...): ...
```

Do not create abstractions for hypothetical providers. Introduce an interface when it protects the domain/application layer from a real external dependency.

## 7. Flow Integration

Google Flow may initially be a human-in-the-loop step rather than a programmatic API.

Therefore:

```
Storyboard
   ↓
Visual prompt package
   ↓
Google Flow
   ↓
Exported clips
   ↓
Asset ingestion
   ↓
FFmpeg assembly
```

The architecture must support a future automated Flow integration without requiring the rest of the application to know Flow-specific details.

## 8. CLI

Initial commands should be small and composable.

Example:

```bash
content topic create
content research
content brief generate
content script generate
content storyboard generate
content assets prepare
content video assemble
content validate
content package
```

Exact command names can be refined during implementation.

Commands should call application services rather than contain business logic.

## 9. Optional Frontend

A frontend is **not part of the initial MVP**, but the architecture must permit one.

Future structure:

```
                 ┌───────────────┐
                 │ Web Frontend  │
                 └───────┬───────┘
                         ↓
                 ┌───────────────┐
                 │ API / Web App │
                 └───────┬───────┘
                         ↓
                 Application Layer
                         ↓
                  Domain / Providers
```

If implemented, likely candidates are:

- FastAPI for HTTP/API.
- A lightweight React/Next.js frontend only if the UI genuinely needs it.

Do not introduce FastAPI, React, or a database merely because they are familiar technologies. The CLI MVP should remain simple.

## 10. Artifact Strategy

Git should contain:

- Source code
- Documentation
- Prompt templates
- Schemas
- Small fixtures
- Experiment metadata

Git should not normally contain:

- Generated MP4 files
- Large raw video
- Large audio files
- Temporary renders
- API responses containing secrets
- Private datasets

Use `.gitignore` and document local artifact directories.

## 11. Configuration

Use environment variables for credentials and runtime settings.

Example:

```text
GEMINI_API_KEY=
CONTENT_ENGINE_ENV=development
ASSET_ROOT=./assets
```

Never commit real credentials.

Use `.env.example` as the configuration contract.

## 12. Error Handling

Errors should be:

- Explicit.
- Actionable.
- Logged with useful context.
- Safe to expose to users.
- Free from credentials/secrets.

External provider failures should not corrupt content state.

## 13. Observability

MVP:

- Structured application logs.
- Workflow IDs/content IDs.
- Provider request timing where available.
- Production step timing.
- Error counts.

Future:

- Metrics backend.
- Distributed tracing.
- Cost dashboards.

Do not overbuild observability before the workflow has meaningful volume.

## 14. Testing Strategy

### Unit

Test:

- Domain validation
- State transitions
- Prompt rendering
- Metadata serialization
- File handling
- FFmpeg command construction

### Integration

Test:

- Provider adapters
- End-to-end sample workflow
- Video assembly with fixture assets

External AI calls should be mocked in normal CI.

## 15. Security

- Secrets only through environment/configuration.
- No credential logging.
- Validate file paths.
- Avoid shell injection when invoking FFmpeg.
- Treat generated content and downloaded assets as untrusted input.
- Do not automatically execute generated code or prompts.

## 16. Architecture Decision Records

Use `docs/decisions/` for decisions that materially affect the project.

Examples:

- ADR-001 CLI-first architecture
- ADR-002 Local filesystem for MVP storage
- ADR-003 FFmpeg as media foundation
- ADR-004 Human review before publishing

Keep ADRs short and decision-focused.

## 17. Evolution Path

### MVP

CLI + local files + AI providers + FFmpeg.

### Extended MVP

Add:

- Better content queue
- Local SQLite
- Review workflow
- Basic FastAPI API
- Optional web frontend

### Production

Only if validation succeeds:

- Hosted service
- Authentication
- Database
- Object storage
- Job queue
- Analytics
- Automated publishing
- Multi-user frontend

The architecture should allow this progression without prematurely paying its complexity cost.
