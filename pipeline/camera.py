"""Camera work for the presenter still, all on the CPU.

Two parts:

CameraPath  one smooth camera move for a whole episode. Every spoken line gets its own framing, and the
            camera glides between framings on a critically damped spring, so speed never jumps. A slow
            push-in and a little hand-held drift sit on top.
StillRig    turns one still into moving frames. A depth estimate of the picture (MiDaS small, ONNX) lets the
            room slide behind the presenter as the camera drifts, her chest rises and falls a few pixels, and
            her head sways a few pixels.

What this cannot do: move her lips, change her expression or make her gesture. That needs a talking-head
model and a GPU (tools/presenter_kit.py).
"""
import math
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
DEPTH_MODEL = ROOT / "models" / "midas-small.onnx"
DEPTH_INPUT_SIZE = 256
DEPTH_MEAN = np.float32([0.485, 0.456, 0.406])
DEPTH_STD = np.float32([0.229, 0.224, 0.225])

BASE_ZOOM = 1.085  # head-room so drift, tilt and parallax never show the edge of the picture
PUSH_IN = 0.035  # extra zoom gained evenly from the first frame to the last
LINE_ZOOMS = [0.0, 0.042, 0.014, 0.052]  # framing per spoken line, repeating
LINE_PANS = [0.0, 10.0, -8.0, 4.0]  # px
CHECK_ZOOM = 0.03  # the camera stays this much closer from the 10-second check onwards
SPRING_STIFFNESS = 5.5  # rad/s; a new framing settles in about 0.9 s without overshoot
DRIFT_X_PX, DRIFT_Y_PX, DRIFT_TILT_DEG = 6.0, 4.5, 0.22
PARALLAX_X_PX, PARALLAX_Y_PX = 20.0, 8.0  # how far the far wall slides behind her face
BREATH_PX, BREATH_PERIOD_S = 2.4, 4.3
SWAY_PX = 3.0
FOCUS_Y = 0.26  # the zoom closes in on this height of the frame (her face)
MAP_STEP = 4  # the warp is worked out on a grid this much coarser than the frame, then enlarged
SUPERSAMPLE = 1.5  # the still is enlarged once, so zooming in does not soften it a second time


def smooth_follow(targets, fps, stiffness=SPRING_STIFFNESS):
    """Follow a stepped target with a critically damped spring: position and speed stay continuous."""
    substeps = 4
    step = 1.0 / (fps * substeps)
    position = float(targets[0])
    velocity = 0.0
    followed = np.empty(len(targets), dtype=np.float64)
    for index, target in enumerate(targets):
        for _ in range(substeps):
            acceleration = stiffness * stiffness * (target - position) - 2.0 * stiffness * velocity
            velocity += acceleration * step
            position += velocity * step
        followed[index] = position
    return followed


def slow_wander(times, random, periods):
    """Smooth, never-repeating movement between -1 and 1: a few slow sine waves with random phases."""
    total = np.zeros_like(times)
    for period in periods:
        total += np.sin(2 * np.pi * times / period + random.uniform(0, 2 * np.pi))
    return total / len(periods)


