"""Generate Vera's portrait: a fictional, AI-generated presenter (not a real person's likeness).

Uses the free Pollinations image endpoint. If it cannot be reached, a clearly labelled placeholder is written
so the rest of the pipeline still runs, and the sidecar JSON says so.
"""
import io
import json
import sys
from pathlib import Path
from urllib.parse import quote

import requests
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
WIDTH, HEIGHT = 1080, 1920
PROMPT = (
    "photorealistic vertical portrait photo of a fictional woman in her early thirties, "
    "chin-length dark brown bob, calm confident half smile, looking straight into the camera, "
    "charcoal blazer over a plain black top, medium close-up from the chest up, head in the upper third, "
    "soft key light from the left, dark teal studio background with gentle bokeh, 85mm lens, "
    "natural skin texture, sharp eyes, no text, no watermark"
)
ATTEMPTS = [("flux", 7), ("flux", 2026), ("turbo", 7)]


def cover_crop(image):
    """Scale and centre-crop to exactly 1080x1920."""
    scale = max(WIDTH / image.width, HEIGHT / image.height)
    resized = image.resize((round(image.width * scale), round(image.height * scale)), Image.LANCZOS)
    left = (resized.width - WIDTH) // 2
    top = (resized.height - HEIGHT) // 2
    return resized.crop((left, top, left + WIDTH, top + HEIGHT))


def fetch_portrait(model, seed):
    url = (
        "https://image.pollinations.ai/prompt/"
        + quote(PROMPT)
        + f"?width={WIDTH}&height={HEIGHT}&seed={seed}&model={model}&nologo=true"
    )
    response = requests.get(url, timeout=150)
    if response.status_code != 200 or "image" not in response.headers.get("content-type", ""):
        raise RuntimeError(f"HTTP {response.status_code} {response.headers.get('content-type')}")
    image = Image.open(io.BytesIO(response.content)).convert("RGB")
    if min(image.size) < 512:
        raise RuntimeError(f"image too small: {image.size}")
    return image


def placeholder():
    image = Image.new("RGB", (WIDTH, HEIGHT))
    draw = ImageDraw.Draw(image)
    for row in range(HEIGHT):
        blend = row / HEIGHT
        draw.line([(0, row), (WIDTH, row)], fill=(int(14 + 20 * blend), int(52 - 20 * blend), int(60 - 10 * blend)))
    draw.ellipse((340, 380, 740, 780), fill=(40, 70, 78))
    draw.rounded_rectangle((180, 820, 900, 1920), radius=260, fill=(40, 70, 78))
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\segoeuib.ttf", 44)
    except OSError:
        font = ImageFont.load_default()
    draw.text((WIDTH // 2, 1000), "PORTRAIT PLACEHOLDER", font=font, fill=(200, 220, 222), anchor="mm")
    return image


def main():
    ASSETS.mkdir(parents=True, exist_ok=True)
    record = {"prompt": PROMPT, "person": "fictional, AI-generated; not a real person", "placeholder": False}
    image = None
    for model, seed in ATTEMPTS:
        try:
            image = fetch_portrait(model, seed)
            record.update({"model": model, "seed": seed, "service": "image.pollinations.ai"})
            print(f"portrait ok: model={model} seed={seed} size={image.size}")
            break
        except Exception as error:
            print(f"portrait attempt failed: model={model} seed={seed}: {type(error).__name__}: {error}")
    if image is None:
        image = placeholder()
        record["placeholder"] = True
        print("portrait: wrote a PLACEHOLDER (image service unreachable)")
    cover_crop(image).save(ASSETS / "vera.jpg", quality=92)
    (ASSETS / "vera.source.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
