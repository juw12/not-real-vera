"""Fetch the two small helper models the renderer uses on top of the voice model. Both run on the CPU.

    python tools/get_motion_models.py

models/midas-small.onnx           depth estimate of the presenter still, for the parallax camera move (MIT licence)
models/vosk-model-small-en-us-0.15  speech recogniser, used only to time each caption word to the voice (Apache 2.0)
"""
import io
import sys
import zipfile
from pathlib import Path

import requests

MODELS = Path(__file__).resolve().parent.parent / "models"
DEPTH_URL = "https://github.com/isl-org/MiDaS/releases/download/v2_1/model-small.onnx"
DEPTH_FILE = MODELS / "midas-small.onnx"
DEPTH_MIN_BYTES = 60_000_000
SPEECH_URL = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
SPEECH_FOLDER = MODELS / "vosk-model-small-en-us-0.15"


def download(url):
    """Return the whole file; a download that the proxy cut short raises instead of passing quietly."""
    with requests.get(url, stream=True, timeout=120) as response:
        response.raise_for_status()
        expected = int(response.headers.get("Content-Length", 0))
        data = bytearray()
        for chunk in response.iter_content(1 << 20):
            data.extend(chunk)
            print(f"\r  {len(data) / 1e6:6.1f} MB", end="", flush=True)
    print()
    if expected and len(data) != expected:
        raise RuntimeError(f"got {len(data)} of {expected} bytes from {url}")
    return bytes(data)


def main():
    MODELS.mkdir(exist_ok=True)
    if DEPTH_FILE.exists() and DEPTH_FILE.stat().st_size >= DEPTH_MIN_BYTES:
        print(f"have {DEPTH_FILE.name}")
    else:
        print(f"fetching {DEPTH_FILE.name}")
        DEPTH_FILE.write_bytes(download(DEPTH_URL))
    if (SPEECH_FOLDER / "am" / "final.mdl").exists():
        print(f"have {SPEECH_FOLDER.name}")
    else:
        print(f"fetching {SPEECH_FOLDER.name}")
        zipfile.ZipFile(io.BytesIO(download(SPEECH_URL))).extractall(MODELS)
    return 0


if __name__ == "__main__":
    sys.exit(main())
