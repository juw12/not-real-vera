"""Objective gates for the Vera Checks (repo: not-real-vera) scripts and renders.

    python tools/gates.py            # script gates and render gates (length, captions, caption timing, sound)
    python tools/gates.py --links    # also check that every source link answers HTTP 200
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
    for name, passed, detail in results:
        print(f"{'PASS' if passed else 'FAIL'}  {name}  {detail if detail else ''}")
    passed_count = sum(1 for _, passed, _ in results if passed)
    print(f"gates {passed_count}/{len(results)}")
    return 0 if passed_count == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
