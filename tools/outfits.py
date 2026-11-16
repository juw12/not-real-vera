"""Vera's wardrobe: one presenter still per episode, same face, a different outfit each time.

    python tools/outfits.py base            # trial base portraits -> assets/candidates/base_<seed>.jpg + sheet
    python tools/outfits.py base --use 7    # keep one trial as assets/outfits/base.jpg
    python tools/outfits.py dress           # one outfit per episode -> assets/outfits/<episode id>.jpg
    python tools/outfits.py dress ep03      # redo one episode
    python tools/outfits.py dress --reuse   # blend the saved repaints again, without the service
    python tools/outfits.py finish          # smooth every outfit picture and put the base face back
    python tools/outfits.py finish ep03     # redo one episode

Pictures come from AI Horde (free volunteer service, anonymous key; see tools/horde.py). Two steps per outfit:
dress repaints only the clothing area of the base picture; finish runs the whole result through the model
once more at low strength, which removes the seam where the repaint meets the base, and then copies the
face back from the base picture so she is the same person in every episode.
pipeline/make_episode.py uses assets/outfits/<episode id>.jpg when it exists, otherwise assets/vera.jpg.

The presenter is a fictional, AI-generated adult. Outfits stay inside what YouTube, Instagram and TikTok allow
in the normal feed: fitted and low-cut is fine, lingerie or see-through is not.
"""
import argparse
import json
import shutil
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parent))
import horde  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUTFITS = ROOT / "assets" / "outfits"
CANDIDATES = ROOT / "assets" / "candidates"
SERVICE = "AI Horde (aihorde.net), free volunteer service, anonymous key"
MODEL = "Juggernaut XL"
WIDTH, HEIGHT = 768, 1344
BASE_SEEDS = [7, 21, 133]
SCENE = (
    "candid vertical photo of a fictional adult woman aged thirty, long wavy dark brown hair, "
    "warm confident smile, looking straight into the camera, standing in a bright modern apartment living room, "
    "framed from the hips up, her head in the upper quarter of the frame, hourglass figure, {outfit}, "
    "{pose}, real photograph, natural skin texture, soft window daylight, 35mm, "
    "shallow depth of field"
)
BASE_OUTFIT = "fitted black V-neck top with a low neckline"
BASE_POSE = "arms relaxed at her sides"
# The base picture came out with her hands on her hips. Saying so keeps the repainted upper arms joined to
# the forearms that are copied from the base. Long sleeves break that join (the model hangs the arm
# straight down and the base forearm is left floating), so every outfit is sleeveless or short-sleeved.
# Each outfit also names what she wears below the top, otherwise a camisole comes out as nightwear.
DRESSED_POSE = "both hands resting on her hips, elbows out"
OUTFIT_BY_EPISODE = {
    "ep01": (
        "fitted black sleeveless V-neck top with a low neckline and a thin gold pendant necklace, "
        "tucked into black high-waisted trousers"
    ),
    "ep02": "deep red satin wrap blouse with a plunging V neckline, tied at the waist",
    "ep03": "bright white ribbed-knit square-neck fitted top with a low neckline",
    "ep04": (
        "emerald green silk camisole with thin straps and a low neckline, "
        "tucked into high-waisted cream trousers"
    ),
    "ep05": "fitted sweetheart-neckline corset-style top in dark denim with a delicate silver necklace",
}
# Clothing area of assets/outfits/base.jpg (seed 21) in base-picture pixels: the top with its sleeves and the
# chest below the collarbone, down to the bottom edge of the frame. Face, forearms and room are outside it.
CLOTHING_POLYGON = [
    (140, 475), (300, 500), (384, 512), (470, 500), (515, 462), (640, 462), (705, 530),
    (752, 720), (748, 792), (645, 794), (612, 762), (590, 870), (588, 960), (610, 1050),
    (630, 1150), (660, 1360), (115, 1360), (135, 1150), (160, 1050), (180, 960), (185, 870),
    (178, 762), (170, 716), (60, 768), (28, 700), (60, 580), (100, 520),
]
SUBMIT_GAP_SECONDS = 3  # the service allows 2 new jobs per second per address
MASK_GROW = 16  # px the repaint area reaches past the polygon, so sleeve cuffs and hems are inside it
BLEND_GROW = 18  # px the blend reaches past the repaint area, so no old clothing shows through at its edge
BLEND_FEATHER = 9
FINISH_STRENGTH = 0.4  # how far the smoothing pass may move away from the dressed picture (0 = not at all)
# Face of assets/outfits/base.jpg in base-picture pixels: forehead to chin, without the hair.
FACE_CENTER = (385, 282)
FACE_HALF_WIDTH, FACE_HALF_HEIGHT = 98, 148
FACE_FEATHER = 14


