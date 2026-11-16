"""Sound for one episode: the voice, polished, over a music bed that is synthesised here.

Nothing is sampled or downloaded, so there is no licence to clear. Every episode gets its own key and tempo.
The bed has three parts that follow the script: a tense, sparse part while the scam is shown, a riser and an
impact exactly on the 10-second check, then a fuller beat, and one held chord under the sign-off. The music
ducks whenever she speaks. The finished mix is stereo and set to -14 LUFS, the level the platforms play at.
"""
import json
import re
import subprocess
import wave
import zlib

import imageio_ffmpeg
import numpy as np
from scipy import signal

SAMPLE_RATE = 48000
TARGET_LUFS = -14.0
# Sample peak ceiling to start from, about -1.6 dBFS. The peak between samples comes out higher by an
# amount that changes from mix to mix (measured: 0.6 to 0.9 dB), so a fixed ceiling is not enough:
# mix_episode measures the true peak and lowers the ceiling until it is at or under the limit.
PEAK_CEILING = 0.83
TRUE_PEAK_LIMIT_DBTP = -1.0
TRUE_PEAK_AIM_DBTP = -1.2  # what the ceiling is corrected towards, a little under the limit
MUSIC_UNDER_VOICE_DB = -17.0  # music level while she is speaking, relative to her voice
DUCK_DEPTH = 0.62  # share of the music that is taken away at full voice level
EFFECTS_UNDER_VOICE_DB = -12.0  # level of the impact on the check, relative to her voice
# Each key is the root note of a minor key (Hz, around octave 2); chords are i, VI, III, VII of that key.
KEY_ROOTS = [110.00, 98.00, 123.47, 87.31, 103.83]
TEMPOS = [96, 100, 92, 104, 98]
PROGRESSION = [0, 8, 3, 10]  # semitones above the root: i, VI, III, VII
CHORD_SHAPES = {0: [0, 3, 7, 12], 8: [0, 4, 7, 12], 3: [0, 4, 7, 12], 10: [0, 4, 7, 12]}


def seconds(length):
    return int(round(length * SAMPLE_RATE))


def time_axis(length):
    return np.arange(seconds(length)) / SAMPLE_RATE


def semitones(frequency, steps):
    return frequency * 2.0 ** (steps / 12.0)


def filtered(samples, kind, cutoff, order=2):
    return signal.sosfiltfilt(signal.butter(order, cutoff, kind, fs=SAMPLE_RATE, output="sos"), samples, axis=0)


def follow_level(samples, attack_s, release_s):
    """Loudness of a mono signal over time (0..1 scale), rising fast and falling slowly."""
    block = seconds(0.005)
    count = len(samples) // block
    levels = np.sqrt(np.mean(samples[: count * block].reshape(count, block) ** 2, axis=1))
    rise = 1.0 - np.exp(-0.005 / attack_s)
    fall = 1.0 - np.exp(-0.005 / release_s)
    followed = np.empty(count)
    current = 0.0
    for index, level in enumerate(levels):
        current += (level - current) * (rise if level > current else fall)
        followed[index] = current
    return np.interp(np.arange(len(samples)), (np.arange(count) + 0.5) * block, followed)


def place(bus, sound, at_seconds, gain=1.0, pan=0.0):
    """Add a mono or stereo sound to the stereo bus. pan: -1 left, 0 centre, 1 right."""
    start = seconds(at_seconds)
    if start < 0:
        sound = sound[-start:]
        start = 0
    end = min(len(bus), start + len(sound))
    if end <= start:
        return
    part = sound[: end - start]
    if part.ndim == 1:
        angle = (pan + 1.0) * np.pi / 4.0
        part = np.stack([part * np.cos(angle), part * np.sin(angle)], axis=1) * np.sqrt(2.0)
    bus[start:end] += part * gain


# ---------------------------------------------------------------- voice


def polish_voice(voice):
    """Clean the low end, even out the level, add presence and air. Returns the voice peaking at 0.9."""
    cleaned = filtered(voice, "highpass", 85.0)
    level_db = 20.0 * np.log10(np.maximum(follow_level(cleaned, 0.006, 0.14), 1e-5))
    threshold_db, ratio = -24.0, 2.8
    reduction_db = np.minimum(0.0, (threshold_db - level_db) * (1.0 - 1.0 / ratio))
    compressed = cleaned * 10.0 ** (reduction_db / 20.0)
    presence = filtered(compressed, "bandpass", [2200.0, 5200.0], order=1)
    air = filtered(compressed, "highpass", 8500.0)
    warmth = filtered(compressed, "bandpass", [140.0, 320.0], order=1)
    polished = compressed + 0.42 * presence + 0.22 * air + 0.14 * warmth
    return (polished * (0.9 / max(float(np.max(np.abs(polished))), 1e-6))).astype(np.float32)


