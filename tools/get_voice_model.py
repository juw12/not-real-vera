"""Download the free local Kokoro voice model (Apache-2.0) into models/. Resumable; goes through the system proxy.

    python tools/get_voice_model.py
"""
import sys
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"
RELEASE = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
FILES = ["voices-v1.0.bin", "kokoro-v1.0.int8.onnx"]


def download(name):
    target = MODELS / name
    partial = MODELS / (name + ".part")
    if target.exists():
        print(f"{name}: already present ({target.stat().st_size} bytes)", flush=True)
        return True
    for attempt in range(1, 7):
        done = partial.stat().st_size if partial.exists() else 0
        headers = {"Range": f"bytes={done}-"} if done else {}
        try:
            with requests.get(f"{RELEASE}/{name}", headers=headers, stream=True, timeout=60) as response:
                if response.status_code == 416:
                    break
                response.raise_for_status()
                if done and response.status_code != 206:
                    done = 0
                    partial.unlink()
                with open(partial, "ab") as handle:
                    last_report = time.time()
                    for block in response.iter_content(1 << 20):
                        handle.write(block)
                        done += len(block)
                        if time.time() - last_report > 10:
                            print(f"{name}: {done / 1e6:.0f} MB", flush=True)
                            last_report = time.time()
            break
        except requests.RequestException as error:
            print(f"{name}: attempt {attempt} interrupted at {done / 1e6:.0f} MB ({type(error).__name__})", flush=True)
            time.sleep(3)
    else:
        return False
    partial.rename(target)
    print(f"{name}: done, {target.stat().st_size} bytes", flush=True)
    return True


def main():
    MODELS.mkdir(parents=True, exist_ok=True)
    results = [download(name) for name in FILES]
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
