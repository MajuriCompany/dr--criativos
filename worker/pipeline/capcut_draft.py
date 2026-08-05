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
    Its boundaries are always snapped to the nearest audio cut, since the
    two are independently-computed estimates of "where's the gap" (ASR
    sentence/word timing vs real waveform silence) that often don't agree
    at all — confirmed on a real draft, one take switch's nearest real
    audio cut was 484ms away. A real silence cut is unconditionally the
    right place to switch video (nothing audible is playing there), so
    there's no cap on how far a boundary can move to reach one — see
    _place_new_video_ranges for the monotonic + take-capacity clamps that
    keep that safe.
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
# Take switches (sync_takes.py, from ASR sentence/word boundaries mapped
# through the cut) and audio cuts (cut_silence.py, from real waveform
# silence detection) are two independent measurements of "where's the gap
# here" — they don't always agree, and sometimes disagree by far more than
# a couple frames (confirmed on a real draft: one take switch's nearest
# real audio cut was 484ms away). A capped "snap tolerance" used to gate
# this — anything past 150ms fell back to the uncorrected sentence
# boundary, landing the video switch mid-clip with no audio cut there at
# all, which is what showed up as visibly misaligned clips in CapCut.
# There's no good reason for that cap: a real silence cut in the audio is
# unconditionally the right place to switch video (nothing is playing
# there, so any distance from the grammatical sentence boundary is
# perceptually free), so _place_new_video_ranges always snaps to the
# nearest one now — safe because the monotonic (never move a boundary
# backward past the previous one) and take-capacity clamps immediately
# below already guard against a snap producing a nonsensical result.

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

    # Take-switch boundaries (raw, unsnapped), computed first so every
    # boundary can be snapped to the nearest audio cut before any segment
    # is built. Anchored to r["output_end"] — sync_takes.py's own
    # audio-timeline position for that piece — NOT a running sum of each
    # range's video SOURCE duration (r["end"]-r["start"]). Those two only
    # look the same when every take fully covers its piece; when one
    # falls short (sync_takes.py accepts a take up to
    # TAKE_FIT_TOLERANCE_S=0.15s short rather than force an awkward
    # split/freeze), a source-duration running sum silently carries that
    # shortfall into every LATER boundary too, compounding across the
    # video. Confirmed on a real render: one 60ms shortfall pushed the
    # next 3 boundaries 60ms out of place each. output_end has no such
    # accumulation — it's sync_takes.py's own ground truth for where that
    # piece actually sits on the timeline, independent of what came
    # before it. The very first (start_us) and very last (audio_total_us)
    # boundaries are pinned outright: pinning the last one is what
    # guarantees the video track always ends exactly where the audio
    # track does, with no separate "fill the gap" step needed.
    raw_bounds = [start_us] + [start_us + _us(r["output_end"]) for r in edl["ranges"]]

    snapped_bounds = [start_us]
    for i, b in enumerate(raw_bounds[1:-1], start=1):
        # Always try the TRUE nearest real cut first — restricting the
        # search to cuts not yet used by an earlier boundary (a first
        # version of this fix) is wrong: in a stretch with fewer real
        # cuts than pieces, that forced boundaries to hunt further and
        # further for a "free" cut, landing several SECONDS away instead
        # of just declining to snap. Only reject the true-nearest
        # candidate when using it would collide with (or reverse) the
        # previous boundary — then fall back to this boundary's own raw
        # (sentence-boundary) position instead of chasing a distant cut,
        # same as when no real cut exists nearby at all. The trailing
        # max(...) is a last-resort floor: raw_bounds is itself strictly
        # increasing (sync_takes.py's pieces always have positive
        # duration), so the fallback can't collapse either, but it stays
        # as a guarantee against a zero/negative-duration segment
        # crashing pycapcut (ZeroDivisionError computing
        # speed = source_duration / 0).
        nearest = min(audio_bounds, key=lambda ab: abs(ab - b))
        candidate = nearest if nearest > snapped_bounds[-1] else b
        candidate = max(candidate, snapped_bounds[-1] + 1)
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