# ---------------------------------------------------------------- instruments


def pad_note(frequency, length, brightness, random):
    """A soft, wide sustained note: two slightly detuned voices, one per side."""
    axis = time_axis(length)
    sides = []
    for detune_cents in (-7.0, 7.0):
        tuned = frequency * 2.0 ** (detune_cents / 1200.0)
        voice = np.zeros_like(axis)
        for harmonic in range(1, 9):
            if tuned * harmonic > 7000:
                break
            weight = np.exp(-(harmonic - 1) / brightness) / harmonic
            voice += weight * np.sin(2 * np.pi * tuned * harmonic * axis + random.uniform(0, 2 * np.pi))
        sides.append(voice)
    attack, release = min(0.5, length / 3), min(0.7, length / 3)
    shape = np.clip(axis / attack, 0, 1) * np.clip((length - axis) / release, 0, 1)
    return np.stack(sides, axis=1) * shape[:, None]


def bass_note(frequency, length, pluck):
    axis = time_axis(length)
    tone = np.sin(2 * np.pi * frequency * axis) + 0.28 * np.sin(4 * np.pi * frequency * axis)
    decay = np.exp(-axis / (0.22 if pluck else 1.6))
    return np.tanh(1.4 * tone * decay) * np.clip(axis / 0.008, 0, 1) * np.clip((length - axis) / 0.03, 0, 1)


def kick():
    axis = time_axis(0.32)
    pitch = 46.0 + 78.0 * np.exp(-axis / 0.035)
    body = np.sin(2 * np.pi * np.cumsum(pitch) / SAMPLE_RATE) * np.exp(-axis / 0.11)
    return body + 0.25 * np.exp(-axis / 0.003) * np.sin(2 * np.pi * 1800 * axis)


def hat(random, open_hat=False):
    axis = time_axis(0.16 if open_hat else 0.06)
    noise = filtered(random.standard_normal(len(axis)), "highpass", 7500.0)
    return noise * np.exp(-axis / (0.05 if open_hat else 0.016))


def clap(random):
    axis = time_axis(0.22)
    noise = filtered(random.standard_normal(len(axis)), "bandpass", [900.0, 3800.0])
    bursts = sum(np.exp(-np.abs(axis - offset) / 0.004) for offset in (0.0, 0.011, 0.023))
    return noise * (0.5 * bursts + np.exp(-axis / 0.07))


def pluck(frequency, length=0.42):
    axis = time_axis(length)
    tone = sum(np.sin(2 * np.pi * frequency * harmonic * axis) / harmonic ** 2 for harmonic in (1, 2, 3, 4))
    return tone * np.exp(-axis / 0.13) * np.clip(axis / 0.004, 0, 1)


def bell(frequency, length=1.4):
    axis = time_axis(length)
    partials = [(1.0, 1.0, 0.55), (2.76, 0.45, 0.28), (5.4, 0.22, 0.14), (8.93, 0.1, 0.08)]
    return sum(
        weight * np.sin(2 * np.pi * frequency * ratio * axis) * np.exp(-axis / decay)
        for ratio, weight, decay in partials
    )


def riser(length, random):
    axis = time_axis(length)
    progress = axis / length
    noise = random.standard_normal(len(axis))
    dull = filtered(noise, "lowpass", 1200.0)
    bright = filtered(noise, "highpass", 3000.0)
    sweep = np.sin(2 * np.pi * np.cumsum(180.0 * 2.0 ** (3.2 * progress)) / SAMPLE_RATE)
    return (dull * (1 - progress) + bright * progress + 0.5 * sweep) * progress ** 2.2


def impact(random):
    axis = time_axis(1.6)
    pitch = 34.0 + 50.0 * np.exp(-axis / 0.09)
    boom = np.sin(2 * np.pi * np.cumsum(pitch) / SAMPLE_RATE) * np.exp(-axis / 0.42)
    crash = filtered(random.standard_normal(len(axis)), "lowpass", 5200.0) * np.exp(-axis / 0.3)
    return boom + 0.3 * crash


def whoosh(random, length=0.42):
    axis = time_axis(length)
    noise = filtered(random.standard_normal(len(axis)), "bandpass", [500.0, 5000.0])
    swell = np.sin(np.pi * axis / length) ** 2
    pan = np.linspace(-0.8, 0.8, len(axis))
    angle = (pan + 1.0) * np.pi / 4.0
    return np.stack([noise * swell * np.cos(angle), noise * swell * np.sin(angle)], axis=1)


