"""Objective gates for the Vera Checks (repo: not-real-vera) scripts and renders.

    python tools/gates.py            # script gates and render gates (length, captions, caption timing, sound,
                                     # short on-screen text, lip-sync timing, picture motion)
    python tools/gates.py --links    # also check that every source link answers HTTP 200

Gates 13 and 14 read numbers the renderer measures. They catch a mouth that is late, a mouth that never
closes, or a picture that stands still. They do not judge whether the result looks like a real person.
"""
import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
OFFICIAL_DOMAINS = ("ftc.gov", "ic3.gov", "fbi.gov", "cisa.gov", "consumerfinance.gov")
BROWSER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124.0 Safari/537.36"
# Sound targets for a finished render: the level YouTube, Instagram and TikTok normalise to, with headroom
# so the platforms' re-encoding does not clip.
LOUDNESS_TARGET_LUFS = -14.0
LOUDNESS_TOLERANCE = 0.5
TRUE_PEAK_LIMIT_DBTP = -1.0
# Text that stays on the picture is a short label, never a sentence to read. The longest pillar label,
# "SEND THIS TO YOUR PARENTS", is 25 characters and 5 words.
STATIC_TEXT_MAX_CHARACTERS = 26
STATIC_TEXT_MAX_WORDS = 5
CAPTION_MAX_WORDS = 3
# Lip-sync timing. The mouth opening is drawn from the voice, so these catch timing mistakes only.
# The five renders measure a correlation of 0.60 to 0.65; 0.5 leaves room for a different script and still
# fails a mouth track that is cut loose from the voice. One frame at 30 fps is 33 ms.
LIP_SYNC_MIN_CORRELATION = 0.5
LIP_SYNC_MAX_SHIFT_FRAMES = 1
MIN_BLINKS = 3
# Picture motion: mean brightness change per frame (0-255 scale) in the quietest second of the video.
# The old renders (camera drift only) measured 0.026 to 0.073; the new ones are listed in the README.
# 0.15 is twice the best old value, so a render that falls back to a stationary picture fails.
MOTION_MIN_QUIETEST_SECOND = 0.15
# The script neither announces that the host is synthetic nor claims that she is a person.
IDENTITY_CLAIM = re.compile(
    r"\bI'm (Vera, )?an AI\b|\bI am an AI\b|\bI'm not real\b|\bI'm real\b|\breal person\b"
    r"|\bI'm (a )?human\b|\bAI[- ]generated\b|\bAI host\b",
    re.IGNORECASE,
)


def word_count(lines):
    return sum(len(line.split()) for line in lines)


def script_gates(data):
    """Return a list of (gate name, passed, detail)."""
    episodes = data["episodes"]
    results = []

    bad_sources = [
        episode["id"]
        for episode in episodes
        if not urlparse(episode["source"]["url"]).hostname.endswith(OFFICIAL_DOMAINS)
    ]
    results.append(("1 official source domain", not bad_sources, bad_sources))

    lengths = {episode["id"]: word_count(episode["narration"]) for episode in episodes}
    out_of_range = {key: value for key, value in lengths.items() if not 85 <= value <= 125}
    results.append(("2 narration 85-125 words", not out_of_range, lengths))

    off_script = [
        episode["id"]
        for episode in episodes
        if IDENTITY_CLAIM.search(" ".join(episode["narration"]))
        or episode["narration"][-1] != data["signoff"]
    ]
    results.append(("3 sign-off last, no identity claim in narration", not off_script, off_script))

    duplicates = []
    for label, values in (
        ("first line", [episode["narration"][0] for episode in episodes]),
        ("card text", [episode["card"]["text"] for episode in episodes]),
        ("source", [episode["source"]["url"] for episode in episodes]),
        ("pillar", [episode["pillar"] for episode in episodes]),
    ):
        if len(set(values)) != len(values):
            duplicates.append(label)
    results.append(("4 no repeated first line, card, source or pillar", not duplicates, duplicates))

    statistics = [
        episode["id"]
        for episode in episodes
        if re.search(r"%|percent|million|billion|trillion", " ".join(episode["narration"]), re.IGNORECASE)
    ]
    results.append(("5 no unsourced statistics in narration", not statistics, statistics))

    bad_captions = [
        episode["id"]
        for episode in episodes
        if len(episode["caption"]) > 300
        or episode["source"]["url"] not in episode["caption"]
        or IDENTITY_CLAIM.search(episode["caption"])
    ]
    results.append(("6 caption <= 300 chars, carries the source link, no identity claim", not bad_captions, bad_captions))

    long_lines = [
        f"{episode['id']}:{index}"
        for episode in episodes
        for index, line in enumerate(episode["narration"])
        if len(line.split()) > 24
    ]
    results.append(("7 no spoken line over 24 words", not long_lines, long_lines))
    return results


