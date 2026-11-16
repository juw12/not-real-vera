"""Render one Vera Checks episode as a 1080x1920 short with voice, sound cues and live captions.

    python pipeline/make_episode.py ep01
    python pipeline/make_episode.py all

Presenter layer, first match wins: assets/presenter/<id>.mp4 (a talking-head clip made for that episode's own
voice track, played in sync), assets/presenter.mp4 (a generic looped clip), then a still filmed by a moving
camera (pipeline/camera.py). The still is that episode's own outfit picture, assets/outfits/<id>.jpg
(tools/outfits.py), or assets/vera.jpg when the episode has none. The metadata file records which one was used.

Text on the picture stays short: a caption of at most three words that appears word by word as each word
is spoken (pipeline/word_timing.py), one short chip, a short source credit and the sign-off. The scam's
wording is spoken, not shown, and the alert number and link live in the post caption.

On the still, her mouth follows the voice (pipeline/lipsync.py drives pipeline/face_rig.py), she blinks and
moves her head, and every spoken line is its own camera shot (pipeline/camera.py). The sound is mixed in
pipeline/sound.py. Caption timing and depth need the models fetched by tools/get_motion_models.py, and the
face needs assets/outfits/landmarks.json (tools/face_landmarks.py); without them the episode still renders,
with estimated caption timing, no depth, or a face that does not move.
"""
import argparse
import asyncio
import hashlib
import json
import math
import os
import subprocess
import sys
import wave
import zlib
from pathlib import Path

import cv2
import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFont

