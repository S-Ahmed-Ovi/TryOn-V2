"""Head pose for the real 3D try-on, and the live-camera frame handler."""
import cv2
import numpy as np
import pytest

from tests.conftest import FakeTracker, head_matrix
from tryon.vision.landmarks import Face
from tryon.vision.live import MAX_FRAME_BYTES, process_frame
from tryon.vision.pose3d import FOV_Y_DEG, euler_degrees, head_pose


def jpeg(seq=1, w=320, h=240):
    ok, buf = cv2.imencode(".jpg", np.full((h, w, 3), 100, np.uint8))
    assert ok
    return seq.to_bytes(4, "big") + buf.tobytes()


def test_a_straight_head_has_no_rotation():
    pose = head_pose(head_matrix(), 640, 480)
    assert pose["yaw"] == pytest.approx(0, abs=0.1) and pose["pitch"] == pytest.approx(0, abs=0.1) and pose["roll"] == pytest.approx(0, abs=0.1)
    assert pose["fov_y"] == FOV_Y_DEG == 63.0 and pose["aspect"] == pytest.approx(640 / 480, abs=1e-4)
    assert len(pose["matrix"]) == 16 and pose["usable"]


def test_yaw_sign_and_usable_limit():
    right = head_pose(head_matrix(yaw_deg=30), 640, 480)          # nose towards image-right
    left = head_pose(head_matrix(yaw_deg=-30), 640, 480)
    assert right["yaw"] == pytest.approx(30, abs=0.2) and left["yaw"] == pytest.approx(-30, abs=0.2)
    assert head_pose(head_matrix(yaw_deg=70), 640, 480)["usable"] is False        # too far round to place glasses convincingly


def test_pitch_and_roll_are_recovered():
    a = np.radians(20)
    down = np.eye(4); down[:3, :3] = [[1, 0, 0], [0, np.cos(a), -np.sin(a)], [0, np.sin(a), np.cos(a)]]; down[2, 3] = -45   # +x turn tips the face down
    assert head_pose(down, 640, 480)["pitch"] == pytest.approx(-20, abs=0.2)
    up = down.copy(); up[:3, :3] = up[:3, :3].T
    assert head_pose(up, 640, 480)["pitch"] == pytest.approx(20, abs=0.2)
    roll = np.eye(4); roll[:3, :3] = [[np.cos(a), -np.sin(a), 0], [np.sin(a), np.cos(a), 0], [0, 0, 1]]; roll[2, 3] = -45
    assert abs(head_pose(roll, 640, 480)["roll"]) == pytest.approx(20, abs=0.2)
    assert euler_degrees(np.eye(3)) == pytest.approx((0, 0, 0), abs=1e-6)


def test_nonsense_matrices_are_rejected():
    assert head_pose(None, 640, 480) is None
    bad = head_matrix(); bad[0, 0] = np.nan
    assert head_pose(bad, 640, 480) is None
    behind = head_matrix(); behind[2, 3] = 20                      # behind the camera
    assert head_pose(behind, 640, 480) is None
    huge = head_matrix(); huge[:3, :3] *= 5                        # not a head-sized transform
    assert head_pose(huge, 640, 480) is None


# ── live frames ────────────────────────────────────────────────────────────
def test_a_frame_gives_a_pose_with_its_own_number():
    out = process_frame(FakeTracker(), jpeg(seq=41))
    assert out["seq"] == 41 and out["ok"] and out["pose"]["usable"] and out["ms"] >= 0


def test_no_face_and_extreme_turns_are_reported():
    class Nobody:
        def process(self, bgr): return None
    assert process_frame(Nobody(), jpeg(seq=2)) == {"seq": 2, "ok": False, "reason": "no_face"}
    out = process_frame(FakeTracker(yaw=75), jpeg(seq=3))
    assert out["ok"] is False and out["reason"] == "unusable" and out["pose"]["yaw"] > 60


def test_bad_frames_never_raise():
    assert process_frame(FakeTracker(), b"")["reason"] == "bad_frame"
    assert process_frame(FakeTracker(), b"\x00\x00\x00\x01" + b"not an image")["reason"] == "bad_frame"
    assert process_frame(FakeTracker(), b"\x00" * (MAX_FRAME_BYTES + 1))["reason"] == "bad_frame"
    assert process_frame(FakeTracker(), jpeg(w=2000, h=100))["reason"] == "bad_frame"     # larger than the tracker accepts
