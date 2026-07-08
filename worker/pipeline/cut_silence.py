"""Silence-cutting, ported from edicao-videos/ad02/edit/cut_silence.py and
parametrized (no hardcoded ad02 paths). Tuned caps confirmed by the user:
INTRA_CAP=0.10s (intra-sentence gaps), INTER_CAP=0.11s (inter-phrase/clause
gaps, i.e. after a word ending in .,;:!?), 30ms fades at every cut edge.

Also emits sentences.json: each sentence (split on .!?) with original +
post-cut ("new") timestamps per word, used by sync_takes.py downstream.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

INTRA_CAP = 0.10
INTER_CAP = 0.11
PUNCT = set(".,;:!?")
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


def _ends_with_punct(text: str) -> bool:
    stripped = _strip_trailing_wrappers(text)
    return bool(stripped) and stripped[-1] in PUNCT

# The ASR (ElevenLabs Scribe) sometimes folds the pause after a sentence-final
# word into that word's own end timestamp instead of emitting it as a
# separate "spacing" gap — e.g. a short word tagged as lasting 0.7-1.0s,
# most of which is actually trailing silence. Normal gap-based excision
# never sees this (word spans are never touched), so it survives cutting
# as an audible dead-air stretch. These constants bound a conservative
# second pass that looks for real trailing silence *inside* suspiciously
# long sentence-final words via actual audio analysis (not just the
# transcript), and only trims it with a safety margin — never close enough
# to risk clipping the word's real audio.
WORD_TAIL_MIN_DURATION_S = 0.5  # only consider words tagged longer than this
WORD_TAIL_NOISE_DB = -25.0  # -30 missed real trailing silence on some real
# recordings whose ambient noise floor sits a bit above -30dB
WORD_TAIL_MIN_SILENCE_S = 0.15  # only trust a silence run at least this long
WORD_TAIL_SAFETY_MARGIN_S = 0.15  # keep this much confirmed-audible tail


def _ffprobe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


def _detect_word_tail_silence(audio_path: Path, word_start: float, word_end: float) -> float | None:
    """Return the original-timeline point where trailing silence begins
    inside [word_start, word_end], or None if no clear silence is found."""
    dur = word_end - word_start
    if dur < WORD_TAIL_MIN_DURATION_S:
        return None
    result = subprocess.run(
        ["ffmpeg", "-ss", f"{word_start:.3f}", "-t", f"{dur:.3f}", "-i", str(audio_path),
         "-af", f"silencedetect=noise={WORD_TAIL_NOISE_DB}dB:d={WORD_TAIL_MIN_SILENCE_S}",
         "-f", "null", "NUL"],
        capture_output=True, text=True,
    )
    for line in result.stderr.splitlines():
        if "silence_start" in line:
            rel_start = float(line.split("silence_start:")[1].strip())
            return word_start + rel_start
    return None


def cut_silence(audio_path: Path, transcript_path: Path, edit_dir: Path, base_name: str) -> dict:
    """Cut excess silence from audio_path using the transcript's word timestamps.

    Returns {"final_mp3": Path, "sentences_json": Path, "duration_before": float,
    "duration_after": float, "cuts_made": int}.
    """
    data = json.loads(transcript_path.read_text(encoding="utf-8"))
    words = [w for w in data["words"] if w.get("type") in ("word", "spacing")]

    total_duration = _ffprobe_duration(audio_path)

    excisions: list[tuple[float, float]] = []
    prev_word_text = ""
    for w in words:
        if w["type"] == "word":
            prev_word_text = (w.get("text") or "").strip()
            continue
        gap_start, gap_end = w["start"], w["end"]
        gap = gap_end - gap_start
        ends_punct = _ends_with_punct(prev_word_text)
        cap = INTER_CAP if ends_punct else INTRA_CAP
        if gap > cap:
            pad = cap / 2
            excisions.append((gap_start + pad, gap_end - pad))

    # Second pass: trailing silence hidden inside sentence-final word spans
    # (see WORD_TAIL_* comment above) — gap-based excision above can't see
    # this since it only ever looks at "spacing" entries between words.
    for w in words:
        if w["type"] != "word":
            continue
        text = (w.get("text") or "").strip()
        if not _ends_sentence(text):
            continue
        silence_at = _detect_word_tail_silence(audio_path, w["start"], w["end"])
        if silence_at is None:
            continue
        excise_start = silence_at + WORD_TAIL_SAFETY_MARGIN_S
        if excise_start < w["end"] - 0.05:
            excisions.append((excise_start, w["end"]))

    excisions.sort()

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
        fade_out_start = max(0.0, dur - 0.03)
        af = f"afade=t=in:st=0:d=0.03,afade=t=out:st={fade_out_start:.3f}:d=0.03"
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

    return {
        "final_mp3": final_mp3,
        "sentences_json": sentences_json,
        "duration_before": total_duration,
        "duration_after": duration_after,
        "cuts_made": len(excisions),
    }
