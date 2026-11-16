"""Make the talking presenter clip for an episode.

    python tools/presenter_kit.py export ep01      # voice track + portrait, for any avatar tool
    python tools/presenter_kit.py sadtalker ep01   # free local lip-sync (CPU, slow, face only)
    python tools/presenter_kit.py status           # which episodes have a clip

Without a clip, make_episode.py already moves the still's mouth, eyelids, eyebrows and head with the voice
(pipeline/lipsync.py, pipeline/face_rig.py). That is rule-based. A clip from a neural avatar tool looks more
like a person talking and replaces it.

A presenter clip is a video of Vera saying one episode's voice track. make_episode.py plays
assets/presenter/<id>.mp4 locked to the timeline, so the clip must be made from that episode's
own voice.wav and start at 0:00 of it.

"export" writes output/_work/<id>/voice.wav (voice only, including the short lead-in) and tells you
which picture belongs to that episode (its outfit still, assets/outfits/<id>.jpg, when there is one).
Give both to any audio-driven avatar tool, then save its result as
assets/presenter/<id>.mp4 and render the episode again.

"sadtalker" does the same job on this PC with the open-source SadTalker model in .presenter/
(see README, "Presenter"). It moves the lips, eyes and head. It does not move hands or body.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

ASSETS = ROOT / "assets"
OUTPUT = ROOT / "output"
PRESENTER_HOME = ROOT / ".presenter"
SADTALKER = PRESENTER_HOME / "SadTalker"
VENV_PYTHON = PRESENTER_HOME / "venv" / "Scripts" / "python.exe"
FFMPEG_DIR = PRESENTER_HOME / "bin"
CLIPS = ASSETS / "presenter"


def load_episodes(selector):
    data = json.loads((ROOT / "episodes.json").read_text(encoding="utf-8"))
    selected = [item for item in data["episodes"] if selector in ("all", item["id"])]
    if not selected:
        raise SystemExit(f"no episode named {selector}")
    return selected


def wav_seconds(path):
    with wave.open(str(path), "rb") as handle:
        return handle.getnframes() / handle.getframerate()


def export_voice(episode):
    """Write the voice-only track for one episode and return its path."""
    import make_episode

    work_dir = OUTPUT / "_work" / episode["id"]
    work_dir.mkdir(parents=True, exist_ok=True)
    _, track, _ = make_episode.build_audio(episode["narration"], work_dir)
    voice_path = work_dir / "voice.wav"
    make_episode.write_wav(track, voice_path)
    return voice_path


def portrait_for(episode):
    import make_episode

    return make_episode.portrait_path_for(episode["id"])


def command_export(episodes):
    for episode in episodes:
        voice_path = export_voice(episode)
        print(f"{episode['id']}: {voice_path}  ({wav_seconds(voice_path):.1f} s)")
        print(f"      picture: {portrait_for(episode)}")
        print(f"      save the finished clip as {CLIPS / (episode['id'] + '.mp4')}")
    print("Use an audio-driven avatar tool: picture + voice.wav in, one vertical talking clip out.")
    print("Keep the full length of the audio and do not trim the start, or the lips will drift.")
    return 0


def command_status(episodes):
    for episode in episodes:
        clip = CLIPS / f"{episode['id']}.mp4"
        state = f"{clip.stat().st_size / 1e6:.1f} MB" if clip.exists() else "missing (still portrait will be used)"
        print(f"{episode['id']}: {state}")
    return 0


def command_sadtalker(episodes):
    if not VENV_PYTHON.exists() or not (SADTALKER / "inference.py").exists():
        raise SystemExit("SadTalker is not set up in .presenter/. See README, section 'Presenter'.")
    if not (FFMPEG_DIR / "ffmpeg.exe").exists():
        # SadTalker shells out to a program literally named "ffmpeg".
        import imageio_ffmpeg

        FFMPEG_DIR.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(imageio_ffmpeg.get_ffmpeg_exe(), FFMPEG_DIR / "ffmpeg.exe")
    environment = dict(os.environ)
    environment["PATH"] = str(FFMPEG_DIR) + os.pathsep + environment.get("PATH", "")
    environment["TORCH_FORCE_NO_WEIGHTS_ONLY_LOAD"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    CLIPS.mkdir(parents=True, exist_ok=True)
    for episode in episodes:
        voice_path = export_voice(episode)
        result_dir = OUTPUT / "_work" / episode["id"] / "sadtalker"
        shutil.rmtree(result_dir, ignore_errors=True)
        completed = subprocess.run(
            [
                str(VENV_PYTHON), "inference.py",
                "--driven_audio", str(voice_path),
                "--source_image", str(portrait_for(episode)),
                "--result_dir", str(result_dir),
                "--preprocess", "full",
                "--still",
                "--size", "256",
                "--batch_size", "4",
                "--cpu",
            ],
            cwd=SADTALKER,
            env=environment,
        )
        if completed.returncode != 0:
            raise SystemExit(f"SadTalker failed on {episode['id']}")
        results = sorted(result_dir.rglob("*.mp4"), key=lambda path: path.stat().st_mtime)
        if not results:
            raise SystemExit(f"SadTalker wrote no video for {episode['id']}")
        target = CLIPS / f"{episode['id']}.mp4"
        shutil.copyfile(results[-1], target)
        print(f"{episode['id']}: {target}  (voice {wav_seconds(voice_path):.1f} s)")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Presenter clips for Vera Checks episodes")
    parser.add_argument("command", choices=["export", "sadtalker", "status"])
    parser.add_argument("episode", nargs="?", default="all", help="episode id such as ep01, or 'all'")
    arguments = parser.parse_args()
    episodes = load_episodes(arguments.episode)
    commands = {"export": command_export, "sadtalker": command_sadtalker, "status": command_status}
    return commands[arguments.command](episodes)


if __name__ == "__main__":
    sys.exit(main())
