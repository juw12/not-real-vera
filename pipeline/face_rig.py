"""Make the face of a still move: mouth, eyelids and eyebrows. CPU only, no model download.

FaceRig takes the enlarged still and the 98 face landmarks (tools/face_landmarks.py) and redraws the face
for every frame from four numbers:

mouth_open  -1 lips pressed together ... 0 the still's own smile ... 1 jaw dropped
mouth_wide  -1 lips rounded ("oo", "w") ... 0 as in the still ... 1 stretched ("ee")
blink        0 eyes open ... 1 eyes closed
brow         0 as in the still ... 1 eyebrows raised

How: the picture is warped, never repainted. Opening slides the lower lip and chin down and shows a dark
mouth behind the upper teeth, which stay where they are. Closing slides the lips over the teeth until they
meet. A blink covers the eye with a smooth eyelid painted in the skin colour sampled just above it, with a lash
line where the lids meet; up close it is a flat patch, which is acceptable for the 150 ms a blink lasts.
Everything fades to zero movement at the corners of the mouth and eyes, so there is no seam.

expression_track() decides when she blinks and raises her eyebrows.

What this is not: a neural talking-head model. The tongue, the lower teeth and cheek muscles are not
modelled, and the face cannot turn. It is the lip-sync a game character gets, applied to a photo.
"""
import cv2
import numpy as np

# WFLW landmark numbers
JAW_FIRST, JAW_LAST = 0, 32
NOSE_BASE = 57
EYES = (
    {"corners": (60, 64), "upper": (61, 62, 63), "lower": (65, 66, 67)},
    {"corners": (68, 72), "upper": (69, 70, 71), "lower": (73, 74, 75)},
)
BROWS = (range(33, 42), range(42, 51))
BROW_LOWER_EDGES = ((33, 41, 40, 39, 38, 37), (42, 50, 49, 48, 47, 46))
MOUTH_CORNERS = ((76, 88), (82, 92))
UPPER_INNER_LIP = (89, 90, 91)
LOWER_INNER_LIP = (93, 94, 95)

# Sizes are in "units": one fiftieth of the mouth's half width, about one pixel of the 768 px wide still.
OPEN_UNITS = 10.0  # how far the lower lip drops at mouth_open = 1
JAW_FOLLOW = 0.9  # share of that drop the chin makes
UPPER_LIP_SHARE = 0.3  # when the lips close, the upper lip covers this share of the teeth
JAW_CLOSE = 0.35  # share of the lower lip's rise the chin makes when the lips close
CLOSE_OVERLAP_UNITS = 2.5  # closed lips overlap by this much, so no tooth shows between them
CHIN_MIN_UNITS = 25.0  # the chin line stays at least this far below the lower lip line
NECK_UNITS = 40.0  # the skin below the chin line that takes up the chin's movement
JAW_FULL, JAW_NONE = 0.75, 1.7  # the chin moves fully within this many half widths, not at all beyond
ROUND_SCALE, STRETCH_SCALE = 0.87, 1.04  # mouth width at mouth_wide = -1 and 1
OPEN_NARROWS = 0.03  # a dropped jaw pulls the corners in by this share
EDGE_SOFT_UNITS = 0.8
MOUTH_DARK_TOP = np.float32([30, 10, 12])  # RGB, just under the upper teeth
MOUTH_DARK_BOTTOM = np.float32([128, 56, 60])  # RGB, over the lower lip (tongue)
LASH_UNITS = 2.6  # the eyelid's edge is this far below where the skin turns into lashes
LASH_BAND_UNITS = 4.5  # the lashes and the lid's edge travel as they are, without stretching
LID_SKIN_UNITS = 12.0  # eyelid skin above the lash line that stretches during a blink
BROW_CLEAR_UNITS = 2.5  # ... but never closer to the eyebrow than this, so the brow stays put
BLINK_OVERLAP_UNITS = 3.0  # closed lashes overlap the lower lid by this much
EYE_ARCH_POWER = 0.6
EYE_MARGIN_UNITS = 6.0  # the eye's working patch reaches this far past the corners
CREASE_UNITS = 9.0  # the closing eyelid's cover is an almond: this high above the lashes mid-eye
LID_FEATHER_UNITS = 1.6  # softness of the closing eyelid's outline
LASH_DARK = 0.8  # eyelid pixels darker than this share of the lid's skin count as lashes
CLEAN_LID_FROM = 0.3  # from this much blink on, the closing eyelid is painted as smooth skin
BROW_RAISE_UNITS = 3.2
BLINK_SHAPE = (0.6, 1.0, 0.75, 0.35, 0.1)  # eyelid position over the frames of one blink (30 fps)
BLINK_GAP_S = (2.2, 4.8)
BROW_AFTER_LINE_START_S = 0.3
BROW_WIDTH_S = 0.2


