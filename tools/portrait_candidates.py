"""Fetch a few portrait candidates so a human (or the agent) can pick the most photoreal one.

    python tools/portrait_candidates.py

Writes assets/candidates/cand_<n>.jpg and a side-by-side assets/candidates/sheet.jpg. Nothing is overwritten in
assets/vera.jpg; pick one with:  python tools/portrait_candidates.py --use 2
"""
import argparse
import io
import json
import sys
from pathlib import Path
from urllib.parse import quote

import requests
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
CANDIDATES = ROOT / "assets" / "candidates"
PROMPT = (
    "candid smartphone selfie-video still of a fictional woman, early thirties, chin-length dark brown bob, "
    "friendly direct eye contact, slight smile, plain charcoal crew-neck sweater, sitting at a home desk, "
    "warm lamp and bookshelf softly out of focus behind her, head and shoulders in the upper half of the frame, "
    "real photograph, natural skin pores, slight asymmetry, unretouched, natural window light, 35mm"
)
ATTEMPTS = [("flux-realism", 11), ("flux", 41), ("flux", 314), ("turbo", 9)]


def fetch(model, seed):
    url = (
        "https://image.pollinations.ai/prompt/"
        + quote(PROMPT)
        + f"?width=1080&height=1920&seed={seed}&model={model}&nologo=true"
    )
    response = requests.get(url, timeout=150)
    if response.status_code != 200 or "image" not in response.headers.get("content-type", ""):
        raise RuntimeError(f"HTTP {response.status_code} {response.headers.get('content-type')}")
    return Image.open(io.BytesIO(response.content)).convert("RGB")


def use_candidate(number):
    record = json.loads((CANDIDATES / "candidates.json").read_text(encoding="utf-8"))[str(number)]
    image = Image.open(CANDIDATES / f"cand_{number}.jpg")
    scale = max(1080 / image.width, 1920 / image.height)
    resized = image.resize((round(image.width * scale), round(image.height * scale)), Image.LANCZOS)
    left = (resized.width - 1080) // 2
    top = (resized.height - 1920) // 2
    resized.crop((left, top, left + 1080, top + 1920)).save(ROOT / "assets" / "vera.jpg", quality=92)
    source = {
        "prompt": PROMPT,
        "person": "fictional, AI-generated; not a real person",
        "placeholder": False,
        "service": "image.pollinations.ai (free tier; keeps the service's small corner mark)",
        "native_size": list(image.size),
    }
    source.update(record)
    (ROOT / "assets" / "vera.source.json").write_text(
        json.dumps(source, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    print(f"assets/vera.jpg now uses candidate {number}: {record}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--use", type=int, help="copy this candidate number to assets/vera.jpg")
    arguments = parser.parse_args()
    if arguments.use is not None:
        use_candidate(arguments.use)
        return 0
    CANDIDATES.mkdir(parents=True, exist_ok=True)
    records = {}
    thumbnails = []
    for number, (model, seed) in enumerate(ATTEMPTS, start=1):
        try:
            image = fetch(model, seed)
        except Exception as error:
            print(f"candidate {number} failed: model={model} seed={seed}: {type(error).__name__}: {error}", flush=True)
            continue
        image.save(CANDIDATES / f"cand_{number}.jpg", quality=92)
        records[str(number)] = {"model": model, "seed": seed}
        thumbnails.append(image.resize((360, 640)))
        print(f"candidate {number} ok: model={model} seed={seed} size={image.size}", flush=True)
    (CANDIDATES / "candidates.json").write_text(json.dumps(records, indent=2) + "\n", encoding="utf-8")
    if thumbnails:
        sheet = Image.new("RGB", (360 * len(thumbnails), 640))
        for position, thumbnail in enumerate(thumbnails):
            sheet.paste(thumbnail, (360 * position, 0))
        sheet.save(CANDIDATES / "sheet.jpg", quality=88)
    return 0 if thumbnails else 1


if __name__ == "__main__":
    sys.exit(main())
