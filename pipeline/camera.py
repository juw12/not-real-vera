"""Camera work and body movement for the presenter still, all on the CPU.

Three parts:

CameraPath   the camera and head pose for every frame of one episode. Every spoken line is its own shot: the
             framing jumps at the start of the line (a jump cut, the way talking-head shorts are edited) and
             creeps in slowly until the next one. Hand-held drift, a slow push-in, her breathing and her head
             movement (slow wander, a small nod on loud syllables) sit on top. The sign-off shot pushes in
             faster, so the picture is still moving after her last word.
StillRig     turns one still into moving frames. A depth estimate of the picture (MiDaS small, ONNX) lets the
             room slide behind the presenter as the camera drifts, her chest rises and falls a few pixels, and
             her head shifts and tilts as one piece about the base of her neck. With face landmarks
             (tools/face_landmarks.py) her mouth, eyelids and eyebrows move too (pipeline/face_rig.py).
MotionMeter  measures how much the picture changes from frame to frame, so "it moves" is a number.

What this cannot do: turn her head, move her hands or make her gesture. That needs a talking-head model and
a GPU (tools/presenter_kit.py).
"""
import math
from pathlib import Path

import cv2
import numpy as np

import face_rig

ROOT = Path(__file__).resolve().parent.parent
DEPTH_MODEL = ROOT / "models" / "midas-small.onnx"
DEPTH_INPUT_SIZE = 256
DEPTH_MEAN = np.float32([0.485, 0.456, 0.406])
DEPTH_STD = np.float32([0.229, 0.224, 0.225])

BASE_ZOOM = 1.11  # head-room so drift, tilt and parallax never show the edge of the picture
PUSH_IN = 0.03  # extra zoom gained evenly from the first frame to the last
SHOT_ZOOMS = [0.0, 0.11, 0.02, 0.14, 0.05, 0.13]  # framing per spoken line, repeating; applied as a cut
SHOT_PANS = [0.0, 14.0, -12.0, 6.0, -6.0]  # px, per spoken line, repeating; applied as a cut
SHOT_CREEP, SHOT_CREEP_S = 0.02, 6.0  # zoom gained inside one shot, and the time it takes
CHECK_ZOOM = 0.03  # shots from the 10-second check onwards are this much closer
END_PUSH_IN = 0.06  # the sign-off shot closes in this much, at a steady speed, until the last frame
DRIFT_X_PX, DRIFT_Y_PX, DRIFT_TILT_DEG = 9.0, 6.0, 0.35
PARALLAX_X_PX, PARALLAX_Y_PX = 26.0, 10.0  # how far the far wall slides behind her face
BREATH_PX, BREATH_PERIOD_S = 3.2, 4.3
HEAD_X_PX, HEAD_Y_PX, HEAD_ROLL_DEG = 10.0, 6.0, 2.0  # size of the head's slow wander (typical: half of this)
HEAD_SHOT_PX, HEAD_SHOT_ROLL_DEG = 4.0, 0.6  # each shot starts with the head in a slightly different place
NOD_PX = 9.0  # the head dips this much on a syllable that is as loud as the voice gets
NOD_FAST_S, NOD_SLOW_S = 0.09, 0.9
FOCUS_Y = 0.26  # the zoom closes in on this height of the frame (her face)
MAP_STEP = 4  # the warp is worked out on a grid this much coarser than the frame, then enlarged
SUPERSAMPLE = 1.5  # the still is enlarged once, so zooming in does not soften it a second time

MOTION_BAND = (250, 900)  # rows of the 1080x1920 frame that hold her face and shoulders (no captions there)
MOTION_SHRINK = 4
MOTION_CUT_LEVEL = 12.0  # a change this large between two frames is a camera cut, not movement


def slow_wander(times, random, periods):
    """Smooth, never-repeating movement between -1 and 1: a few slow sine waves with random phases."""
    total = np.zeros_like(times)
    for period in periods:
        total += np.sin(2 * np.pi * times / period + random.uniform(0, 2 * np.pi))
    return total / len(periods)


def blur_in_time(values, seconds, fps):
    sigma = seconds * fps
    radius = int(math.ceil(3 * sigma))
    kernel = np.exp(-0.5 * (np.arange(-radius, radius + 1) / sigma) ** 2)
    return np.convolve(np.pad(values, radius, mode="edge"), kernel / kernel.sum(), mode="valid")


