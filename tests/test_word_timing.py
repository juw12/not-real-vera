"""Caption words must be matched to what the voice says, including digits the recogniser only knows as words."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))

import word_timing  # noqa: E402


def test_digits_become_the_words_the_voice_says():
    assert word_timing.spoken_parts("3") == ["three"]
    assert word_timing.spoken_parts("24") == ["twenty", "four"]
    assert word_timing.spoken_parts("310") == ["three", "hundred", "ten"]
    assert word_timing.spoken_parts("2025") == ["two", "zero", "two", "five"]


def test_letters_and_digits_in_one_token_are_split():
    assert word_timing.spoken_parts("IC3,") == ["ic", "three"]


def test_plain_words_are_unchanged():
    assert word_timing.spoken_parts("Fifty-one") == ["fifty", "one"]
    assert word_timing.spoken_parts("service's,") == ["service's"]
    assert word_timing.spoken_parts("--") == []


def test_a_digit_token_is_placed_when_the_voice_says_the_word():
    tokens = ["I", "C", "3", "dot", "gov."]
    heard = [("i", 0.0, 0.2), ("c", 0.2, 0.4), ("three", 0.4, 0.7), ("dot", 0.7, 0.9), ("gov", 0.9, 1.2)]
    spans, placed = word_timing.place_tokens(tokens, heard, 1.2)
    assert placed == [True] * 5
    assert spans[2] == (0.4, 0.7)
