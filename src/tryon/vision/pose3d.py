"""3D head pose for the real 3D try-on.

MediaPipe's Face Landmarker fits a metric canonical head to the landmarks and returns the 4x4 matrix that moves that
head into the camera's space (centimetres, OpenGL convention: the camera looks down -z, +y is up, +x is image right).
The matrix assumes a virtual pinhole camera with a 63 degree vertical field of view, so the browser can rebuild the exact
same camera from the image size alone and draw the glasses in the right place, size and orientation.

The canonical head is about 1.15 x a real head (its inter-pupil distance is ~7.2 cm instead of 6.3 cm). That scale and where
the glasses sit on the head are calibrated in the browser (static/js/tryon3d.js, HEAD constants).
"""
from __future__ import annotations

import math

import numpy as np

FOV_Y_DEG = 63.0
MAX_YAW, MAX_PITCH, MAX_ROLL = 55.0, 40.0, 45.0     # beyond this the glasses cannot be placed convincingly


def euler_degrees(R: np.ndarray) -> tuple[float, float, float]:
    """(yaw, pitch, roll) of the head, in degrees. Yaw > 0 = the face turns towards image-right, pitch > 0 = looking up."""
    # R maps head axes to camera axes. The head's forward axis (+z) expressed in the camera:
    fwd = R[:, 2]
    yaw = math.degrees(math.atan2(fwd[0], fwd[2]))
    pitch = math.degrees(math.asin(float(np.clip(fwd[1], -1, 1))))
    up = R[:, 1]
    roll = math.degrees(math.atan2(-up[0], up[1]))
    return yaw, pitch, roll


def head_pose(matrix: np.ndarray | None, width: int, height: int) -> dict | None:
    """The JSON the browser needs, or None when MediaPipe gave no usable pose."""
    if matrix is None:
        return None
    m = np.asarray(matrix, float).reshape(4, 4)
    if not np.all(np.isfinite(m)):
        return None
    R = m[:3, :3]
    scale = float(np.cbrt(abs(np.linalg.det(R))))
    if not 0.5 < scale < 2.0 or m[2, 3] >= 0:               # the head must be in front of the camera (negative z)
        return None
    yaw, pitch, roll = euler_degrees(R / scale)
    return {
        "matrix": [round(float(x), 5) for x in m.reshape(-1)],       # row-major
        "fov_y": FOV_Y_DEG,
        "aspect": round(width / height, 5),
        "yaw": round(yaw, 1), "pitch": round(pitch, 1), "roll": round(roll, 1),
        "usable": bool(abs(yaw) <= MAX_YAW and abs(pitch) <= MAX_PITCH and abs(roll) <= MAX_ROLL),
    }