def link_gate(data):
    import requests

    failures = []
    for episode in data["episodes"]:
        url = episode["source"]["url"]
        try:
            status = requests.get(url, headers={"User-Agent": BROWSER_AGENT}, timeout=40).status_code
        except requests.exceptions.RequestException as error:
            status = type(error).__name__
        if status != 200:
            failures.append(f"{episode['id']}: {status}")
    return ("8 source links answer 200", not failures, failures)


def render_gate(data):
    failures = []
    rendered = 0
    for episode in data["episodes"]:
        report_path = ROOT / "output" / f"{episode['id']}.json"
        if not report_path.exists():
            continue
        rendered += 1
        report = json.loads(report_path.read_text(encoding="utf-8"))
        problems = []
        if not 30 <= report["duration_s"] <= 50:
            problems.append(f"duration {report['duration_s']}")
        if not report["has_audio_stream"] or report["audio_rms"] < 0.01:
            problems.append("silent or no audio")
        if report["max_words_per_caption"] > 3:
            problems.append("caption over 3 words")
        if problems:
            failures.append(f"{episode['id']}: {', '.join(problems)}")
    if rendered == 0:
        return ("9 renders: 30-50 s, audible, captions <= 3 words", False, ["nothing rendered yet"])
    return ("9 renders: 30-50 s, audible, captions <= 3 words", not failures, failures or f"{rendered} rendered")


def sync_and_sound_gate(data):
    """Captions follow the measured voice timing, and the mix sits at the level the platforms play at."""
    name = "10 renders: every caption word timed from the voice, -14 LUFS +/- 0.5, true peak <= -1 dBTP"
    failures = []
    rendered = 0
    for episode in data["episodes"]:
        report_path = ROOT / "output" / f"{episode['id']}.json"
        if not report_path.exists():
            continue
        rendered += 1
        report = json.loads(report_path.read_text(encoding="utf-8"))
        sync = report.get("caption_sync")
        sound = report.get("sound")
        if not sync or not sound:
            failures.append(f"{episode['id']}: rendered before caption timing and sound were measured")
            continue
        problems = []
        if sync["words_timed_from_the_voice"] < sync["words"]:
            problems.append(f"{sync['words'] - sync['words_timed_from_the_voice']} words not timed from the voice")
        if abs(sound["loudness_lufs"] - LOUDNESS_TARGET_LUFS) > LOUDNESS_TOLERANCE:
            problems.append(f"loudness {sound['loudness_lufs']} LUFS")
        if sound["true_peak_dbtp"] > TRUE_PEAK_LIMIT_DBTP:
            problems.append(f"true peak {sound['true_peak_dbtp']} dBTP")
        if problems:
            failures.append(f"{episode['id']}: {', '.join(problems)}")
    if rendered == 0:
        return (name, False, ["nothing rendered yet"])
    return (name, not failures, failures or f"{rendered} rendered")


def short_text_script_gate(data):
    """Every label that stays on the picture is short. The long scam message lives in the post caption."""
    name = (
        f"11 on-screen labels: chip, check chip and source credit present, each <= "
        f"{STATIC_TEXT_MAX_CHARACTERS} characters and <= {STATIC_TEXT_MAX_WORDS} words"
    )
    failures = []
    for episode in data["episodes"]:
        labels = {
            "pillar": episode.get("pillar"),
            "chip": episode.get("chip"),
            "check_chip": episode.get("check_chip"),
            "source.short": episode["source"].get("short"),
        }
        for label, value in labels.items():
            if not value:
                failures.append(f"{episode['id']}: {label} missing")
            elif len(value) > STATIC_TEXT_MAX_CHARACTERS or len(value.split()) > STATIC_TEXT_MAX_WORDS:
                failures.append(f"{episode['id']}: {label} too long ({value})")
    for label, value in (("signoff", data["signoff"]), ("handle", data["handle"])):
        if len(value) > STATIC_TEXT_MAX_CHARACTERS or len(value.split()) > STATIC_TEXT_MAX_WORDS:
            failures.append(f"{label} too long ({value})")
    return (name, not failures, failures)


