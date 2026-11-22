"""Developer tool: find the face in a photo and save what tools/compose_photo.mjs needs to draw a model on it.

    python tools/export_pose.py portrait.jpg out/portrait        # writes out/portrait.rgba and out/portrait.json
    node tools/compose_photo.mjs out/portrait.rgba out/portrait.json TO-WAY-01 look.png [x0,y0,x1,y1]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from tryon.vision.landmarks import FaceLandmarker  # noqa: E402
from tryon.vision.pose3d import head_pose  # noqa: E402


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    photo, base = Path(sys.argv[1]), Path(sys.argv[2])
    bgr = cv2.imread(str(photo))
    if bgr is None:
        print(f"Cannot read {photo}")
        return 1
    h, w = bgr.shape[:2]
    detector = FaceLandmarker()
    try:
        faces = detector.detect_faces(bgr)
    finally:
        detector.close()
    pose = head_pose(faces[0].matrix, w, h) if faces else None
    if pose is None:
        print("No face with a usable 3D pose was found.")
        return 1
    base.parent.mkdir(parents=True, exist_ok=True)
    cv2.cvtColor(bgr, cv2.COLOR_BGR2RGBA).tofile(str(base.with_suffix(".rgba")))
    base.with_suffix(".json").write_text(json.dumps({"w": w, "h": h, "pose": pose}), encoding="utf-8")
    print(f"{w}x{h}  yaw {pose['yaw']:.1f}  pitch {pose['pitch']:.1f}  roll {pose['roll']:.1f}  usable={pose['usable']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
