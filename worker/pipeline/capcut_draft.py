"""Generate a CapCut draft that shows the cut/sync "skeleton" as separate,
individually-adjustable clips, instead of a single burned-together video.

Uses pycapcut (community, reverse-engineered draft format) — confirmed
working against the user's real CapCut install (app 8.9.1, draft schema
360000) via a real test draft the user opened successfully. If a future
CapCut update breaks this, the failure mode is pycapcut raising or CapCut
refusing to open the draft — not silent corruption, since we always write
into a fresh draft folder (`allow_replace=True` only replaces our own
previous test/auto draft, never a real project).

Two tracks, both placed on the same post-cut timeline (the audio track's
cumulative kept-segment duration IS that timeline — sync_takes.py's EDL
output_start/output_end already assume it):
  - audio: each KEPT segment from cut_silence.py's `kept_ranges`, back to
    back as separate clips — every cut point is a visible, draggable clip
    boundary in CapCut instead of being invisible inside one file.
  - video: each take assignment from sync_takes.py's EDL, one clip per
    piece — every take switch is likewise a visible, adjustable boundary.
"""
from __future__ import annotations

from pathlib import Path

import pycapcut as cc

WIDTH = 1080
HEIGHT = 1920
FPS = 30
FRAME_US = round(1_000_000 / FPS)  # video (unlike audio) can't have sub-frame clips

AUDIO_TRACK_NAME = "audio_cortado"
VIDEO_TRACK_NAME = "sincronia_takes"


def _us(seconds: float) -> int:
    return round(seconds * 1_000_000)


def probe_duration(path: Path) -> float:
    """Duration via pycapcut's own probing, in seconds. Use this (not
    ffprobe) for anything whose duration feeds a CapCut draft — ffprobe
    and pycapcut disagree on some real files (seen: up to 22ms, on 9 of
    one expert's takes), and using ffprobe upstream to decide how much of
    a take sync_takes.py can allocate, while pycapcut enforces a stricter
    limit downstream, compounds into a real, audible shortfall by the end
    of a video (confirmed: ~150ms across one real EDL). Keeping every
    duration pycapcut-sourced from the start avoids the mismatch instead
    of patching around it per-segment."""
    return cc.VideoMaterial(str(path)).duration / 1_000_000


def build_draft(
    draft_name: str,
    drafts_folder: Path,
    audio_path: Path,
    kept_ranges: list[tuple[float, float]],
    edl: dict,
) -> Path:
    """Returns the path to the created draft folder (inside drafts_folder)."""
    folder = cc.DraftFolder(str(drafts_folder))
    script = folder.create_draft(draft_name, WIDTH, HEIGHT, FPS, allow_replace=True)

    script.add_track(cc.TrackType.audio, AUDIO_TRACK_NAME)
    script.add_track(cc.TrackType.video, VIDEO_TRACK_NAME)

    audio_material = cc.AudioMaterial(str(audio_path))
    # Round each range's own duration to whole microseconds ONCE, then
    # advance the placement cursor by that exact same integer — using an
    # independently-rounded running float cursor instead let consecutive
    # segments' rounding drift by a microsecond and collide
    # (pycapcut.exceptions.SegmentOverlap), even though the source seconds
    # never actually overlapped.
    cursor_us = 0
    for s, e in kept_ranges:
        dur_us = _us(e) - _us(s)
        seg = cc.AudioSegment(
            audio_material,
            cc.Timerange(cursor_us, dur_us),
            source_timerange=cc.Timerange(_us(s), dur_us),
        )
        script.add_segment(seg, AUDIO_TRACK_NAME)
        cursor_us += dur_us
    audio_total_us = cursor_us

    video_materials: dict[str, cc.VideoMaterial] = {}
    # Same running-cursor approach as the audio track, for the same reason:
    # using each range's own output_start/output_end independently let two
    # *adjacent* ranges' shared boundary round to different microseconds
    # (SegmentOverlap), even though sync_takes.py's EDL is genuinely
    # gapless/non-overlapping on the output timeline by construction.
    cursor_us = 0
    for r in edl["ranges"]:
        source_path = edl["sources"][r["source"]]
        if source_path not in video_materials:
            video_materials[source_path] = cc.VideoMaterial(source_path)
        material = video_materials[source_path]
        # Anchor duration on the SOURCE trim, not output_end - output_start:
        # assign_takes() can clamp a piece's video extraction a hair short
        # of its output slot (sub-frame near-miss, see its own comment) —
        # using the mismatched duration here would read as an implicit
        # speed change to pycapcut instead of the harmless rounding it is.
        source_dur_us = _us(r["end"]) - _us(r["start"])
        source_start_us = _us(r["start"])
        # ffprobe (used upstream to size takes) and pycapcut's own duration
        # probing don't always agree on a file's exact length (seen: 19ms
        # apart on a real take) — pycapcut raises instead of silently
        # stopping at EOF like ffmpeg extraction does. First fix tried
        # clamping the duration down to fit, but that quietly lost a few
        # ms per affected clip; those losses compounded across a whole
        # video into a visibly-wrong trailing clip and a gap at the very
        # end. Shift the SOURCE start point earlier instead, so the target
        # duration (and therefore every later clip's position) is
        # preserved exactly — the shift is a few ms into footage that's
        # already just B-roll, imperceptible. Only fall back to shrinking
        # the clip if the take is genuinely too short to absorb the shift.
        overshoot_us = (source_start_us + source_dur_us) - material.duration
        if overshoot_us > 0:
            source_start_us = max(0, source_start_us - overshoot_us)
            source_dur_us = min(source_dur_us, material.duration - source_start_us)
        seg = cc.VideoSegment(
            material,
            cc.Timerange(cursor_us, source_dur_us),
            source_timerange=cc.Timerange(source_start_us, source_dur_us),
        )
        script.add_segment(seg, VIDEO_TRACK_NAME)
        cursor_us += source_dur_us
        last_material, last_source_end_us = material, source_start_us + source_dur_us

    # Safety net for a GENUINE shortfall only (bigger than what frame
    # quantization noise alone could produce) — real gap, real fix. A
    # first version of this fired on a sub-microsecond difference that's
    # really just rounding dust: pycapcut can't create a video clip
    # shorter than one frame, so it silently rounded that up to a FULL
    # frame taken from an arbitrary point in the last take's footage —
    # visible in CapCut as a random, unrelated-looking clip stuck at the
    # end. Video is inherently frame-quantized (unlike audio); anything
    # under half a frame is both unfixable and imperceptible, so it's
    # left alone rather than "fixed" into something worse.
    shortfall_us = audio_total_us - cursor_us
    if shortfall_us >= FRAME_US // 2 and edl["ranges"]:
        available_us = last_material.duration - last_source_end_us
        fill_us = min(shortfall_us, max(0, available_us))
        if fill_us > 0:
            seg = cc.VideoSegment(
                last_material,
                cc.Timerange(cursor_us, fill_us),
                source_timerange=cc.Timerange(last_source_end_us, fill_us),
            )
            script.add_segment(seg, VIDEO_TRACK_NAME)

    script.save()
    return Path(drafts_folder) / draft_name
