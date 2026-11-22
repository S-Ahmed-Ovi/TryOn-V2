import math

import numpy as np
import pytest

from tryon.vision.face_shape import PROTOTYPES, classify
from tryon.vision.placement import CHEEK_L, CHEEK_R, EYE_L, EYE_R, compute_placement


def test_each_prototype_is_classified_as_itself():
    for shape, ((L, _), (J, _), (F, _), (A, _)) in PROTOTYPES.items():
        ranked = classify({"length_cheek": L, "jaw_cheek": J, "fore_jaw": F, "chin_angle": A})
        assert ranked[0][0] == shape
        assert sum(p for _, p in ranked) == pytest.approx(1.0)


def _mesh(eye_dy=0.0):
    pts = np.zeros((478, 3))
    for i in EYE_R:
        pts[i] = (0.40, 0.40, 0)
    for i in EYE_L:
        pts[i] = (0.60, 0.40 + eye_dy, 0)
    pts[CHEEK_R] = (0.30, 0.5, 0)
    pts[CHEEK_L] = (0.70, 0.5, 0)
    return pts


def test_placement_is_relative_to_the_photo():
    p = compute_placement(_mesh(), 1000, 500)
    assert (p.cx, p.cy) == pytest.approx((0.5, 0.40))
    assert p.width == pytest.approx(0.4)            # 400 px of a 1000 px photo
    assert p.angle == pytest.approx(0.0)


def test_placement_measures_head_tilt_clockwise():
    p = compute_placement(_mesh(eye_dy=0.1), 1000, 1000)    # right eye lower -> head tilted clockwise
    assert p.angle == pytest.approx(math.degrees(math.atan2(0.1, 0.2)))
