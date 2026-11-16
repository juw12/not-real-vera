"""The mouth must follow the words: closed lips on b, m and p, open on vowels, back to the smile in silence."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))

import lipsync  # noqa: E402

FPS = 30
SAMPLE_RATE = 24000
SOUNDS = {"mama": "mɑmɑ", "papa": "pɑpɑ", "baby": "beɪbi", "see": "siː", "who": "huː"}


def voice_for(words, seconds):
    """A steady tone while each word is spoken, silence in between."""
    times = np.arange(int(seconds * SAMPLE_RATE)) / SAMPLE_RATE
    voice = np.zeros_like(times)
    for _, start, end in words:
        voice[(times >= start) & (times < end)] = 0.3
    return (voice * np.sin(2 * np.pi * 180 * times)).astype(np.float32)


def track(words, seconds=3.0, phonemize=SOUNDS.get):
    lines = [{"words": words}]
    voice = voice_for(words, seconds)
    return lipsync.mouth_track(lines, voice, SAMPLE_RATE, FPS, int(seconds * FPS), phonemize)


def frames(start, end):
    return slice(int(round(start * FPS)), int(round(end * FPS)))


def test_track_rate_divides_into_whole_video_frames():
    assert lipsync.TRACK_RATE % FPS == 0
    assert lipsync.TRACK_RATE % 60 == 0


def test_one_value_per_video_frame():
    mouth_open, mouth_wide, speech = track([("mama", 0.5, 1.1)])
    assert len(mouth_open) == len(mouth_wide) == len(speech) == 90
    assert -1.0 <= mouth_open.min() and mouth_open.max() <= 1.0


def test_mouth_opens_inside_the_word_and_rests_in_silence():
    mouth_open, _, speech = track([("mama", 0.5, 1.1)])
    assert mouth_open[frames(0.5, 1.1)].max() > 0.4
    assert np.abs(mouth_open[frames(0.0, 0.3)]).max() < 0.02
    assert np.abs(mouth_open[frames(1.5, 3.0)]).max() < 0.02
    assert speech[frames(0.6, 1.0)].min() > 0.5
    assert speech[frames(1.5, 3.0)].max() < 0.01


def test_lips_meet_on_b_m_and_p():
    for word in ("mama", "papa", "baby"):
        mouth_open, _, speech = track([(word, 0.5, 1.1)])
        assert mouth_open[frames(0.45, 0.65)].min() < -0.45, word
        assert lipsync.sync_report(mouth_open, speech, FPS)["lip_closures"] >= 1, word


def test_a_word_without_b_m_or_p_never_closes_the_lips():
    mouth_open, _, speech = track([("see", 0.5, 1.1)])
    assert mouth_open.min() > -0.05
    assert lipsync.sync_report(mouth_open, speech, FPS)["lip_closures"] == 0


def test_lips_round_for_oo_and_stretch_for_ee():
    _, wide_for_who, _ = track([("who", 0.5, 1.1)])
    _, wide_for_see, _ = track([("see", 0.5, 1.1)])
    assert wide_for_who.min() < -0.4
    assert wide_for_see.max() > 0.3


def test_a_silent_voice_keeps_the_mouth_from_opening():
    lines = [{"words": [("see", 0.5, 1.1)]}]
    silence = np.zeros(3 * SAMPLE_RATE, dtype=np.float32)
    mouth_open, _, _ = lipsync.mouth_track(lines, silence, SAMPLE_RATE, FPS, 90, SOUNDS.get)
    assert mouth_open.max() < 0.02


def test_a_failing_phonemizer_falls_back_to_the_letters():
    def broken(word):
        raise RuntimeError("no phonemizer")

    mouth_open, _, _ = track([("mama", 0.5, 1.1)], phonemize=broken)
    assert mouth_open.max() > 0.4
    assert mouth_open.min() < -0.45
    without, _, _ = track([("mama", 0.5, 1.1)], phonemize=None)
    assert np.allclose(mouth_open, without)


def test_long_marks_and_unknown_symbols_do_not_break_a_word():
    shapes = lipsync.word_shapes("ˈsiː!")
    assert len(shapes) == 2
    assert shapes[1][2] > lipsync.VOWEL_WEIGHT


def test_closure_is_long_enough_to_be_seen_in_a_fast_word():
    spans = lipsync.shape_spans(lipsync.word_shapes("stɑmp"), 0.0, 0.25)
    closure = [end - start for open_amount, _, start, end in spans if open_amount <= -0.99]
    assert closure and closure[0] >= 0.06
    assert abs(spans[-1][3] - 0.25) < 1e-9


def test_sync_report_finds_a_mouth_that_runs_late_or_early():
    random = np.random.default_rng(3)
    speech = np.clip(np.convolve(random.uniform(0, 1, 400), np.ones(5) / 5, mode="same"), 0, 1)
    on_time = lipsync.sync_report(speech, speech, FPS)
    assert on_time["best_shift_frames"] == 0
    assert on_time["correlation"] > 0.99
    late = lipsync.sync_report(np.roll(speech, 3), speech, FPS)
    assert late["best_shift_frames"] == 3
    assert late["best_shift_ms"] == 100.0
    early = lipsync.sync_report(np.roll(speech, -2), speech, FPS)
    assert early["best_shift_frames"] == -2


def test_sync_report_of_a_mouth_that_never_moves():
    report = lipsync.sync_report(np.zeros(90), np.linspace(0, 1, 90), FPS)
    assert report["correlation"] == 0.0
    assert report["best_shift_frames"] is None
