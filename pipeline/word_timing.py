"""Time every caption word to the voice, so the highlighted word is the one being spoken.

Kokoro gives no word timings. This runs a small offline speech recogniser (Vosk) over each spoken line with
the line's own words as its only vocabulary, which makes it report when each of those words starts and ends.
Words it cannot place (a name it does not know, say) are spaced between their placed neighbours.
"""
import difflib
import json
import re
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

ROOT = Path(__file__).resolve().parent.parent
SPEECH_MODEL = ROOT / "models" / "vosk-model-small-en-us-0.15"
RECOGNISER_RATE = 16000

_model = None

ONES = [
    "zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen",
]
TENS = ["", "", "twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"]


def number_words(digits):
    """'3' -> ['three'];  '24' -> ['twenty', 'four'];  '310' -> ['three', 'hundred', 'ten'].
    The recogniser only knows spelled-out words. Longer digit runs are read digit by digit."""
    if len(digits) > 3 or (len(digits) > 1 and digits.startswith("0")):
        return [ONES[int(digit)] for digit in digits]
    value = int(digits)
    words = []
    if value >= 100:
        words += [ONES[value // 100], "hundred"]
        value %= 100
        if value == 0:
            return words
    if value < 20:
        return words + [ONES[value]]
    words.append(TENS[value // 10])
    if value % 10:
        words.append(ONES[value % 10])
    return words


def spoken_parts(token):
    """'Fifty-one' -> ['fifty', 'one'];  "service's," -> ["service's"];  '3' -> ['three'].
    The recogniser hears these parts."""
    parts = re.split(r"[-\u2010-\u2015/]", token.lower())
    cleaned = [re.sub(r"[^a-z0-9']", "", part).strip("'") for part in parts]
    spoken = []
    for part in cleaned:
        for piece in re.findall(r"\d+|[a-z']+", part):
            spoken += number_words(piece) if piece.isdigit() else [piece]
    return [piece for piece in spoken if piece.strip("'")]


def load_model():
    global _model
    if _model is None:
        if not SPEECH_MODEL.exists():
            return None
        import vosk

        vosk.SetLogLevel(-1)
        _model = vosk.Model(str(SPEECH_MODEL))
    return _model


def recognise(samples, sample_rate, vocabulary=None):
    """Return [(word, start_s, end_s)] heard in the samples."""
    import vosk

    audio = resample_poly(samples, RECOGNISER_RATE, sample_rate)
    data = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16).tobytes()
    if vocabulary:
        recogniser = vosk.KaldiRecognizer(load_model(), RECOGNISER_RATE, json.dumps([" ".join(vocabulary), "[unk]"]))
    else:
        recogniser = vosk.KaldiRecognizer(load_model(), RECOGNISER_RATE)
    recogniser.SetWords(True)
    recogniser.AcceptWaveform(data)
    heard = json.loads(recogniser.FinalResult()).get("result", [])
    return [(item["word"], float(item["start"]), float(item["end"])) for item in heard]


def place_tokens(tokens, heard, duration):
    """Match heard words to the script's tokens. Returns (spans, placed): spans is [(start, end)] per token,
    placed says which tokens were really heard (the others are spaced between their neighbours)."""
    parts = []
    owner = []
    for token_index, token in enumerate(tokens):
        for part in spoken_parts(token):
            parts.append(part)
            owner.append(token_index)
    starts = [None] * len(tokens)
    ends = [None] * len(tokens)
    matcher = difflib.SequenceMatcher(a=parts, b=[word for word, _, _ in heard], autojunk=False)
    for block in matcher.get_matching_blocks():
        for offset in range(block.size):
            token_index = owner[block.a + offset]
            _, start, end = heard[block.b + offset]
            is_first_part = block.a + offset == 0 or owner[block.a + offset - 1] != token_index
            if is_first_part:
                starts[token_index] = start
            if starts[token_index] is not None:
                ends[token_index] = end
    placed = [start is not None for start in starts]

    index = 0
    while index < len(tokens):
        if starts[index] is not None:
            index += 1
            continue
        run_end = index
        while run_end < len(tokens) and starts[run_end] is None:
            run_end += 1
        left = ends[index - 1] if index > 0 else 0.0
        right = starts[run_end] if run_end < len(tokens) else duration
        weights = [len(tokens[position]) + 1 for position in range(index, run_end)]
        elapsed = 0.0
        for position, weight in zip(range(index, run_end), weights):
            starts[position] = left + (right - left) * elapsed / sum(weights)
            elapsed += weight
        index = run_end

    spans = []
    for position, start in enumerate(starts):
        next_start = starts[position + 1] if position + 1 < len(tokens) else duration
        end = ends[position] if placed[position] and ends[position] else next_start
        spans.append((start, max(min(end, max(next_start, start + 0.05)), start + 0.05)))
    return spans, placed


def align(tokens, samples, sample_rate):
    """Return (spans, placed) for one spoken line, or None when the recogniser is not installed."""
    if load_model() is None:
        return None
    duration = len(samples) / sample_rate
    vocabulary = [part for token in tokens for part in spoken_parts(token)]
    best = place_tokens(tokens, recognise(samples, sample_rate, vocabulary), duration)
    if sum(best[1]) < 0.8 * len(tokens):
        free = place_tokens(tokens, recognise(samples, sample_rate), duration)
        if sum(free[1]) > sum(best[1]):
            best = free
    return best