class CameraPath:
    """The camera pose for every frame of one episode."""

    def __init__(self, total_frames, fps, line_starts, check_start, seed):
        times = np.arange(total_frames) / fps
        random = np.random.default_rng(seed)
        line_index = np.clip(np.searchsorted(line_starts, times, side="right") - 1, 0, None)
        zoom_target = np.take(LINE_ZOOMS, line_index % len(LINE_ZOOMS)) + CHECK_ZOOM * (times >= check_start)
        pan_target = np.take(LINE_PANS, line_index % len(LINE_PANS))
        self.fps = fps
        self.zoom = (
            BASE_ZOOM
            + PUSH_IN * times / max(times[-1], 1.0)
            + smooth_follow(zoom_target, fps)
            + 0.006 * slow_wander(times, random, [9.0, 14.5])
        )
        self.shift_x = smooth_follow(pan_target, fps) + DRIFT_X_PX * slow_wander(times, random, [6.1, 9.7, 15.3])
        self.shift_y = DRIFT_Y_PX * slow_wander(times, random, [5.3, 8.9, 13.1])
        self.tilt = np.radians(DRIFT_TILT_DEG) * slow_wander(times, random, [7.7, 12.4])
        self.parallax_x = PARALLAX_X_PX * slow_wander(times, random, [8.3, 13.7])
        self.parallax_y = PARALLAX_Y_PX * slow_wander(times, random, [10.9, 17.3])
        self.breath = BREATH_PX * np.sin(2 * np.pi * times / BREATH_PERIOD_S)
        self.sway = SWAY_PX * slow_wander(times, random, [5.7, 9.1])

    def point_track(self, width, height, below_focus_px):
        """Where a point of the still, this far below the zoom centre, lands in the frame, per frame (px)."""
        x = width / 2 + self.shift_x - self.zoom * np.sin(self.tilt) * below_focus_px
        y = height * FOCUS_Y + self.shift_y + self.zoom * np.cos(self.tilt) * below_focus_px
        return np.stack([x, y], axis=1)

    def smoothness(self, width, height):
        """Largest frame-to-frame step, and largest change of that step, of a point 300 px below the zoom
        centre (about her collarbone). A jump in speed shows up as a large change of step."""
        step = np.diff(self.point_track(width, height, 300.0), axis=0)
        change = np.diff(step, axis=0)
        return {
            "max_step_px_per_frame": round(float(np.max(np.linalg.norm(step, axis=1))), 3),
            "max_step_change_px_per_frame2": round(float(np.max(np.linalg.norm(change, axis=1))), 4),
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

    def __init__(self, fitted_picture, face_box=None):
        """fitted_picture: RGB picture already covering the frame. face_box: (centre x, centre y, half
        width, half height) in frame pixels; guessed from the usual framing when it is not given."""
        self.height, self.width = fitted_picture.shape[:2]
        big_size = (round(self.width * SUPERSAMPLE), round(self.height * SUPERSAMPLE))
        self.source = cv2.resize(fitted_picture, big_size, interpolation=cv2.INTER_LANCZOS4)
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
        head_top = face_y - 1.5 * face_half_height
        chest = ramp(self.grid_y, chin + 0.3 * face_half_height, chin + 1.8 * face_half_height)
        chest *= 1.0 - ramp(self.grid_y, chin + 3.0 * face_half_height, chin + 6.0 * face_half_height)
        head = 1.0 - ramp(self.grid_y, head_top, chin + 1.2 * face_half_height)
        self.layers = np.dstack([relative_depth, chest * person, head * person]).astype(np.float32)
        self.focus = (self.width / 2, self.height * FOCUS_Y)

    def describe(self):
        if self.has_depth:
            return "still portrait with depth-parallax camera motion, breathing and head sway (no lip-sync)"
        return "still portrait with camera motion (no depth model, no lip-sync)"

    def frame(self, path, frame_index):
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
        parallax_x, parallax_y = float(path.parallax_x[index]), float(path.parallax_y[index])
        still_x += layers[..., 0] * parallax_x + layers[..., 2] * float(path.sway[index])
        still_y += layers[..., 0] * parallax_y + layers[..., 1] * float(path.breath[index])
        size = (self.width, self.height)
        map_x = (cv2.resize(still_x, size, interpolation=cv2.INTER_LINEAR) + 0.5) * SUPERSAMPLE - 0.5
        map_y = (cv2.resize(still_y, size, interpolation=cv2.INTER_LINEAR) + 0.5) * SUPERSAMPLE - 0.5
        return cv2.remap(self.source, map_x, map_y, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)


def move_clip_frame(frame, path, frame_index):
    """The same camera move for a presenter video frame (no depth layers)."""
    index = min(frame_index, len(path.zoom) - 1)
    height, width = frame.shape[:2]
    centre = (width / 2, height * FOCUS_Y)
    matrix = cv2.getRotationMatrix2D(centre, math.degrees(float(path.tilt[index])), float(path.zoom[index]))
    matrix[0, 2] += path.shift_x[index]
    matrix[1, 2] += path.shift_y[index]
    return cv2.warpAffine(frame, matrix, (width, height), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
