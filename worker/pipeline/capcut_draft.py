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
    Its boundaries are snapped to the nearest audio cut (SNAP_TOLERANCE_US)
    since the two are independently-computed estimates of "where's the
    gap" (ASR word timing vs real waveform silence) that don't naturally
    agree to the microsecond — confirmed on a real draft, every take
    switch landed 1-2 frames after the nearest audio cut, consistently.
"""
from __future__ import annotations

import json
from pathlib import Path

import pycapcut as cc

WIDTH = 1080
HEIGHT = 1920
FPS = 30
# Take switches (sync_takes.py, from ASR word timestamps mapped through the
# cut) and audio cuts (cut_silence.py, from real waveform silence
# detection) are two independent measurements of "where's the gap here" —
# they don't always agree to the microsecond. Confirmed on a real draft:
# every take switch landed 1-2 frames (33-67ms) after the nearest audio
# cut, consistently. Snap a take switch to a nearby audio cut within this
# tolerance so the visible clip boundaries actually line up in CapCut,
# matching TAKE_FIT_TOLERANCE_S's existing "close enough" margin elsewhere
# in this pipeline (sync_takes.py) rather than inventing a new number.
SNAP_TOLERANCE_US = 150_000

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


def _place_new_video_ranges(
    script: cc.ScriptFile,
    video_materials: dict[str, cc.VideoMaterial],
    edl: dict,
    audio_bounds: list[int],
    audio_total_us: int,
    start_us: int,
) -> None:
    """Places edl["ranges"] on the video track starting at start_us, with
    every internal boundary snapped to the nearest audio cut and clamped
    so no take is asked to stretch past what it actually has. Shared by
    build_draft (start_us=0) and append_to_draft (start_us = wherever the
    preserved old content ends) — the logic doesn't otherwise differ."""
    for r in edl["ranges"]:
        source_path = edl["sources"][r["source"]]
        if source_path not in video_materials:
            video_materials[source_path] = cc.VideoMaterial(source_path)
    # How much each range's take can actually stretch to, from where
    # sync_takes.py already placed its source start — the ceiling any
    # snap below must respect. sync_takes.py guarantees the RAW duration
    # fits (take_durations is pycapcut-sourced, see _take_durations in
    # run_worker.py), so this is always >= the raw duration; it's the
    # SNAP-driven growth beyond that raw duration that can overshoot it.
    range_capacity_us = [
        video_materials[edl["sources"][r["source"]]].duration - _us(r["start"])
        for r in edl["ranges"]
    ]

    # Take-switch boundaries (raw, unsnapped) — same running-total idea as
    # the audio track, computed first so every boundary can be snapped to
    # the nearest audio cut (see SNAP_TOLERANCE_US) before any segment is
    # built. The very first (start_us) and very last (audio_total_us)
    # boundaries are pinned outright: pinning the last one is what
    # guarantees the video track always ends exactly where the audio
    # track does, with no separate "fill the gap" step needed.
    raw_bounds = [start_us]
    for r in edl["ranges"]:
        raw_bounds.append(raw_bounds[-1] + _us(r["end"]) - _us(r["start"]))

    snapped_bounds = [start_us]
    for i, b in enumerate(raw_bounds[1:-1], start=1):
        nearest = min(audio_bounds, key=lambda ab: abs(ab - b))
        candidate = nearest if abs(nearest - b) <= SNAP_TOLERANCE_US else b
        candidate = max(candidate, snapped_bounds[-1])
        # This boundary is range (i-1)'s END. If snapping it out would ask
        # that range's take for more than it can give, clamp directly
        # against that take's capacity FROM WHEREVER ITS START ACTUALLY
        # LANDED (snapped_bounds[-1]) — not the range's raw/unsnapped
        # duration. A first version fell back to the raw boundary here,
        # which is only safe if the range's START is also still at its
        # raw position; if an *earlier* snap had already pulled that
        # start earlier (extending how much this range needs to cover),
        # "revert to raw end" could still overshoot. Confirmed on a real
        # sweep: a range needing 6.272s from a take with only 6.200s
        # available still overshot with the raw-revert version.
        max_safe = snapped_bounds[-1] + range_capacity_us[i - 1]
        if candidate > max_safe:
            candidate = max(max_safe, snapped_bounds[-1])
        snapped_bounds.append(candidate)
    snapped_bounds.append(audio_total_us)

    # The forward pass above only capacity-checks INTERNAL boundaries —
    # the final one is pinned to audio_total_us unconditionally, with no
    # check that the last range's take can actually reach it. Confirmed
    # on a real render: it can't always, leaving a silent-video stretch
    # at the very end (audio kept playing, no clip covered it). Walk
    # backward from the fixed end and pull a boundary earlier whenever
    # the range it closes needs more than its take's capacity — this
    # only ever shrinks the PRECEDING range's window, which is always
    # capacity-safe (shrinking a range never overshoots its own take).
    # Floored at start_us, never lower — in append mode that's the seam
    # with the preserved old content, which must never be eaten into.
    for i in range(len(snapped_bounds) - 1, 0, -1):
        needed = snapped_bounds[i] - snapped_bounds[i - 1]
        cap = range_capacity_us[i - 1]
        if needed > cap:
            snapped_bounds[i - 1] = max(start_us, snapped_bounds[i] - cap)

    for i, r in enumerate(edl["ranges"]):
        material = video_materials[edl["sources"][r["source"]]]
        # Placed at the FIXED snapped boundary, never an accumulated
        # running cursor — a cursor that advances by each segment's own
        # (possibly clamped) duration lets one shrink silently drag every
        # later segment's position out of place, compounding into a large
        # gap by the end of the video (confirmed on a real render: the
        # final take landed 146ms short of the audio because an earlier
        # clamp went uncorrected). Each segment's placement here depends
        # only on the precomputed, capacity-checked snapped_bounds, so a
        # clamp (if the defensive fallback below still needs one) stays
        # local to that one segment instead of cascading.
        target_start_us = snapped_bounds[i]
        target_dur_us = snapped_bounds[i + 1] - snapped_bounds[i]
        source_start_us = _us(r["start"])
        # Defensive fallback only — the capacity check above should make
        # this a no-op in practice. ffprobe (used upstream to size takes)
        # and pycapcut's own duration probing don't always agree on a
        # file's exact length (seen: 19ms apart on a real take); pycapcut
        # raises instead of silently stopping at EOF like ffmpeg
        # extraction does. Shift the SOURCE start point earlier to absorb
        # any overshoot rather than shrinking the clip.
        source_dur_us = target_dur_us
        overshoot_us = (source_start_us + source_dur_us) - material.duration
        if overshoot_us > 0:
            source_start_us = max(0, source_start_us - overshoot_us)
            source_dur_us = min(source_dur_us, material.duration - source_start_us)
            target_dur_us = source_dur_us
        seg = cc.VideoSegment(
            material,
            cc.Timerange(target_start_us, target_dur_us),
            source_timerange=cc.Timerange(source_start_us, source_dur_us),
        )
        script.add_segment(seg, VIDEO_TRACK_NAME)


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
    audio_bounds = [0]
    for s, e in kept_ranges:
        dur_us = _us(e) - _us(s)
        seg = cc.AudioSegment(
            audio_material,
            cc.Timerange(cursor_us, dur_us),
            source_timerange=cc.Timerange(_us(s), dur_us),
        )
        script.add_segment(seg, AUDIO_TRACK_NAME)
        cursor_us += dur_us
        audio_bounds.append(cursor_us)
    audio_total_us = cursor_us

    video_materials: dict[str, cc.VideoMaterial] = {}
    _place_new_video_ranges(script, video_materials, edl, audio_bounds, audio_total_us, start_us=0)

    script.save()
    return Path(drafts_folder) / draft_name


