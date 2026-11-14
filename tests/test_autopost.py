"""Offline tests for the autoposter. No network, no Buffer key needed.

    python -m unittest discover -s tests -v
"""
import json
import re
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
import autopost  # noqa: E402

CONFIG = {
    "media_base_url": "https://example.test/media",
    "services": ["youtube", "instagram", "tiktok"],
    "post_time": "19:00",
    "utc_offset_hours": -5,
}
CHANNELS = [
    {"id": "yt1", "name": "Vera YT", "service": "youtube", "disconnected": False},
    {"id": "ig1", "name": "Vera IG", "service": "instagram", "disconnected": False},
    {"id": "tt1", "name": "Vera TT", "service": "tiktok", "disconnected": False},
]
NOW = datetime(2026, 11, 14, 6, 0, tzinfo=timezone.utc)
EPISODES = json.loads((ROOT / "episodes.json").read_text(encoding="utf-8"))["episodes"]


def schema_fields():
    """Field names per input type, read from the schema that was pulled from Buffer's live API."""
    fields = {}
    for line in (ROOT / "docs" / "buffer_schema.txt").read_text(encoding="utf-8").splitlines():
        match = re.match(r"input (\w+) \{ (.*) \}", line)
        if match:
            fields[match.group(1)] = {
                part.split(":")[0].strip(): part.split(":")[1].strip()
                for part in match.group(2).split(";")
                if ":" in part
            }
    return fields


def always_reachable(url):
    return True, "ok"


def fresh_state(approved=("ep01", "ep02")):
    return {"approved": list(approved), "posts": {}}


def plan(state, channels=CHANNELS, count=1, media_ok=always_reachable, rendered=("ep01", "ep02")):
    return autopost.plan_actions(CONFIG, state, EPISODES, channels, set(rendered), NOW, count, media_ok)


class PostInputTests(unittest.TestCase):
    def test_every_field_exists_in_the_live_buffer_schema(self):
        fields = schema_fields()
        metadata_types = {
            "youtube": "YoutubePostMetadataInput",
            "instagram": "InstagramPostMetadataInput",
            "tiktok": "TikTokPostMetadataInput",
        }
        for channel in CHANNELS:
            post_input = autopost.build_post_input(EPISODES[0], channel, "https://example.test/media/ep01.mp4", NOW)
            self.assertLessEqual(set(post_input), set(fields["CreatePostInput"]))
            service = channel["service"]
            self.assertEqual(list(post_input["metadata"]), [service])
            self.assertLessEqual(set(post_input["metadata"][service]), set(fields[metadata_types[service]]))
            video = post_input["assets"][0]["video"]
            self.assertLessEqual(set(video), set(fields["VideoAssetInput"]))
            self.assertLessEqual(set(video["metadata"]), set(fields["VideoMetadataInput"]))

    def test_required_fields_are_always_sent(self):
        fields = schema_fields()
        required = {name for name, signature in fields["CreatePostInput"].items() if signature.endswith("!")}
        for channel in CHANNELS:
            post_input = autopost.build_post_input(EPISODES[0], channel, "https://example.test/media/ep01.mp4", NOW)
            self.assertLessEqual(required, set(post_input))
        instagram = autopost.build_post_input(EPISODES[0], CHANNELS[1], "u", NOW)["metadata"]["instagram"]
        self.assertEqual(instagram["type"], "reel")
        self.assertIn("shouldShareToFeed", instagram)

    def test_platform_ai_label_is_set_on_every_platform(self):
        for channel in CHANNELS:
            post_input = autopost.build_post_input(EPISODES[0], channel, "u", NOW)
            self.assertTrue(post_input["metadata"][channel["service"]]["isAiGenerated"])

    def test_youtube_title_fits_and_is_not_for_kids(self):
        youtube = autopost.build_post_input(EPISODES[0], CHANNELS[0], "u", NOW)["metadata"]["youtube"]
        self.assertLessEqual(len(youtube["title"]), 100)
        self.assertFalse(youtube["madeForKids"])


