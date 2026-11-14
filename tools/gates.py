"""Objective gates for Not Real Vera scripts and renders.

    python tools/gates.py            # script gates and render gates
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

    undisclosed = [
        episode["id"]
        for episode in episodes
        if not re.search(r"\bAI\b", " ".join(episode["narration"][:2]))
        or episode["narration"][-1] != data["signoff"]
    ]
    results.append(("3 AI disclosed in first two lines, sign-off last", not undisclosed, undisclosed))

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
        if len(episode["caption"]) > 300 or "AI-generated" not in episode["caption"]
    ]
    results.append(("6 caption <= 300 chars and says AI-generated", not bad_captions, bad_captions))

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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--links", action="store_true", help="also fetch every source link")
    arguments = parser.parse_args()
    data = json.loads((ROOT / "episodes.json").read_text(encoding="utf-8"))
    results = script_gates(data)
    if arguments.links:
        results.append(link_gate(data))
    results.append(render_gate(data))
    for name, passed, detail in results:
        print(f"{'PASS' if passed else 'FAIL'}  {name}  {detail if detail else ''}")
    passed_count = sum(1 for _, passed, _ in results if passed)
    print(f"gates {passed_count}/{len(results)}")
    return 0 if passed_count == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
