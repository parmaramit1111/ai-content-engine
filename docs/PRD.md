# PRD — AI Content Engine

**Phase:** 1 — AI Content Validation  
**Status:** Planning / MVP  
**Repository:** `ai-content-engine`

## 1. Product Summary

AI Content Engine is an AI-assisted content production workflow for turning practical software-engineering and AI-engineering knowledge into short-form vertical videos.

The project is a validation experiment, not a commercial content platform. The first objective is to determine whether we can produce technically credible, visually engaging content efficiently and whether the resulting content generates meaningful audience signals.

### Core hypothesis

> We can use AI-assisted research, scripting, visual generation, and media automation to produce useful technical short-form videos at very low incremental cost, while retaining human engineering judgment and quality control.

### Secondary hypothesis

A validated content workflow can later provide distribution for Phase 2, an AI micro-SaaS.

## 2. Goals

### Primary

1. Establish a repeatable content-production pipeline.
2. Produce publishable 20–60 second technical videos efficiently.
3. Validate topics, hooks, visual formats, and audience response.
4. Measure production effort against audience performance.
5. Identify what should be automated further.

### Secondary

- Demonstrate practical AI engineering publicly.
- Create reusable prompts, schemas, workflows, and tooling.
- Build a portfolio-quality engineering project.
- Create a potential distribution channel for Phase 2.

### Non-goals

- Full commercial CMS.
- Fully autonomous publishing.
- Large-scale infrastructure.
- Complex analytics dashboard.
- Multi-platform automation in the first iteration.
- Building a frontend before the workflow proves useful.
- Optimizing revenue before audience/product validation.

## 3. Target Audience

Primary:

- Software engineers
- Backend engineers
- AI/ML engineers
- Developers learning AI engineering
- Engineering managers and technical leads

Secondary:

- Technical founders
- Developers moving into AI
- Technology professionals who prefer concise visual explanations

## 4. Initial Content Positioning

**Practical software engineering and AI engineering explained visually and simply.**

Initial categories:

- AI engineering: LLMs, tokens, embeddings, RAG, vector databases, context windows, tool calling, agents, inference.
- Backend engineering: APIs, authentication, caching, Redis, queues, database indexes, connection pooling, rate limiting.
- Architecture: monoliths, microservices, event-driven systems, scaling, fault tolerance, API gateways, observability.
- Engineering lessons: performance bottlenecks, production debugging, architecture mistakes, reliability and security lessons.

We should test multiple categories rather than assuming one will win.

## 5. Content Format

Primary channel: **YouTube Shorts**.

Initial format:

- 9:16 vertical video.
- 20–60 seconds.
- One main concept per video.
- Strong opening hook.
- Simple explanation.
- Relevant generated visuals.
- Captions.
- Clear takeaway.
- Lightweight CTA.

Suggested structure:

1. 0–3s: hook.
2. 3–10s: problem/context.
3. 10–45s: explanation.
4. 45–55s: takeaway.
5. Final seconds: CTA.

This is a starting hypothesis and must be tested.

## 6. Production Workflow

```
Idea
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
Audio / Narration
  ↓
Captioning
  ↓
Video Assembly
  ↓
Human Review
  ↓
Publish
  ↓
Analytics
  ↓
Learning / Iteration
```

The workflow should support both manual and automated steps.

## 7. Functional Requirements

### FR-01 Topic Management

Track:

- Topic
- Category
- Audience
- Difficulty
- Hook
- Core takeaway
- Source material
- Status
- Publication metadata

Suggested statuses:

`IDEA`, `RESEARCHING`, `SCRIPTED`, `STORYBOARDED`, `GENERATING`, `EDITING`, `REVIEW`, `APPROVED`, `PUBLISHED`, `ANALYZING`, `ARCHIVED`.

### FR-02 Research

Research should capture:

- Key facts
- Terminology
- Examples
- Caveats
- Primary sources
- Visual concepts

Preferred sources/tools:

- NotebookLM
- Gemini
- Official documentation
- Primary technical sources
- Existing Engineering Journal material

### FR-03 Content Brief

Each video should have structured metadata:

```yaml
topic:
category:
audience:
difficulty:
hook:
problem:
core_explanation:
example:
takeaway:
cta:
sources:
estimated_duration:
visual_style:
```

### FR-04 Script

Scripts must be structured, editable, and versioned.

Each scene should support:

- Narration
- Visual direction
- On-screen text
- Duration
- Transition

### FR-05 Storyboard

Storyboard generation should split a video into independent scenes so that visual generation can be controlled at scene level.

### FR-06 Visual Generation

Primary experiment: Google Flow.

Evaluate available capabilities such as text-to-video, image-to-video, frames/ingredients, scene composition, consistency, and video extension.

Do not tightly couple core architecture to undocumented or unstable Flow APIs. Flow-generated assets may initially be produced through the user-facing workflow and imported into the project.

### FR-07 Audio

Evaluate:

1. Available Google AI voice/TTS.
2. Local/open-source TTS.
3. Human narration where it materially improves credibility.

### FR-08 Video Assembly

Use FFmpeg as the preferred media-processing foundation.

Pipeline should support:

