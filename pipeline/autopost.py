"""Schedule rendered Not Real Vera episodes to YouTube Shorts, Instagram Reels and TikTok through Buffer.

    python pipeline/autopost.py check            # which channels are connected, which videos are reachable
    python pipeline/autopost.py approve ep01     # you watched it and it may go out ("all" approves every render)
    python pipeline/autopost.py publish          # copy renders to media/ and push, so Buffer can fetch them
    python pipeline/autopost.py plan             # what would be scheduled, and what is blocking the rest
    python pipeline/autopost.py post             # dry run: prints the exact request, sends nothing
    python pipeline/autopost.py post --live      # really schedule (one episode per run unless --count N)

Safe by default: nothing is sent without --live, nothing unapproved is sent, and nothing is sent twice
(state/posted.json remembers every scheduled post). Field names follow docs/buffer_schema.txt, which was
read from Buffer's live API.
"""
import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import buffer_client  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "autopost.config.json"
STATE_PATH = ROOT / "state" / "posted.json"
STAGGER_MINUTES = 10
CREATE_POST = """
mutation CreatePost($input: CreatePostInput!) {
  createPost(input: $input) {
    ... on PostActionSuccess { post { id externalLink } }
    ... on MutationError { message }
  }
}
"""


def load_json(path, default):
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return default


def save_state(state):
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8", newline="\n")


def load_state():
    state = load_json(STATE_PATH, {})
    state.setdefault("approved", [])
    state.setdefault("posts", {})
    return state


