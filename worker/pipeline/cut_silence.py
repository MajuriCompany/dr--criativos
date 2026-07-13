"""Silence-cutting, ported from edicao-videos/ad02/edit/cut_silence.py and
parametrized (no hardcoded ad02 paths).

CUTTING METHOD (rewritten — see history below): real waveform silence
detection (ffmpeg silencedetect), matching the user's own Recut config,
NOT the ASR word-gap-cap method used previously. The transcript is now
used only to find sentence boundaries for sentences.json (sync_takes.py
needs those) — it no longer decides where to cut.

History: the original method classified every ASR "spacing" gap as
intra-sentence vs inter-phrase and cut it if it exceeded a cap
(INTRA_CAP=0.10s/INTER_CAP=0.11s). Tightening those caps to catch more
silence (0.08/0.10, then 0.07/0.09) reliably cut a stuttery "machine gun"
cadence into real speech, confirmed on real renders. Later, a
median-seconds-per-char word-tail mechanism to catch breath/dead-air
hidden inside a word's own tagged span was tried and also failed
real-world validation across several rescoping attempts. Both were
reverted; see git history if resurrecting either is ever considered.

Root cause once diagnosed: ASR word-boundary timestamps are the model's
*estimate* of where a word starts/ends, not the true acoustic silence in
the waveform — tightening caps built on that estimate cuts into real
audio the model just mis-timed. The user's own tool, Recut, sidesteps
this entirely by measuring actual amplitude in the waveform. Reproduced
Recut's behavior against a real reference pair (original vs
Recut-cut audio) before adopting these exact parameters — see
SILENCE_* below, values sourced directly from the user's own working
Recut config (screenshot), not re-tuned by feel.

30ms fades at every cut edge — never skip, prevents audio pops.

Also emits sentences.json: each sentence (split on .!?) with original +
post-cut ("new") timestamps per word, used by sync_takes.py downstream.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

# Sourced from the user's own Recut config (screenshot) and calibrated
# against a real before/after pair from the user's own Recut output
# (AD13): Recut's threshold slider is a linear amplitude (0.04333), which
# converts to ~-27.3dB via 20*log10(0.04333) — but ffmpeg's silencedetect
# and Recut evidently don't measure amplitude the same way (different
# reference/windowing), so that theoretical value under-cut real Recut's
# result (6.75s removed vs Recut's actual 8.19s on AD13). Swept nearby dB
# values against that same file and matched empirically instead:
# -26dB removes 8.225s, ~= Recut's real 8.19s. Trust this over the
# theoretical conversion if the two ever disagree again on a new sample.
SILENCE_NOISE_DB = -26.0  # empirically matched to Recut's real output, not the raw slider-to-dB math
SILENCE_MIN_DURATION_S = 0.1  # Recut "Minimum Duration"
SILENCE_PADDING_S = 0.01  # Recut "Padding" — kept on the trailing side of a cut
# (end of the word before the cut, going into the fade-out). Fade-out into
# real silence is perceptually forgiving, so Recut's own small value is fine
# here.
FADE_S = 0.03  # 30ms fade in/out at every cut edge — never skip, prevents pops
# The LEADING side of a cut (right before the next kept segment, going into
# its fade-IN) needs more margin than Recut's own padding: unlike Recut,
# we always apply a FADE_S fade-in on that edge. Verified on a real case
# (AD13, "pero" at ~4.08s): raw silence there actually ends at 4.090s, but
# with only SILENCE_PADDING_S margin the kept segment (and its fade-in)
# started at 4.080s — so the fade was still ramping up when the real
# consonant attack (a plosive "p", near-instant onset) hit at ~4.090-4.095s,
# audibly softening it even though no real audio was ever clipped. Sized to
# the fade duration itself so the fade-in has time to finish before content.
SILENCE_LEAD_IN_S = FADE_S
# Recut "Remove Short Audio Spikes": an audible blip shorter than this,
# sitting between two silence spans, is treated as noise too — the two
# silence spans merge into one bigger excision across it, rather than
# leaving a tiny fragment of "kept" audio between two cuts.
SPIKE_MIN_DURATION_S = 0.1

SENTENCE_END = set(".!?")

# A word can carry punctuation followed by a closing quote/bracket (e.g.
# 'cuesta?"'), which would hide the real punctuation from a naive
# text[-1] check. Strip these before checking so quoted dialogue is
# classified the same as unquoted text.
_TRAILING_WRAPPERS = "\"'”’»)]"


def _strip_trailing_wrappers(text: str) -> str:
    return text.rstrip(_TRAILING_WRAPPERS)


def _ends_sentence(text: str) -> bool:
    stripped = _strip_trailing_wrappers(text)
    return bool(stripped) and stripped[-1] in SENTENCE_END


def _ffprobe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def _detect_silence_spans(audio_path: Path) -> list[tuple[float, float]]:
    """Real waveform silence spans via ffmpeg silencedetect, at Recut's
    threshold/min-duration. Returns sorted, non-overlapping (start, end)."""
    result = subprocess.run(
        ["ffmpeg", "-i", str(audio_path),
         "-af", f"silencedetect=noise={SILENCE_NOISE_DB}dB:d={SILENCE_MIN_DURATION_S}",
         "-f", "null", "NUL"],
        capture_output=True, text=True,
    )
    spans: list[tuple[float, float]] = []
    pending_start: float | None = None
    for line in result.stderr.splitlines():
        if "silence_start" in line:
            pending_start = float(line.split("silence_start:")[1].strip())
        elif "silence_end" in line and pending_start is not None:
            end = float(line.split("silence_end:")[1].split("|")[0].strip())
            spans.append((pending_start, end))
            pending_start = None
    if pending_start is not None:
        # Silence still ongoing when the stream ended — ffmpeg never emits
        # a matching silence_end for this case (there's no "audio resumes"
        # transition to report), so without this the whole trailing
        # silence gets silently dropped and never cut. Confirmed on a
        # real file: a real ~150ms silent tail at the very end survived
        # every previous fix because it was never even in `spans`.
        spans.append((pending_start, _ffprobe_duration(audio_path)))
    return spans


def _compute_excisions(audio_path: Path) -> list[tuple[float, float]]:
    """Silence spans, with short audible spikes between them merged in
    (Recut's "Remove Short Audio Spikes"), then padded (Recut's
    "Padding") to get the actual regions to cut from the audio."""
    spans = _detect_silence_spans(audio_path)
    if not spans:
        return []

    merged: list[list[float]] = [list(spans[0])]
    for start, end in spans[1:]:
        audible_gap = start - merged[-1][1]
        if audible_gap < SPIKE_MIN_DURATION_S:
            merged[-1][1] = end
        else:
            merged.append([start, end])

    excisions = []
    for s, e in merged:
        exc_start, exc_end = s + SILENCE_PADDING_S, e - SILENCE_LEAD_IN_S
        if exc_end > exc_start:
            excisions.append((exc_start, exc_end))
    return excisions


def cut_silence(audio_path: Path, transcript_path: Path, edit_dir: Path, base_name: str) -> dict:
    """Cut excess silence from audio_path using the transcript's word timestamps.

    Returns {"final_mp3": Path, "sentences_json": Path, "duration_before": float,
    "duration_after": float, "cuts_made": int}.
    """
    data = json.loads(transcript_path.read_text(encoding="utf-8"))

    total_duration = _ffprobe_duration(audio_path)

    excisions = _compute_excisions(audio_path)

    ranges: list[tuple[float, float]] = []
    cursor = 0.0
    for exc_start, exc_end in excisions:
        if exc_start > cursor:
            ranges.append((cursor, exc_start))
        cursor = exc_end
    ranges.append((cursor, total_duration))
    ranges = [(s, e) for s, e in ranges if e - s > 0.01]

    def orig_to_new(t: float) -> float:
        removed = 0.0
        for exc_start, exc_end in excisions:
            if exc_end <= t:
                removed += exc_end - exc_start
            elif exc_start < t < exc_end:
                removed += t - exc_start
            else:
                break
        return t - removed

    clips_dir = edit_dir / "clips_graded"
    clips_dir.mkdir(parents=True, exist_ok=True)
    seg_paths = []
    for i, (s, e) in enumerate(ranges):
        dur = e - s
        out_path = clips_dir / f"seg_{i:02d}.wav"
        fade_out_start = max(0.0, dur - FADE_S)
        af = f"afade=t=in:st=0:d={FADE_S},afade=t=out:st={fade_out_start:.3f}:d={FADE_S}"
        subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{s:.3f}", "-i", str(audio_path), "-t", f"{dur:.3f}",
             "-af", af, "-ar", "48000", "-ac", "2", str(out_path)],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        )
        seg_paths.append(out_path)

    concat_list = edit_dir / "_concat.txt"
    concat_list.write_text("".join(f"file '{p.resolve()}'\n" for p in seg_paths))
    base_wav = edit_dir / "base.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat_list), "-c", "copy", str(base_wav)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    concat_list.unlink(missing_ok=True)

    final_mp3 = edit_dir / f"{base_name}_final.mp3"
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(base_wav), "-c:a", "libmp3lame", "-b:a", "192k", str(final_mp3)],
        check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
    )
    duration_after = _ffprobe_duration(final_mp3)

    # sentence-level mapping for the sync step
    plain_words = [w for w in data["words"] if w.get("type") == "word"]
    sentences: list[list[dict]] = []
    cur_words: list[dict] = []
    for w in plain_words:
        cur_words.append(w)
        txt = (w.get("text") or "").strip()
        if _ends_sentence(txt):
            sentences.append(cur_words)
            cur_words = []
    if cur_words:
        sentences.append(cur_words)

    sent_out = []
    for sw in sentences:
        mapped_words = [
            {"text": w.get("text"), "orig_start": w["start"], "orig_end": w["end"],
             "new_start": round(orig_to_new(w["start"]), 3), "new_end": round(orig_to_new(w["end"]), 3)}
            for w in sw
        ]
        sent_out.append({
            "text": " ".join((w.get("text") or "").strip() for w in sw),
            "new_start": round(orig_to_new(sw[0]["start"]), 3),
            "new_end": round(orig_to_new(sw[-1]["end"]), 3),
            "words": mapped_words,
        })

    sentences_json = edit_dir / f"{base_name}_sentences.json"
    sentences_json.write_text(json.dumps(sent_out, ensure_ascii=False, indent=2), encoding="utf-8")

    # Persisted separately (not just returned) because cut_silence and sync
    # can run as two independent jobs, potentially minutes/hours apart —
    # capcut_draft.py needs these later, in a process that never saw this
    # function's return value.
    kept_ranges_json = edit_dir / f"{base_name}_kept_ranges.json"
    kept_ranges_json.write_text(json.dumps(ranges), encoding="utf-8")

    return {
        "final_mp3": final_mp3,
        "sentences_json": sentences_json,
        "kept_ranges_json": kept_ranges_json,
        "duration_before": total_duration,
        "duration_after": duration_after,
        "kept_ranges": ranges,  # (orig_start, orig_end) per kept segment — for capcut_draft.py
        "cuts_made": len(excisions),
    }
