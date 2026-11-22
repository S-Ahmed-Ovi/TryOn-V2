"""One frame of the live camera: JPEG in, head pose out. Kept free of web code so it is easy to test.

Wire format (browser -> server, binary WebSocket message):   4 bytes frame number (big endian) + a JPEG
Reply (server -> browser, JSON):   {"seq": n, "ok": true, "pose": {...}, "ms": 14.2}
                                   {"seq": n, "ok": false, "reason": "no_face" | "unusable" | "bad_frame"}
"""
from __future__ import annotations

import time

import cv2
import numpy as np

from tryon.vision.pose3d import head_pose

MAX_FRAME_BYTES = 1_000_000
MAX_SIDE = 1280


def process_frame(tracker, data: bytes) -> dict:
    t0 = time.perf_counter()
    if len(data) < 12 or len(data) > MAX_FRAME_BYTES:
        return {"seq": 0, "ok": False, "reason": "bad_frame"}
    seq = int.from_bytes(data[:4], "big")
    bgr = cv2.imdecode(np.frombuffer(data, np.uint8, offset=4), cv2.IMREAD_COLOR)
    if bgr is None or max(bgr.shape[:2]) > MAX_SIDE:
        return {"seq": seq, "ok": False, "reason": "bad_frame"}
    h, w = bgr.shape[:2]
    face = tracker.process(bgr)
    if face is None:
        return {"seq": seq, "ok": False, "reason": "no_face"}
    pose = head_pose(face.matrix, w, h)
    if pose is None:
        return {"seq": seq, "ok": False, "reason": "unusable"}
    return {"seq": seq, "ok": bool(pose["usable"]), **({} if pose["usable"] else {"reason": "unusable"}),
            "pose": pose, "ms": round((time.perf_counter() - t0) * 1000, 1)}