def iso_utc(moment):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def parse_iso(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def media_url(config, episode_id):
    return config["media_base_url"].rstrip("/") + f"/{episode_id}.mp4"


def media_reachable(url, head=requests.head):
    """Buffer downloads the video itself, so the link must be public, answer 200 and be a video."""
    try:
        response = head(url, allow_redirects=True, timeout=30)
    except requests.exceptions.RequestException as error:
        return False, type(error).__name__
    content_type = response.headers.get("content-type", "")
    if response.status_code != 200:
        return False, f"HTTP {response.status_code}"
    if "video" not in content_type:
        return False, f"content-type {content_type or 'missing'}"
    return True, "ok"


def post_text(episode):
    tags = " ".join("#" + tag for tag in episode["hashtags"])
    return f"{episode['caption']}\n\n{episode['source']['url']}\n\n{tags}"


def build_post_input(episode, channel, video_url, due_at):
    """One CreatePostInput. The AI-generated flag is set on every platform; that is not optional for this channel."""
    post_input = {
        "channelId": channel["id"],
        "text": post_text(episode),
        "schedulingType": "automatic",
        "mode": "customScheduled",
        "dueAt": iso_utc(due_at),
        "needsApproval": False,
        "assets": [{"video": {"url": video_url, "metadata": {"title": episode["title"]}}}],
    }
    service = channel["service"]
    if service == "youtube":
        post_input["metadata"] = {
            "youtube": {
                "title": (episode["title"] + " #Shorts")[:100],
                "privacy": "public",
                "madeForKids": False,
                "isAiGenerated": True,
            }
        }
    elif service == "instagram":
        post_input["metadata"] = {"instagram": {"type": "reel", "shouldShareToFeed": True, "isAiGenerated": True}}
    elif service == "tiktok":
        post_input["metadata"] = {"tiktok": {"title": episode["title"][:90], "isAiGenerated": True}}
    else:
        raise ValueError(f"unsupported service: {service}")
    return post_input


def new_slots(config, state, now_utc):
    """Yield one posting time per day at the configured local hour, after anything already scheduled."""
    zone = timezone(timedelta(hours=config["utc_offset_hours"]))
    hour, minute = (int(part) for part in config["post_time"].split(":"))
    local_now = now_utc.astimezone(zone)
    candidate = local_now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate < local_now + timedelta(minutes=30):
        candidate += timedelta(days=1)
    taken_days = {parse_iso(entry["slot"]).astimezone(zone).date() for entry in state["posts"].values()}
    while True:
        if candidate.date() not in taken_days:
            yield candidate
        candidate += timedelta(days=1)


def plan_actions(config, state, episodes, channels, rendered, now_utc, count, media_ok):
    """Decide what to schedule. Returns action dicts with status 'ready' or 'blocked' and a plain reason."""
    connected = {channel["service"]: channel for channel in channels if not channel["disconnected"]}
    slots = new_slots(config, state, now_utc)
    actions = []
    taken = 0
    for episode in episodes:
        episode_id = episode["id"]
        missing = [service for service in config["services"] if f"{episode_id}:{service}" not in state["posts"]]
        if not missing:
            continue
        if taken == count:
            break
        blocked_reason = None
        if episode_id not in rendered:
            blocked_reason = "not rendered yet (run make_episode.py)"
        elif episode_id not in state["approved"]:
            blocked_reason = "not approved (watch it, then run: autopost.py approve " + episode_id + ")"
        else:
            reachable, detail = media_ok(media_url(config, episode_id))
            if not reachable:
                blocked_reason = f"video link not public yet ({detail}); run: autopost.py publish"
        if blocked_reason:
            actions.append({"episode": episode_id, "service": "all", "status": "blocked", "reason": blocked_reason})
            continue
        taken += 1
        earlier = [
            parse_iso(state["posts"][f"{episode_id}:{service}"]["slot"])
            for service in config["services"]
            if f"{episode_id}:{service}" in state["posts"]
        ]
        slot = earlier[0] if earlier and earlier[0] > now_utc + timedelta(minutes=30) else next(slots)
        for index, service in enumerate(config["services"]):
            if service not in missing:
                continue
            if service not in connected:
                actions.append(
                    {
                        "episode": episode_id,
                        "service": service,
                        "status": "blocked",
                        "reason": f"no connected {service} channel on this Buffer login",
                    }
                )
                continue
            due_at = slot + timedelta(minutes=STAGGER_MINUTES * index)
            actions.append(
                {
                    "episode": episode_id,
                    "service": service,
                    "status": "ready",
                    "slot": iso_utc(slot),
                    "input": build_post_input(episode, connected[service], media_url(config, episode_id), due_at),
                }
            )
    return actions


def execute(actions, state, live, send, now_utc):
    """Send the ready actions when live; record each success so it can never be sent twice."""
    results = []
    for action in actions:
        if action["status"] != "ready":
            results.append({**action, "result": "skipped"})
            continue
        if not live:
            results.append({**action, "result": "dry run, nothing sent"})
            continue
        payload = send(action["input"])
        outcome = ((payload.get("data") or {}).get("createPost")) or {}
        post = outcome.get("post")
        if post and post.get("id"):
            state["posts"][f"{action['episode']}:{action['service']}"] = {
                "postId": post["id"],
                "slot": action["slot"],
                "dueAt": action["input"]["dueAt"],
                "createdAt": iso_utc(now_utc),
            }
            results.append({**action, "result": "scheduled", "postId": post["id"]})
        else:
            errors = payload.get("errors") or [{}]
            message = outcome.get("message") or errors[0].get("message") or "unknown error"
            results.append({**action, "result": f"rejected: {message}"})
    return results


def rendered_ids():
    return {path.stem for path in (ROOT / "output").glob("ep*.mp4")}


def describe(results):
    for item in results:
        if item["status"] == "blocked":
            print(f"BLOCKED  {item['episode']}  {item['service']}: {item['reason']}")
        else:
            print(f"{item.get('result', 'ready').upper():<24} {item['episode']}  {item['service']}  due {item['input']['dueAt']}")


def command_check(config, state, episodes):
    key, source = buffer_client.load_api_key()
    print(f"Buffer key: found in {source}")
    channels = buffer_client.list_channels(key)
    for channel in channels:
        print(f"  channel  {channel['service']:<10} {channel['name']}  {'DISCONNECTED' if channel['disconnected'] else 'connected'}")
    connected = {channel["service"] for channel in channels if not channel["disconnected"]}
    missing = [service for service in config["services"] if service not in connected]
    for episode_id in sorted(rendered_ids()):
        reachable, detail = media_reachable(media_url(config, episode_id))
        approved = "approved" if episode_id in state["approved"] else "not approved"
        print(f"  video    {episode_id}  {media_url(config, episode_id)}  {detail}  {approved}")
    if missing:
        print("NOT READY: connect these in Buffer first: " + ", ".join(missing))
        return 2
    print("READY: all three channels are connected")
    return 0


def publishable_ids(rendered, approved):
    """Episodes that may be copied to the public media folder: rendered and approved by a human."""
    return sorted(set(rendered) & set(approved))


def command_publish(state):
    chosen = publishable_ids(rendered_ids(), state["approved"])
    if not chosen:
        print("Nothing approved yet. Watch a render, then run: autopost.py approve ep01")
        return 1
    media = ROOT / "media"
    media.mkdir(exist_ok=True)
    for episode_id in chosen:
        video = ROOT / "output" / f"{episode_id}.mp4"
        shutil.copy2(video, media / video.name)
        print(f"copied {video.name} to media/")
    for git_arguments in (["add", "media"], ["commit", "-m", "Publish rendered episodes"], ["push"]):
        completed = subprocess.run(["git", *git_arguments], cwd=ROOT, capture_output=True, text=True)
        print(f"git {git_arguments[0]}: exit {completed.returncode} {completed.stderr.strip()[:200]}")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Not Real Vera autoposter (Buffer)")
    parser.add_argument("command", choices=["check", "approve", "publish", "plan", "post"])
    parser.add_argument("episode", nargs="?", help="for approve: an episode id, or 'all'")
    parser.add_argument("--live", action="store_true", help="really schedule the posts")
    parser.add_argument("--count", type=int, default=1, help="episodes to schedule in this run")
    arguments = parser.parse_args()

    config = load_json(CONFIG_PATH, None)
    state = load_state()
    episodes = json.loads((ROOT / "episodes.json").read_text(encoding="utf-8"))["episodes"]
    try:
        if arguments.command == "check":
            return command_check(config, state, episodes)
        if arguments.command == "publish":
            return command_publish(state)
        if arguments.command == "approve":
            chosen = sorted(rendered_ids()) if arguments.episode == "all" else [arguments.episode]
            unknown = [episode_id for episode_id in chosen if episode_id not in rendered_ids()]
            if unknown or not chosen:
                print("not rendered, cannot approve: " + ", ".join(str(item) for item in unknown or ["(nothing)"]))
                return 1
            state["approved"] = sorted(set(state["approved"]) | set(chosen))
            save_state(state)
            print("approved: " + ", ".join(state["approved"]))
            return 0
        key, _ = buffer_client.load_api_key()
        channels = buffer_client.list_channels(key)
        now_utc = datetime.now(timezone.utc)
        actions = plan_actions(
            config, state, episodes, channels, rendered_ids(), now_utc, arguments.count, media_reachable
        )
        live = arguments.command == "post" and arguments.live
        results = execute(
            actions,
            state,
            live,
            lambda post_input: buffer_client.graphql(key, CREATE_POST, {"input": post_input}),
            now_utc,
        )
        if live:
            save_state(state)
        describe(results)
        if arguments.command == "post" and not live:
            for item in results:
                if item["status"] == "ready":
                    print(json.dumps(item["input"], indent=2))
            print("Dry run. Add --live to really schedule.")
        if not results:
            print("Nothing to do: every episode is already scheduled.")
        return 0
    except buffer_client.BufferError as error:
        print(f"Buffer problem: {error}")
        return 3


if __name__ == "__main__":
    sys.exit(main())
