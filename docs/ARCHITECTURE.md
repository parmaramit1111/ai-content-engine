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
- Explicit quota/budget protection so free-tier experiments cannot silently create paid usage.

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
   ┌────┼───────────┐
   ↓    ↓     ↓     ↓
Gemini Flow   TTS  Research
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

## 4. External Services & Provider Boundaries

### 4.1 Service responsibilities

| Service | Responsibility | MVP integration |
|---|---|---|
| Gemini API | Structured AI generation: briefs, scripts, storyboards, metadata | Programmatic |
| Google AI Studio | Model/API project management and experimentation | Human/admin |
| NotebookLM | Source-grounded research and fact checking | Human-in-the-loop |
| Google Flow | Video clip generation | Human-in-the-loop |
| FFmpeg | Deterministic media assembly | Programmatic |
| YouTube | Distribution and analytics | Manual in MVP |
| Google Drive | Optional asset/document sharing | Manual/optional |

The core application must not treat NotebookLM, Flow, or Drive as mandatory APIs in MVP.

### 4.2 Provider abstraction

External services must sit behind small interfaces where the application directly calls them.

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

## 5. Quota, Budget & Threshold Architecture

Quota protection is a first-class concern because Phase 1 is explicitly a free/low-cost experiment.

### 5.1 Principles

- Provider limits are configuration, not hard-coded business rules.
- Official quotas and our local safety budgets are separate concepts.
- Unknown quotas must never be presented as known quotas.
- The application must never silently enable paid usage.
- Warning and hard-stop thresholds must be configurable.
- Usage must be observable and attributable to a content/workflow ID where possible.

### 5.2 Budget model

Every measurable provider budget should conceptually contain:

```text
ProviderBudget
├── provider
├── model (optional)
├── period
├── official_limit (optional)
├── local_budget
├── warning_threshold
├── hard_stop_threshold
├── reserve
├── current_usage
├── last_reset
└── reset_strategy
```

### 5.3 Default threshold policy

```text
Warning threshold: 80%
Hard stop:         100%
Reserve:           20%
Paid fallback:     Disabled
```

These percentages are **our safety policy**, not provider guarantees.

### 5.4 Configuration example

```yaml
budgets:
  flow:
    period: daily
    official_limit: 50
    local_budget: 50
    warning_percent: 80
    hard_stop_percent: 100
    reserve_percent: 20
    reset: first_generation_plus_24h

  gemini:
    model: <configured-model>
    period: provider-defined
    official_limit:
      requests_per_minute: null
      tokens_per_minute: null
      requests_per_day: null
    local_budget:
      requests_per_day: null
      tokens_per_day: null
    warning_percent: 80
    hard_stop_percent: 100
    reserve_percent: 20
    paid_fallback: false

  notebooklm:
    period: provider-defined
    official_limit: null
    local_budget: null
    warning_percent: 80
    hard_stop_percent: 100
    paid_fallback: false

  youtube:
    period: provider-defined
    official_limit: null
    local_budget: null
    warning_percent: 80
    hard_stop_percent: 100
    paid_fallback: false
```

For NotebookLM and manually operated services, the budget object is primarily an operational record. It must not invent unsupported provider quotas. For an automated provider, a local budget must be explicitly configured before automated work is allowed.

## 6. Google Flow Integration

Google Flow may initially be a human-in-the-loop step rather than a programmatic API.

Current free-tier assumption, checked September 9, 2026:

- 50 credits/day for non-subscribers.
- Unused daily credits do not roll over.
- Daily refresh is triggered by the first generation.
- Current documented generation costs include 10 credits for Veo 3.1 Lite, 20 for Veo 3.1 Fast, and 100 for Veo 3.1 Quality.
- Gemini Omni Flash generation costs vary by resolution and duration.

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

The application should track manually entered/imported Flow usage rather than pretending it can inspect the user's Flow account.

### Flow safety defaults

```text
Daily allocation: 50
Warning:          40 used
Hard stop:        50 used
Reserve:          10
```

If Google changes these limits, update configuration/documentation rather than application logic.

## 7. Gemini API Integration

Gemini is the primary programmatic AI provider.

Use it for:

- Content briefs
- Script generation
- Storyboards
- Structured metadata
- Evaluation
- Research synthesis where appropriate

Google documents Gemini API rate limits using RPM, TPM and RPD, with limits varying by model and usage tier.

The application must therefore support model-specific limits:

```text
GeminiBudget
├── model
├── RPM
├── TPM
├── RPD
├── local daily request budget
├── local daily token budget
└── warning/hard-stop thresholds
```

Do not assume one global Gemini quota.

If an official limit is unknown, use a local safety budget and label it as such.

### Gemini safety defaults

- Warning: 80% of configured limit.
- Hard stop: 100%.
- Reserve: 20%.
- Paid fallback: disabled.
- Model changes require explicit configuration.