def add_room(bus, random, wet=0.2):
    """A short, wide room tail, so the instruments sit in one space."""
    axis = time_axis(1.1)
    tail = random.standard_normal((len(axis), 2)) * np.exp(-axis / 0.28)[:, None]
    tail = filtered(tail, "lowpass", 6000.0)
    tail /= np.sqrt(np.sum(tail ** 2, axis=0, keepdims=True))
    for side in range(2):
        bus[:, side] += wet * signal.fftconvolve(bus[:, side], tail[:, side])[: len(bus)]


# ---------------------------------------------------------------- arrangement


def music_choice(episode_id):
    """Return (key root in Hz, tempo in bpm) for an episode.

    Numbered episodes walk through the two lists, so no two of 25 episodes in a row share both and
    neighbours never share either. A hash of the name gave tempo 104 to all of ep01 to ep05.
    """
    number = re.search(r"(\d+)$", episode_id)
    index = int(number.group(1)) - 1 if number else zlib.crc32(episode_id.encode("utf-8"))
    root = KEY_ROOTS[index % len(KEY_ROOTS)]
    tempo = TEMPOS[(2 * index + index // len(KEY_ROOTS)) % len(TEMPOS)]
    return root, tempo


def build_music(total, check_start, end_start, episode_id):
    """Return (stereo music bus, stereo effects bus, settings). The first beat of a bar lands on the check."""
    seed = zlib.crc32(episode_id.encode("utf-8"))
    random = np.random.default_rng(seed)
    root, tempo = music_choice(episode_id)
    beat = 60.0 / tempo
    bar = 4 * beat
    music = np.zeros((seconds(total), 2))
    effects = np.zeros((seconds(total), 2))
    first_bar = check_start - bar * np.ceil(check_start / bar)
    bar_starts = np.arange(first_bar, total, bar)
    kick_sound, clap_sound = kick(), clap(random)

    for bar_index, bar_start in enumerate(bar_starts):
        chord_root = semitones(root, PROGRESSION[bar_index % len(PROGRESSION)])
        shape = CHORD_SHAPES[PROGRESSION[bar_index % len(PROGRESSION)]]
        if bar_start >= end_start:
            break
        driving = bar_start >= check_start - 1e-6
        for step in shape:
            note = pad_note(semitones(chord_root, 12 + step), bar + 0.6, 2.6 if driving else 1.5, random)
            place(music, note, bar_start, 0.09 if driving else 0.075)
        if not driving:
            place(music, bass_note(chord_root / 2, bar, pluck=False), bar_start, 0.30)
            for eighth in range(8):
                place(music, hat(random), bar_start + eighth * beat / 2, 0.035, pan=0.25)
            for quarter in range(4):
                place(music, pluck(semitones(chord_root, 24)), bar_start + quarter * beat, 0.05, pan=-0.3)
            continue
        for eighth in range(8):
            moment = bar_start + eighth * beat / 2
            place(music, bass_note(chord_root / 2, beat / 2, pluck=True), moment, 0.34 if eighth % 2 == 0 else 0.24)
            place(music, hat(random, open_hat=eighth == 7), moment, 0.07 if eighth % 2 else 0.045, pan=0.3)
            arp_step = shape[(eighth * 3) % len(shape)]
            arp = pluck(semitones(chord_root, 24 + arp_step))
            place(music, arp, moment, 0.085, pan=-0.45 if eighth % 2 else 0.45)
            place(music, arp, moment + 0.75 * beat, 0.035, pan=0.45 if eighth % 2 else -0.45)
        for quarter in range(4):
            place(music, kick_sound, bar_start + quarter * beat, 0.5 if quarter % 2 == 0 else 0.36)
        for quarter in (1, 3):
            place(music, clap_sound, bar_start + quarter * beat, 0.11)

    # Sign-off: one held home chord and a bell, no beat.
    for step in (0, 7, 12, 15, 19):
        place(music, pad_note(semitones(root, 12 + step), total - end_start + 0.2, 2.2, random), end_start, 0.085)
    place(music, bass_note(root / 2, total - end_start, pluck=False), end_start, 0.3)
    place(music, bell(semitones(root, 36)), end_start + 0.02, 0.1, pan=0.2)
    place(music, bell(semitones(root, 43)), end_start + 0.22, 0.07, pan=-0.2)
    add_room(music, random)

    # Effects that mark what happens on screen.
    place(effects, bell(1318.5, 0.9), 0.03, 0.2, pan=-0.15)  # message arrives
    place(effects, bell(1760.0, 0.9), 0.15, 0.16, pan=0.15)
    place(effects, whoosh(random), 0.0, 0.2)
    riser_length = min(1.7, check_start - 0.2)
    place(effects, riser(riser_length, random), check_start - riser_length, 0.2)
    place(effects, whoosh(random, 0.3), check_start - 0.3, 0.25)
    place(effects, impact(random), check_start, 0.55)
    place(effects, whoosh(random, 0.5), end_start - 0.25, 0.2)

    axis = np.arange(len(music)) / SAMPLE_RATE
    fade = np.clip(np.minimum(axis / 0.6, (total - axis) / 1.3), 0.0, 1.0)[:, None]
    return music * fade, effects * fade, {"tempo_bpm": tempo, "key_root_hz": root, "bars_start_s": round(first_bar, 3)}


# ---------------------------------------------------------------- mix and master


def measure_loudness(wav_path):
    """Integrated loudness (LUFS) and true peak (dBTP) of a file, measured by ffmpeg's EBU R128 meter."""
    result = subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-nostats", "-i", str(wav_path),
            "-af", "loudnorm=I=-14:TP=-1:LRA=11:print_format=json", "-f", "null", "-",
        ],
        capture_output=True,
        text=True,
        errors="replace",
    )
    measured = json.loads(re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", result.stderr).group(0))
    return float(measured["input_i"]), float(measured["input_tp"])


def write_wav(samples, path):
    """Write mono (n,) or stereo (n, 2) float samples as 16-bit PCM."""
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1 if samples.ndim == 1 else samples.shape[1])
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes((np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16).tobytes())


