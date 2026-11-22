"""Face landmarks with MediaPipe's Face Landmarker (CPU). The model file ships inside the package."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from tryon.config import FACE_MODEL_PATH


@dataclass(frozen=True)
class Face:
    landmarks: np.ndarray            # (478, 3) normalised x, y, z
    matrix: np.ndarray | None        # 4x4 head pose (canonical face in cm -> camera), None if MediaPipe gave none


def _faces(result) -> list[Face]:
    mats = list(getattr(result, "facial_transformation_matrixes", None) or [])
    out = []
    for i, face in enumerate(result.face_landmarks):
        out.append(Face(np.array([[p.x, p.y, p.z] for p in face]), np.array(mats[i], float).reshape(4, 4) if i < len(mats) else None))
    return out


class FaceLandmarker:
    """Returns, for a photo, one (478, 3) array of normalised x, y, z per face found (and the head pose via `detect_faces`)."""

    def __init__(self, model_path: Path = FACE_MODEL_PATH) -> None:
        if not Path(model_path).is_file():
            raise FileNotFoundError(f"Face model missing: {model_path}. Reinstall the project or restore that file.")
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision

        self._mp = mp
        self._lock = threading.Lock()          # the MediaPipe graph handles one photo at a time
        self._landmarker = vision.FaceLandmarker.create_from_options(
            vision.FaceLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=str(model_path)),
                running_mode=vision.RunningMode.IMAGE,
                num_faces=2,
                min_face_detection_confidence=0.5,
                min_face_presence_confidence=0.5,
                output_facial_transformation_matrixes=True,
            )
        )

    def detect_faces(self, bgr: np.ndarray) -> list[Face]:
        rgb = np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        with self._lock:
            result = self._landmarker.detect(image)
        return _faces(result)

    def detect(self, bgr: np.ndarray) -> list[np.ndarray]:
        return [f.landmarks for f in self.detect_faces(bgr)]

    def close(self) -> None:
        with self._lock:
            if self._landmarker is not None:
                self._landmarker.close()
                self._landmarker = None


class FaceTracker:
    """One person's live camera: video mode (tracks from frame to frame, cheaper and steadier than detecting every time).

    Create one per connection and call `process` with one frame at a time. Not shared between users.
    """

    def __init__(self, model_path: Path = FACE_MODEL_PATH) -> None:
        if not Path(model_path).is_file():
            raise FileNotFoundError(f"Face model missing: {model_path}.")
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision

        self._mp = mp
        self._last_ms = 0
        self._landmarker = vision.FaceLandmarker.create_from_options(
            vision.FaceLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=str(model_path)),
                running_mode=vision.RunningMode.VIDEO,
                num_faces=1,
                min_face_detection_confidence=0.5,
                min_face_presence_confidence=0.5,
                min_tracking_confidence=0.5,
                output_facial_transformation_matrixes=True,
            )
        )

    def process(self, bgr: np.ndarray) -> Face | None:
        rgb = np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        now = int(time.monotonic() * 1000)
        self._last_ms = max(now, self._last_ms + 1)            # MediaPipe needs strictly increasing timestamps
        result = self._landmarker.detect_for_video(image, self._last_ms)
        faces = _faces(result)
        return faces[0] if faces else None

    def close(self) -> None:
        if self._landmarker is not None:
            self._landmarker.close()
            self._landmarker = None