def read_existing_audio_track(draft_name: str, drafts_folder: Path, edicao_videos_root: Path) -> list[dict]:
    """Reads the segments already placed on a draft's own VOICE audio
    track directly from draft_content.json — for syncing video ONTO
    audio the user cut/arranged manually in CapCut, not something this
    pipeline built. Returns a list of {"path": str, "source_start":
    float, "source_end": float, "target_start": float, "target_end":
    float} (all times in seconds), sorted by target_start.

    Picks the audio track whose segments resolve under
    edicao_videos_root as "the" voice track when a draft has more than
    one — NOT the one with the most segments. A first version used
    segment count as the heuristic and picked wrong on two real drafts:
    a background-music track (looped, so MORE segments than the actual
    voiceover) beat the real voice track both times. Music/SFX dragged
    in from CapCut's own library lives under CapCut's own cache
    folders, never under edicao_videos_root, so this is a real,
    reliable signal, not another guess.

    Raises RuntimeError if no audio track has ANY segment resolving
    under edicao_videos_root (no voice track found), or if the chosen
    track's segments don't all resolve to a real source file path —
    the latter happens when CapCut has "consolidated" the draft's clips
    into its own opaque combination cache (confirmed real: this happens
    after the user opens/plays a heavily-edited draft in CapCut itself).
    There's no reliable way to recover the real cut points from that
    state; the user has to re-derive kept audio some other way (e.g.
    re-export it) if this happens."""
    draft_dir = Path(drafts_folder) / draft_name
    content_path = draft_dir / "draft_content.json"
    if not content_path.is_file():
        raise RuntimeError(f"[capcut_draft_erro] projeto do CapCut {draft_name!r} não encontrado.")
    dc = json.loads(content_path.read_text(encoding="utf-8"))

    mat_path = {m["id"]: m.get("path", "") for m in dc["materials"].get("audios", [])}
    audio_tracks = [t for t in dc.get("tracks", []) if t.get("type") == "audio"]
    if not audio_tracks:
        raise RuntimeError(
            f"[capcut_draft_erro] o projeto do CapCut {draft_name!r} não tem nenhuma trilha "
            f"de áudio."
        )

    root_str = str(Path(edicao_videos_root).resolve())

    def voice_segment_count(t: dict) -> int:
        count = 0
        for seg in t.get("segments", []):
            path = mat_path.get(seg.get("material_id", ""), "")
            if path and str(Path(path).resolve()).lower().startswith(root_str.lower()):
                count += 1
        return count

    def empty_path_count(t: dict) -> int:
        return sum(1 for seg in t.get("segments", []) if not mat_path.get(seg.get("material_id", ""), ""))

    def consolidated_error() -> RuntimeError:
        return RuntimeError(
            f"[capcut_draft_erro] o CapCut reorganizou (\"consolidou\") os clipes do "
            f"projeto {draft_name!r} internamente depois que ele foi aberto/reproduzido "
            f"lá, e não é mais possível ler os cortes reais de volta a partir do arquivo "
            f"do projeto. Isso costuma acontecer em projetos já bastante mexidos no "
            f"próprio CapCut. Não tem como recuperar automaticamente — seria preciso "
            f"re-exportar o áudio cortado de algum outro jeito para reconstruir os cortes."
        )

    # Check for consolidation FIRST, on whichever track has the most
    # segments overall (regardless of path) — a track whose segments
    # mostly/all have no resolvable path at all is a sign CapCut
    # consolidated it, which is a fundamentally different, unrecoverable
    # situation from "the real voice track just isn't obvious yet" below.
    # Diagnosing that case as "couldn't identify the voice track" (as if
    # the user dragged in the wrong file) would be actively misleading —
    # confirmed on a real draft: 162/162 segments on the biggest track
    # had empty paths (audio auto-extracted from a video clip via a
    # "video_original_sound" material whose own video_id didn't resolve
    # to anything either), not a track-selection ambiguity at all.
    busiest = max(audio_tracks, key=lambda t: len(t.get("segments", [])))
    if busiest.get("segments") and empty_path_count(busiest) == len(busiest["segments"]):
        raise consolidated_error()

    track = max(audio_tracks, key=voice_segment_count)
    if voice_segment_count(track) == 0:
        raise RuntimeError(
            f"[capcut_draft_erro] não consegui identificar qual trilha de áudio é a voz "
            f"real no projeto {draft_name!r} — só encontrei música/efeitos vindos da "
            f"biblioteca do próprio CapCut, nada apontando para dentro de "
            f"{edicao_videos_root}. Confirme que o áudio da voz foi arrastado pra lá a "
            f"partir de um arquivo em edicao-videos, não gerado/gravado direto no CapCut."
        )

    out = []
    for seg in track.get("segments", []):
        path = mat_path.get(seg.get("material_id", ""), "")
        if not path:
            raise consolidated_error()
        st = seg["source_timerange"]
        tt = seg["target_timerange"]
        out.append({
            "path": path,
            "source_start": st["start"] / 1_000_000,
            "source_end": (st["start"] + st["duration"]) / 1_000_000,
            "target_start": tt["start"] / 1_000_000,
            "target_end": (tt["start"] + tt["duration"]) / 1_000_000,
        })
    out.sort(key=lambda r: r["target_start"])
    return out


def add_video_sync_to_existing_draft(
    draft_name: str, drafts_folder: Path, edl: dict, audio_bounds_us: list[int], audio_total_us: int,
) -> Path:
    """Adds a NEW video track, synced to whatever's already on the
    draft's audio track, WITHOUT touching that audio at all — for a
    draft the user cut/arranged manually in CapCut themselves (see
    read_existing_audio_track), as opposed to build_draft/append_to_draft
    which always rebuild the audio track fresh from kept_ranges this
    pipeline computed itself.

    Uses pycapcut's load_template() (opens a draft AS-IS for editing,
    unlike create_draft(allow_replace=True) which wipes it first) —
    edits a COPY of the real draft folder first, only swapping it over
    the real one if the whole thing succeeds (same crash-safety
    reasoning as _build_and_swap elsewhere in this module: a crash
    mid-edit must never leave the user's manually-built project broken
    or half-written)."""
    drafts_folder = Path(drafts_folder)
    real_path = drafts_folder / draft_name
    if not real_path.is_dir():
        raise FileNotFoundError(f"draft not found: {draft_name}")

    temp_name = f"__tmp_{draft_name}_{uuid.uuid4().hex[:8]}"
    temp_path = drafts_folder / temp_name
    try:
        shutil.copytree(real_path, temp_path)
        folder = cc.DraftFolder(str(drafts_folder))
        script = folder.load_template(temp_name)
        script.add_track(cc.TrackType.video, VIDEO_TRACK_NAME)
        video_materials: dict[str, cc.VideoMaterial] = {}
        _place_new_video_ranges(script, video_materials, edl, audio_bounds_us, audio_total_us, start_us=0)
        script.save()
    except Exception:
        shutil.rmtree(temp_path, ignore_errors=True)
        raise
    shutil.rmtree(real_path, ignore_errors=True)
    temp_path.rename(real_path)
    return real_path


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
