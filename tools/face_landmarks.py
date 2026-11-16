"""Find the eyes, mouth and jaw on every outfit still, once, and save them for the renderer.

    .presenter\\venv\\Scripts\\python.exe tools/face_landmarks.py

Needs torch and facexlib, so it runs in the .presenter virtual environment (README, "Presenter").
It writes assets/outfits/landmarks.json. The renderer (system Python, no torch) reads that file to know
where to put the moving mouth and where the eyelids are.

Landmarks are the 98 WFLW points: 0-32 jaw line (16 = chin), 33-50 eyebrows, 51-59 nose, 60-67 one eye,
68-75 the other eye, 76-95 lips, 96-97 pupils.
"""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import torch
from facexlib.alignment import FAN

# facexlib still uses the np.float alias that newer numpy removed.
if not hasattr(np, "float"):
    np.float = float

ROOT = Path(__file__).resolve().parent.parent
OUTFITS = ROOT / "assets" / "outfits"
WEIGHTS = ROOT / ".presenter" / "SadTalker" / "gfpgan" / "weights"
CROP_MARGIN = 0.45  # extra room around the recorded face box, as a share of its size


def face_crop_box(face, picture_shape):
    half_width = face["half_width"] * (1.0 + CROP_MARGIN)
    half_height = face["half_height"] * (1.0 + CROP_MARGIN)
    half = max(half_width, half_height)
    left = int(max(face["center"][0] - half, 0))
    top = int(max(face["center"][1] - half, 0))
    right = int(min(face["center"][0] + half, picture_shape[1]))
    bottom = int(min(face["center"][1] + half, picture_shape[0]))
    return left, top, right, bottom


def main():
    record = json.loads((OUTFITS / "outfits.json").read_text(encoding="utf-8"))
    face = record["face"]
    # facexlib's own loader assumes a CUDA machine, so the weights are loaded here, onto the CPU.
    model = FAN(num_modules=4, num_landmarks=98, device="cpu")
    weights = torch.load(WEIGHTS / "alignment_WFLW_4HG.pth", map_location="cpu")
    model.load_state_dict(weights["state_dict"], strict=True)
    model.eval()
    found = {}
    for still in sorted(OUTFITS.glob("*.jpg")):
        picture = cv2.imread(str(still))
        left, top, right, bottom = face_crop_box(face, picture.shape)
        with torch.no_grad():
            points = model.get_landmarks(picture[top:bottom, left:right])
        points = np.asarray(points, dtype=np.float64) + [left, top]
        found[still.stem] = {
            "picture_size": [picture.shape[1], picture.shape[0]],
            "points": [[round(float(x), 1), round(float(y), 1)] for x, y in points],
        }
        print(still.name, "chin", found[still.stem]["points"][16], "pupils", found[still.stem]["points"][96:98])
    target = OUTFITS / "landmarks.json"
    target.write_text(json.dumps(found, indent=1) + "\n", encoding="utf-8", newline="\n")
    print("wrote", target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
