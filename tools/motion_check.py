"""Measure how much the presenter picture moves in finished renders.

    python tools/motion_check.py            # every output/epNN.mp4
    python tools/motion_check.py ep01

Uses the same meter the renderer uses (camera.MotionMeter): the band of the frame that holds her face and
shoulders, shrunk, mean change of brightness between neighbouring frames (0-255 scale). A stationary picture
scores near 0. The quietest one-second stretch is reported too, because a clip that moves on average can
still freeze.
"""
import json
import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import camera  # noqa: E402


def measure(video_path):
    capture = cv2.VideoCapture(str(video_path))
    fps = capture.get(cv2.CAP_PROP_FPS) or 30.0
    meter = camera.MotionMeter()
    while True:
        ok, frame = capture.read()
        if not ok:
            break
        meter.add(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
    capture.release()
    return meter.report(fps)


def main():
    selector = sys.argv[1] if len(sys.argv) > 1 else "all"
    videos = sorted((ROOT / "output").glob("ep[0-9][0-9].mp4"))
    results = {video.stem: measure(video) for video in videos if selector in ("all", video.stem)}
    print(json.dumps(results, indent=2))
    return 0 if results else 1


if __name__ == "__main__":
    sys.exit(main())
