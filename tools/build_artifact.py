"""Join the channel bible and the episode scripts into one markdown file for the outside judges.

    python tools/build_artifact.py hone/v0.md
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def episode_markdown(episode, signoff):
    lines = [
        f"### {episode['id']}: {episode['title']}",
        "",
        f"- Pillar: {episode['pillar']}",
        f"- Structure: {episode.get('format', 'confession and playbook')}",
        f"- On screen from frame one ({episode['card']['kind']}, sender \"{episode['card']['sender']}\"): "
        f"\"{episode['card']['text']}\"",
        f"- The 10-second check card: \"{episode['check']}\"",
        f"- Source shown on screen and linked in the caption: {episode['source']['name']} ({episode['source']['url']})",
    ]
    for extra in episode.get("extra_sources", []):
        lines.append(f"- Second source for this episode: {extra['name']} ({extra['url']})")
    lines.extend(
        [
            f"- Post caption: {episode['caption']}",
            "",
            "Spoken script, one line per breath:",
            "",
        ]
    )
    for number, text in enumerate(episode["narration"], start=1):
        lines.append(f"{number}. {text}")
    lines.append("")
    return "\n".join(lines)


def main():
    target = ROOT / sys.argv[1]
    data = json.loads((ROOT / "episodes.json").read_text(encoding="utf-8"))
    parts = [
        (ROOT / "channel_bible.md").read_text(encoding="utf-8").rstrip(),
        "",
        "---",
        "",
        "# The five scripts",
        "",
    ]
    parts.extend(episode_markdown(episode, data["signoff"]) for episode in data["episodes"])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("\n".join(parts), encoding="utf-8", newline="\n")
    print(f"wrote {target} ({target.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
