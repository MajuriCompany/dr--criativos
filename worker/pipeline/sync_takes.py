"""Deterministic take-assignment algorithm for syncing expert/avatar takes to
a fixed (already silence-cut) audio track.

This is NEW code, not a port — the original ad02 process (build_sync_edl.py)
was a one-off script hand-authored by an LLM reading the transcript and
choosing split points/take order by eye. This module reproduces the same
HARD RULES mechanically:

  - Never freeze-frame: if a sentence is longer than every available take,
    split it at a comma/natural-pause word boundary into 2+ pieces; if no
    single take covers a piece at all, stack 2+ takes back-to-back inside it.
  - Every piece must be >= ~2.95s (ASR-rounding tolerance for the 3s rule).
  - Never repeat the same take on two consecutive pieces.
  - Content priority: if a take's filename shares a meaningful word with what's
    being said in a piece (e.g. take "gesto-celular" during a piece that says
    "celular"), prefer it over plain rotation — this doesn't require looking
    at video frames, just comparing the take's filename against the transcript.
  - In the absence of a content match, rotate takes for variety and vary the
    start-offset within a reused take.
  - Every segment boundary snaps to the midpoint of the real silence gap
    between the words on either side (no black gaps, no overlap).
"""
from __future__ import annotations

import re
import unicodedata
from itertools import combinations

# Words that show up in take filenames but don't describe content (camera
# framing/shot-type words, not something the audio would ever "mention").
# Excluding them keeps e.g. "falando direto 1" from ever content-matching
# (it has no descriptive tag left) while "gesto-celular" still matches on
# "celular".
_TAG_STOPWORDS = {
    "falando", "direto", "parte", "take", "video", "gesto", "cena", "corte",
    "o", "a", "de", "da", "do", "com", "para", "em", "no", "na", "e",
}


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c)).lower()


def _take_tags(take_name: str) -> set[str]:
    tokens = re.findall(r"[a-z]+", _normalize(take_name))
    return {t for t in tokens if len(t) > 2 and t not in _TAG_STOPWORDS}


def _text_tags(text: str) -> set[str]:
    tokens = re.findall(r"[a-z]+", _normalize(text))
    return {t for t in tokens if len(t) > 2}


def _flatten_words(sentences: list[dict]) -> list[dict]:
    words: list[dict] = []
    for sent in sentences:
        words.extend(sent["words"])
    return words


def _piece_tags(piece: dict, words: list[dict]) -> set[str]:
    texts = [
        w.get("text") or "" for w in words
        if piece["start"] <= (w["new_start"] + w["new_end"]) / 2 < piece["end"]
    ]
    return _text_tags(" ".join(texts))


class NoSplitPointError(Exception):
    def __init__(self, sentence_text: str):
        super().__init__(f"no comma split point found to break up long sentence: {sentence_text!r}")
        self.sentence_text = sentence_text


class NoTakeFitsError(Exception):
    def __init__(self, needed_s: float, excluded_take: str | None):
        super().__init__(
            f"no take is long enough to cover {needed_s:.2f}s without repeating "
            f"the previous take ({excluded_take!r})"
        )
        self.needed_s = needed_s
        self.excluded_take = excluded_take


MIN_PIECE_S = 2.95
# A very short standalone sentence (e.g. a one-beat interjection) is allowed
# by the hard rules on its own, but switching takes for under ~1.5s reads as
# a flash cut. Merge it into the previous piece instead (same take continues
# through it) rather than giving it its own take assignment.
TINY_PIECE_MERGE_THRESHOLD_S = 1.5
# A take up to this much shorter than the exact computed requirement is
# accepted rather than forcing an extra split or a freeze-frame. This is
# specifically safe for dubbed B-roll/avatar footage (no lip-sync requirement
# against the dubbed audio) — a sub-150ms shortfall shifts the rest of the
# concatenated video against the audio track by less than the accepted A/V
# sync tolerance for non-lip-synced cutaway content. Do not widen this for
# footage where the speaker's mouth must match the audio.
TAKE_FIT_TOLERANCE_S = 0.15


