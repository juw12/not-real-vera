"""The music bed must not sound the same from one episode to the next."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))

import sound  # noqa: E402


def test_first_25_episodes_each_get_their_own_key_and_tempo_pair():
    choices = [sound.music_choice(f"ep{number:02d}") for number in range(1, 26)]
    assert len(set(choices)) == 25


def test_neighbouring_episodes_share_neither_key_nor_tempo():
    choices = [sound.music_choice(f"ep{number:02d}") for number in range(1, 61)]
    for before, after in zip(choices, choices[1:]):
        assert before[0] != after[0]
        assert before[1] != after[1]


def test_a_name_without_a_number_still_gets_a_choice():
    root, tempo = sound.music_choice("pilot")
    assert root in sound.KEY_ROOTS
    assert tempo in sound.TEMPOS
