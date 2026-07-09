"""Silence-cutting, ported from edicao-videos/ad02/edit/cut_silence.py and
parametrized (no hardcoded ad02 paths). Tuned caps confirmed by the user:
INTRA_CAP=0.10s (intra-sentence gaps), INTER_CAP=0.11s (inter-phrase/clause
gaps, i.e. after a word ending in .,;:!?), 30ms fades at every cut edge.
Two rounds of tightening these two caps (down to 0.08/0.10, then 0.07/0.09)
were both reverted: gap-cap tightening applies everywhere, including
mid-sentence between plain words, and on fast-paced passages (short words,
already-tiny natural gaps) it cut a stuttery "machine gun" cadence into
real speech. Do not lower these two below 0.10/0.11 again for that reason.

A separate mechanism (median-seconds-per-char word-tail trimming, scoped to
sentence-final words) was tried to catch breath/dead-air hidden inside a
word's own tagged span. It went through several rounds — global, then
sentence-final-only — and kept over-cutting on real files even in its most
restricted form. Per explicit user instruction it was removed entirely:
"Devido a essa parada do tempo médio, pode tirar isso, não vai dar certo,
deixe só o tempo normal de corte que já combinamos." Only the plain
gap-cap excision below remains. Do not reintroduce word-tail/implausible-
duration trimming — it has failed real-world validation three times.

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


def _ffprobe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True,
    )
    return float(out.stdout.strip())


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
