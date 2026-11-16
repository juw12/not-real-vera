"""Every spoken line is its own shot, the camera is smooth inside a shot, and movement is a number."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "pipeline"))

import camera  # noqa: E402

FPS = 30
LINE_STARTS = [0.0, 3.0, 7.5, 12.0, 16.0]


def path(speech=None):
    return camera.CameraPath(20 * FPS, FPS, LINE_STARTS, 12.0, seed=11, speech=speech)


def test_the_framing_cuts_at_the_start_of_every_line_after_the_first():
    assert path().cuts == [90, 225, 360, 480]


def test_a_cut_jumps_and_the_rest_of_the_shot_glides():
    camera_path = path()
    report = camera_path.smoothness(1080, 1920)
    assert report["cuts"] == 4
    track = camera_path.point_track(1080, 1920, 300.0)
    steps = np.linalg.norm(np.diff(track, axis=0), axis=1)
    for cut in camera_path.cuts:
        assert steps[cut - 1] > 3 * report["max_step_px_per_frame"]
    assert report["max_step_px_per_frame"] < 1.5
    assert report["max_step_change_px_per_frame2"] < 0.2


def test_the_head_keeps_moving_and_nods_on_loud_syllables():
    quiet = path()
    assert quiet.smoothness(1080, 1920)["head_travel_px"] > 4
    assert quiet.smoothness(1080, 1920)["head_roll_range_deg"] > 0.8
    speech = np.zeros(20 * FPS)
    speech[150:156] = 1.0
    loud = path(speech)
    dip = loud.head_y - quiet.head_y
    assert dip[150:158].max() > 0.3 * camera.NOD_PX
    assert abs(dip[400]) < 0.05


def test_the_sign_off_shot_pushes_in_until_the_last_frame():
    end_start = LINE_STARTS[-1]
    plain = path()
    pushed = camera.CameraPath(20 * FPS, FPS, LINE_STARTS, 12.0, seed=11, end_start=end_start)
    extra = pushed.zoom - plain.zoom
    first_end_frame = int(end_start * FPS)
    assert np.allclose(extra[:first_end_frame], 0.0)  # nothing changes before the sign-off
    assert abs(extra[-1] - camera.END_PUSH_IN) < 1e-9  # the whole push has arrived on the last frame
    steps = np.diff(extra[first_end_frame:])
    assert steps.min() > 0  # still closing in on every frame, also after her last word
    assert np.allclose(steps, steps[0])  # at a steady speed
    assert pushed.cuts == plain.cuts  # the push starts on the sign-off cut and adds no cut of its own


def test_same_seed_same_path():
    assert np.array_equal(path().zoom, path().zoom)
    other = camera.CameraPath(20 * FPS, FPS, LINE_STARTS, 12.0, seed=12)
    assert not np.array_equal(path().shift_x, other.shift_x)


def test_motion_meter_reads_zero_for_a_stationary_picture():
    meter = camera.MotionMeter()
    random = np.random.default_rng(1)
    frame = random.integers(0, 255, (1920, 1080, 3), dtype=np.uint8)
    for _ in range(45):
        meter.add(frame)
    report = meter.report(FPS)
    assert report["mean_change_per_frame"] == 0.0
    assert report["quietest_second"] == 0.0
    assert report["camera_cuts_seen"] == 0


def test_motion_meter_sees_movement_a_freeze_and_a_cut():
    meter = camera.MotionMeter()
    columns = np.arange(1080, dtype=np.float32)
    for index in range(120):
        offset = min(index, 60) * 3.0  # slides for two seconds, then stands still for two
        stripes = (127 + 100 * np.sin((columns + offset) / 40.0)).astype(np.uint8)
        frame = np.broadcast_to(stripes, (1920, 1080)).copy()
        if index >= 100:
            frame = 255 - frame  # a hard cut to a different picture
        meter.add(frame)
    report = meter.report(FPS)
    assert report["mean_change_per_frame"] > 1.0
    assert report["quietest_second"] < 0.01
    assert report["camera_cuts_seen"] == 1
