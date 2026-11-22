"""Face shape from a photo: landmark geometry compared with a prototype for each shape.

The numbers in PROTOTYPES are first estimates, not calibrated on a dataset, so the app always lets the person
correct the detected shape. To tune them, see docs/TUNING.md.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import cv2
import numpy as np

from tryon.vision.landmarks import FaceLandmarker
from tryon.vision.pose3d import head_pose
from tryon.vision.placement import Placement, compute_placement

SHAPES = ("oval", "round", "square", "heart", "oblong")

# Landmark indices of the face mesh
I_TOP, I_CHIN = 10, 152                 # top of forehead, chin
I_CHEEK_R, I_CHEEK_L = 234, 454         # cheekbones (widest part of the face)
I_JAW_R, I_JAW_L = 172, 397             # jaw corners
I_FORE_R, I_FORE_L = 54, 284            # upper forehead corners
I_EYE_R, I_EYE_L = 33, 263              # outer eye corners
I_NOSE = 1

# (mean, tolerance) per shape for: length / cheek width, jaw / cheek width, forehead / jaw width, chin angle (deg)
PROTOTYPES = {
    "oval":   ((1.20, 0.08), (0.74, 0.06), (1.08, 0.10), (100, 10)),
    "round":  ((1.08, 0.06), (0.80, 0.06), (1.02, 0.10), (108, 10)),
    "square": ((1.14, 0.07), (0.86, 0.05), (0.98, 0.08), (113, 10)),
    "heart":  ((1.20, 0.09), (0.68, 0.06), (1.25, 0.10), (92, 10)),
    "oblong": ((1.34, 0.08), (0.78, 0.07), (1.05, 0.10), (102, 10)),
}

GUIDE_POINTS = {"top": I_TOP, "chin": I_CHIN, "cheek_r": I_CHEEK_R, "cheek_l": I_CHEEK_L,
                "jaw_r": I_JAW_R, "jaw_l": I_JAW_L, "fore_r": I_FORE_R, "fore_l": I_FORE_L}


@dataclass
class Issue:
    level: str          # "warn" | "reject"
    message: str


@dataclass
class FaceAnalysis:
    status: str                                   # ok | warn | reject
    issues: list[Issue] = field(default_factory=list)
    shape: str | None = None
    confidence: float = 0.0                       # 0-0.85: face shapes are fuzzy, so never claim more
    needs_confirmation: bool = True               # True -> ask the person to confirm the shape
    probabilities: dict[str, float] = field(default_factory=dict)
    measurements: dict[str, float] = field(default_factory=dict)
    guide_points: dict[str, tuple[float, float]] = field(default_factory=dict)
    face_box: tuple[float, float, float, float] | None = None     # x0, y0, x1, y1 (fractions of the photo)
    placement: Placement | None = None
    pose3d: dict | None = None                    # head pose for the real 3D try-on (None when unavailable)


# ----------------------------------------------------------------------------- geometry
def measure(pts: np.ndarray, w: int, h: int) -> dict[str, float]:
    """Measurements after rotating the face so the eye line is level (head tilt removed)."""
    P = pts[:, :2] * [w, h]
    Z = pts[:, 2] * w
    roll = math.degrees(math.atan2(P[I_EYE_L, 1] - P[I_EYE_R, 1], P[I_EYE_L, 0] - P[I_EYE_R, 0]))
    t = -math.radians(roll)
    R = np.array([[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]])
    Q = (P - P.mean(0)) @ R.T
    width = lambda a, b: abs(Q[a, 0] - Q[b, 0])
    Wc, Wj, Wf = width(I_CHEEK_R, I_CHEEK_L), width(I_JAW_R, I_JAW_L), width(I_FORE_R, I_FORE_L)
    length = abs(Q[I_CHIN, 1] - Q[I_TOP, 1])
    v1, v2 = Q[I_JAW_R] - Q[I_CHIN], Q[I_JAW_L] - Q[I_CHIN]
    chin = math.degrees(math.acos(np.clip(v1 @ v2 / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-9), -1, 1)))
    yaw = math.degrees(math.atan2(abs(Z[I_CHEEK_L] - Z[I_CHEEK_R]), width(I_CHEEK_R, I_CHEEK_L)))
    eye_y = (Q[I_EYE_R, 1] + Q[I_EYE_L, 1]) / 2
    nose_ratio = (Q[I_NOSE, 1] - eye_y) / max(Q[I_CHIN, 1] - eye_y, 1e-6)
    return {
        "length_cheek": length / Wc, "jaw_cheek": Wj / Wc, "fore_jaw": Wf / Wj, "chin_angle": chin,
        "yaw": yaw, "roll": abs(roll), "nose_ratio": nose_ratio,
        "face_h_frac": float(pts[:, 1].max() - pts[:, 1].min()),
    }


def photo_checks(m: dict[str, float], pts: np.ndarray, bgr: np.ndarray) -> list[Issue]:
    issues: list[Issue] = []
    cut_off = pts[:, 0].min() < 0.0 or pts[:, 0].max() > 1.0 or pts[:, 1].min() < 0.0 or pts[:, 1].max() > 1.0
    if cut_off:
        issues.append(Issue("reject", "Your face is cut off by the edge of the photo. Show your whole face."))
    if m["face_h_frac"] < 0.18:
        issues.append(Issue("reject", "Your face is too small in this photo. Move closer to the camera."))
    elif m["face_h_frac"] < 0.30:
        issues.append(Issue("warn", "Your face is fairly small in this photo. A closer shot is more accurate."))
    if m["yaw"] > 25:
        issues.append(Issue("reject", f"Your head is turned sideways ({m['yaw']:.0f}°). Look straight at the camera."))
    elif m["yaw"] > 12:
        issues.append(Issue("warn", f"Your head is slightly turned ({m['yaw']:.0f}°). Straight on is more accurate."))
    if m["roll"] > 35:
        issues.append(Issue("reject", f"Your head is tilted too far ({m['roll']:.0f}°). Keep it upright."))
    elif m["roll"] > 12:
        issues.append(Issue("warn", f"Your head is tilted ({m['roll']:.0f}°). We corrected the measurements for it."))
    if not 0.28 <= m["nose_ratio"] <= 0.56:
        issues.append(Issue("warn", "Your head looks tilted up or down. Keep your chin level."))
    if not cut_off:
        h, w = bgr.shape[:2]
        x0, x1 = int(pts[:, 0].min() * w), int(pts[:, 0].max() * w)
        y0, y1 = int(pts[:, 1].min() * h), int(pts[:, 1].max() * h)
        crop = cv2.cvtColor(bgr[max(y0, 0):y1, max(x0, 0):x1], cv2.COLOR_BGR2GRAY)
        if crop.size and cv2.Laplacian(crop, cv2.CV_64F).var() < 30:
            issues.append(Issue("warn", "The photo looks blurry. A sharper photo is more accurate."))
    return issues


def classify(m: dict[str, float]) -> list[tuple[str, float]]:
    """Probability of each shape (they sum to 1), best first."""
    x = [m["length_cheek"], m["jaw_cheek"], m["fore_jaw"], m["chin_angle"]]
    raw = {s: math.exp(-0.5 * sum(((v - mu) / sd) ** 2 for v, (mu, sd) in zip(x, protos)))
           for s, protos in PROTOTYPES.items()}
    total = sum(raw.values()) + 1e-12
    return sorted(((s, v / total) for s, v in raw.items()), key=lambda t: -t[1])


# ----------------------------------------------------------------------------- detector
class FaceShapeDetector:
    MAX_SIDE = 1280

    def __init__(self, landmarker: FaceLandmarker | None = None) -> None:
        self.landmarker = landmarker or FaceLandmarker()

    def analyze(self, bgr: np.ndarray) -> FaceAnalysis:
        h, w = bgr.shape[:2]
        s = self.MAX_SIDE / max(h, w)
        if s < 1:
            bgr = cv2.resize(bgr, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
            h, w = bgr.shape[:2]
        faces = self.landmarker.detect_faces(bgr)
        if not faces:
            return FaceAnalysis("reject", [Issue("reject", "We could not find a face. Use a clear, front-facing photo in good light.")])
        if len(faces) > 1:
            return FaceAnalysis("reject", [Issue("reject", "We found more than one face. Use a photo with only you in it.")])

        pts = faces[0].landmarks
        m = measure(pts, w, h)
        issues = photo_checks(m, pts, bgr)
        result = FaceAnalysis(
            status="reject" if any(i.level == "reject" for i in issues) else ("warn" if issues else "ok"),
            issues=issues,
            measurements={k: round(float(v), 3) for k, v in m.items()},
            guide_points={name: (float(pts[i, 0]), float(pts[i, 1])) for name, i in GUIDE_POINTS.items()},
            face_box=(float(pts[:, 0].min()), float(pts[:, 1].min()), float(pts[:, 0].max()), float(pts[:, 1].max())),
            placement=compute_placement(pts, w, h),
            pose3d=head_pose(faces[0].matrix, w, h),
        )
        if result.status == "reject":
            return result
        ranked = classify(m)
        (top, p1), (_, p2) = ranked[0], ranked[1]
        conf = min(0.85, p1 * (0.75 if issues else 1.0))
        result.shape = top
        result.confidence = round(conf, 2)
        result.probabilities = {s_: round(p, 4) for s_, p in ranked}
        result.needs_confirmation = bool(issues) or conf < 0.55 or (p1 - p2) < 0.15
        return result

    def close(self) -> None:
        self.landmarker.close()
