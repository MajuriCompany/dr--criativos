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

# Per-voice escape hatch: SILENCE_*/SPIKE_MIN_DURATION_S above are
# calibrated defaults, validated across many real files — this dict is
# for a specific MiniMax voice_id whose TTS delivery doesn't fit those
# defaults, WITHOUT touching them for every other voice. Empty unless a
# real file demonstrated a real, evidenced problem; a voice_id not in
# here (i.e. every voice except the ones explicitly listed) behaves
# exactly as if this dict didn't exist.
#
# "protect_word_interior": True clips every excision so it never
# overlaps the interior of an ASR-tagged word (only cuts in the gaps
# BETWEEN words) — added because tuning SILENCE_MIN_DURATION_S alone
# couldn't fix the voice below: even at 0.3s minimum duration (up from
# 0.1s), 53% of cuts still landed inside a word, because this voice's
# TTS delivery has genuinely long silent micro-gaps between syllables
# WITHIN single ASR-tagged words (confirmed via real waveform
# inspection: "WhatsApp," and "attrici" both showed real 100-150ms+ dips
# to -40..-65dB mid-word — true silence, not a threshold illusion).
VOICE_OVERRIDES: dict[str, dict] = {
    # Italian voice ("Italiano - Libido" ad). Verified against the real
    # file: eliminates all 28 (of 40) mid-word cuts, keeps 7.64s of the
    # original 10.74s removed (the genuinely-between-words portion).
    "moss_audio_dbd44289-8797-11f1-9b50-3ab6e7864d46": {"protect_word_interior": True},
    # French voice ("frances - homem"). First real file
    # (VSL_-_LIBIDO_FRANCES_-_PARTE_1) showed 41/45 excisions (91%)
    # landing inside a word with NO override at all — far worse than
    # any other voice seen, including the original mid-word case above.
    # User's own diagnosis matches what the data shows: this voice's
    # French delivery is fast, with many short (100-160ms) function
    # words ("le", "qu'elle", "Ta") — some get fully swallowed by a
    # merged excision spanning past their own boundaries entirely, most
    # others show the same decay-toward-silence pattern as the Italian
    # voices, just consuming a much larger FRACTION of the word's own
    # (already short) duration. Starting with the same simple, fully
    # structural guarantee that's needed zero follow-up tuning for the
    # first Italian voice above since it shipped — no excision can ever
    # touch a word's interior at all, full stop. If this proves too
    # conservative on more real files (leaves real silence in), that's
    # the next thing to evidence-check — don't preemptively add a
    # capped/threshold variant before a real file demonstrates it's
    # needed (see italiano2's VOICE_OVERRIDES entry for how many rounds
    # that took when done the other way around).
    "moss_audio_6813fe09-9be6-11f1-8e76-2e99d62c0bd6": {"protect_word_interior": True},
    # Second Italian voice ("italiano2" — user disliked the first one's
    # sound, unrelated to cutting quality). Long, real-evidence-based
    # history on this one — see git log for the full blow-by-blow. Short
    # version: several rounds of CAPPED protection (protect_word_interior_
    # max_s/min_cut_s/end_tolerance_s — all removed now, see
    # _protect_only_brief_word_interior_gaps for what replaced them) each
    # fixed the specific real case they were tuned against but kept
    # surfacing new ones ("avere."/"possederla." -> "fertile"/"diventare"/
    # "bagnata" -> "forza." -> "importante."), because every version tried
    # to use WHERE in the word a gap fell (how far from the start, how
    # close to the end, sentence-final or not) to decide whether to trust
    # it. Switched to full protect_word_interior=True after "importante."
    # per explicit user instruction ("arrume de uma vez por todas") — but
    # that immediately broke on "specifici" (Aula_2_-_Parte_1): a real,
    # substantial (413ms) internal silence inside an ordinary mid-sentence
    # word, left as audible dead air because full protection trusts the
    # ASR word tag unconditionally. Checked systematically across that
    # whole file (not just the one word): a LOT of ordinary words have a
    # genuine, substantial internal gap for this voice (18 words in one
    # 53.8s file alone) — full protection was silently leaving all of them
    # in, which is what "diversos trechos com silencio" was.
    #
    # The fix that actually held up: stop trying to use WHERE a gap is:
    # use only HOW LONG it is, on its own, independent of word position.
    # Real data from that same file makes a clean case for this: every
    # excision that should stay protected (a brief, natural articulation
    # dip) measured 60-113ms; every one that should be cut (real dead air,
    # whether from ASR mistiming or the TTS itself) measured 202-622ms —
    # no overlap between the two clusters. protect_word_interior_min_cut_s
    # = 0.15 sits in that real gap: excisions shorter than it get clipped
    # out of any word they touch (protected); excisions at or above it are
    # trusted as real silence and allowed to cut straight through a word,
    # full stop, regardless of position, sentence-finality, or distance
    # from the word's end — all signals every prior round relied on and
    # that turned out not to matter.
    #
    # noise_db=-55: user's explicit, direct instruction after the -34dB
    # retune still over-cut in practice ("bora mudar a regra... nao
    # coloque pra tipo abaixo de tal db cortar... deixe só pra tipo
    # quando é 0db... pra realmente nao tem nada") — stop trying to find
    # a threshold that also catches quiet-but-real decay, only cut when
    # a stretch is close to true digital silence. Swept the global
    # SILENCE_NOISE_DB=-26dB down against the real Reconquista manual
    # correction: over-cutting (real content removed) doesn't reach
    # exactly 0.00s until -55dB — anything less strict still occasionally
    # eats real (if quiet) content, confirmed down to -50dB (0.02s
    # over-cut, not zero). This is a real, explicit trade-off, not a
    # free win: total silence removed on that same file drops from
    # ~5-7s (at -26dB) to 1.90s at -55dB — words like "avere."/
    # "possederla."/"specifici." (confirmed real decay-to-silence
    # cases from earlier rounds) mostly stop getting cut too, since
    # their decay sits in the -25..-35dB range, well above -55dB. That
    # cost was accepted explicitly, in favor of never cutting real
    # content — do not walk this back to a more lenient value without a
    # new, explicit instruction to do so.
    #
    # padding_s/lead_in_s halved (0.01->0.005, 0.03->0.015): separate,
    # smaller follow-up ask after the -55dB change — user pointed at a
    # real CapCut screenshot (Aula_1.mp3, two adjacent kept clips) and
    # asked for the cut to sit a little closer to the truly-silent point
    # at each edge, explicitly "não precisa ser tanto, mas um pouco
    # mais" (doesn't need to be much, just a bit more). This only
    # shrinks the safety margin kept around each cut edge — it does NOT
    # touch the noise_db=-55 threshold itself (still only cuts stretches
    # close to true digital silence), just tightens how much of that
    # near-silence stays attached to the kept clips on either side.
    #
    # protect_word_interior_min_cut_s dropped 0.15->0.05: user reported
    # real silent stretches STILL not getting cut even now ("quando tá
    # zerado zerado e mesmo assim nao foi cortado"). Investigated
    # against a real render (AULA_1_-_REC): at noise_db=-55, ffmpeg
    # found 67 genuinely-qualifying silence spans (i.e. already passed
    # the strict digital-silence bar), but 11 of them (84-141ms each)
    # were being dropped anyway purely for being SHORTER than the old
    # 0.15s floor — despite being just as real as the longer ones. That
    # floor made sense back when it had to compensate for a LENIENT
    # threshold (-26dB, can't tell "real pause" from "brief articulation
    # dip" by loudness alone) — it stopped being needed, and started
    # actively dropping real silence, once noise_db got this strict:
    # anything clearing -55dB is already established as true silence
    # regardless of how short it is. 0.05 is a low floor kept only to
    # reject truly-degenerate near-zero-duration artifacts (rounding at
    # the edges of padding_s/lead_in_s), not a real duration
    # requirement — verified it still comfortably clears all 67 real
    # spans found on that file (16.04s recovered vs 14.77s at 0.15).
    # The _INTERIOR_END_TOLERANCE_S leftover-content safety check (see
    # _protect_only_brief_word_interior_gaps) still applies independent
    # of this value, so a word-interior split still can't happen even
    # with the duration floor this low.
    "moss_audio_d497d00d-8864-11f1-84c0-1e0b7b847846": {
        "protect_word_interior_min_cut_s": 0.05,
        "noise_db": -55.0,
        "padding_s": 0.005,
        "lead_in_s": 0.015,
    },
}

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