def arch(position):
    """1 in the middle, 0 at -1 and 1 and beyond."""
    return np.clip(1.0 - position * position, 0.0, 1.0)


def eye_arch(position):
    """Like arch(), but fuller towards the corners: an eye opening is closer to an ellipse."""
    return np.clip(1.0 - position * position, 0.0, 1.0) ** EYE_ARCH_POWER


def ease(values, start, end):
    """0 at start, 1 at end, smooth in between (start may be larger than end)."""
    progress = np.clip((values - start) / (end - start), 0.0, 1.0)
    return progress * progress * (3.0 - 2.0 * progress)


class FaceRig:
    def __init__(self, source, points):
        """source: the enlarged still (RGB, uint8). points: the 98 landmarks in source pixels."""
        points = np.asarray(points, dtype=np.float64)
        left_corner = points[list(MOUTH_CORNERS[0])].mean(axis=0)
        right_corner = points[list(MOUTH_CORNERS[1])].mean(axis=0)
        self.unit = float(right_corner[0] - left_corner[0]) / 100.0
        unit = self.unit
        brow_points = points[33:51]
        left = int(max(points[:, 0].min() - 14 * unit, 0))
        right = int(min(points[:, 0].max() + 14 * unit, source.shape[1]))
        top = int(max(brow_points[:, 1].min() - 34 * unit, 0))
        bottom = int(min(points[:, 1].max() + (NECK_UNITS + 8) * unit, source.shape[0]))
        self.box = (left, top, right, bottom)
        self.base = np.ascontiguousarray(source[top:bottom, left:right])
        self.canvas = source.copy()
        height, width = self.base.shape[:2]
        self.columns = np.arange(width, dtype=np.float32)
        self.rows = np.arange(height, dtype=np.float32).reshape(height, 1)
        self.identity_x = np.ascontiguousarray(np.broadcast_to(self.columns, (height, width)))
        self.identity_y = np.ascontiguousarray(np.broadcast_to(self.rows, (height, width)))
        local = points - [left, top]
        self.notes = {}
        self._prepare_mouth(local)
        self.eyes = [self._prepare_eye(local, eye, edge) for eye, edge in zip(EYES, BROW_LOWER_EDGES)]
        self.brow_field = self._prepare_brows(local)

    # ------------------------------------------------------------ set-up

    def _prepare_mouth(self, points):
        unit = self.unit
        left_corner = points[list(MOUTH_CORNERS[0])].mean(axis=0)
        right_corner = points[list(MOUTH_CORNERS[1])].mean(axis=0)
        centre_x = (left_corner[0] + right_corner[0]) / 2.0
        half_width = (right_corner[0] - left_corner[0]) / 2.0
        position = (self.columns - centre_x) / half_width
        corner_line = left_corner[1] + (right_corner[1] - left_corner[1]) * np.clip((position + 1.0) / 2.0, 0.0, 1.0)

        def height_from_landmarks(numbers):
            heights = []
            for x, y in points[list(numbers)]:
                place = (x - centre_x) / half_width
                heights.append((y - np.interp(x, self.columns, corner_line)) / max(1.0 - place * place, 0.2))
            return float(np.mean(heights))

        upper_height = height_from_landmarks(UPPER_INNER_LIP)
        lower_height = height_from_landmarks(LOWER_INNER_LIP)
        measured = self._tooth_heights(centre_x, half_width, corner_line, upper_height, lower_height)
        self.notes["lip_lines"] = "measured from the teeth in the picture" if measured else "from the landmarks"
        if measured:
            upper_height, lower_height = measured
        shape = arch(position)
        upper = corner_line + upper_height * shape
        lower = corner_line + lower_height * shape
        jaw = points[JAW_FIRST:JAW_LAST + 1]
        order = np.argsort(jaw[:, 0])
        outline = np.interp(self.columns, jaw[order, 0], jaw[order, 1])
        chin = np.maximum(outline - 4.0 * unit, lower + CHIN_MIN_UNITS * unit)
        nose_base = np.full_like(self.columns, points[NOSE_BASE, 1])
        first_row = int(nose_base.min())
        last_row = int(min(np.ceil((chin + NECK_UNITS * unit).max()) + 1, self.base.shape[0]))
        columns = np.nonzero(np.abs(position) < JAW_NONE)[0]
        first_column, last_column = int(columns[0]), int(columns[-1]) + 1
        span = slice(first_column, last_column)

        def row_vector(values):
            return np.asarray(values[span], dtype=np.float32).reshape(1, -1)

        self.mouth = {
            "block": (slice(first_row, last_row), span),
            "rows": self.rows[first_row:last_row],
            "top": row_vector(nose_base),
            "upper": row_vector(upper),
            "lower": row_vector(lower),
            "chin": row_vector(chin),
            "bottom": row_vector(chin + NECK_UNITS * unit),
            "arch": row_vector(shape),
            "gap": row_vector(lower - upper),
            "cover": row_vector(lower - upper + CLOSE_OVERLAP_UNITS * unit * np.clip(4.0 * shape, 0.0, 1.0)),
            "centre_gap": float(lower_height - upper_height),
            "jaw_window": row_vector(1.0 - ease(np.abs(position), JAW_FULL, JAW_NONE)),
        }
        self.open_px = OPEN_UNITS * unit
        # Second, sideways step: rounding or stretching the lips around the middle of the mouth.
        centre_y = float(np.interp(centre_x, self.columns, corner_line)) + 0.2 * half_width
        reach_x, reach_y = 1.75 * half_width, 0.95 * half_width
        box_left = int(max(centre_x - reach_x, 0))
        box_right = int(min(centre_x + reach_x, self.base.shape[1]))
        box_top = int(max(centre_y - reach_y, 0))
        box_bottom = int(min(centre_y + reach_y, self.base.shape[0]))
        from_centre_x = self.identity_x[box_top:box_bottom, box_left:box_right] - centre_x
        from_centre_y = self.identity_y[box_top:box_bottom, box_left:box_right] - centre_y
        distance = np.sqrt((from_centre_x / reach_x) ** 2 + (from_centre_y / reach_y) ** 2)
        self.width_step = {
            "block": (slice(box_top, box_bottom), slice(box_left, box_right)),
            "from_centre_x": from_centre_x,
            "weight": (1.0 - ease(distance, 0.55, 1.0)).astype(np.float32),
            "map_y": np.ascontiguousarray(self.identity_y[box_top:box_bottom, box_left:box_right] - box_top),
            "centre_x": float(centre_x - box_left),
        }

    def _tooth_heights(self, centre_x, half_width, corner_line, upper_guess, lower_guess):
        """Measure where the upper teeth start and end (the lips' inner edges) from the picture itself.
        The landmarks are a few pixels off here, and a lip line drawn through a tooth would show. Returns
        (upper height, lower height) of the two lip lines below the corner line at the middle of the mouth,
        or None when the teeth cannot be found (closed mouth, odd lighting)."""
        unit = self.unit
        picture = self.base.astype(np.float32)
        brightest = picture.max(axis=2)
        saturation = (brightest - picture.min(axis=2)) / np.maximum(brightest, 1.0)
        middle_line = float(np.interp(centre_x, self.columns, corner_line))
        if lower_guess - upper_guess < 5 * unit:
            return None
        core_rows = slice(
            int(middle_line + upper_guess + 0.35 * (lower_guess - upper_guess)),
            int(middle_line + upper_guess + 0.65 * (lower_guess - upper_guess)) + 1,
        )
        lip_rows = slice(int(middle_line + lower_guess + 5 * unit), int(middle_line + lower_guess + 9 * unit))
        core_columns = slice(int(centre_x - 0.35 * half_width), int(centre_x + 0.35 * half_width))
        tooth_saturation = float(np.median(saturation[core_rows, core_columns]))
        lip_saturation = float(np.median(saturation[lip_rows, core_columns]))
        tooth_brightness = float(np.median(brightest[core_rows, core_columns]))
        if lip_saturation - tooth_saturation < 0.08:
            return None
        teeth = (saturation < (tooth_saturation + lip_saturation) / 2.0) & (brightest > 0.6 * tooth_brightness)
        upper_heights, lower_heights = [], []
        for column in range(int(centre_x - 0.6 * half_width), int(centre_x + 0.6 * half_width)):
            place = (column - centre_x) / half_width
            line = float(np.interp(column, self.columns, corner_line))
            start = int(line + (upper_guess + 0.5 * (lower_guess - upper_guess)) * (1.0 - place * place))
            if not teeth[start, column]:
                continue
            first = start
            while first > 0 and teeth[first - 1, column]:
                first -= 1
            last = start
            while last + 1 < teeth.shape[0] and teeth[last + 1, column]:
                last += 1
            upper_heights.append((first - line) / (1.0 - place * place))
            lower_heights.append((last + 1 - line) / (1.0 - place * place))
        if len(upper_heights) < 0.5 * 1.2 * half_width:
            return None
        upper_height = float(np.clip(np.median(upper_heights), upper_guess - 8 * unit, upper_guess + 8 * unit))
        lower_height = float(np.clip(np.median(lower_heights), lower_guess - 8 * unit, lower_guess + 8 * unit))
        if lower_height - upper_height < 5 * unit:
            return None
        return upper_height, lower_height

    def _prepare_eye(self, points, eye, brow_edge):
        unit = self.unit
        corners = points[list(eye["corners"])]
        corners = corners[np.argsort(corners[:, 0])]
        centre_x = corners[:, 0].mean()
        half_width = (corners[1, 0] - corners[0, 0]) / 2.0
        first_column = int(max(corners[0, 0] - EYE_MARGIN_UNITS * unit, 0))
        last_column = int(min(corners[1, 0] + EYE_MARGIN_UNITS * unit, self.base.shape[1]))
        columns = self.columns[first_column:last_column]
        position = (columns - centre_x) / half_width
        corner_line = corners[0, 1] + (corners[1, 1] - corners[0, 1]) * np.clip((position + 1.0) / 2.0, 0.0, 1.0)
        shape = eye_arch(position)

        def height_from_landmarks(numbers):
            heights = []
            for x, y in points[list(numbers)]:
                place = (x - centre_x) / half_width
                heights.append((y - np.interp(x, columns, corner_line)) / max(float(eye_arch(place)), 0.2))
            return float(np.mean(heights))

        lower_height = height_from_landmarks(eye["lower"])
        upper_height = height_from_landmarks(eye["upper"])
        lash_height, lash_lean = self._lash_line(columns, position, corner_line, upper_height, lower_height)
        lower = corner_line + lower_height * shape
        lid = corner_line + (lash_height + lash_lean * position) * shape
        lid = np.minimum(lid, lower)
        brow = points[list(brow_edge)]
        brow = brow[np.argsort(brow[:, 0])]
        brow_bottom = np.interp(columns, brow[:, 0], brow[:, 1]) + BROW_CLEAR_UNITS * unit
        band_top = lid - LASH_BAND_UNITS * unit
        skin_top = np.minimum(np.maximum(lid - LID_SKIN_UNITS * unit, brow_bottom), band_top - 2.0 * unit)
        first_row = int(max(skin_top.min() - 1, 0))
        last_row = int(min(lower.max() + (BLINK_OVERLAP_UNITS + 2) * unit, self.base.shape[0]))

        def row_vector(values):
            return np.asarray(values, dtype=np.float32).reshape(1, -1)

        self.notes.setdefault("eyelid_edge_units_below_landmarks", []).append(round((lash_height - upper_height) / unit, 1))
        block = (slice(first_row, last_row), slice(first_column, last_column))
        rows = self.rows[first_row:last_row]
        travel = (lower - lid) * (1.0 + BLINK_OVERLAP_UNITS * unit / max(float((lower - lid).max()), 1.0))
        return {
            "block": block,
            "skin": self._eyelid_skin(block, rows, skin_top, band_top),
            "rows": rows,
            "skin_top": row_vector(skin_top),
            "band_top": row_vector(band_top),
            "lid": row_vector(lid),
            "travel": row_vector(travel),
            "cover_top": row_vector(np.maximum(lid - CREASE_UNITS * unit * arch(position) ** 0.8, skin_top)),
        }

    def _eyelid_skin(self, block, rows, skin_top, band_top):
        """Smooth eyelid skin for the eye's patch of the picture: what a closed eyelid is painted with.
        It is the eyelid's own colour, averaged from the skin between the lashes and the eyebrow with the
        upturned lashes left out, so a closing lid is skin and not stretched lashes."""
        patch = self.base[block].astype(np.float32)
        luminance = cv2.cvtColor(self.base[block], cv2.COLOR_RGB2GRAY).astype(np.float32)
        lid_zone = (rows >= skin_top.reshape(1, -1)) & (rows < band_top.reshape(1, -1))
        if not lid_zone.any():
            return patch
        skin_level = float(np.percentile(luminance[lid_zone], 70))
        clear = (lid_zone & (luminance >= LASH_DARK * skin_level)).astype(np.uint8)
        reach = max(int(round(1.2 * self.unit)), 1)
        clear = cv2.erode(clear, np.ones((2 * reach + 1, 2 * reach + 1), np.uint8)).astype(np.float32)
        if clear.sum() < 20:
            return patch
        # One colour per column (the mean of that column's clear eyelid skin), smoothed sideways, so the
        # cover always matches the skin right above it.
        sigma = 2.5 * self.unit
        weight = cv2.GaussianBlur(clear.sum(axis=0).reshape(1, -1), (0, 0), sigma)
        colour = cv2.GaussianBlur((patch * clear[..., None]).sum(axis=0).reshape(1, -1, 3), (0, 0), sigma)
        colour = colour / np.maximum(weight, 1e-3)[..., None]
        wide = cv2.GaussianBlur(clear.sum(axis=0).reshape(1, -1), (0, 0), 4.0 * sigma)
        wide_colour = cv2.GaussianBlur((patch * clear[..., None]).sum(axis=0).reshape(1, -1, 3), (0, 0), 4.0 * sigma)
        wide_colour = wide_colour / np.maximum(wide, 1e-3)[..., None]
        trust = np.clip(weight / 2.0, 0.0, 1.0)[..., None]
        colour = trust * colour + (1.0 - trust) * wide_colour
        return np.ascontiguousarray(np.broadcast_to(colour, patch.shape), dtype=np.float32)

    def _lash_line(self, columns, position, corner_line, upper_guess, lower_height):
        """Find the upper lash line: the strongest change from light skin to dark going down each column.
        The landmarks sit on the eyelid crease, a few pixels above it. Returns the line's height at the
        middle of the eye (below the lashes, so they travel with the lid) and how much it leans."""
        unit = self.unit
        fallback = (min(upper_guess + 5.0 * unit, lower_height - 4 * unit), 0.0)
        luminance = cv2.GaussianBlur(cv2.cvtColor(self.base, cv2.COLOR_RGB2GRAY), (0, 0), 0.6 * unit).astype(np.float32)
        reach = max(int(round(unit)), 1)
        places, heights = [], []
        for index, column in enumerate(columns.astype(int)):
            place = float(position[index])
            if abs(place) > 0.72:
                continue
            bend = float(eye_arch(place))
            first = int(corner_line[index] + upper_guess * bend - 4 * unit)
            last = int(corner_line[index] + lower_height * bend - 4 * unit)
            if last - first < 3 * reach or first - reach < 0:
                continue
            profile = luminance[first - reach:last + reach, column]
            change = profile[2 * reach:] - profile[:-2 * reach]
            lash_top = first + int(np.argmin(change))
            places.append(place)
            heights.append((lash_top + LASH_UNITS * unit - corner_line[index]) / bend)
        if len(places) < 8:
            return fallback
        places, heights = np.asarray(places), np.asarray(heights)
        keep = np.abs(heights - np.median(heights)) < 5 * unit
        if keep.sum() < 8:
            return fallback
        lean, height = np.polyfit(places[keep], heights[keep], 1)
        height = float(np.clip(height, upper_guess - 2 * unit, min(upper_guess + 11 * unit, lower_height - 3 * unit)))
        lean = float(np.clip(lean, -0.5 * abs(height), 0.5 * abs(height)))
        return height, lean

    def _prepare_brows(self, points):
        unit = self.unit
        field = np.zeros(self.base.shape[:2], dtype=np.float32)
        for brow in BROWS:
            brow_points = points[list(brow)]
            left, right = brow_points[:, 0].min(), brow_points[:, 0].max()
            top, bottom = brow_points[:, 1].min(), brow_points[:, 1].max()
            across = ease(self.columns, left - 8 * unit, left + 6 * unit) * (
                1.0 - ease(self.columns, right - 6 * unit, right + 8 * unit)
            )
            down = ease(self.rows, top - 30 * unit, top - 4 * unit) * (
                1.0 - ease(self.rows, bottom + 2 * unit, bottom + 9 * unit)
            )
            field = np.maximum(field, (down * across).astype(np.float32))
        return field * (BROW_RAISE_UNITS * unit)

    # ------------------------------------------------------------ per frame

    def render(self, mouth_open=0.0, mouth_wide=0.0, blink=0.0, brow=0.0):
        """Return the whole enlarged still with the face redrawn. The array is reused: copy it to keep it."""
        mouth_open = float(np.clip(mouth_open, -1.0, 1.0))
        mouth_wide = float(np.clip(mouth_wide, -1.0, 1.0))
        blink = float(np.clip(blink, 0.0, 1.0))
        map_y = self.identity_y.copy()
        if brow > 0.0:
            map_y += float(brow) * self.brow_field
        lids = []
        if blink > 0.0:
            for eye in self.eyes:
                rows = eye["rows"]
                drop = blink * eye["travel"]
                band_top, skin_top = eye["band_top"], eye["skin_top"]
                stretched = skin_top + (rows - skin_top) * (band_top - skin_top) / (band_top + drop - skin_top)
                source_rows = np.where(rows < band_top + drop, stretched, rows - drop)
                lid_area = (rows >= skin_top) & (rows < eye["lid"] + drop)
                block = map_y[eye["block"]]
                block[lid_area] = source_rows[lid_area]
                cover = (rows >= eye["cover_top"]) & (rows < band_top + drop)
                lids.append((eye, cover.astype(np.float32)))
        mouth = self.mouth
        opening, closing = max(mouth_open, 0.0), max(-mouth_open, 0.0)
        rows = mouth["rows"]
        dark = None
        if opening > 0.0 or closing > 0.0:
            upper = mouth["upper"] + closing * UPPER_LIP_SHARE * mouth["cover"]
            lower = (
                mouth["lower"]
                + opening * self.open_px * mouth["arch"]
                - closing * (1.0 - UPPER_LIP_SHARE) * mouth["cover"]
            )
            chin_shift = opening * self.open_px * JAW_FOLLOW
            chin_shift -= closing * (1.0 - UPPER_LIP_SHARE) * mouth["centre_gap"] * JAW_CLOSE
            chin = mouth["chin"] + chin_shift * mouth["jaw_window"]
            top, bottom = mouth["top"], mouth["bottom"]
            source_rows = np.where(
                rows < upper, top + (rows - top) * (mouth["upper"] - top) / (upper - top), rows
            )
            below_lip = mouth["lower"] + (rows - lower) * (mouth["chin"] - mouth["lower"]) / (chin - lower)
            source_rows = np.where(rows >= lower, below_lip, source_rows)
            below_chin = mouth["chin"] + (rows - chin) * (bottom - mouth["chin"]) / (bottom - chin)
            source_rows = np.where(rows >= chin, below_chin, source_rows)
            source_rows = np.where((rows < top) | (rows >= bottom), rows, source_rows)
            map_y[mouth["block"]] += (source_rows - rows).astype(np.float32)
            if opening > 0.0:
                soft = EDGE_SOFT_UNITS * self.unit
                dark = (
                    np.clip((rows - mouth["lower"]) / soft + 0.5, 0.0, 1.0)
                    * np.clip((lower - rows) / soft + 0.5, 0.0, 1.0)
                    * np.clip((lower - mouth["lower"]) / soft, 0.0, 1.0)
                )
                depth = np.clip((rows - mouth["lower"]) / np.maximum(lower - mouth["lower"], 1.0), 0.0, 1.0) ** 1.5
        face = cv2.remap(self.base, self.identity_x, map_y, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
        cover_strength = float(ease(blink, 0.0, CLEAN_LID_FROM))
        for eye, cover in lids:
            cover = cv2.GaussianBlur(cover, (0, 0), LID_FEATHER_UNITS * self.unit)[..., None] * cover_strength
            patch = face[eye["block"]]
            patch[:] = (patch * (1.0 - cover) + eye["skin"] * cover).astype(np.uint8)
        if dark is not None:
            block = face[mouth["block"]].astype(np.float32)
            colour = MOUTH_DARK_TOP + (MOUTH_DARK_BOTTOM - MOUTH_DARK_TOP) * depth[..., None]
            dark = dark[..., None]
            face[mouth["block"]] = (block * (1.0 - dark) + colour * dark).astype(np.uint8)
        scale = 1.0 + (STRETCH_SCALE - 1.0) * max(mouth_wide, 0.0) - (1.0 - ROUND_SCALE) * max(-mouth_wide, 0.0)
        scale -= OPEN_NARROWS * opening
        if abs(scale - 1.0) > 0.004:
            step = self.width_step
            local_scale = 1.0 + (scale - 1.0) * step["weight"]
            map_x = (step["centre_x"] + step["from_centre_x"] / local_scale).astype(np.float32)
            patch = np.ascontiguousarray(face[step["block"]])
            face[step["block"]] = cv2.remap(patch, map_x, step["map_y"], cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
        left, top, right, bottom = self.box
        self.canvas[top:bottom, left:right] = face
        return self.canvas


def expression_track(total_frames, fps, line_starts, question_ends, seed):
    """When she blinks and raises her eyebrows. Returns (blink per frame, brow per frame, number of blinks).

    Blinks come every few seconds at irregular gaps (fixed per episode by the seed). The eyebrows lift
    briefly as each new line starts and at the end of each question.
    """
    random = np.random.default_rng(seed)
    blink = np.zeros(total_frames)
    brow = np.zeros(total_frames)
    times = np.arange(total_frames) / fps
    blinks = 0
    moment = random.uniform(0.9, 2.0)
    while moment < total_frames / fps - 0.4:
        first = int(moment * fps)
        shape = np.interp(np.arange(len(BLINK_SHAPE) * fps // 30), np.arange(len(BLINK_SHAPE)) * fps / 30.0, BLINK_SHAPE)
        last = min(first + len(shape), total_frames)
        blink[first:last] = np.maximum(blink[first:last], shape[: last - first])
        blinks += 1
        moment += random.uniform(*BLINK_GAP_S)
    lifts = [(start + BROW_AFTER_LINE_START_S, random.uniform(0.45, 1.0)) for start in line_starts]
    lifts += [(end - 0.25, 1.0) for end in question_ends]
    for moment, strength in lifts:
        brow = np.maximum(brow, strength * np.exp(-0.5 * ((times - moment) / BROW_WIDTH_S) ** 2))
    return blink, brow, blinks
