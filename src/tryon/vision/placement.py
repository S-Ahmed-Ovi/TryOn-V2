"""Where the glasses go on a photo: centre between the eyes, head tilt, and face width."""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

EYE_R = (33, 133, 159, 145)        # the subject's right eye (left side of the picture): corners + lids
EYE_L = (362, 263, 386, 374)
CHEEK_R, CHEEK_L = 234, 454        # widest part of the face


@dataclass(frozen=True)
class Placement:
    """All values are relative to the photo, so they stay valid at any display size.

    cx, cy  centre between the eyes, as a fraction of photo width / height
    width   face width (cheek to cheek), as a fraction of photo width
    angle   head tilt in degrees, clockwise positive
    """
    cx: float
    cy: float
    width: float
    angle: float

    def as_dict(self) -> dict:
        return {"cx": round(self.cx, 5), "cy": round(self.cy, 5), "width": round(self.width, 5), "angle": round(self.angle, 3)}


def compute_placement(pts: np.ndarray, width: int, height: int) -> Placement:
    p = pts[:, :2] * [width, height]
    eye_r, eye_l = p[list(EYE_R)].mean(0), p[list(EYE_L)].mean(0)
    centre = (eye_r + eye_l) / 2
    roll = math.degrees(math.atan2(eye_l[1] - eye_r[1], eye_l[0] - eye_r[0]))
    cheek = float(np.linalg.norm(p[CHEEK_L] - p[CHEEK_R]))
    return Placement(cx=float(centre[0] / width), cy=float(centre[1] / height), width=cheek / width, angle=roll)