class CameraPath:
    """The camera pose and her head pose for every frame of one episode."""

    def __init__(self, total_frames, fps, line_starts, check_start, seed, speech=None, end_start=None):
        """speech: how loud the voice is per frame, 0 to 1 (pipeline/lipsync.py); drives the small nod.
        end_start: when the sign-off shot starts (s); from there the camera pushes in until the last frame,
        because she stops talking before the clip ends and the picture must not come to rest."""
        times = np.arange(total_frames) / fps
        random = np.random.default_rng(seed)
        line_starts = np.asarray(line_starts, dtype=np.float64)
        shot = np.clip(np.searchsorted(line_starts, times, side="right") - 1, 0, None)
        shot_age = np.clip(times - line_starts[shot], 0.0, SHOT_CREEP_S)
        self.fps = fps
        self.cuts = [int(index) for index in np.nonzero(np.diff(shot))[0] + 1]
        self.zoom = (
            BASE_ZOOM
            + PUSH_IN * times / max(times[-1], 1.0)
            + np.take(SHOT_ZOOMS, shot % len(SHOT_ZOOMS))
            + CHECK_ZOOM * (line_starts[shot] >= check_start)
            + SHOT_CREEP * shot_age / SHOT_CREEP_S
            + 0.006 * slow_wander(times, random, [9.0, 14.5])
        )
        if end_start is not None and end_start < times[-1]:
            self.zoom = self.zoom + END_PUSH_IN * np.clip(
                (times - end_start) / (times[-1] - end_start), 0.0, 1.0
            )
        self.shift_x = np.take(SHOT_PANS, shot % len(SHOT_PANS)) + DRIFT_X_PX * slow_wander(
            times, random, [6.1, 9.7, 15.3]
        )
        self.shift_y = DRIFT_Y_PX * slow_wander(times, random, [5.3, 8.9, 13.1])
        self.tilt = np.radians(DRIFT_TILT_DEG) * slow_wander(times, random, [7.7, 12.4])
        self.parallax_x = PARALLAX_X_PX * slow_wander(times, random, [8.3, 13.7])
        self.parallax_y = PARALLAX_Y_PX * slow_wander(times, random, [10.9, 17.3])
        self.breath = BREATH_PX * np.sin(2 * np.pi * times / BREATH_PERIOD_S)

        shots = len(line_starts)
        shot_x = random.uniform(-HEAD_SHOT_PX, HEAD_SHOT_PX, shots)
        shot_roll = np.radians(random.uniform(-HEAD_SHOT_ROLL_DEG, HEAD_SHOT_ROLL_DEG, shots))
        self.head_x = HEAD_X_PX * slow_wander(times, random, [3.1, 5.3, 8.9]) + shot_x[shot]
        self.head_y = HEAD_Y_PX * slow_wander(times, random, [2.7, 4.3, 7.1])
        self.head_roll = np.radians(HEAD_ROLL_DEG) * slow_wander(times, random, [3.7, 6.1, 9.4]) + shot_roll[shot]
        if speech is not None:
            speech = np.asarray(speech, dtype=np.float64)[:total_frames]
            speech = np.pad(speech, (0, total_frames - len(speech)))
            accent = blur_in_time(speech, NOD_FAST_S, fps) - blur_in_time(speech, NOD_SLOW_S, fps)
            self.head_y = self.head_y + NOD_PX * accent

    def point_track(self, width, height, below_focus_px):
        """Where a point of the still, this far below the zoom centre, lands in the frame, per frame (px)."""
        x = width / 2 + self.shift_x - self.zoom * np.sin(self.tilt) * below_focus_px
        y = height * FOCUS_Y + self.shift_y + self.zoom * np.cos(self.tilt) * below_focus_px
        return np.stack([x, y], axis=1)

    def smoothness(self, width, height):
        """Inside the shots (cuts are left out): the largest frame-to-frame step, and the largest change of
        that step, of a point 300 px below the zoom centre (about her collarbone). A jump in speed shows up
        as a large change of step."""
        step = np.diff(self.point_track(width, height, 300.0), axis=0)
        change = np.diff(step, axis=0)
        cut_steps = np.zeros(len(step), dtype=bool)
        cut_steps[[cut - 1 for cut in self.cuts]] = True
        cut_changes = cut_steps[1:] | cut_steps[:-1]
        return {
            "cuts": len(self.cuts),
            "max_step_px_per_frame": round(float(np.max(np.linalg.norm(step[~cut_steps], axis=1))), 3),
            "max_step_change_px_per_frame2": round(float(np.max(np.linalg.norm(change[~cut_changes], axis=1))), 4),
            "head_travel_px": round(float(np.ptp(self.head_x)), 1),
            "head_roll_range_deg": round(float(np.degrees(np.ptp(self.head_roll))), 2),
        }