def _load_track_segments(draft_json_path: Path, track_name: str) -> list[dict]:
    """Reads one named track's segments straight from a saved draft's own
    JSON — material path + exact timeranges, verbatim. Used to preserve
    existing content exactly when appending, without going through
    pycapcut's load_template()/get_imported_track() API: that mode is
    built for REPLACING materials inside an existing template's segments,
    not adding new ones — confirmed directly (add_segment after
    load_template() silently created a second, duplicate-named track
    instead of extending the original)."""
    data = json.loads(draft_json_path.read_text(encoding="utf-8"))
    material_paths: dict[str, str] = {}
    for category in ("videos", "audios"):
        for m in data.get("materials", {}).get(category, []):
            if "path" in m:
                material_paths[m["id"]] = m["path"]

    for t in data.get("tracks", []):
        if t.get("name") != track_name:
            continue
        segments = sorted(t.get("segments", []), key=lambda s: s["target_timerange"]["start"])
        return [
            {
                "material_path": material_paths.get(s["material_id"], ""),
                "target_dur_us": s["target_timerange"]["duration"],
                "source_start_us": s["source_timerange"]["start"],
                "source_dur_us": s["source_timerange"]["duration"],
            }
            for s in segments
        ]
    return []


def append_to_draft(
    draft_name: str,
    drafts_folder: Path,
    new_audio_path: Path,
    new_kept_ranges: list[tuple[float, float]],
    new_edl: dict,
) -> Path:
    """Extends an EXISTING draft (built by build_draft or a previous
    append_to_draft call) with new content placed after whatever's
    already there — e.g. Part 2 of the same CTV/VSL landing in the same
    CapCut project as a continuation, not a fresh draft. Raises
    FileNotFoundError if draft_name doesn't exist yet, or ValueError if
    it exists but doesn't look like one this pipeline built."""
    drafts_folder = Path(drafts_folder)
    old_json_path = drafts_folder / draft_name / "draft_content.json"
    if not old_json_path.exists():
        raise FileNotFoundError(f"draft not found to append to: {draft_name!r}")

    old_audio_segs = _load_track_segments(old_json_path, AUDIO_TRACK_NAME)
    old_video_segs = _load_track_segments(old_json_path, VIDEO_TRACK_NAME)
    if not old_audio_segs or not old_video_segs:
        raise ValueError(
            f"draft {draft_name!r} doesn't have the tracks this pipeline expects "
            f"({AUDIO_TRACK_NAME!r}/{VIDEO_TRACK_NAME!r}) — was it built by something else?"
        )

    folder = cc.DraftFolder(str(drafts_folder))
    script = folder.create_draft(draft_name, WIDTH, HEIGHT, FPS, allow_replace=True)
    script.add_track(cc.TrackType.audio, AUDIO_TRACK_NAME)
    script.add_track(cc.TrackType.video, VIDEO_TRACK_NAME)

    audio_materials: dict[str, cc.AudioMaterial] = {}

    def _audio_material(path: str) -> cc.AudioMaterial:
        if path not in audio_materials:
            audio_materials[path] = cc.AudioMaterial(path)
        return audio_materials[path]

    cursor_us = 0
    audio_bounds = [0]
    for seg in old_audio_segs:
        s = cc.AudioSegment(
            _audio_material(seg["material_path"]),
            cc.Timerange(cursor_us, seg["target_dur_us"]),
            source_timerange=cc.Timerange(seg["source_start_us"], seg["source_dur_us"]),
        )
        script.add_segment(s, AUDIO_TRACK_NAME)
        cursor_us += seg["target_dur_us"]
        audio_bounds.append(cursor_us)

    new_audio_material = _audio_material(str(new_audio_path))
    for s_sec, e_sec in new_kept_ranges:
        dur_us = _us(e_sec) - _us(s_sec)
        seg = cc.AudioSegment(
            new_audio_material,
            cc.Timerange(cursor_us, dur_us),
            source_timerange=cc.Timerange(_us(s_sec), dur_us),
        )
        script.add_segment(seg, AUDIO_TRACK_NAME)
        cursor_us += dur_us
        audio_bounds.append(cursor_us)
    audio_total_us = cursor_us

    video_materials: dict[str, cc.VideoMaterial] = {}
    video_cursor_us = 0
    for seg in old_video_segs:
        if seg["material_path"] not in video_materials:
            video_materials[seg["material_path"]] = cc.VideoMaterial(seg["material_path"])
        s = cc.VideoSegment(
            video_materials[seg["material_path"]],
            cc.Timerange(video_cursor_us, seg["target_dur_us"]),
            source_timerange=cc.Timerange(seg["source_start_us"], seg["source_dur_us"]),
        )
        script.add_segment(s, VIDEO_TRACK_NAME)
        video_cursor_us += seg["target_dur_us"]

    _place_new_video_ranges(
        script, video_materials, new_edl, audio_bounds, audio_total_us, start_us=video_cursor_us,
    )

    script.save()
    return Path(drafts_folder) / draft_name