def _detect_silence_spans(audio_path: Path, noise_db: float = SILENCE_NOISE_DB) -> list[tuple[float, float]]:
    """Real waveform silence spans via ffmpeg silencedetect, at Recut's
    threshold/min-duration (or a per-voice override — see VOICE_OVERRIDES'
    noise_db). Returns sorted, non-overlapping (start, end)."""
    result = subprocess.run(
        ["ffmpeg", "-i", str(audio_path),
         "-af", f"silencedetect=noise={noise_db}dB:d={SILENCE_MIN_DURATION_S}",
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


def _clip_to_word_gaps(
    excisions: list[tuple[float, float]], words: list[dict],
) -> list[tuple[float, float]]:
    """Subtracts every word's own [start, end] span (or a caller-capped
    version of it — see protect_word_interior_max_s in VOICE_OVERRIDES)
    from each excision, so none of them can ever overlap the protected
    span. Only the gaps survive. See VOICE_OVERRIDES for why/when."""
    clipped: list[tuple[float, float]] = []
    for exc_start, exc_end in excisions:
        pieces = [(exc_start, exc_end)]
        for w in words:
            ws, we = w["start"], w["end"]
            next_pieces = []
            for s, e in pieces:
                if we <= s or ws >= e:
                    next_pieces.append((s, e))
                    continue
                if ws > s:
                    next_pieces.append((s, ws))
                if we < e:
                    next_pieces.append((we, e))
            pieces = next_pieces
        clipped.extend((s, e) for s, e in pieces if e - s > 0.005)
    return clipped


_INTERIOR_END_TOLERANCE_S = 0.05
# A trusted (long enough) excision that lands INSIDE a word is still only
# safe to cut through if it reaches close to the word's own end. If it
# stops well short, real audio of the SAME word resumes after it — and
# that's not a quiet tail, it's genuinely spoken content: measured
# directly on a real case ("forza.", PARTE-2) the 77ms leftover chunk
# after the cut was LOUDER (-25.3dB mean) than the word's own confirmed
# onset (-28.0dB mean). Splitting that is the exact "inicio de uma
# palavra, silencio pequeno, mais um pouco de audio completando a
# palavra" pattern reported at sentence transitions. Cases that DO
# reach close to the word's end (avere. 34ms short, consapevolmente,
# 30ms short — both confirmed real, imperceptible tail) still cut
# fine; only a real, substantial leftover (forza. 77ms, lei 72ms,
# rispetta, 71ms — all confirmed to contain real signal, not near-
# silence, by direct amplitude measurement) blocks the cut.


def _protect_only_brief_word_interior_gaps(
    excisions: list[tuple[float, float]], words: list[dict], min_cut_s: float,
) -> list[tuple[float, float]]:
    """Trusts an excision as real silence only if it's long enough
    (>= min_cut_s) AND, when it lands inside a word, reaches close to
    that word's own end (see _INTERIOR_END_TOLERANCE_S) — otherwise it's
    dropped ENTIRELY (left as kept audio), not partially clipped down to
    whatever fragment of it doesn't touch a word. That distinction
    matters for plain BETWEEN-word gaps too, not just word-interior
    ones: a first version clipped a rejected excision against
    _clip_to_word_gaps, which is a no-op when the excision doesn't touch
    any word at all — so short between-word gaps (breaths/natural
    cadence pauses) were passing through completely unfiltered, uncut
    only when they happened to touch a word. Confirmed on a real
    controlled test (user manually marked 14 "should cut" spans in
    CapCut on Aula_1_-_PARTE_1/Parte_2 and exported before/after audio
    for exact comparison via waveform alignment, not guessing): the
    smallest wanted cut was 243ms; several unwanted between-word gaps we
    were still cutting anyway measured 64-125ms — comfortably below
    min_cut_s, they just weren't being rejected outright. Dropping a
    failing excision fully (instead of clip-and-partially-keep) fixes
    that with the SAME min_cut_s value, no threshold change needed —
    confirmed all 14 marked spans still cut correctly after the fix.
    Deliberately does not care where in the word a trusted excision
    STARTS, or the word's position in its sentence — see VOICE_OVERRIDES
    for why those signals turned out not to reliably distinguish "real
    decay/pause" from "natural articulation dip" for this voice, while
    raw duration does, cleanly, in real data."""
    kept: list[tuple[float, float]] = []
    for s, e in excisions:
        long_enough = (e - s) >= min_cut_s
        leaves_real_leftover = any(
            s > w["start"] + 0.005 and e < w["end"] - _INTERIOR_END_TOLERANCE_S for w in words
        )
        if long_enough and not leaves_real_leftover:
            kept.append((s, e))
    return kept


def _compute_excisions(
    audio_path: Path,
    words: list[dict] | None = None,
    protect_word_interior: bool = False,
    protect_word_interior_min_cut_s: float | None = None,
    noise_db: float = SILENCE_NOISE_DB,
    padding_s: float = SILENCE_PADDING_S,
    lead_in_s: float = SILENCE_LEAD_IN_S,
) -> list[tuple[float, float]]:
    """Silence spans, with short audible spikes between them merged in
    (Recut's "Remove Short Audio Spikes"), then padded (Recut's
    "Padding") to get the actual regions to cut from the audio.

    noise_db/padding_s/lead_in_s (see VOICE_OVERRIDES) override the
    global SILENCE_NOISE_DB/SILENCE_PADDING_S/SILENCE_LEAD_IN_S for a
    specific voice — no-ops (module defaults) unless a caller explicitly
    opts in.

    protect_word_interior (see VOICE_OVERRIDES) clips the result so no
    excision ever overlaps the interior of a transcript word at all — off
    by default, a no-op unless a caller explicitly opts in for a specific
    voice. protect_word_interior_min_cut_s is a different, less absolute
    version of the same idea: only excisions SHORTER than this get
    clipped out of a word's interior; longer ones are trusted as real
    silence and allowed to cut straight through a word if that's where
    the waveform says it is — see _protect_only_brief_word_interior_gaps.
    The two are mutually exclusive per call (min_cut_s takes precedence
    if both are somehow set)."""
    spans = _detect_silence_spans(audio_path, noise_db=noise_db)
    if not spans:
        return []

    merged: list[list[float]] = [list(spans[0])]
    for start, end in spans[1:]:
        audible_gap = start - merged[-1][1]
        if audible_gap < SPIKE_MIN_DURATION_S:
            merged[-1][1] = end
        else:
            merged.append([start, end])

    total_duration = _ffprobe_duration(audio_path)
    excisions = []
    for s, e in merged:
        # SILENCE_LEAD_IN_S exists to give the FOLLOWING kept segment's
        # fade-in room to finish before real content starts — meaningless
        # for the trailing silence span (the one reaching the file's own
        # end), since there is no following segment. Using it there left
        # a pointless ~30ms sliver of "kept" near-silence dangling after
        # the real audio ends, showing up as a separate, nonsensical tail
        # clip in the CapCut draft. Use the smaller, plain padding there
        # instead, same as the trailing side of every other cut.
        end_pad = padding_s if e >= total_duration - 0.001 else lead_in_s
        exc_start, exc_end = s + padding_s, e - end_pad
        if exc_end > exc_start:
            excisions.append((exc_start, exc_end))

    if words and protect_word_interior_min_cut_s is not None:
        excisions = _protect_only_brief_word_interior_gaps(excisions, words, protect_word_interior_min_cut_s)
    elif protect_word_interior and words:
        excisions = _clip_to_word_gaps(excisions, words)
    return excisions


def sentences_from_kept_ranges(
    words: list[dict], kept_ranges: list[tuple[float, float]], total_duration: float,
    new_offset: float = 0.0,
) -> list[dict]:
    """Same sentence/new-timestamp mapping cut_silence() builds internally
    from its own computed kept ranges, but usable with ANY kept_ranges —
    including ones extracted from a CapCut draft the user cut manually
    (see capcut_draft.read_existing_audio_track), not just ones this
    module's own silencedetect logic computed. new_offset shifts every
    resulting new_start/new_end by a constant, for splicing several
    source files' sentences into one shared, longer draft timeline
    (each part's own words are only ever mapped through ITS OWN
    kept_ranges — new_offset is applied after that, uniformly)."""
    kept_sorted = sorted(kept_ranges)
    excisions: list[tuple[float, float]] = []
    cursor = 0.0
    for s, e in kept_sorted:
        if s > cursor:
            excisions.append((cursor, s))
        cursor = e
    if cursor < total_duration:
        excisions.append((cursor, total_duration))

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

    sentences: list[list[dict]] = []
    cur_words: list[dict] = []
    for w in words:
        cur_words.append(w)
        if _ends_sentence((w.get("text") or "").strip()):
            sentences.append(cur_words)
            cur_words = []
    if cur_words:
        sentences.append(cur_words)

    sent_out = []
    for sw in sentences:
        mapped_words = [
            {"text": w.get("text"), "orig_start": w["start"], "orig_end": w["end"],
             "new_start": round(orig_to_new(w["start"]) + new_offset, 3),
             "new_end": round(orig_to_new(w["end"]) + new_offset, 3)}
            for w in sw
        ]
        sent_out.append({
            "text": " ".join((w.get("text") or "").strip() for w in sw),
            "new_start": round(orig_to_new(sw[0]["start"]) + new_offset, 3),
            "new_end": round(orig_to_new(sw[-1]["end"]) + new_offset, 3),
            "words": mapped_words,
        })
    return sent_out


def cut_silence(
    audio_path: Path, transcript_path: Path, edit_dir: Path, base_name: str,
    voice_id: str | None = None,
) -> dict:
    """Cut excess silence from audio_path using the transcript's word timestamps.

    voice_id: the MiniMax voice this audio was generated with, if known —
    only used to look up VOICE_OVERRIDES; omitting it (or passing a
    voice_id with no override) behaves exactly as before this parameter
    existed.

    Returns {"final_mp3": Path, "sentences_json": Path, "duration_before": float,
    "duration_after": float, "cuts_made": int}.
    """
    data = json.loads(transcript_path.read_text(encoding="utf-8"))

    total_duration = _ffprobe_duration(audio_path)

    overrides = VOICE_OVERRIDES.get(voice_id, {}) if voice_id else {}
    excisions = _compute_excisions(
        audio_path,
        words=[w for w in data["words"] if w.get("type") == "word"],
        protect_word_interior=overrides.get("protect_word_interior", False),
        protect_word_interior_min_cut_s=overrides.get("protect_word_interior_min_cut_s"),
        noise_db=overrides.get("noise_db", SILENCE_NOISE_DB),
        padding_s=overrides.get("padding_s", SILENCE_PADDING_S),
        lead_in_s=overrides.get("lead_in_s", SILENCE_LEAD_IN_S),
    )

    ranges: list[tuple[float, float]] = []
    cursor = 0.0
    for exc_start, exc_end in excisions:
        if exc_start > cursor:
            ranges.append((cursor, exc_start))
        cursor = exc_end
    ranges.append((cursor, total_duration))
    ranges = [(s, e) for s, e in ranges if e - s > 0.01]

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
    sent_out = sentences_from_kept_ranges(plain_words, ranges, total_duration)

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
