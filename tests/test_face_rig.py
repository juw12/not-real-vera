"""The face rig must leave the still alone at rest and move only what it is asked to move."""
import json
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import face_rig  # noqa: E402

FPS = 30


@pytest.fixture(scope="module")
def rig_and_points():
    record = json.loads((ROOT / "assets" / "outfits" / "landmarks.json").read_text(encoding="utf-8"))["base"]
    picture = cv2.cvtColor(cv2.imread(str(ROOT / "assets" / "outfits" / "base.jpg")), cv2.COLOR_BGR2RGB)
    assert [picture.shape[1], picture.shape[0]] == list(record["picture_size"])
    points = np.asarray(record["points"], dtype=np.float64)
    return face_rig.FaceRig(picture, points), points, picture


def box_around(points, numbers, margin):
    chosen = points[list(numbers)]
    left, top = np.floor(chosen.min(axis=0) - margin).astype(int)
    right, bottom = np.ceil(chosen.max(axis=0) + margin).astype(int)
    return slice(top, bottom), slice(left, right)


def changed(before, after, level=6):
    return np.abs(before.astype(np.int16) - after.astype(np.int16)).max(axis=2) > level


def test_every_picture_has_98_landmarks():
    records = json.loads((ROOT / "assets" / "outfits" / "landmarks.json").read_text(encoding="utf-8"))
    episodes = json.loads((ROOT / "episodes.json").read_text(encoding="utf-8"))["episodes"]
    for key in ["base"] + [episode["id"] for episode in episodes]:
        assert np.asarray(records[key]["points"]).shape == (98, 2), key


def test_the_rest_pose_is_the_still_itself(rig_and_points):
    rig, _, picture = rig_and_points
    rest = rig.render(0.0, 0.0, 0.0, 0.0)
    assert rest.shape == picture.shape
    assert np.abs(rest.astype(np.int16) - picture.astype(np.int16)).max() <= 2


def test_opening_the_mouth_shows_a_dark_gap_and_leaves_the_eyes_alone(rig_and_points):
    rig, points, picture = rig_and_points
    opened = rig.render(mouth_open=1.0).copy()
    inner_mouth = box_around(points, range(88, 96), 0)
    assert opened[inner_mouth].mean() < picture[inner_mouth].mean() - 4
    eyes = box_around(points, range(60, 76), 6)
    assert not changed(picture, opened)[eyes].any()


def test_opening_more_moves_the_chin_further(rig_and_points):
    rig, points, picture = rig_and_points
    lower_face = box_around(points, range(76, 96), 30)
    half = changed(picture, rig.render(mouth_open=0.5).copy())[lower_face].sum()
    full = changed(picture, rig.render(mouth_open=1.0).copy())[lower_face].sum()
    assert 0 < half < full


def test_pressing_the_lips_together_hides_the_teeth(rig_and_points):
    rig, points, picture = rig_and_points
    closed = rig.render(mouth_open=-1.0).copy()
    inner_mouth = box_around(points, range(88, 96), 0)
    brightest_before = np.percentile(picture[inner_mouth].min(axis=2), 95)
    brightest_after = np.percentile(closed[inner_mouth].min(axis=2), 95)
    assert brightest_after < brightest_before - 10


def test_a_blink_changes_the_eyes_and_nothing_else(rig_and_points):
    rig, points, picture = rig_and_points
    blinked = rig.render(blink=1.0).copy()
    difference = changed(picture, blinked)
    for eye in (range(60, 68), range(68, 76)):
        assert difference[box_around(points, eye, 0)].mean() > 0.2
    outside = difference.copy()
    outside[box_around(points, range(60, 68), 16)] = False
    outside[box_around(points, range(68, 76), 16)] = False
    assert not outside.any()


def test_a_blink_leaves_the_eyebrows_in_place(rig_and_points):
    """The eyelid skin that stretches during a blink ends at the brow's lower edge. Measured on these pictures
    it touches under 4 % of a brow's area (its lowest row of hairs), so the limit here is 6 %."""
    rig, points, picture = rig_and_points
    difference = changed(picture, rig.render(blink=1.0).copy())
    for brow in (range(33, 42), range(42, 51)):
        outline = np.round(points[list(brow)]).astype(np.int32)
        inside = np.zeros(difference.shape, dtype=np.uint8)
        cv2.fillPoly(inside, [outline], 1)
        assert inside.sum() > 200
        assert difference[inside == 1].mean() < 0.06


def test_raising_the_eyebrows_moves_them_and_not_the_mouth(rig_and_points):
    rig, points, picture = rig_and_points
    raised = rig.render(brow=1.0).copy()
    difference = changed(picture, raised)
    assert difference[box_around(points, range(33, 51), 4)].any()
    assert not difference[box_around(points, range(76, 96), 4)].any()


def test_blinks_and_brow_lifts_are_planned_for_the_whole_episode():
    line_starts = [0.0, 4.0, 9.0, 15.0]
    blink, brow, blinks = face_rig.expression_track(30 * FPS, FPS, line_starts, [8.5], seed=7)
    assert len(blink) == len(brow) == 30 * FPS
    assert 5 <= blinks <= 14
    assert blink.max() == 1.0 and blink.min() == 0.0
    assert np.mean(blink > 0) < 0.2
    for start in line_starts:
        assert brow[int((start + face_rig.BROW_AFTER_LINE_START_S) * FPS)] > 0.4
    again = face_rig.expression_track(30 * FPS, FPS, line_starts, [8.5], seed=7)
    assert np.array_equal(blink, again[0])