def grow(mask, pixels):
    return mask.filter(ImageFilter.MaxFilter(2 * pixels + 1))


def clothing_mask():
    """Area the service repaints."""
    mask = Image.new("L", (WIDTH, HEIGHT), 0)
    ImageDraw.Draw(mask).polygon(CLOTHING_POLYGON, fill=255)
    return grow(mask, MASK_GROW)


def blend_mask():
    """Weight of the repaint in the final picture: 1 over the whole repaint area, fading out just outside it."""
    return grow(clothing_mask(), BLEND_GROW).filter(ImageFilter.GaussianBlur(BLEND_FEATHER))


def face_mask():
    """Weight of the base picture when its face is copied back: 1 on the face, fading out at the hairline."""
    mask = Image.new("L", (WIDTH, HEIGHT), 0)
    center_x, center_y = FACE_CENTER
    box = (
        center_x - FACE_HALF_WIDTH,
        center_y - FACE_HALF_HEIGHT,
        center_x + FACE_HALF_WIDTH,
        center_y + FACE_HALF_HEIGHT,
    )
    ImageDraw.Draw(mask).ellipse(box, fill=255)
    return mask.filter(ImageFilter.GaussianBlur(FACE_FEATHER))


def raw_path(episode_id):
    return CANDIDATES / f"repaint_{episode_id}.png"


def smooth_path(episode_id):
    return CANDIDATES / f"smooth_{episode_id}.png"


def make_base_trials():
    CANDIDATES.mkdir(parents=True, exist_ok=True)
    thumbnails = []
    for seed in BASE_SEEDS:
        print(f"base trial seed={seed}", flush=True)
        try:
            image, _, _ = horde.generate(
                SCENE.format(outfit=BASE_OUTFIT, pose=BASE_POSE), MODEL, seed, WIDTH, HEIGHT
            )
        except RuntimeError as error:
            print(f"  failed: {error}", flush=True)
            continue
        image.save(CANDIDATES / f"base_{seed}.jpg", quality=93)
        thumbnails.append(image.resize((384, 672)))
    if not thumbnails:
        return 1
    sheet = Image.new("RGB", (384 * len(thumbnails), 672))
    for position, thumbnail in enumerate(thumbnails):
        sheet.paste(thumbnail, (384 * position, 0))
    sheet.save(CANDIDATES / "base_sheet.jpg", quality=88)
    print(f"wrote {len(thumbnails)} trial(s) and assets/candidates/base_sheet.jpg")
    return 0


