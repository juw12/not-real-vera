"""Mouth shapes for every video frame, worked out from the voice. No model download, CPU only.

How it works
1. Each spoken word already has a start and an end measured from the voice (pipeline/word_timing.py).
2. The word is turned into its sounds with the same phonemizer the voice engine uses, and every sound gets
   a mouth shape: how far the jaw is open (-1 lips pressed shut ... 0 the still's smile ... 1 wide open) and
   how wide the lips are (-1 rounded ... 1 stretched).
3. The sounds share the word's time span (vowels get more of it than consonants; b, m and p always get long
   enough for the lips to visibly meet).
4. How far the mouth opens is scaled by how loud the voice really is at that instant, so a quiet syllable
   opens less and silence returns to the smile.

This is classic rule-based lip-sync (the kind used for game characters), not a neural talking-head model.
The lips open, close and round in time with the words; they do not reproduce every tongue and teeth detail.
"""
import numpy as np

TRACK_RATE = 120  # mouth-shape samples per second before they are read off per video frame
ENVELOPE_WINDOW_S = 0.025
MIN_CLOSURE_S = 0.085  # b, m, p: lips stay together at least this long (about 2.5 frames at 30 fps)
SMOOTH_SIGMA_S = 0.020  # blends neighbouring shapes the way a real mouth does
QUIET_LEVEL = 0.06  # below this share of the loud level, the mouth is not opened

VOWEL_WEIGHT, CONSONANT_WEIGHT, LONG_BONUS = 1.6, 1.0, 0.7
# sound -> (open, wide)
SHAPES = {}
for sounds, shape in (
    ("pbm", (-1.0, 0.0)),
    ("fv", (-0.6, 0.1)),
    ("w", (0.15, -0.9)),
    ("uʊ", (0.3, -0.8)),
    ("oɔ", (0.7, -0.6)),
    ("ɹrʃʒ", (0.2, -0.4)),
    ("aɑɐɒæʌ", (1.0, 0.1)),
    ("ɛe", (0.6, 0.4)),
    ("iɪj", (0.35, 0.6)),
    ("əɚɜɝᵊ", (0.45, 0.0)),
    ("tdnlszθðɾ", (0.15, 0.3)),
    ("kgɡŋhʔx", (0.3, 0.1)),
):
    for sound in sounds:
        SHAPES[sound] = shape
VOWELS = set("aɑɐɒæʌɛeiɪəɚɜɝᵊoɔuʊ")
LETTER_SOUNDS = {"c": "k", "q": "k", "x": "k", "y": "i", "h": "h"}


def spell_out(word):
    """Fallback when no phonemizer is available: treat letters as sounds."""
    return "".join(LETTER_SOUNDS.get(letter, letter) for letter in word.lower() if letter.isalpha())


def word_shapes(sounds):
    """[(open, wide, weight)] for one word's sounds; marks and unknown symbols are skipped."""
    shapes = []
    for sound in sounds:
        if sound == "ː" and shapes:
            open_amount, wide, weight = shapes[-1]
            shapes[-1] = (open_amount, wide, weight + LONG_BONUS)
        elif sound in SHAPES:
            weight = VOWEL_WEIGHT if sound in VOWELS else CONSONANT_WEIGHT
            shapes.append(SHAPES[sound] + (weight,))
    return shapes


def shape_spans(shapes, start, end):
    """Share the word's time between its sounds: [(open, wide, start, end)]."""
    duration = max(end - start, 1e-3)
    weights = np.array([weight for _, _, weight in shapes], dtype=np.float64)
    lengths = duration * weights / weights.sum()
    closures = np.array([open_amount <= -0.99 for open_amount, _, _ in shapes])
    if closures.any() and not closures.all():
        wanted = min(MIN_CLOSURE_S, duration * 0.5 / closures.sum())
        short = closures & (lengths < wanted)
        if short.any():
            taken = float(np.sum(wanted - lengths[short]))
            others = ~short
            lengths[others] *= max(1.0 - taken / lengths[others].sum(), 0.2)
            lengths[short] = wanted
            lengths *= duration / lengths.sum()
    spans = []
    cursor = start
    for (open_amount, wide, _), length in zip(shapes, lengths):
        spans.append((open_amount, wide, cursor, cursor + length))
        cursor += length
    return spans