sys.path.insert(0, str(Path(__file__).resolve().parent))
import camera  # noqa: E402
import face_rig  # noqa: E402
import lipsync  # noqa: E402
import sound  # noqa: E402
import word_timing  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
OUTPUT = ROOT / "output"
WIDTH, HEIGHT, FPS = 1080, 1920, 30
SAMPLE_RATE = 48000
# Voice engine. "kokoro" runs fully on this PC (free, same voice every day, no network).
# "edge" uses Microsoft's online voices and needs a network that allows the websocket.
TTS_ENGINE = os.environ.get("VERA_TTS", "kokoro")
KOKORO_VOICE = "af_heart"
KOKORO_SPEED = 1.06
KOKORO_MODEL = ROOT / "models" / "kokoro-v1.0.int8.onnx"
KOKORO_VOICES = ROOT / "models" / "voices-v1.0.bin"
EDGE_VOICE = "en-US-AvaMultilingualNeural"
EDGE_RATE = "+8%"
LEAD_IN = 0.45
LINE_GAP = 0.20
TAIL = 1.1
MAX_CAPTION_WORDS = 3
CHIP_BOTTOM = 1300
CAPTION_CENTER_Y = 1420
SOURCE_LINE_Y = 1500
CAPTION_POP_SCALES = (1.16, 1.09, 1.04)  # the word being spoken starts this much larger, then settles
END_CARD_DARKENING = 0.4
SHADE_START_ROW = 1050.0
DEFAULT_HANDLE = "@verachecks"
FONT_FILES = [r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arialbd.ttf"]


def portrait_path_for(episode_id):
    """The still for one episode: its own outfit picture when there is one, otherwise the shared portrait."""
    outfit_still = ASSETS / "outfits" / f"{episode_id}.jpg"
    return outfit_still if outfit_still.exists() else ASSETS / "vera.jpg"


def load_font(size):
    for font_file in FONT_FILES:
        try:
            return ImageFont.truetype(font_file, size)
        except OSError:
            continue
    return ImageFont.load_default()


def hex_to_rgb(text):
    text = text.lstrip("#")
    return tuple(int(text[index:index + 2], 16) for index in (0, 2, 4))


# ---------------------------------------------------------------- audio


_kokoro = None


def voice_label():
    if TTS_ENGINE == "edge":
        return f"edge-tts {EDGE_VOICE} (online)"
    return f"kokoro-onnx {KOKORO_VOICE} (local, synthetic voice)"


def word_sounds():
    """Return a function word -> its sounds (IPA), from the voice engine's own phonemizer, or None.

    It runs on this PC. Without it the mouth still moves, from the letters and the loudness of the voice."""
    try:
        from kokoro_onnx.tokenizer import Tokenizer

        tokenizer = Tokenizer()
        tokenizer.phonemize("check", "en-us")
    except Exception:  # no phonemizer on this PC: lipsync falls back to letters
        return None
    return lambda word: tokenizer.phonemize(word, "en-us")


def speak_with_kokoro(text, wav_path):
    """Speak one line with the local Kokoro model. It gives no word timings; build_audio measures them."""
    global _kokoro
    if _kokoro is None:
        if not (KOKORO_MODEL.exists() and KOKORO_VOICES.exists()):
            raise SystemExit("Voice model is missing. Run: python tools/get_voice_model.py")
        from kokoro_onnx import Kokoro

        _kokoro = Kokoro(str(KOKORO_MODEL), str(KOKORO_VOICES))
    samples, sample_rate = _kokoro.create(text, voice=KOKORO_VOICE, speed=KOKORO_SPEED, lang="en-us")
    with wave.open(str(wav_path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(int(sample_rate))
        handle.writeframes((np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16).tobytes())
    return []


async def speak_with_edge(text, mp3_path):
    """Speak one line with edge-tts; return word boundaries as (start_s, length_s) when the service gives them."""
    import edge_tts

    options = {"rate": EDGE_RATE}
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if proxy:
        options["proxy"] = proxy
    try:
        communicate = edge_tts.Communicate(text, EDGE_VOICE, boundary="WordBoundary", **options)
    except TypeError:
        communicate = edge_tts.Communicate(text, EDGE_VOICE, **options)
    boundaries = []
    with open(mp3_path, "wb") as handle:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                handle.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                boundaries.append((chunk["offset"] / 1e7, chunk["duration"] / 1e7))
    return boundaries


def synthesize_line(text, work_dir, index):
    """Return (audio_path, word_boundaries) for one spoken line using the configured engine."""
    if TTS_ENGINE == "edge":
        path = work_dir / f"line{index:02d}.mp3"
        return path, asyncio.run(speak_with_edge(text, path))
    digest = hashlib.sha1(f"{KOKORO_VOICE}|{KOKORO_SPEED}|{text}".encode("utf-8")).hexdigest()[:10]
    path = work_dir / f"line{index:02d}_{digest}.wav"
    if not path.exists():
        speak_with_kokoro(text, path)
    return path, []


def decode_audio(path):
    result = subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(), "-v", "error", "-i", str(path),
            "-f", "s16le", "-ac", "1", "-ar", str(SAMPLE_RATE), "-",
        ],
        capture_output=True,
        check=True,
    )
    return np.frombuffer(result.stdout, dtype=np.int16).astype(np.float32) / 32768.0


def trim_tail(samples):
    """Drop trailing silence so the gaps between lines are the ones we choose."""
    loud = np.nonzero(np.abs(samples) > 0.012)[0]
    if loud.size == 0:
        return samples
    return samples[: min(len(samples), loud[-1] + int(0.06 * SAMPLE_RATE))]


def time_words(tokens, boundaries, duration):
    """Return (start, end) per token, from real word boundaries when they line up, else by word length."""
    if len(boundaries) == len(tokens):
        starts = [start for start, _ in boundaries]
    else:
        weights = [len(token) + 1 for token in tokens]
        total = float(sum(weights))
        starts = []
        elapsed = 0.0
        for weight in weights:
            starts.append(duration * elapsed / total)
            elapsed += weight
    spans = []
    for index, start in enumerate(starts):
        end = starts[index + 1] if index + 1 < len(starts) else duration
        spans.append((start, max(end, start + 0.05)))
    return spans


def add_at(track, clip, at_seconds, gain):
    start = int(at_seconds * SAMPLE_RATE)
    end = min(len(track), start + len(clip))
    if end > start:
        track[start:end] += clip[: end - start] * gain


def build_audio(narration, work_dir):
    """Synthesize every line, time its words, lay the lines on one voice track, and return the timeline."""
    lines = []
    clips = []
    cursor = LEAD_IN
    for index, text in enumerate(narration):
        audio_path, boundaries = synthesize_line(text, work_dir, index)
        samples = trim_tail(decode_audio(audio_path))
        duration = len(samples) / SAMPLE_RATE
        tokens = text.split()
        estimate = time_words(tokens, boundaries, duration)
        spans, timing, placed = estimate, "service" if len(boundaries) == len(tokens) else "estimated", []
        measured = None if timing == "service" else word_timing.align(tokens, samples, SAMPLE_RATE)
        if measured is not None:
            spans, placed = measured
            timing = "aligned"
        lines.append(
            {
                "text": text,
                "start": cursor,
                "end": cursor + duration,
                "words": [(token, cursor + start, cursor + end) for token, (start, end) in zip(tokens, spans)],
                "word_timing": timing,
                "placed": placed,
                # How far the old word-length guess was from the measured start of each word that was heard.
                "guess_errors": [abs(estimate[index][0] - spans[index][0]) for index, heard in enumerate(placed) if heard],
            }
        )
        clips.append((cursor, samples))
        cursor += duration + LINE_GAP
    total = cursor - LINE_GAP + TAIL
    track = np.zeros(int(total * SAMPLE_RATE), dtype=np.float32)
    voice_peak = max(float(np.max(np.abs(samples))) for _, samples in clips) or 1.0
    for start, samples in clips:
        add_at(track, samples, start, 0.88 / voice_peak)
    return lines, track, total


def caption_sync_report(lines):
    """How the caption words were timed, for the episode's metadata file."""
    placed = [heard for line in lines for heard in line["placed"]]
    errors = [error for line in lines for error in line["guess_errors"]]
    words = sum(len(line["words"]) for line in lines)
    return {
        "words": words,
        "words_timed_from_the_voice": int(sum(placed)),
        "words_spaced_between_neighbours": words - int(sum(placed)),
        "old_guess_mean_error_s": round(float(np.mean(errors)), 3) if errors else None,
        "old_guess_max_error_s": round(float(np.max(errors)), 3) if errors else None,
    }


# ---------------------------------------------------------------- picture layers


def render_pill(text, fill, text_fill, size=32):
    font = load_font(size)
    text_width = int(font.getlength(text))
    image = Image.new("RGBA", (text_width + 52, size + 30), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, image.width - 1, image.height - 1), radius=image.height // 2, fill=fill)
    draw.text((26, 11), text, font=font, fill=text_fill)
    return np.asarray(image)


def render_chip(text, accent, highlight=False):
    """One short line in a pill: the scam in a few words (dark), or what to do about it (accent colour)."""
    if highlight:
        return render_pill(text, accent + (246,), (14, 14, 18, 255), size=54)
    return render_pill(text, (16, 18, 26, 236), (255, 255, 255, 255), size=54)


def render_caption(tokens, spoken, pop_scale, accent):
    """The caption for one chunk with only its first `spoken` words drawn. Every word keeps its place, so
    nothing shifts when the next word appears. The newest word is in the accent colour, pop_scale times larger."""
    size = 94
    font = load_font(size)
    while size > 56 and font.getlength(" ".join(tokens)) > 940:
        size -= 6
        font = load_font(size)
    space = font.getlength(" ")
    widths = [font.getlength(token) for token in tokens]
    total = sum(widths) + space * (len(tokens) - 1)
    margin = 70
    image = Image.new("RGBA", (int(total) + 2 * margin, size + 2 * margin), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    x = float(margin)
    for index, token in enumerate(tokens[:spoken]):
        newest = index == spoken - 1
        word_font = load_font(round(size * pop_scale)) if newest and pop_scale != 1.0 else font
        draw.text(
            (x + widths[index] / 2, image.height / 2),
            token,
            font=word_font,
            fill=accent + (255,) if newest else (255, 255, 255, 255),
            anchor="mm",
            stroke_width=9,
            stroke_fill=(8, 8, 12, 255),
        )
        x += widths[index] + space
    return np.asarray(image)


def render_text_line(text, size, fill, max_width=980):
    font = load_font(size)
    while size > 22 and font.getlength(text) > max_width:
        size -= 2
        font = load_font(size)
    image = Image.new("RGBA", (int(font.getlength(text)) + 24, size + 24), (0, 0, 0, 0))
    ImageDraw.Draw(image).text((12, 8), text, font=font, fill=fill, stroke_width=3, stroke_fill=(8, 8, 12, 230))
    return np.asarray(image)


def signoff_parts(signoff):
    return [part.strip() + "." for part in signoff.split(".") if part.strip()]


def render_end_card(signoff, handle, source_credit, accent):
    """Return ([(layer, y) per sign-off sentence], footer layer, footer y). The renderer shows each sentence
    when she starts saying it."""
    big = load_font(104)
    parts = signoff_parts(signoff)
    layers = []
    for index, part in enumerate(parts):
        image = Image.new("RGBA", (WIDTH, 136), (0, 0, 0, 0))
        fill = accent + (255,) if index == len(parts) - 1 else (255, 255, 255, 255)
        ImageDraw.Draw(image).text(
            (WIDTH // 2, 68), part, font=big, fill=fill, anchor="mm", stroke_width=6, stroke_fill=(8, 8, 12, 255)
        )
        layers.append((np.asarray(image), 136 * index))
    footer = Image.new("RGBA", (WIDTH, 190), (0, 0, 0, 0))
    draw = ImageDraw.Draw(footer)
    draw.text((WIDTH // 2, 60), handle, font=load_font(56), fill=(255, 255, 255, 255), anchor="mm")
    draw.text((WIDTH // 2, 140), source_credit, font=load_font(32), fill=(200, 206, 220, 255), anchor="mm")
    return layers, np.asarray(footer), 136 * len(parts) + 10


def overlay(frame, layer, x, y, opacity=1.0):
    """Alpha-blend an RGBA layer onto the RGB frame, clipped to the frame."""
    if opacity <= 0.0:
        return
    height, width = layer.shape[:2]
    x, y = int(round(x)), int(round(y))
    left, top = max(x, 0), max(y, 0)
    right, bottom = min(x + width, WIDTH), min(y + height, HEIGHT)
    if left >= right or top >= bottom:
        return
    part = layer[top - y:bottom - y, left - x:right - x]
    alpha = part[..., 3:4].astype(np.float32) * (opacity / 255.0)
    region = frame[top:bottom, left:right].astype(np.float32)
    frame[top:bottom, left:right] = (region * (1.0 - alpha) + part[..., :3].astype(np.float32) * alpha).astype(np.uint8)


def ease_out(progress):
    progress = min(max(progress, 0.0), 1.0)
    return 1.0 - (1.0 - progress) ** 3


class Presenter:
    """The presenter layer.

    Order of preference:
    1. assets/presenter/<episode id>.mp4: a talking clip made from that episode's voice track
       (tools/presenter_kit.py). It is played once, locked to the timeline, so the lips match the audio.
    2. assets/presenter.mp4: one generic clip, looped (no lip-sync to the words).
    3. The still, filmed by a moving camera with depth parallax (pipeline/camera.py), with her mouth,
       eyelids, eyebrows and head moving (pipeline/face_rig.py): assets/outfits/<episode id>.jpg, else
       assets/vera.jpg.
    """

    def __init__(self, episode_id):
        self.capture = None
        self.synced = False
        self.clip_fps = float(FPS)
        self.clip_index = -1
        self.last_frame = None
        episode_clip = ASSETS / "presenter" / f"{episode_id}.mp4"
        generic_clip = ASSETS / "presenter.mp4"
        if episode_clip.exists():
            self.capture = cv2.VideoCapture(str(episode_clip))
            self.clip_fps = self.capture.get(cv2.CAP_PROP_FPS) or 25.0
            self.synced = True
            self.mode = f"lip-synced presenter clip (assets/presenter/{episode_id}.mp4)"
        elif generic_clip.exists():
            self.capture = cv2.VideoCapture(str(generic_clip))
            self.mode = "looped presenter video without lip-sync (assets/presenter.mp4)"
        portrait_path = portrait_path_for(episode_id)
        if not portrait_path.exists():
            raise SystemExit("assets/vera.jpg is missing. Run: python pipeline/make_portrait.py")
        self.still = portrait_path.relative_to(ROOT).as_posix()
        picture = np.asarray(Image.open(portrait_path).convert("RGB"))
        self.portrait = self.fit(picture)
        self.rig = None
        if self.capture is None:
            self.rig = camera.StillRig(
                self.portrait,
                self.face_box(portrait_path, picture.shape),
                self.face_points(portrait_path, picture.shape),
            )
            self.mode = self.rig.describe()
        rows = np.arange(HEIGHT, dtype=np.float32)
        top = np.clip(0.72 + 0.28 * rows / 300.0, 0.0, 1.0)
        bottom = np.clip(1.0 - 0.88 * (rows - SHADE_START_ROW) / 500.0, 0.12, 1.0)
        self.shade = np.minimum(top, bottom).reshape(HEIGHT, 1, 1)

    @staticmethod
    def face_box(portrait_path, picture_shape):
        """Her face in frame pixels, from the wardrobe record (tools/outfits.py), or None when not recorded."""
        record_path = portrait_path.parent / "outfits.json"
        if not record_path.exists():
            return None
        face = json.loads(record_path.read_text(encoding="utf-8")).get("face")
        if not face:
            return None
        scale = max(WIDTH / picture_shape[1], HEIGHT / picture_shape[0])
        left = (picture_shape[1] * scale - WIDTH) / 2
        top = (picture_shape[0] * scale - HEIGHT) / 2
        return (
            face["center"][0] * scale - left,
            face["center"][1] * scale - top,
            face["half_width"] * scale,
            face["half_height"] * scale,
        )

    @staticmethod
    def face_points(portrait_path, picture_shape):
        """Her 98 face landmarks in frame pixels (tools/face_landmarks.py), or None when not recorded for
        this picture at this size."""
        record_path = ASSETS / "outfits" / "landmarks.json"
        if not record_path.exists():
            return None
        key = portrait_path.stem if portrait_path.parent.name == "outfits" else "base"
        record = json.loads(record_path.read_text(encoding="utf-8")).get(key)
        if not record or list(record["picture_size"]) != [picture_shape[1], picture_shape[0]]:
            return None
        # The same enlargement and centre crop as fit().
        scale = max(WIDTH / picture_shape[1], HEIGHT / picture_shape[0])
        fitted_width = math.ceil(picture_shape[1] * scale)
        fitted_height = math.ceil(picture_shape[0] * scale)
        points = np.asarray(record["points"], dtype=np.float64)
        x = (points[:, 0] + 0.5) * fitted_width / picture_shape[1] - 0.5 - (fitted_width - WIDTH) // 2
        y = (points[:, 1] + 0.5) * fitted_height / picture_shape[0] - 0.5 - (fitted_height - HEIGHT) // 2
        return np.stack([x, y], axis=1)

    @property
    def face_moves(self):
        return self.rig is not None and self.rig.face_rig is not None

    @staticmethod
    def fit(frame):
        """Scale and centre-crop a frame so it covers the whole 1080x1920 picture."""
        scale = max(WIDTH / frame.shape[1], HEIGHT / frame.shape[0])
        size = (math.ceil(frame.shape[1] * scale), math.ceil(frame.shape[0] * scale))
        frame = cv2.resize(frame, size, interpolation=cv2.INTER_LANCZOS4)
        left = (frame.shape[1] - WIDTH) // 2
        top = (frame.shape[0] - HEIGHT) // 2
        return frame[top:top + HEIGHT, left:left + WIDTH]

    def read(self):
        ok, frame = self.capture.read()
        if not ok:
            return None
        return self.fit(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))

    def source_frame(self, time_s):
        if self.capture is None:
            return self.portrait
        if self.synced:
            # Advance the clip to the frame that belongs to this moment; hold the last one when it ends.
            target = int(time_s * self.clip_fps)
            while self.clip_index < target:
                frame = self.read()
                if frame is None:
                    break
                self.last_frame = frame
                self.clip_index += 1
            return self.last_frame if self.last_frame is not None else self.portrait
        frame = self.read()
        if frame is None:
            self.capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            frame = self.read()
        return frame if frame is not None else self.portrait

    def frame(self, time_s, frame_index, path, face=None):
        """face: (mouth_open, mouth_wide, blink, brow) for this frame; used only by the still."""
        if self.rig is not None:
            moved = self.rig.frame(path, frame_index, face)
        else:
            moved = camera.move_clip_frame(self.source_frame(time_s), path, frame_index)
        return (moved.astype(np.float32) * self.shade).astype(np.uint8)


# ---------------------------------------------------------------- episode


def caption_chunks(lines):
    """Split every spoken line into chunks of at most MAX_CAPTION_WORDS words, breaking at punctuation."""
    chunks = []
    for line in lines:
        current = []
        for word in line["words"]:
            current.append(word)
            if len(current) == MAX_CAPTION_WORDS or word[0][-1] in ".,?!:;":
                chunks.append(current)
                current = []
        if current:
            chunks.append(current)
    return chunks


def find_check_line(episode):
    if "check_from" in episode:
        return int(episode["check_from"])
    for index, text in enumerate(episode["narration"]):
        if "check" in text.lower():
            return index
    return len(episode["narration"]) // 2


def on_screen_text(episode, signoff, handle, source_credit, chunks):
    """Every piece of text the episode draws on the picture, with its longest item, for the metadata file."""
    items = [episode["pillar"].upper(), episode["chip"], episode["check_chip"], source_credit]
    items += signoff_parts(signoff) + [handle]
    captions = [" ".join(word[0] for word in chunk) for chunk in chunks]
    return {
        "items": items,
        "max_characters": max(len(item) for item in items),
        "max_words": max(len(item.split()) for item in items),
        "captions_appear_word_by_word": True,
        "max_words_per_caption": max(len(chunk) for chunk in chunks),
        "longest_caption_characters": max(len(caption) for caption in captions),
    }


def render_episode(episode, signoff, handle=DEFAULT_HANDLE):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    work_dir = OUTPUT / "_work" / episode["id"]
    work_dir.mkdir(parents=True, exist_ok=True)
    accent = hex_to_rgb(episode["accent"])
    seed = zlib.crc32(episode["id"].encode("utf-8"))

    lines, voice, total = build_audio(episode["narration"], work_dir)
    check_start = lines[find_check_line(episode)]["start"]
    end_start = lines[-1]["start"]
    line_starts = [line["start"] for line in lines]
    total_frames = int(total * FPS)
    # The voice alone, on the episode's timeline: the mouth is driven from it, and a presenter clip is
    # generated from it.
    sound.write_wav(voice, work_dir / "voice.wav")
    wav_path = work_dir / "audio.wav"
    track, sound_report = sound.mix_episode(voice, total, check_start, end_start, episode["id"], wav_path)

    presenter = Presenter(episode["id"])
    phonemize = word_sounds() if presenter.face_moves else None
    mouth_open, mouth_wide, speech = lipsync.mouth_track(lines, voice, SAMPLE_RATE, FPS, total_frames, phonemize)
    question_ends = [line["end"] for line in lines if line["text"].rstrip().endswith("?")]
    blink, brow, blink_count = face_rig.expression_track(total_frames, FPS, line_starts, question_ends, seed)
    camera_path = camera.CameraPath(total_frames, FPS, line_starts, check_start, seed, speech, end_start)

    source_credit = "Source: " + episode["source"]["short"]
    pillar = render_pill(episode["pillar"].upper(), accent + (240,), (12, 12, 16, 255), size=30)
    chip = render_chip(episode["chip"], accent)
    check_chip = render_chip(episode["check_chip"], accent, highlight=True)
    source_line = render_text_line(source_credit, 30, (214, 220, 232, 255))
    end_parts, end_footer, end_footer_y = render_end_card(signoff, handle, source_credit, accent)
    # Each sentence of the sign-off appears when she starts saying it.
    end_words = lines[-1]["words"]
    part_starts = []
    word_index = 0
    for part in signoff_parts(signoff):
        part_starts.append(end_words[min(word_index, len(end_words) - 1)][1])
        word_index += len(part.split())
    chunks = caption_chunks(lines[:-1])
    caption_cache = {}

    video_path = OUTPUT / f"{episode['id']}.mp4"
    encoder = subprocess.Popen(
        [
            imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-v", "error",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS), "-i", "-",
            "-i", str(wav_path),
            "-c:v", "libx264", "-preset", "fast", "-crf", "19", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", str(video_path),
        ],
        stdin=subprocess.PIPE,
    )
    sheet_times = [1.2, (lines[2]["start"] + check_start) / 2, check_start + 1.6, end_start + 1.0]
    sheet_frames = {int(moment * FPS): None for moment in sheet_times}
    meter = camera.MotionMeter()

    for frame_index in range(total_frames):
        time_s = frame_index / FPS
        face = (mouth_open[frame_index], mouth_wide[frame_index], blink[frame_index], brow[frame_index])
        frame = presenter.frame(time_s, frame_index, camera_path, face)
        overlay(frame, pillar, 44, 150)

        if time_s < check_start:
            appear = ease_out((time_s - 0.05) / 0.3)
            leave = 1.0 - ease_out((time_s - (check_start - 0.2)) / 0.2)
            chip_y = CHIP_BOTTOM - chip.shape[0] + (1.0 - appear) * 60
            overlay(frame, chip, (WIDTH - chip.shape[1]) // 2, chip_y, appear * leave)
        elif time_s < end_start:
            appear = ease_out((time_s - check_start) / 0.3)
            chip_y = CHIP_BOTTOM - check_chip.shape[0] + (1.0 - appear) * 60
            overlay(frame, check_chip, (WIDTH - check_chip.shape[1]) // 2, chip_y, appear)

        if time_s < end_start:
            for chunk_index, chunk in enumerate(chunks):
                chunk_end = chunks[chunk_index + 1][0][1] if chunk_index + 1 < len(chunks) else end_start
                if chunk[0][1] <= time_s < min(chunk_end, chunk[-1][2] + 0.6):
                    # Live caption: only the words she has started to say, the newest one popping in.
                    spoken = sum(1 for _, word_start, _ in chunk if time_s >= word_start)
                    since_word = int((time_s - chunk[spoken - 1][1]) * FPS + 1e-6)
                    pop = CAPTION_POP_SCALES[since_word] if since_word < len(CAPTION_POP_SCALES) else 1.0
                    key = (chunk_index, spoken, pop)
                    if key not in caption_cache:
                        caption_cache[key] = render_caption([word[0] for word in chunk], spoken, pop, accent)
                    caption = caption_cache[key]
                    overlay(frame, caption, (WIDTH - caption.shape[1]) // 2, CAPTION_CENTER_Y - caption.shape[0] // 2)
                    break
            overlay(frame, source_line, (WIDTH - source_line.shape[1]) // 2, SOURCE_LINE_Y)
        else:
            reveal = ease_out((time_s - end_start) / 0.4)
            frame[:] = (frame.astype(np.float32) * (1.0 - END_CARD_DARKENING * reveal)).astype(np.uint8)
            for (layer, layer_y), part_start in zip(end_parts, part_starts):
                overlay(frame, layer, 0, 1000 + layer_y, ease_out((time_s - part_start) / 0.2))
            overlay(frame, end_footer, 0, 1000 + end_footer_y, reveal)

        bar_width = int(WIDTH * (frame_index + 1) / total_frames)
        frame[HEIGHT - 10:HEIGHT, :bar_width] = accent
        meter.add(frame)
        if frame_index in sheet_frames:
            sheet_frames[frame_index] = frame.copy()
        encoder.stdin.write(frame.tobytes())

    encoder.stdin.close()
    if encoder.wait() != 0:
        raise SystemExit("ffmpeg failed while encoding")

    sheet = Image.new("RGB", (540 * len(sheet_frames), 960))
    for position, frame_index in enumerate(sorted(sheet_frames)):
        if sheet_frames[frame_index] is not None:
            sheet.paste(Image.fromarray(sheet_frames[frame_index]).resize((540, 960)), (540 * position, 0))
    sheet_path = OUTPUT / f"{episode['id']}_sheet.jpg"
    sheet.save(sheet_path, quality=86)

    probe = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-i", str(video_path)], capture_output=True, text=True, errors="replace"
    ).stderr
    uses_outfit_still = presenter.still.startswith("assets/outfits/")
    portrait_record = {} if uses_outfit_still else json.loads(
        (ASSETS / "vera.source.json").read_text(encoding="utf-8")
    )
    if presenter.face_moves:
        lip_sync = {
            "method": "rule-based mouth shapes from the words' sounds and the loudness of the voice, drawn by "
            "warping the still (pipeline/lipsync.py, pipeline/face_rig.py); not a neural talking-head model",
            "sounds_from": "the voice engine's phonemizer" if phonemize is not None else "letters (no phonemizer)",
            **lipsync.sync_report(mouth_open, speech, FPS),
            "face": presenter.rig.face_rig.notes,
        }
    elif presenter.synced:
        lip_sync = {"method": "presenter clip generated from this episode's voice track"}
    else:
        lip_sync = {"method": "none"}
    report = {
        "id": episode["id"],
        "title": episode["title"],
        "file": video_path.name,
        "duration_s": round(total, 2),
        "size_mb": round(video_path.stat().st_size / 1e6, 2),
        "has_video_stream": "Video: h264" in probe,
        "has_audio_stream": "Audio: aac" in probe,
        "audio_rms": round(float(np.sqrt(np.mean(track ** 2))), 4),
        "spoken_words": sum(len(line["words"]) for line in lines),
        "caption_chunks": len(chunks),
        "max_words_per_caption": max(len(chunk) for chunk in chunks),
        "word_timing": sorted({line["word_timing"] for line in lines}),
        "caption_sync": caption_sync_report(lines),
        "on_screen_text": on_screen_text(episode, signoff, handle, source_credit, chunks),
        "lip_sync": lip_sync,
        "blinks": blink_count if presenter.face_moves else 0,
        "picture_motion": meter.report(FPS),
        "sound": sound_report,
        "camera": camera_path.smoothness(WIDTH, HEIGHT),
        "voice": voice_label(),
        "presenter": presenter.mode,
        "still": presenter.still,
        "portrait_is_placeholder": bool(portrait_record.get("placeholder")),
        "source": episode["source"],
    }
    (OUTPUT / f"{episode['id']}.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description="Render Vera Checks episodes")
    parser.add_argument("episode", help="episode id such as ep01, or 'all'")
    arguments = parser.parse_args()
    data = json.loads((ROOT / "episodes.json").read_text(encoding="utf-8"))
    selected = [item for item in data["episodes"] if arguments.episode in ("all", item["id"])]
    if not selected:
        raise SystemExit(f"no episode named {arguments.episode}")
    for episode in selected:
        render_episode(episode, data["signoff"], data.get("handle", DEFAULT_HANDLE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