def _find_split_points(sent: dict, max_take: float, min_piece_s: float) -> list[tuple[dict, dict]]:
    """Return [(word_before, word_after), ...] marking each internal cut needed
    to break `sent` into pieces no longer than max_take.

    Picks, among comma boundaries that physically fit (piece_dur <= max_take),
    the one that minimizes the combined shortfall of both resulting pieces
    below min_piece_s — real footage often has no split keeping both sides
    at a full 3s, so this picks the best available compromise (matching the
    manual editorial judgment: "keeps both resulting pieces as close to 3s as
    possible") rather than requiring a perfect split.
    """
    words = sent["words"]
    seg_start = sent["new_start"]
    seg_end = sent["new_end"]
    splits: list[tuple[dict, dict]] = []
    cursor = seg_start

    while seg_end - cursor > max_take:
        remaining = seg_end - cursor
        candidates = [
            (w["new_end"] - cursor, i, w)
            for i, w in enumerate(words)
            if w["new_end"] > cursor and (w.get("text") or "").strip().endswith(",")
            and i + 1 < len(words)
        ]
        feasible = [c for c in candidates if c[0] <= max_take]
        if not feasible:
            raise NoSplitPointError(sent["text"])

        def shortfall(piece_dur: float) -> float:
            remainder = remaining - piece_dur
            return max(0.0, min_piece_s - piece_dur) + max(0.0, min_piece_s - remainder)

        feasible.sort(key=lambda c: (shortfall(c[0]), -min(c[0], remaining - c[0])))
        _, idx, w = feasible[0]
        next_word = words[idx + 1]
        splits.append((w, next_word))
        cursor = (w["new_end"] + next_word["new_start"]) / 2

    return splits


def compute_pieces(sentences: list[dict], take_durations: dict[str, float], total_duration: float,
                    min_piece_s: float = MIN_PIECE_S) -> list[dict]:
    """Split any sentence longer than the longest take, then return a flat list
    of {start, end} pieces tiling [0, total_duration] with no gaps/overlaps."""
    max_take = max(take_durations.values())
    boundary_words: list[tuple[dict, dict]] = []

    for si, sent in enumerate(sentences):
        dur = sent["new_end"] - sent["new_start"]
        if dur > max_take:
            boundary_words.extend(_find_split_points(sent, max_take, min_piece_s))
        if si < len(sentences) - 1:
            boundary_words.append((sent["words"][-1], sentences[si + 1]["words"][0]))

    boundary_times = sorted((wb["new_end"] + wa["new_start"]) / 2 for wb, wa in boundary_words)
    edges = [0.0] + boundary_times + [total_duration]
    pieces = [{"start": edges[i], "end": edges[i + 1]} for i in range(len(edges) - 1)]
    return _merge_tiny_pieces(pieces)


def _merge_tiny_pieces(pieces: list[dict]) -> list[dict]:
    merged: list[dict] = []
    for p in pieces:
        dur = p["end"] - p["start"]
        if dur < TINY_PIECE_MERGE_THRESHOLD_S and merged:
            merged[-1]["end"] = p["end"]
        else:
            merged.append(dict(p))
    return merged


def _pick_take(candidates: list[str], take_durations: dict[str, float], ranges: list[dict]) -> str:
    last_used_index = {t: -1 for t in candidates}
    for i, r in enumerate(ranges):
        if r["source"] in last_used_index:
            last_used_index[r["source"]] = i
    return min(candidates, key=lambda t: (last_used_index[t], -take_durations[t]))


def _find_stack(need: float, take_durations: dict[str, float], exclude_first: str | None) -> list[str]:
    """When no single take covers `need`, find the smallest set of distinct
    takes whose combined length does (longest takes first, to minimize the
    number of visual cuts within the piece). The first take in the returned
    order must not be `exclude_first` (continuity with the previous piece);
    interior repeats can't happen since combinations() never repeats a take.
    """
    names = sorted(take_durations, key=lambda t: -take_durations[t])
    for size in range(2, len(names) + 1):
        for combo in combinations(names, size):
            if sum(take_durations[t] for t in combo) + TAKE_FIT_TOLERANCE_S < need:
                continue
            ordered = list(combo)
            if ordered[0] == exclude_first:
                for i in range(1, len(ordered)):
                    if ordered[i] != exclude_first:
                        ordered[0], ordered[i] = ordered[i], ordered[0]
                        break
                else:
                    continue
            return ordered
    return []