def voice_envelope(voice, sample_rate, samples_wanted):
    """Loudness of the voice at TRACK_RATE, 0 (silent) to 1 (as loud as its loud syllables)."""
    window = max(int(ENVELOPE_WINDOW_S * sample_rate), 1)
    power = np.concatenate([[0.0], np.cumsum(voice.astype(np.float64) ** 2)])
    centres = (np.arange(samples_wanted) + 0.5) * sample_rate / TRACK_RATE
    first = np.clip((centres - window / 2).astype(np.int64), 0, len(voice))
    last = np.clip(first + window, 0, len(voice))
    level = np.sqrt((power[last] - power[first]) / window)
    loud = np.percentile(level[level > 1e-4], 95) if np.any(level > 1e-4) else 1.0
    return np.clip(level / loud, 0.0, 1.0)


def smooth(values, sigma_s):
    sigma = sigma_s * TRACK_RATE
    radius = int(np.ceil(3 * sigma))
    kernel = np.exp(-0.5 * (np.arange(-radius, radius + 1) / sigma) ** 2)
    return np.convolve(np.pad(values, radius, mode="edge"), kernel / kernel.sum(), mode="valid")


def mouth_track(lines, voice, sample_rate, fps, total_frames, phonemize=None):
    """Return per-frame arrays: open (-1..1), wide (-1..1) and speech (0..1, how loud the voice is).

    lines: the timeline from make_episode.build_audio (each word is (token, start_s, end_s)).
    voice: the voice-only track on that same timeline. phonemize: word -> string of sounds, or None.
    """
    per_frame = TRACK_RATE // fps
    samples = total_frames * per_frame
    envelope = voice_envelope(voice, sample_rate, samples)
    open_target = np.zeros(samples)
    wide_target = np.zeros(samples)
    spoken = np.zeros(samples, dtype=bool)
    for line in lines:
        for token, start, end in line["words"]:
            sounds = ""
            if phonemize is not None:
                try:
                    sounds = phonemize(token)
                except Exception:  # an odd token must not stop a render; fall back to its letters
                    sounds = ""
            shapes = word_shapes(sounds) or word_shapes(spell_out(token))
            if not shapes:
                continue
            for open_amount, wide, span_start, span_end in shape_spans(shapes, start, end):
                first = int(round(span_start * TRACK_RATE))
                last = max(int(round(span_end * TRACK_RATE)), first + 1)
                open_target[first:last] = open_amount
                wide_target[first:last] = wide
                spoken[first:last] = True
    loud_enough = np.clip(envelope / QUIET_LEVEL, 0.0, 1.0)
    opening = np.clip(open_target, 0.0, None) * loud_enough * (0.35 + 0.65 * envelope)
    closing = np.clip(open_target, None, 0.0)
    mouth_open = smooth(opening + closing, SMOOTH_SIGMA_S)
    mouth_wide = smooth(wide_target * np.where(spoken, 1.0, 0.0), SMOOTH_SIGMA_S * 1.5)
    centre = np.arange(total_frames) * per_frame + per_frame // 2
    speech = envelope.reshape(total_frames, per_frame).mean(axis=1)
    return mouth_open[centre], mouth_wide[centre], speech


def sync_report(mouth_open, speech, fps):
    """How well the drawn mouth opening follows the voice: correlation, and the shift (in frames) at which
    the two line up best. The opening is driven by the voice, so this is a check for timing mistakes, not a
    measure of realism."""
    opening = np.clip(mouth_open, 0.0, None)
    if opening.std() < 1e-6 or speech.std() < 1e-6:
        return {"correlation": 0.0, "best_shift_frames": None, "best_shift_ms": None}
    best_shift, best_value = 0, -1.0
    for shift in range(-6, 7):
        if shift >= 0:
            value = np.corrcoef(opening[shift:], speech[: len(speech) - shift])[0, 1]
        else:
            value = np.corrcoef(opening[:shift], speech[-shift:])[0, 1]
        if value > best_value:
            best_shift, best_value = shift, float(value)
    talking = speech > 0.25
    return {
        "correlation": round(float(np.corrcoef(opening, speech)[0, 1]), 3),
        "best_shift_frames": best_shift,
        "best_shift_ms": round(1000.0 * best_shift / fps, 1),
        "mouth_moves_while_talking": round(float(np.mean(np.abs(np.diff(mouth_open))[talking[1:]] > 0.02)), 3),
        "lip_closures": int(np.sum((mouth_open[1:] < -0.45) & (mouth_open[:-1] >= -0.45))),
    }