def estimate_depth(picture):
    """Return nearness per pixel, 0 (far wall) to 1 (closest), or None when the depth model is not there."""
    if not DEPTH_MODEL.exists():
        return None
    import onnxruntime

    session = onnxruntime.InferenceSession(str(DEPTH_MODEL), providers=["CPUExecutionProvider"])
    small = cv2.resize(picture, (DEPTH_INPUT_SIZE, DEPTH_INPUT_SIZE), interpolation=cv2.INTER_AREA)
    tensor = ((small.astype(np.float32) / 255.0 - DEPTH_MEAN) / DEPTH_STD).transpose(2, 0, 1)[None]
    nearness = session.run(None, {session.get_inputs()[0].name: tensor})[0].squeeze().astype(np.float32)
    low, high = np.percentile(nearness, [2, 98])
    return np.clip((nearness - low) / max(high - low, 1e-6), 0.0, 1.0)


def ramp(values, start, end):
    """0 below start, 1 above end, smooth in between."""
    progress = np.clip((values - start) / (end - start), 0.0, 1.0)
    return progress * progress * (3.0 - 2.0 * progress)


class StillRig:
    """One still, ready to be filmed by a CameraPath."""

    def __init__(self, fitted_picture, face_box=None, face_points=None):
        """fitted_picture: RGB picture already covering the frame. face_box: (centre x, centre y, half
        width, half height) in frame pixels; guessed from the usual framing when it is not given.
        face_points: the 98 face landmarks in frame pixels; with them the face itself can move."""
        self.height, self.width = fitted_picture.shape[:2]
        big_size = (round(self.width * SUPERSAMPLE), round(self.height * SUPERSAMPLE))
        self.source = cv2.resize(fitted_picture, big_size, interpolation=cv2.INTER_LANCZOS4)
        self.face_rig = None
        if face_points is not None:
            points = (np.asarray(face_points, dtype=np.float64) + 0.5) * SUPERSAMPLE - 0.5
            self.face_rig = face_rig.FaceRig(self.source, points)
        if face_box is None:
            face_box = (self.width / 2, self.height * 0.2, self.width * 0.13, self.height * 0.1)
        face_x, face_y, face_half_width, face_half_height = face_box

        grid_width, grid_height = self.width // MAP_STEP, self.height // MAP_STEP
        columns = (np.arange(grid_width, dtype=np.float32) + 0.5) * MAP_STEP - 0.5
        rows = (np.arange(grid_height, dtype=np.float32) + 0.5) * MAP_STEP - 0.5
        self.grid_x, self.grid_y = np.meshgrid(columns, rows)

        nearness = estimate_depth(fitted_picture)
        self.has_depth = nearness is not None
        if self.has_depth:
            nearness = cv2.resize(nearness, (grid_width, grid_height), interpolation=cv2.INTER_CUBIC)
            nearness = cv2.GaussianBlur(nearness, (0, 0), 4.0)
            face_rows = slice(int((face_y - face_half_height) / MAP_STEP), int((face_y + face_half_height) / MAP_STEP))
            face_columns = slice(
                int((face_x - face_half_width) / MAP_STEP), int((face_x + face_half_width) / MAP_STEP)
            )
            face_nearness = float(np.median(nearness[face_rows, face_columns]))
            # Her face stays where the camera puts it; things behind her slide one way, things in front the other.
            relative_depth = nearness - face_nearness
            person = ramp(nearness, face_nearness - 0.30, face_nearness - 0.10)
        else:
            relative_depth = np.zeros((grid_height, grid_width), np.float32)
            person = np.zeros((grid_height, grid_width), np.float32)
        chin = face_y + face_half_height
        chest = ramp(self.grid_y, chin + 0.3 * face_half_height, chin + 1.8 * face_half_height)
        chest *= 1.0 - ramp(self.grid_y, chin + 3.0 * face_half_height, chin + 6.0 * face_half_height)
        # The head moves as one piece; the neck takes up the difference; the shoulders stay.
        head = 1.0 - ramp(self.grid_y, chin - 0.1 * face_half_height, chin + 1.5 * face_half_height)
        self.layers = np.dstack([relative_depth, chest * person, head * person]).astype(np.float32)
        self.focus = (self.width / 2, self.height * FOCUS_Y)
        self.neck = (float(face_x), float(chin + 0.9 * face_half_height))

    def describe(self):
        face = "rule-based lip-sync, blinks and eyebrows" if self.face_rig is not None else "no lip-sync"
        if self.has_depth:
            return f"still portrait with {face}, head movement, breathing and a jump-cut depth-parallax camera"
        return f"still portrait with {face} and a jump-cut camera (no depth model)"

    def frame(self, path, frame_index, face=None):
        """face: (mouth_open, mouth_wide, blink, brow) for this frame, or None to leave the face as it is."""
        index = min(frame_index, len(path.zoom) - 1)
        # Plain Python numbers: a numpy float64 would turn the float32 maps into float64, which remap refuses.
        zoom = float(path.zoom[index])
        tilt = float(path.tilt[index])
        cosine, sine = math.cos(tilt) / zoom, math.sin(tilt) / zoom
        focus_x, focus_y = self.focus
        from_x = self.grid_x - (focus_x + float(path.shift_x[index]))
        from_y = self.grid_y - (focus_y + float(path.shift_y[index]))
        still_x = focus_x + cosine * from_x + sine * from_y
        still_y = focus_y - sine * from_x + cosine * from_y
        # Read depth and body weights where the camera is looking, on the coarse grid.
        layers = cv2.remap(
            self.layers,
            (still_x + 0.5) / MAP_STEP - 0.5,
            (still_y + 0.5) / MAP_STEP - 0.5,
            cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_REPLICATE,
        )
        # Her head: every head pixel comes from where it was before the head shifted and tilted about the neck.
        roll = float(path.head_roll[index])
        neck_x, neck_y = self.neck
        moved_x = still_x - neck_x - float(path.head_x[index])
        moved_y = still_y - neck_y - float(path.head_y[index])
        head_from_x = neck_x + math.cos(roll) * moved_x + math.sin(roll) * moved_y
        head_from_y = neck_y - math.sin(roll) * moved_x + math.cos(roll) * moved_y
        head = layers[..., 2]
        parallax_x, parallax_y = float(path.parallax_x[index]), float(path.parallax_y[index])
        still_x += head * (head_from_x - still_x) + layers[..., 0] * parallax_x
        still_y += head * (head_from_y - still_y) + layers[..., 0] * parallax_y + layers[..., 1] * float(path.breath[index])
        size = (self.width, self.height)
        map_x = (cv2.resize(still_x, size, interpolation=cv2.INTER_LINEAR) + 0.5) * SUPERSAMPLE - 0.5
        map_y = (cv2.resize(still_y, size, interpolation=cv2.INTER_LINEAR) + 0.5) * SUPERSAMPLE - 0.5
        source = self.source
        if self.face_rig is not None and face is not None:
            source = self.face_rig.render(*face)
        return cv2.remap(source, map_x, map_y, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)


