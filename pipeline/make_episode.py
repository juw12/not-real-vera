"""Render one Not Real Vera episode as a 1080x1920 short with voice, sound cues and short captions.

    python pipeline/make_episode.py ep01
    python pipeline/make_episode.py all

Presenter layer: if assets/presenter.mp4 exists (a lip-synced clip from any talking-head tool) it is used as the
moving background. Without it the presenter is a still AI portrait with camera motion, and the metadata says so.
"""
import argparse
import asyncio
import json
import math
import os
import subprocess
import sys
import wave
from pathlib import Path

import cv2
import imageio_ffmpeg
import numpy as np
from PIL import Image, ImageDraw, ImageFont

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
CARD_BOTTOM = 1250
CAPTION_CENTER_Y = 1370
HANDLE = "@notrealvera"
FONT_FILES = [r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arialbd.ttf"]


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


def speak_with_kokoro(text, wav_path):
    """Speak one line with the local Kokoro model. It gives no word timings, so captions use estimates."""
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
    path = work_dir / f"line{index:02d}.wav"
    return path, speak_with_kokoro(text, path)


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


def tone(frequency, length, decay):
    time_axis = np.arange(int(length * SAMPLE_RATE)) / SAMPLE_RATE
    return np.sin(2 * np.pi * frequency * time_axis) * np.exp(-time_axis / decay)


def add_at(track, sound, at_seconds, gain):
    start = int(at_seconds * SAMPLE_RATE)
    end = min(len(track), start + len(sound))
    if end > start:
        track[start:end] += sound[: end - start] * gain


def build_audio(narration, work_dir):
    """Synthesize every line, lay them on one track with sound cues, and return the timeline."""
    lines = []
    clips = []
    cursor = LEAD_IN
    for index, text in enumerate(narration):
        audio_path, boundaries = synthesize_line(text, work_dir, index)
        samples = trim_tail(decode_audio(audio_path))
        duration = len(samples) / SAMPLE_RATE
        tokens = text.split()
        spans = time_words(tokens, boundaries, duration)
        lines.append(
            {
                "text": text,
                "start": cursor,
                "end": cursor + duration,
                "words": [(token, cursor + start, cursor + end) for token, (start, end) in zip(tokens, spans)],
                "word_timing": "service" if len(boundaries) == len(tokens) else "estimated",
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


def add_sound_design(track, total, check_start, end_start):
    """Notification ding on the hook, a rising cue on the check, a soft low bed under everything."""
    add_at(track, tone(880, 0.5, 0.11) + 0.6 * tone(1320, 0.5, 0.09), 0.02, 0.22)
    add_at(track, tone(660, 0.25, 0.07), check_start - 0.16, 0.16)
    add_at(track, tone(990, 0.45, 0.12), check_start - 0.04, 0.16)
    add_at(track, tone(440, 0.9, 0.3) + 0.5 * tone(660, 0.9, 0.3), end_start, 0.10)
    time_axis = np.arange(len(track)) / SAMPLE_RATE
    bed = np.sin(2 * np.pi * 98.0 * time_axis) + 0.6 * np.sin(2 * np.pi * 146.8 * time_axis)
    bed *= 0.5 + 0.5 * np.sin(2 * np.pi * time_axis / 6.0)
    fade = np.clip(np.minimum(time_axis / 1.5, (total - time_axis) / 1.5), 0.0, 1.0)
    track += (bed * fade * 0.014).astype(np.float32)
    np.clip(track, -0.98, 0.98, out=track)


def write_wav(track, path):
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(SAMPLE_RATE)
        handle.writeframes((track * 32767).astype(np.int16).tobytes())


# ---------------------------------------------------------------- picture layers


def wrap_text(text, font, max_width):
    lines = []
    current = ""
    for word in text.split():
        candidate = (current + " " + word).strip()
        if font.getlength(candidate) <= max_width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def render_card(header, body, accent, highlight=False):
    """A message card (dark) or the 10-second check card (accent colour)."""
    width = 968
    padding = 44
    header_font = load_font(34)
    body_font = load_font(58 if highlight else 48)
    body_lines = wrap_text(body, body_font, width - 2 * padding)
    line_height = int(body_font.size * 1.26)
    height = padding + 46 + 22 + line_height * len(body_lines) + padding
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    if highlight:
        draw.rounded_rectangle((0, 0, width - 1, height - 1), radius=46, fill=accent + (246,))
        text_fill = (14, 14, 18, 255)
        header_fill = (14, 14, 18, 215)
        dot_fill = (14, 14, 18, 255)
    else:
        draw.rounded_rectangle(
            (0, 0, width - 1, height - 1), radius=46, fill=(16, 18, 26, 236), outline=accent + (255,), width=3
        )
        text_fill = (255, 255, 255, 255)
        header_fill = (186, 192, 208, 255)
        dot_fill = accent + (255,)
    draw.ellipse((padding, padding + 8, padding + 28, padding + 36), fill=dot_fill)
    draw.text((padding + 44, padding), header, font=header_font, fill=header_fill)
    y = padding + 46 + 22
    for line in body_lines:
        draw.text((padding, y), line, font=body_font, fill=text_fill)
        y += line_height
    return np.asarray(image)


def render_pill(text, fill, text_fill, size=32):
    font = load_font(size)
    text_width = int(font.getlength(text))
    image = Image.new("RGBA", (text_width + 52, size + 30), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, image.width - 1, image.height - 1), radius=image.height // 2, fill=fill)
    draw.text((26, 11), text, font=font, fill=text_fill)
    return np.asarray(image)


def render_caption(tokens, active_index, accent):
    size = 94
    font = load_font(size)
    while size > 56 and font.getlength(" ".join(tokens)) > 960:
        size -= 6
        font = load_font(size)
    space = font.getlength(" ")
    widths = [font.getlength(token) for token in tokens]
    total = sum(widths) + space * (len(tokens) - 1)
    image = Image.new("RGBA", (int(total) + 80, size + 80), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    x = 40.0
    for index, token in enumerate(tokens):
        fill = accent + (255,) if index == active_index else (255, 255, 255, 255)
        draw.text((x, 30), token, font=font, fill=fill, stroke_width=9, stroke_fill=(8, 8, 12, 255))
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


def render_end_card(signoff, source_name, accent):
    image = Image.new("RGBA", (WIDTH, 760), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    big = load_font(104)
    parts = [part.strip() + "." for part in signoff.split(".") if part.strip()]
    y = 0
    for index, part in enumerate(parts):
        fill = accent + (255,) if index == len(parts) - 1 else (255, 255, 255, 255)
        draw.text((WIDTH // 2, y + 60), part, font=big, fill=fill, anchor="mm", stroke_width=6, stroke_fill=(8, 8, 12, 255))
        y += 136
    draw.text((WIDTH // 2, y + 70), HANDLE, font=load_font(56), fill=(255, 255, 255, 255), anchor="mm")
    draw.text((WIDTH // 2, y + 150), "AI-generated host. Advice from the source below.", font=load_font(32), fill=(200, 206, 220, 255), anchor="mm")
    source_font = load_font(30)
    for row, line in enumerate(wrap_text("Source: " + source_name, source_font, 940)[:3]):
        draw.text((WIDTH // 2, y + 220 + row * 42), line, font=source_font, fill=(200, 206, 220, 255), anchor="mm")
    return np.asarray(image)


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
    """The moving presenter layer: a lip-synced clip when supplied, otherwise the still portrait with motion."""

    def __init__(self):
        self.capture = None
        clip = ASSETS / "presenter.mp4"
        if clip.exists():
            self.capture = cv2.VideoCapture(str(clip))
            self.mode = "presenter video (assets/presenter.mp4)"
        else:
            self.mode = "still AI portrait with camera motion (no lip-sync)"
        portrait_path = ASSETS / "vera.jpg"
        if not portrait_path.exists():
            raise SystemExit("assets/vera.jpg is missing. Run: python pipeline/make_portrait.py")
        self.portrait = np.asarray(Image.open(portrait_path).convert("RGB").resize((WIDTH, HEIGHT), Image.LANCZOS))
        rows = np.arange(HEIGHT, dtype=np.float32)
        top = np.clip(0.72 + 0.28 * rows / 300.0, 0.0, 1.0)
        bottom = np.clip(1.0 - 0.62 * (rows - 820.0) / (HEIGHT - 820.0), 0.36, 1.0)
        self.shade = np.minimum(top, bottom).reshape(HEIGHT, 1, 1)

    def source_frame(self):
        if self.capture is None:
            return self.portrait
        ok, frame = self.capture.read()
        if not ok:
            self.capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, frame = self.capture.read()
        if not ok:
            return self.portrait
        frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        scale = max(WIDTH / frame.shape[1], HEIGHT / frame.shape[0])
        frame = cv2.resize(frame, (math.ceil(frame.shape[1] * scale), math.ceil(frame.shape[0] * scale)))
        left = (frame.shape[1] - WIDTH) // 2
        top = (frame.shape[0] - HEIGHT) // 2
        return frame[top:top + HEIGHT, left:left + WIDTH]

    def frame(self, time_s, punch):
        zoom = 1.05 + 0.02 * math.sin(2 * math.pi * time_s / 11.0) + punch
        center_x = WIDTH / 2 + 14 * math.sin(2 * math.pi * time_s / 17.0)
        center_y = HEIGHT * 0.36
        matrix = np.float32([[zoom, 0, (1 - zoom) * center_x], [0, zoom, (1 - zoom) * center_y]])
        moved = cv2.warpAffine(
            self.source_frame(), matrix, (WIDTH, HEIGHT), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT
        )
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


def punch_at(time_s, lines):
    """Alternate a small punch-in per spoken line, eased over 0.2 s, so the shot never sits still."""
    index = 0
    for line_index, line in enumerate(lines):
        if time_s >= line["start"]:
            index = line_index
    target = 0.07 if index % 2 else 0.0
    previous = 0.07 if (index - 1) % 2 and index > 0 else 0.0
    return previous + (target - previous) * ease_out((time_s - lines[index]["start"]) / 0.2)


def render_episode(episode, signoff):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    work_dir = OUTPUT / "_work" / episode["id"]
    work_dir.mkdir(parents=True, exist_ok=True)
    accent = hex_to_rgb(episode["accent"])

    lines, track, total = build_audio(episode["narration"], work_dir)
    check_start = lines[find_check_line(episode)]["start"]
    end_start = lines[-1]["start"]
    add_sound_design(track, total, check_start, end_start)
    wav_path = work_dir / "audio.wav"
    write_wav(track, wav_path)

    presenter = Presenter()
    scam_card = render_card(episode["card"]["sender"], episode["card"]["text"], accent)
    check_card = render_card("THE 10-SECOND CHECK", episode["check"], accent, highlight=True)
    badge = render_pill("AI HOST  ·  NOT A REAL PERSON", (12, 12, 16, 215), (255, 255, 255, 255))
    pillar = render_pill(episode["pillar"].upper(), accent + (240,), (12, 12, 16, 255), size=30)
    source_line = render_text_line("Source: " + episode["source"]["name"], 28, (214, 220, 232, 255))
    end_card = render_end_card(signoff, episode["source"]["name"], accent)
    chunks = caption_chunks(lines[:-1])
    caption_cache = {}

    video_path = OUTPUT / f"{episode['id']}.mp4"
    encoder = subprocess.Popen(
        [
            imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-v", "error",
            "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{WIDTH}x{HEIGHT}", "-r", str(FPS), "-i", "-",
            "-i", str(wav_path),
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", "-shortest", str(video_path),
        ],
        stdin=subprocess.PIPE,
    )
    total_frames = int(total * FPS)
    sheet_times = [1.2, (lines[2]["start"] + check_start) / 2, check_start + 1.6, end_start + 1.0]
    sheet_frames = {int(moment * FPS): None for moment in sheet_times}

    for frame_index in range(total_frames):
        time_s = frame_index / FPS
        frame = presenter.frame(time_s, punch_at(time_s, lines))
        overlay(frame, badge, 44, 150)
        overlay(frame, pillar, 44, 232)

        if time_s < check_start:
            appear = ease_out((time_s - 0.05) / 0.35)
            leave = 1.0 - ease_out((time_s - (check_start - 0.25)) / 0.25)
            card_y = CARD_BOTTOM - scam_card.shape[0] + (1.0 - appear) * 90
            overlay(frame, scam_card, (WIDTH - scam_card.shape[1]) // 2, card_y, appear * leave)
        elif time_s < end_start:
            appear = ease_out((time_s - check_start) / 0.35)
            card_y = CARD_BOTTOM - check_card.shape[0] + (1.0 - appear) * 90
            overlay(frame, check_card, (WIDTH - check_card.shape[1]) // 2, card_y, appear)

        if time_s < end_start:
            for chunk_index, chunk in enumerate(chunks):
                chunk_end = chunks[chunk_index + 1][0][1] if chunk_index + 1 < len(chunks) else end_start
                if chunk[0][1] <= time_s < min(chunk_end, chunk[-1][2] + 0.6):
                    active = 0
                    for word_index, (_, word_start, _) in enumerate(chunk):
                        if time_s >= word_start:
                            active = word_index
                    key = (chunk_index, active)
                    if key not in caption_cache:
                        caption_cache[key] = render_caption([word[0] for word in chunk], active, accent)
                    caption = caption_cache[key]
                    overlay(frame, caption, (WIDTH - caption.shape[1]) // 2, CAPTION_CENTER_Y - caption.shape[0] // 2)
                    break
            overlay(frame, source_line, (WIDTH - source_line.shape[1]) // 2, 1486)
        else:
            reveal = ease_out((time_s - end_start) / 0.4)
            frame[:] = (frame.astype(np.float32) * (1.0 - 0.74 * reveal)).astype(np.uint8)
            overlay(frame, end_card, 0, 560, reveal)

        bar_width = int(WIDTH * (frame_index + 1) / total_frames)
        frame[HEIGHT - 10:HEIGHT, :bar_width] = accent
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
    portrait_record = json.loads((ASSETS / "vera.source.json").read_text(encoding="utf-8"))
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
        "voice": voice_label(),
        "presenter": presenter.mode,
        "portrait_is_placeholder": bool(portrait_record.get("placeholder")),
        "source": episode["source"],
    }
    (OUTPUT / f"{episode['id']}.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(report, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description="Render Not Real Vera episodes")
    parser.add_argument("episode", help="episode id such as ep01, or 'all'")
    arguments = parser.parse_args()
    data = json.loads((ROOT / "episodes.json").read_text(encoding="utf-8"))
    selected = [item for item in data["episodes"] if arguments.episode in ("all", item["id"])]
    if not selected:
        raise SystemExit(f"no episode named {arguments.episode}")
    for episode in selected:
        render_episode(episode, data["signoff"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