def use_base(seed):
    OUTFITS.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(CANDIDATES / f"base_{seed}.jpg", OUTFITS / "base.jpg")
    record = {
        "person": "fictional, AI-generated; not a real person",
        "service": SERVICE,
        "model": MODEL,
        "prompt": SCENE.format(outfit=BASE_OUTFIT, pose=BASE_POSE),
        "seed": seed,
        "size": [WIDTH, HEIGHT],
        "outfits": {},
    }
    (OUTFITS / "outfits.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(f"assets/outfits/base.jpg now uses seed {seed}")
    return 0


def dress(episode_ids, seed, reuse=False):
    base_path = OUTFITS / "base.jpg"
    if not base_path.exists():
        raise SystemExit("assets/outfits/base.jpg is missing. Run: python tools/outfits.py base, then --use <seed>")
    record_path = OUTFITS / "outfits.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    base = Image.open(base_path).convert("RGB")
    mask = clothing_mask()
    soft_mask = blend_mask()
    CANDIDATES.mkdir(parents=True, exist_ok=True)

    def repaint(job):
        position, episode_id = job
        prompt = SCENE.format(outfit=OUTFIT_BY_EPISODE[episode_id], pose=DRESSED_POSE)
        if reuse:
            if not raw_path(episode_id).exists():
                return episode_id, prompt, None, "no saved repaint; run dress without --reuse"
            return episode_id, prompt, Image.open(raw_path(episode_id)).convert("RGB"), ""
        time.sleep(position * SUBMIT_GAP_SECONDS)
        print(f"{episode_id}: {OUTFIT_BY_EPISODE[episode_id]}", flush=True)
        try:
            painted, _, _ = horde.generate(
                prompt, MODEL, seed, WIDTH, HEIGHT, source_image=base, source_mask=mask, denoising_strength=1.0
            )
        except (RuntimeError, OSError) as error:
            return episode_id, prompt, None, str(error)
        return episode_id, prompt, painted, ""

    failed = []
    with ThreadPoolExecutor(max_workers=len(episode_ids)) as pool:
        for episode_id, prompt, painted, error in pool.map(repaint, enumerate(episode_ids)):
            if painted is None:
                print(f"{episode_id} failed: {error}", flush=True)
                failed.append(episode_id)
                continue
            painted = painted.resize(base.size, Image.LANCZOS)
            painted.save(raw_path(episode_id))
            Image.composite(painted, base, soft_mask).save(OUTFITS / f"{episode_id}.jpg", quality=93)
            if not reuse:
                record["outfits"][episode_id] = {
                    "outfit": OUTFIT_BY_EPISODE[episode_id],
                    "prompt": prompt,
                    "seed": seed,
                }
            record_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n")
            print(f"{episode_id} saved", flush=True)
    if failed:
        print("failed: " + ", ".join(failed))
    return 1 if failed else 0


def finish(episode_ids, seed, strength):
    base = Image.open(OUTFITS / "base.jpg").convert("RGB")
    record_path = OUTFITS / "outfits.json"
    record = json.loads(record_path.read_text(encoding="utf-8"))
    soft_mask = blend_mask()
    face = face_mask()

    def smooth(job):
        position, episode_id = job
        if not raw_path(episode_id).exists():
            return episode_id, None, "no saved repaint; run dress first"
        repaint = Image.open(raw_path(episode_id)).convert("RGB")
        dressed = Image.composite(repaint, base, soft_mask)
        time.sleep(position * SUBMIT_GAP_SECONDS)
        print(f"{episode_id}: smoothing at strength {strength}", flush=True)
        try:
            smoothed, _, _ = horde.generate(
                SCENE.format(outfit=OUTFIT_BY_EPISODE[episode_id], pose=DRESSED_POSE),
                MODEL,
                seed,
                WIDTH,
                HEIGHT,
                source_image=dressed,
                denoising_strength=strength,
            )
        except (RuntimeError, OSError) as error:
            return episode_id, None, str(error)
        return episode_id, smoothed, ""

    failed = []
    with ThreadPoolExecutor(max_workers=len(episode_ids)) as pool:
        for episode_id, smoothed, error in pool.map(smooth, enumerate(episode_ids)):
            if smoothed is None:
                print(f"{episode_id} failed: {error}", flush=True)
                failed.append(episode_id)
                continue
            smoothed = smoothed.resize(base.size, Image.LANCZOS)
            smoothed.save(smooth_path(episode_id))
            Image.composite(base, smoothed, face).save(OUTFITS / f"{episode_id}.jpg", quality=93)
            record["outfits"].setdefault(episode_id, {})["finish"] = {"seed": seed, "strength": strength}
            record_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8", newline="\n")
            print(f"{episode_id} finished", flush=True)
    if failed:
        print("failed: " + ", ".join(failed))
    return 1 if failed else 0


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("command", choices=["base", "dress", "finish"])
    parser.add_argument("episodes", nargs="*", help="episode ids for dress or finish (default: all)")
    parser.add_argument("--use", type=int, help="with base: keep the trial with this seed")
    parser.add_argument("--seed", type=int, default=11, help="with dress: seed for the repaint")
    parser.add_argument("--reuse", action="store_true", help="with dress: blend the saved repaints again")
    parser.add_argument("--strength", type=float, default=FINISH_STRENGTH, help="with finish: smoothing strength")
    arguments = parser.parse_args()
    if arguments.command == "base":
        return use_base(arguments.use) if arguments.use is not None else make_base_trials()
    if arguments.command == "finish":
        return finish(arguments.episodes or list(OUTFIT_BY_EPISODE), arguments.seed, arguments.strength)
    return dress(arguments.episodes or list(OUTFIT_BY_EPISODE), arguments.seed, arguments.reuse)


if __name__ == "__main__":
    sys.exit(main())
