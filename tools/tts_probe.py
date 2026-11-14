"""Probe which free voice engine works on this PC. Prints one line per engine.

    python tools/tts_probe.py
"""
import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "output" / "_work" / "probe"
SAMPLE = "This text is a scam. I'm an AI, and I can prove it in ten seconds."


async def edge_once(path):
    import edge_tts

    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    communicate = edge_tts.Communicate(SAMPLE, "en-US-AvaMultilingualNeural", proxy=proxy)
    size = 0
    with open(path, "wb") as handle:
        async for chunk in communicate.stream():
            if chunk["type"] == "audio":
                handle.write(chunk["data"])
                size += len(chunk["data"])
    return size


def probe_edge():
    for attempt in range(1, 4):
        started = time.time()
        try:
            size = asyncio.run(asyncio.wait_for(edge_once(WORK / "edge.mp3"), timeout=40))
            print(f"edge-tts attempt {attempt}: OK {size} bytes in {time.time() - started:.1f}s")
            return True
        except Exception as error:
            print(f"edge-tts attempt {attempt}: FAIL {type(error).__name__}: {str(error)[:160]}")
            time.sleep(2)
    return False


def probe_kokoro_files():
    model_dir = ROOT / "models"
    for name in ("kokoro-v1.0.onnx", "voices-v1.0.bin"):
        path = model_dir / name
        state = f"{path.stat().st_size} bytes" if path.exists() else "missing"
        print(f"kokoro file {name}: {state}")


def main():
    WORK.mkdir(parents=True, exist_ok=True)
    probe_edge()
    probe_kokoro_files()
    return 0


if __name__ == "__main__":
    sys.exit(main())