class PlanningTests(unittest.TestCase):
    def test_first_slot_is_today_at_19_local_and_platforms_are_staggered(self):
        actions = plan(fresh_state())
        self.assertEqual([action["service"] for action in actions], ["youtube", "instagram", "tiktok"])
        self.assertEqual(actions[0]["input"]["dueAt"], "2026-11-15T00:00:00.000Z")
        self.assertEqual(actions[2]["input"]["dueAt"], "2026-11-15T00:20:00.000Z")

    def test_one_episode_per_day(self):
        actions = plan(fresh_state(), count=2)
        days = sorted({action["slot"] for action in actions})
        self.assertEqual(days, ["2026-11-15T00:00:00.000Z", "2026-11-16T00:00:00.000Z"])

    def test_unapproved_episode_is_blocked(self):
        actions = plan(fresh_state(approved=()))
        self.assertTrue(all(action["status"] == "blocked" for action in actions))
        self.assertIn("not approved", actions[0]["reason"])

    def test_unreachable_video_blocks_the_episode(self):
        actions = plan(fresh_state(), media_ok=lambda url: (False, "HTTP 404"))
        self.assertEqual(actions[0]["status"], "blocked")
        self.assertIn("HTTP 404", actions[0]["reason"])

    def test_missing_channel_blocks_only_that_platform(self):
        actions = plan(fresh_state(), channels=CHANNELS[:1])
        statuses = {action["service"]: action["status"] for action in actions}
        self.assertEqual(statuses, {"youtube": "ready", "instagram": "blocked", "tiktok": "blocked"})

    def test_disconnected_channel_counts_as_missing(self):
        broken = [dict(CHANNELS[0], disconnected=True)] + CHANNELS[1:]
        statuses = {action["service"]: action["status"] for action in plan(fresh_state(), channels=broken)}
        self.assertEqual(statuses["youtube"], "blocked")


class ExecuteTests(unittest.TestCase):
    def setUp(self):
        self.sent = []

    def send_ok(self, post_input):
        self.sent.append(post_input)
        return {"data": {"createPost": {"post": {"id": f"post{len(self.sent)}", "externalLink": None}}}}

    def test_dry_run_sends_nothing_and_records_nothing(self):
        state = fresh_state()
        autopost.execute(plan(state), state, False, self.send_ok, NOW)
        self.assertEqual(self.sent, [])
        self.assertEqual(state["posts"], {})

    def test_live_run_records_posts_and_a_second_run_sends_nothing_new(self):
        state = fresh_state(approved=("ep01",))
        autopost.execute(plan(state), state, True, self.send_ok, NOW)
        self.assertEqual(len(self.sent), 3)
        self.assertEqual(sorted(state["posts"]), ["ep01:instagram", "ep01:tiktok", "ep01:youtube"])
        autopost.execute(plan(state), state, True, self.send_ok, NOW)
        self.assertEqual(len(self.sent), 3)

    def test_next_episode_goes_to_the_next_day(self):
        state = fresh_state()
        autopost.execute(plan(state), state, True, self.send_ok, NOW)
        second = plan(state)
        self.assertEqual({action["episode"] for action in second}, {"ep02"})
        self.assertEqual(second[0]["slot"], "2026-11-16T00:00:00.000Z")

    def test_rejected_post_is_not_recorded_and_is_retried_in_the_same_slot(self):
        state = fresh_state(approved=("ep01",))

        def send_mixed(post_input):
            if "tiktok" in post_input["metadata"]:
                return {"data": {"createPost": {"message": "TikTok needs reconnecting"}}}
            return self.send_ok(post_input)

        results = autopost.execute(plan(state), state, True, send_mixed, NOW)
        self.assertIn("TikTok needs reconnecting", results[2]["result"])
        self.assertNotIn("ep01:tiktok", state["posts"])
        retry = plan(state)
        self.assertEqual([action["service"] for action in retry], ["tiktok"])
        self.assertEqual(retry[0]["slot"], "2026-11-15T00:00:00.000Z")


class MediaCheckTests(unittest.TestCase):
    class FakeResponse:
        def __init__(self, status_code, content_type):
            self.status_code = status_code
            self.headers = {"content-type": content_type}

    def test_only_a_public_video_passes(self):
        cases = [
            (200, "video/mp4", True),
            (404, "text/html", False),
            (200, "text/html", False),
        ]
        for status_code, content_type, expected in cases:
            reachable, _ = autopost.media_reachable(
                "https://example.test/x.mp4", head=lambda *a, **k: self.FakeResponse(status_code, content_type)
            )
            self.assertEqual(reachable, expected)


class PublishGateTests(unittest.TestCase):
    def test_only_approved_renders_are_publishable(self):
        rendered = {"ep01", "ep02", "ep03"}
        self.assertEqual(autopost.publishable_ids(rendered, []), [])
        self.assertEqual(autopost.publishable_ids(rendered, ["ep02"]), ["ep02"])
        self.assertEqual(autopost.publishable_ids(rendered, ["ep03", "ep01", "ep09"]), ["ep01", "ep03"])


if __name__ == "__main__":
    unittest.main()