def move_clip_frame(frame, path, frame_index):
    """The same camera move for a presenter video frame (no depth layers, the clip brings its own movement)."""
    index = min(frame_index, len(path.zoom) - 1)
    height, width = frame.shape[:2]
    centre = (width / 2, height * FOCUS_Y)
    matrix = cv2.getRotationMatrix2D(centre, math.degrees(float(path.tilt[index])), float(path.zoom[index]))
    matrix[0, 2] += path.shift_x[index]
    matrix[1, 2] += path.shift_y[index]
    return cv2.warpAffine(frame, matrix, (width, height), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)


class MotionMeter:
    """How much the picture moves: the mean change of brightness between neighbouring frames (0-255 scale) in
    the band that holds her face and shoulders, after shrinking. A stationary picture scores near 0. The
    quietest one-second stretch is reported too, because a clip that moves on average can still freeze."""

    def __init__(self):
        self.previous = None
        self.changes = []

    def add(self, frame):
        """frame: a full 1080x1920 frame, RGB or already grey."""
        band = frame[MOTION_BAND[0]:MOTION_BAND[1]]
        if band.ndim == 3:
            band = cv2.cvtColor(band, cv2.COLOR_RGB2GRAY)
        size = (band.shape[1] // MOTION_SHRINK, band.shape[0] // MOTION_SHRINK)
        small = cv2.resize(band, size, interpolation=cv2.INTER_AREA).astype(np.float32)
        if self.previous is not None:
            self.changes.append(float(np.mean(np.abs(small - self.previous))))
        self.previous = small

    def report(self, fps):
        changes = np.asarray(self.changes)
        moving = changes[changes < MOTION_CUT_LEVEL]
        window = int(round(fps))
        starts = range(0, max(len(moving) - window, 1), window // 2)
        return {
            "frames": int(len(changes) + 1),
            "mean_change_per_frame": round(float(np.mean(moving)), 3),
            "quietest_second": round(min(float(np.mean(moving[start:start + window])) for start in starts), 3),
            "camera_cuts_seen": int(np.sum(changes >= MOTION_CUT_LEVEL)),
        }