### Google Search grounding

If Gemini Search grounding is enabled later, track its request budget independently from normal Gemini generation because tool quotas can have separate limits.

## 8. NotebookLM Integration

NotebookLM is a human-operated research tool in MVP.

```
Sources
   ↓
NotebookLM
   ↓
Research notes
   ↓
Content brief
   ↓
Gemini
```

Do not build an unofficial or undocumented NotebookLM API integration.

Do not hard-code a NotebookLM quota that has not been confirmed by official documentation for the user's account/plan.

The application may record:

- Research session ID/name
- Source set
- Date
- Topic
- Output notes
- Human verification status

## 9. Google AI Studio

AI Studio is primarily used for:

- Creating/managing Gemini API projects and keys.
- Testing prompts/models.
- Reviewing active model limits.
- Validating free-tier behavior before implementation.

It is not a runtime dependency.

Billing should remain disabled for the Phase 1 free experiment unless explicitly approved.

## 10. YouTube Integration

YouTube is the first distribution channel.

MVP:

- Upload manually.
- Record publication metadata manually.
- Record analytics manually.

No YouTube API is required initially.

If the YouTube Data API is introduced later:

- Track API quota separately.
- Configure a local daily API budget.
- Use warning/hard-stop thresholds.
- Never silently consume paid services.

## 11. Google Drive

Drive is optional manual storage.

MVP:

- No Drive API dependency.
- Local filesystem remains the production source.
- Drive may be used manually for sharing or backup.

## 12. Project Structure

```
ai-content-engine/
├── README.md
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
│       ├── budgets/
│       │   ├── models.py
│       │   ├── tracker.py
│       │   └── policy.py
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

## 13. Domain Model

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

### ProviderUsage

```text
provider
model
operation
content_id
units
unit_type
timestamp
metadata
```

ProviderUsage allows the application to explain how a local budget was consumed without claiming that it has access to provider-side account balances.

## 14. CLI

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
content budget status
```

Exact command names can be refined during implementation.

Commands should call application services rather than contain business logic.

The budget command should show local tracked usage, configured limits, warning state, and hard-stop state.

## 15. Optional Frontend

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

## 16. Artifact Strategy

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

## 17. Configuration

Use environment variables for credentials and runtime settings.

Example:

```text
GEMINI_API_KEY=
CONTENT_ENGINE_ENV=development
ASSET_ROOT=./assets
```

Budget configuration should be separate from secrets.

Example:

```text
CONFIG_ROOT=./config
BUDGET_CONFIG=./config/budgets.yaml
```

Never commit real credentials.

Use `.env.example` as the configuration contract.

## 18. Error Handling

Errors should be:

- Explicit.
- Actionable.
- Logged with useful context.
- Safe to expose to users.
- Free from credentials/secrets.

External provider failures should not corrupt content state.

Quota/budget errors must identify:

- Provider
- Model/operation where applicable
- Current local usage
- Configured threshold
- Whether the limit is official or local
- Recommended next action

## 19. Observability

MVP:

- Structured application logs.
- Workflow IDs/content IDs.
- Provider request timing where available.
- Production step timing.
- Error counts.
- Provider usage events.
- Budget warning/hard-stop events.

Future:

- Metrics backend.
- Distributed tracing.
- Cost dashboards.

Do not overbuild observability before the workflow has meaningful volume.

## 20. Testing Strategy

### Unit

Test:

- Domain validation
- State transitions
- Prompt rendering
- Metadata serialization
- File handling
- FFmpeg command construction
- Budget calculations
- Warning thresholds
- Hard-stop behavior
- Reset-period handling

### Integration

Test:

- Provider adapters
- End-to-end sample workflow
- Video assembly with fixture assets
- Budget tracking around provider calls

External AI calls should be mocked in normal CI.

## 21. Security

- Secrets only through environment/configuration.
- No credential logging.
- Validate file paths.
- Avoid shell injection when invoking FFmpeg.
- Treat generated content and downloaded assets as untrusted input.
- Do not automatically execute generated code or prompts.
- Paid billing must never be enabled by application behavior.

## 22. Architecture Decision Records

Use `docs/decisions/` for decisions that materially affect the project.

Examples:

- ADR-001 CLI-first architecture
- ADR-002 Local filesystem for MVP storage
- ADR-003 FFmpeg as media foundation
- ADR-004 Human review before publishing
- ADR-005 Provider budget and quota protection

Keep ADRs short and decision-focused.

## 23. Evolution Path

### MVP

CLI + local files + AI providers + FFmpeg + local budget tracking.

### Extended MVP

Add:

- Better content queue
- Local SQLite
- Review workflow
- Basic FastAPI API
- Optional web frontend
- Automated usage/analytics collection where supported

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