def rendered_reports(data):
    """(episode id, report) for every episode that has been rendered."""
    reports = []
    for episode in data["episodes"]:
        report_path = ROOT / "output" / f"{episode['id']}.json"
        if report_path.exists():
            reports.append((episode["id"], json.loads(report_path.read_text(encoding="utf-8"))))
    return reports


def short_text_render_gate(data):
    name = (
        f"12 renders: no on-screen item over {STATIC_TEXT_MAX_CHARACTERS} characters or "
        f"{STATIC_TEXT_MAX_WORDS} words, captions word by word and <= {CAPTION_MAX_WORDS} words"
    )
    reports = rendered_reports(data)
    failures = []
    for episode_id, report in reports:
        text = report.get("on_screen_text")
        if not text:
            failures.append(f"{episode_id}: rendered before on-screen text was measured")
            continue
        problems = []
        if text["max_characters"] > STATIC_TEXT_MAX_CHARACTERS:
            problems.append(f"an item has {text['max_characters']} characters")
        if text["max_words"] > STATIC_TEXT_MAX_WORDS:
            problems.append(f"an item has {text['max_words']} words")
        if not text["captions_appear_word_by_word"]:
            problems.append("captions are not word by word")
        if text["max_words_per_caption"] > CAPTION_MAX_WORDS:
            problems.append(f"a caption has {text['max_words_per_caption']} words")
        if problems:
            failures.append(f"{episode_id}: {', '.join(problems)}")
    if not reports:
        return (name, False, ["nothing rendered yet"])
    return (name, not failures, failures or f"{len(reports)} rendered")


def lip_sync_gate(data):
    name = (
        f"13 renders: mouth follows the voice (correlation >= {LIP_SYNC_MIN_CORRELATION}, best shift within "
        f"{LIP_SYNC_MAX_SHIFT_FRAMES} frame), lips close on b/m/p, >= {MIN_BLINKS} blinks"
    )
    reports = rendered_reports(data)
    failures = []
    measured = {}
    for episode_id, report in reports:
        sync = report.get("lip_sync")
        if not sync:
            failures.append(f"{episode_id}: rendered without lip-sync")
            continue
        problems = []
        if sync["correlation"] < LIP_SYNC_MIN_CORRELATION:
            problems.append(f"correlation {sync['correlation']}")
        shift = sync["best_shift_frames"]
        if shift is None or abs(shift) > LIP_SYNC_MAX_SHIFT_FRAMES:
            problems.append(f"mouth is {shift} frames off the voice")
        if sync["lip_closures"] < 1:
            problems.append("lips never close")
        if report.get("blinks", 0) < MIN_BLINKS:
            problems.append(f"{report.get('blinks', 0)} blinks")
        if problems:
            failures.append(f"{episode_id}: {', '.join(problems)}")
        measured[episode_id] = sync["correlation"]
    if not reports:
        return (name, False, ["nothing rendered yet"])
    return (name, not failures, failures or measured)


def motion_gate(data):
    name = f"14 renders: the picture keeps moving (quietest second >= {MOTION_MIN_QUIETEST_SECOND} change per frame)"
    reports = rendered_reports(data)
    failures = []
    measured = {}
    for episode_id, report in reports:
        motion = report.get("picture_motion")
        if not motion:
            failures.append(f"{episode_id}: rendered before picture motion was measured")
            continue
        if motion["quietest_second"] < MOTION_MIN_QUIETEST_SECOND:
            failures.append(f"{episode_id}: quietest second {motion['quietest_second']}")
        measured[episode_id] = motion["quietest_second"]
    if not reports:
        return (name, False, ["nothing rendered yet"])
    return (name, not failures, failures or measured)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--links", action="store_true", help="also fetch every source link")
    arguments = parser.parse_args()
    data = json.loads((ROOT / "episodes.json").read_text(encoding="utf-8"))
    results = script_gates(data)
    if arguments.links:
        results.append(link_gate(data))
    results.append(render_gate(data))
    results.append(sync_and_sound_gate(data))
    results.append(short_text_script_gate(data))
    results.append(short_text_render_gate(data))
    results.append(lip_sync_gate(data))
    results.append(motion_gate(data))
    for name, passed, detail in results:
        print(f"{'PASS' if passed else 'FAIL'}  {name}  {detail if detail else ''}")
    passed_count = sum(1 for _, passed, _ in results if passed)
    print(f"gates {passed_count}/{len(results)}")
    return 0 if passed_count == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
