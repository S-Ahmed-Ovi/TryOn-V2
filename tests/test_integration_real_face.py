"""Optional end-to-end check with a real photo:  TRYON_TEST_PHOTO=path/to/face.jpg pytest tests/test_integration_real_face.py"""
import os

import cv2
import pytest

PHOTO = os.environ.get("TRYON_TEST_PHOTO")
pytestmark = pytest.mark.skipif(not PHOTO, reason="set TRYON_TEST_PHOTO to run")


def test_real_photo_gives_a_face_shape_and_placement():
    from tryon.vision.face_shape import SHAPES, FaceShapeDetector

    detector = FaceShapeDetector()
    try:
        result = detector.analyze(cv2.imread(PHOTO))
    finally:
        detector.close()
    assert result.status in ("ok", "warn")
    assert result.shape in SHAPES and abs(sum(result.probabilities.values()) - 1) < 0.01
    assert 0 < result.placement.width < 1 and 0 < result.placement.cx < 1
