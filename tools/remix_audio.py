"""Mix an episode's sound again and put it under the picture that is already rendered.

Rendering the picture takes about 16 minutes per episode; the sound takes seconds. After a change in
pipeline/sound.py, this rebuilds only the sound and copies the video stream as it is.

    python tools/remix_audio.py ep01
    python tools/remix_audio.py all
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

import make_episode  # noqa: E402
import sound  # noqa: E402


def remix(episode):
    episode_id = episode["id"]
    video_path = make_episode.OUTPUT / f"{episode_id}.mp4"
    report_path = make_episode.OUTPUT / f"{episode_id}.json"
    if not video_path.exists() or not report_path.exists():
        raise SystemExit(f"{episode_id}: render it first (python pipeline/make_episode.py {episode_id})")
    work_dir = make_episode.OUTPUT / "_work" / episode_id

    # The same timeline the render used: the spoken lines are cached, so this does not speak them again.
    lines, voice, total = make_episode.build_audio(episode["narration"], work_dir)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if abs(report["duration_s"] - total) > 0.02:
        raise SystemExit(f"{episode_id}: the voice is {total:.2f} s but the video is {report['duration_s']} s; render again")
    check_start = lines[make_episode.find_check_line(episode)]["start"]
    end_start = lines[-1]["start"]
    wav_path = work_dir / "audio.wav"
    mono, sound_report = sound.mix_episode(voice, total, check_start, end_start, episode_id, wav_path)

    remuxed = video_path.with_name(f"{episode_id}.remix.mp4")
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-v", "error",
            "-i", str(video_path), "-i", str(wav_path),
            "-map", "0:v", "-map", "1:a", "-c:v", "copy",
            "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart", "-shortest", str(remuxed),
        ],
        check=True,
    )
    remuxed.replace(video_path)

    report["sound"] = sound_report
    report["audio_rms"] = round(float(np.sqrt(np.mean(mono ** 2))), 4)
    report["size_mb"] = round(video_path.stat().st_size / 1e6, 2)
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(episode_id, json.dumps(sound_report))


def main():
    parser = argparse.ArgumentParser(description="Mix the sound again without rendering the picture again")
    parser.add_argument("episode", help="episode id such as ep01, or 'all'")
    arguments = parser.parse_args()
    data = json.loads((ROOT / "episodes.json").read_text(encoding="utf-8"))
    selected = [item for item in data["episodes"] if arguments.episode in ("all", item["id"])]
    if not selected:
        raise SystemExit(f"no episode named {arguments.episode}")
    for episode in selected:
        remix(episode)
    return 0


if __name__ == "__main__":
    sys.exit(main())
