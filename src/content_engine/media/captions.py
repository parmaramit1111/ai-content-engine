"""Deterministic caption/subtitle derivation from a Storyboard.

Pure and dependency-free: no subprocess, no filesystem access, no
providers, no AI, no speech-to-text. Caption text and timing come
entirely from ``Storyboard.scenes`` (narration + duration), which
Phase 05's ``ScriptService`` and Phase 08's ``StoryboardService`` already
guarantee are non-empty and in strict sequential order — so this module
trusts that order and that guarantee rather than re-validating it.
"""

from __future__ import annotations

from dataclasses import dataclass

from content_engine.domain.models import Storyboard


@dataclass(frozen=True)
class CaptionCue:
    """A single subtitle cue: one scene's narration with its timing window."""

    index: int
    start_seconds: float
    end_seconds: float
    text: str


def build_caption_cues(storyboard: Storyboard) -> list[CaptionCue]:
    """Derive caption cues from a storyboard's scenes.

    Uses ``storyboard.scenes``'s existing order directly (no re-sorting)
    and ``scene.number`` as the cue index. Start/end times are the
    cumulative sum of preceding scene durations — no defensive handling
    for empty narration, since ``Scene.narration`` already has
    ``min_length=1`` enforced by the domain model.
    """
    cues: list[CaptionCue] = []
    cumulative = 0.0
    for scene in storyboard.scenes:
        start = cumulative
        end = cumulative + scene.duration
        cues.append(
            CaptionCue(
                index=scene.number,
                start_seconds=start,
                end_seconds=end,
                text=scene.narration,
            )
        )
        cumulative = end
    return cues


def _format_srt_timestamp(seconds: float) -> str:
    """Format seconds as an SRT timestamp: ``HH:MM:SS,mmm``."""
    total_ms = round(seconds * 1000)
    hours, remainder_ms = divmod(total_ms, 3_600_000)
    minutes, remainder_ms = divmod(remainder_ms, 60_000)
    secs, ms = divmod(remainder_ms, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def render_srt(cues: list[CaptionCue]) -> str:
    """Render caption cues as standard SRT text.

    Output is a soft-subtitle artifact only — nothing here burns captions
    into video, so it stays reviewable/editable ahead of Phase 11.
    """
    blocks = [
        f"{cue.index}\n{_format_srt_timestamp(cue.start_seconds)} --> "
        f"{_format_srt_timestamp(cue.end_seconds)}\n{cue.text}\n"
        for cue in cues
    ]
    return "\n".join(blocks) + ("\n" if blocks else "")
