"""Generate a CapCut draft that shows the cut/sync "skeleton" as separate,
individually-adjustable clips, instead of a single burned-together video.

Uses pycapcut (community, reverse-engineered draft format) — confirmed
working against the user's real CapCut install (app 8.9.1, draft schema
360000) via a real test draft the user opened successfully. If a future
CapCut update breaks this, the failure mode is pycapcut raising, not
silent corruption — every build writes into a fresh temp folder first
and only swaps it over the real draft_name if the whole build succeeds
(see _build_and_swap).

Multi-part projects (append_to_draft, e.g. Part 2 of the same CTV/VSL)
NEVER read the existing draft's own draft_content.json to figure out
what's already there. First version did, and broke on a real project:
the user opened Part 1 in CapCut just to confirm it looked right, and
CapCut itself silently rewrote the audio track — consolidating ~30
individual clips into 2 CapCut-generated "combination" cache files
(under Resources/combination/, referenced via a relative
##_draftpath_placeholder_...##  token CapCut's own runtime resolves)
that don't even carry a readable duration. Treating a draft the user
might have opened as "ours to read back" is fundamentally unsafe.
Instead, every build_draft() call saves a small manifest (a JSON file
NEXT TO the draft folder, never inside it, so CapCut touching the draft
can't affect it) recording exactly what WE fed in for that part —
audio_path, kept_ranges, edl. append_to_draft() only ever reads that
manifest, then rebuilds the ENTIRE draft from scratch (every part, in
order) via the same fresh create_draft() path build_draft() uses. This
is the only state this module trusts.

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
import shutil
import uuid
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


def _place_audio_ranges(
    script: cc.ScriptFile,
    audio_material: cc.AudioMaterial,
    kept_ranges: list[tuple[float, float]],
    cursor_us: int,
) -> tuple[int, list[int]]:
    """Places kept_ranges on the audio track starting at cursor_us.
    Returns (new_cursor_us, boundaries including the starting one — for
    _place_new_video_ranges's snap-to-nearest-audio-cut logic).

    ffprobe (used to compute total_duration, which the LAST kept_range's
    end is derived from) and pycapcut's own duration probing don't always
    agree on a file's exact length — confirmed on a real render: a
    source_timerange asked for 94 MICROseconds past what pycapcut
    considered the audio material's real length, and pycapcut raises
    instead of silently stopping at EOF like ffmpeg extraction does. Same
    shift-the-source-start fix as the video side (see
    _place_new_video_ranges) rather than shrinking the clip."""
    audio_bounds = [cursor_us]
    material_dur_us = audio_material.duration
    for s, e in kept_ranges:
        dur_us = _us(e) - _us(s)
        source_start_us = _us(s)
        overshoot_us = (source_start_us + dur_us) - material_dur_us
        if overshoot_us > 0:
            source_start_us = max(0, source_start_us - overshoot_us)
            dur_us = min(dur_us, material_dur_us - source_start_us)
        seg = cc.AudioSegment(
            audio_material,
            cc.Timerange(cursor_us, dur_us),
            source_timerange=cc.Timerange(source_start_us, dur_us),
        )
        script.add_segment(seg, AUDIO_TRACK_NAME)
        cursor_us += dur_us
        audio_bounds.append(cursor_us)
    return cursor_us, audio_bounds


def _build_and_swap(drafts_folder: Path, real_name: str, build_fn) -> Path:
    """Builds into a temporary draft folder and only replaces real_name's
    folder if the whole build succeeds, via build_fn(temp_name) ->
    None — so a crash mid-build (confirmed to happen on real files, see
    _place_audio_ranges) never leaves real_name in a broken,
    CapCut-can't-open state. Critical for append_to_draft especially:
    without this, create_draft()'s allow_replace=True would have already
    deleted the target draft before the crash, destroying the user's
    existing multi-part project with nothing usable left in its place."""
    drafts_folder = Path(drafts_folder)
    temp_name = f"__tmp_{real_name}_{uuid.uuid4().hex[:8]}"
    try:
        build_fn(temp_name)
    except Exception:
        shutil.rmtree(drafts_folder / temp_name, ignore_errors=True)
        raise
    real_path = drafts_folder / real_name
    shutil.rmtree(real_path, ignore_errors=True)
    (drafts_folder / temp_name).rename(real_path)
    return real_path


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


def _manifest_path(drafts_folder: Path, draft_name: str) -> Path:
    # Next to the draft folder, never inside it — CapCut deletes/rewrites
    # the draft folder's own contents freely (see module docstring); this
    # file must survive that untouched, since it's the only record left
    # of what WE originally fed into each part.
    return Path(drafts_folder) / f"{draft_name}.parts.json"


def _load_parts(drafts_folder: Path, draft_name: str) -> list[dict]:
    p = _manifest_path(drafts_folder, draft_name)
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8"))


def _save_parts(drafts_folder: Path, draft_name: str, parts: list[dict]) -> None:
    _manifest_path(drafts_folder, draft_name).write_text(json.dumps(parts), encoding="utf-8")


def _build_multi_part_inner(temp_name: str, drafts_folder: Path, parts: list[dict]) -> None:
    """parts: ordered list of {"audio_path": str, "kept_ranges": [[s,e],...],
    "edl": {...}}, each placed after the previous one — the SAME
    single-part logic build_draft always used, just looped. Always builds
    every part fresh from this data; never reads any existing draft."""
    folder = cc.DraftFolder(str(drafts_folder))
    script = folder.create_draft(temp_name, WIDTH, HEIGHT, FPS, allow_replace=True)
    script.add_track(cc.TrackType.audio, AUDIO_TRACK_NAME)
    script.add_track(cc.TrackType.video, VIDEO_TRACK_NAME)

    audio_materials: dict[str, cc.AudioMaterial] = {}
    video_materials: dict[str, cc.VideoMaterial] = {}
    cursor_us = 0
    for part in parts:
        path = part["audio_path"]
        if path not in audio_materials:
            audio_materials[path] = cc.AudioMaterial(path)
        kept_ranges = [tuple(r) for r in part["kept_ranges"]]
        part_start_us = cursor_us
        cursor_us, part_audio_bounds = _place_audio_ranges(script, audio_materials[path], kept_ranges, cursor_us)
        _place_new_video_ranges(
            script, video_materials, part["edl"], part_audio_bounds, cursor_us, start_us=part_start_us,
        )

    script.save()


def build_draft(
    draft_name: str,
    drafts_folder: Path,
    audio_path: Path,
    kept_ranges: list[tuple[float, float]],
    edl: dict,
) -> Path:
    """Returns the path to the created draft folder (inside drafts_folder).
    Also saves a manifest recording this part's inputs (see module
    docstring) so a later append_to_draft() call can rebuild this part
    exactly, without ever needing to read the draft file itself back."""
    drafts_folder = Path(drafts_folder)
    parts = [{"audio_path": str(audio_path), "kept_ranges": kept_ranges, "edl": edl}]
    result = _build_and_swap(
        drafts_folder, draft_name,
        lambda tmp: _build_multi_part_inner(tmp, drafts_folder, parts),
    )
    _save_parts(drafts_folder, draft_name, parts)
    return result


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
    CapCut project as a continuation, not a fresh draft.

    Rebuilds the WHOLE draft from scratch: every part's original inputs
    (from the manifest — see module docstring for why this never reads
    the draft file itself) plus this new one, placed in order via the
    same fresh create_draft() path build_draft() uses. Raises
    FileNotFoundError if draft_name has no known parts (wasn't built by
    this pipeline, or predates the manifest). Builds into a temp folder
    first (see _build_and_swap) — if anything raises, the existing
    draft_name on disk is left completely untouched."""
    drafts_folder = Path(drafts_folder)
    parts = _load_parts(drafts_folder, draft_name)
    if not parts:
        raise FileNotFoundError(
            f"no known parts for draft {draft_name!r} — it either wasn't built by this "
            f"pipeline, or predates append support. Only drafts created with the current "
            f"version can be added to."
        )
    parts = parts + [{"audio_path": str(new_audio_path), "kept_ranges": new_kept_ranges, "edl": new_edl}]
    result = _build_and_swap(
        drafts_folder, draft_name,
        lambda tmp: _build_multi_part_inner(tmp, drafts_folder, parts),
    )
    _save_parts(drafts_folder, draft_name, parts)
    return result