def fit_length(samples, length):
    """Cut or pad with silence, so the voice has exactly as many samples as the music."""
    if len(samples) >= length:
        return samples[:length]
    return np.concatenate([samples, np.zeros(length - len(samples), dtype=samples.dtype)])


def soft_limit(samples, ceiling=PEAK_CEILING):
    """Leave everything below 80% of the ceiling alone and round off what is above it."""
    knee = 0.8 * ceiling
    size = np.abs(samples)
    over = np.maximum(size - knee, 0.0)
    limited = np.where(size > knee, knee + (ceiling - knee) * np.tanh(over / (ceiling - knee)), size)
    return np.sign(samples) * limited


def mix_episode(voice, total, check_start, end_start, episode_id, wav_path):
    """Write the finished stereo mix to wav_path and return (mono fold-down, measurements)."""
    music, effects, settings = build_music(total, check_start, end_start, episode_id)
    polished = fit_length(polish_voice(voice), len(music))
    voice_level = follow_level(polished, 0.03, 0.32)
    speaking = voice_level > 0.25 * np.percentile(voice_level, 95)
    duck = 1.0 - DUCK_DEPTH * np.clip(voice_level / np.percentile(voice_level, 90), 0.0, 1.0)
    music *= duck[:, None]
    effects *= (1.0 - 0.35 * (1.0 - duck))[:, None]
    voice_rms = np.sqrt(np.mean(polished[speaking] ** 2))
    music_rms = np.sqrt(np.mean(music[speaking] ** 2))
    music *= voice_rms * 10.0 ** (MUSIC_UNDER_VOICE_DB / 20.0) / max(music_rms, 1e-9)
    impact_part = effects[seconds(check_start):][: seconds(0.5)]
    impact_rms = np.sqrt(np.mean(impact_part ** 2))
    effects *= voice_rms * 10.0 ** (EFFECTS_UNDER_VOICE_DB / 20.0) / max(impact_rms, 1e-9)

    mix = music + effects + polished[:, None]
    gain = 0.5
    ceiling = PEAK_CEILING
    for _ in range(8):
        finished = soft_limit(mix * gain, ceiling)
        write_wav(finished, wav_path)
        loudness, true_peak = measure_loudness(wav_path)
        loud_enough = abs(loudness - TARGET_LUFS) < 0.15
        peak_safe = true_peak <= TRUE_PEAK_LIMIT_DBTP
        if loud_enough and peak_safe:
            break
        if not peak_safe:
            ceiling *= 10.0 ** ((TRUE_PEAK_AIM_DBTP - true_peak) / 20.0)
        if not loud_enough:
            gain *= 10.0 ** ((TARGET_LUFS - loudness) / 20.0)
    measurements = {
        "loudness_lufs": round(loudness, 2),
        "true_peak_dbtp": round(true_peak, 2),
        "peak_ceiling": round(ceiling, 3),
        "music_under_voice_db": MUSIC_UNDER_VOICE_DB,
        "music_between_lines_db": round(
            20.0 * np.log10(np.sqrt(np.mean(music[~speaking] ** 2)) / np.sqrt(np.mean(music[speaking] ** 2))), 1
        ),
        "stereo": True,
        **settings,
    }
    return finished.mean(axis=1).astype(np.float32), measurements