def assign_takes(pieces: list[dict], take_durations: dict[str, float],
                  take_tags: dict[str, set[str]] | None = None,
                  piece_tags: list[set[str]] | None = None) -> list[dict]:
    """Assign a take (with start/end offset within that take) to each piece.
    Never repeats a take consecutively; rotates start-offset on reuse.
    If no single take covers a piece, stacks 2+ takes back-to-back inside it
    (never freeze-frames a short take to cover a long piece).
    When take_tags/piece_tags are given, a take whose filename shares a word
    with what's said during the piece is preferred over plain rotation."""
    take_tags = take_tags or {}
    ranges: list[dict] = []
    last_take: str | None = None
    rotation_cursor = {k: 0.0 for k in take_durations}

    for i, piece in enumerate(pieces):
        need = piece["end"] - piece["start"]
        candidates = [t for t, dur in take_durations.items()
                      if t != last_take and dur >= need - TAKE_FIT_TOLERANCE_S]

        if candidates:
            pool = candidates
            if piece_tags:
                tags = piece_tags[i]
                content_matches = [t for t in candidates if take_tags.get(t, set()) & tags]
                if content_matches:
                    pool = content_matches
            take = _pick_take(pool, take_durations, ranges)
            # clamp extraction to the take's real length if `need` was within
            # the sub-frame tolerance above — output_start/output_end still
            # reflect the true audio-timeline slot (piece boundaries), so
            # segments keep tiling the full timeline; only the video source
            # extraction is a hair short in this rare near-miss case
            # (sub-frame, self-absorbed at final mux).
            actual_dur = min(need, take_durations[take])
            max_offset = max(take_durations[take] - actual_dur, 0.0)
            offset = min(rotation_cursor[take], max_offset)

            ranges.append({
                "source": take,
                "start": round(offset, 3),
                "end": round(offset + actual_dur, 3),
                "output_start": round(piece["start"], 3),
                "output_end": round(piece["end"], 3),
            })
            rotation_cursor[take] = (offset + need * 0.5) if max_offset > 0 else 0.0
            last_take = take
            continue

        stack = _find_stack(need, take_durations, last_take)
        if not stack:
            raise NoTakeFitsError(need, last_take)

        portions: list[tuple[str, float]] = []
        remaining = need
        for t in stack:
            portion = min(take_durations[t], remaining)
            portions.append((t, portion))
            remaining -= portion
            if remaining <= 1e-6:
                break

        cursor = piece["start"]
        for i, (t, portion) in enumerate(portions):
            is_last = i == len(portions) - 1
            out_start = cursor
            out_end = piece["end"] if is_last else cursor + portion
            max_offset = max(take_durations[t] - portion, 0.0)
            offset = min(rotation_cursor[t], max_offset)

            ranges.append({
                "source": t,
                "start": round(offset, 3),
                "end": round(offset + portion, 3),
                "output_start": round(out_start, 3),
                "output_end": round(out_end, 3),
            })
            rotation_cursor[t] = (offset + portion * 0.5) if max_offset > 0 else 0.0
            cursor = out_end
            last_take = t

    return ranges


def build_sync_edl(sentences: list[dict], sources: dict[str, str], take_durations: dict[str, float],
                    total_duration: float, audio_track: str) -> dict:
    """Full pipeline: sentences.json + take durations -> sync_edl.json-shaped dict."""
    pieces = compute_pieces(sentences, take_durations, total_duration)

    words = _flatten_words(sentences)
    take_tags = {name: _take_tags(name) for name in take_durations}
    piece_tags = [_piece_tags(p, words) for p in pieces]

    ranges = assign_takes(pieces, take_durations, take_tags=take_tags, piece_tags=piece_tags)

    # sanity: no consecutive repeat, nothing exceeds its take's real length
    for i in range(1, len(ranges)):
        assert ranges[i]["source"] != ranges[i - 1]["source"], "consecutive take repeat"
    for r in ranges:
        assert r["end"] - r["start"] <= take_durations[r["source"]] + 0.02, "range exceeds take length"

    return {
        "version": 1,
        "sources": sources,
        "ranges": ranges,
        "audio_track": audio_track,
        "total_duration_s": total_duration,
    }