- Clip ordering
- Audio
- Captions
- Basic transitions
- Resolution/aspect ratio normalization
- Final MP4 generation

### FR-09 Captions

Every published video should have reviewed captions with correct technical terminology and mobile-friendly timing.

### FR-10 Human Review

No automatic publishing in MVP.

Review:

- Technical accuracy
- Source correctness
- Clarity
- Hook
- Pacing
- Visual relevance
- AI artifacts
- Caption quality
- Brand consistency
- Copyright/licensing concerns

### FR-11 Publishing

YouTube Shorts is the first distribution channel.

Other platforms may be added later.

### FR-12 Analytics

Track per video:

- Publish date
- Topic/category
- Duration
- Views
- Watch retention / average view duration where available
- Likes
- Comments
- Shares
- Subscribers gained
- Production time
- Regeneration count
- Incremental AI cost

## 8. Validation Plan

Initial batch: **10–15 videos**.

Suggested distribution:

- 3 AI engineering
- 3 backend engineering
- 3 architecture
- 1–6 engineering lessons / experimental formats

The objective is learning, not maximizing volume.

### Primary validation questions

1. Can we reliably produce publishable videos?
2. Which topics attract attention?
3. Which hooks work?
4. Which visual formats work?
5. Does AI-generated video quality meet our standards?
6. Can technical credibility be maintained?
7. Is further automation worth the engineering effort?

## 9. Metrics

### Audience

- Median views/video
- Average views/video
- Average percentage viewed
- Average view duration
- Subscriber conversion
- Engagement rate

### Production

- Minutes/hours per video
- Manual steps
- Regeneration cycles
- Cost/video
- Time saved through automation

### Quality

Score 1–5:

- Accuracy
- Clarity
- Hook
- Visual quality
- Pacing
- Originality
- Overall quality

The primary business signal is **audience value per unit of production effort**, not raw views alone.

## 10. Cost Strategy

Target incremental cost during validation: **₹0 wherever practical**.

Priority:

1. Free Google offerings.
2. Existing subscriptions/accounts.
3. Open-source/local tools.
4. Paid tools only when they materially improve validation.

All actual usage and limits should be documented because free tiers can change.

## 11. Technology Direction

- Python
- Pydantic
- Gemini / Google AI Studio where appropriate
- NotebookLM for source-grounded research
- Google Flow for video generation
- FFmpeg for media processing
- YAML/Markdown for MVP metadata
- Git/GitHub
- pytest
- Claude Code for implementation acceleration

See `docs/ARCHITECTURE.md` for implementation details.

## 12. Frontend Strategy

**No frontend is required for the initial MVP.**

The first interface is a CLI plus files/metadata.

However, architecture must leave room for a **basic frontend** without rewriting the core domain logic.

Potential future frontend:

- Content queue
- Topic editor
- Brief/script editor
- Storyboard viewer
- Asset browser
- Review/approval screen
- Production status
- Analytics

If a frontend is introduced, it should call the same application/service layer rather than duplicating business logic.

Recommended future direction: a lightweight web UI backed by the Python application/API. Do not implement it until the CLI workflow is validated.

## 13. Repository Strategy

The repository is intentionally **public** because the project is also a portfolio and engineering showcase.

Public:

- Generic source code
- Architecture
- Documentation
- Prompt templates
- Schemas
- Tests
- Sample/non-sensitive assets
- Experiment methodology

Never commit:

- API keys
- OAuth credentials
- Personal tokens
- Private analytics
- Private datasets
- Sensitive source material
- Unreleased commercial strategy

Private operational/business material can live outside this repository if needed later.

## 14. MVP Definition of Done

- [ ] Repository foundation exists.
- [ ] Topic can be represented as structured data.
- [ ] Research workflow is documented.
- [ ] Content brief can be generated.
- [ ] Script can be generated.
- [ ] Storyboard can be generated.
- [ ] Visual prompts/assets can be prepared.
- [ ] Flow-generated clips can be incorporated.
- [ ] Audio can be incorporated.
- [ ] Captions can be generated/added.
- [ ] FFmpeg can assemble a publish-ready 9:16 video.
- [ ] Human review checklist exists.
- [ ] Metadata can be recorded.
- [ ] First 10–15 videos can be produced.
- [ ] Analytics can be recorded.
- [ ] Experiment results are documented.

## 15. Success Criteria

Phase 1 succeeds if:

- The workflow is repeatable.
- Production time decreases as templates and automation improve.
- Technical quality remains consistently acceptable.
- The content batch produces identifiable audience signals.
- We can identify winning topics/hooks/formats.
- The repository demonstrates strong AI/software engineering practices.
- There is enough evidence to decide whether to continue, pivot, or stop.

## 16. Future Extensions

If validated:

- Content queue UI
- Automated research
- Automated script/storyboard generation
- Asset generation orchestration
- Review queue
- Analytics feedback loop
- Multi-platform publishing
- Article → multiple Shorts repurposing
- Distribution for Phase 2 micro-SaaS

## 17. Guiding Principle

> **Use AI to increase leverage, not to remove engineering judgment.**

The differentiator is not that AI can generate a video. The differentiator is that we build a disciplined system that turns real technical knowledge into useful content efficiently and measures whether people actually value it.
