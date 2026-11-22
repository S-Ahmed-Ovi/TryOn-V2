import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from tryon.api.app import create_app
from tryon.catalog.store import load_catalog
from tryon.config import load_settings
from tryon.recommend.rules import load_rules
from tryon.vision.face_shape import FaceAnalysis, Issue
from tryon.vision.landmarks import Face
from tryon.vision.placement import Placement
from tryon.vision.pose3d import head_pose

MEASUREMENTS = {"length_cheek": 1.27, "jaw_cheek": 0.79, "fore_jaw": 1.09, "chin_angle": 107.0,
                "yaw": 3.0, "roll": 1.0, "nose_ratio": 0.4, "face_h_frac": 0.5}


def head_matrix(yaw_deg=0.0, dist=45.0):
    """A head 45 cm in front of the camera, turned by yaw_deg (what MediaPipe's facial transformation matrix looks like)."""
    a = np.radians(yaw_deg)
    m = np.eye(4)
    m[:3, :3] = [[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]]
    m[2, 3] = -dist
    return m


class FakeTracker:
    """Stands in for the live face tracker: always finds a face, turned by `yaw`."""

    def __init__(self, yaw=0.0):
        self.yaw, self.closed = yaw, False

    def process(self, bgr):
        return Face(np.zeros((478, 3)), head_matrix(self.yaw))

    def close(self):
        self.closed = True


class FakeDetector:
    """Stands in for the MediaPipe detector so API tests do not need a real face photo."""

    def __init__(self, status="ok"):
        self.status = status

    def analyze(self, bgr):
        if self.status == "reject":
            return FaceAnalysis("reject", [Issue("reject", "We could not find a face.")])
        probs = {"oblong": 0.55, "oval": 0.25, "square": 0.1, "round": 0.06, "heart": 0.04}
        return FaceAnalysis(
            status="ok", shape="oblong", confidence=0.55, needs_confirmation=False, probabilities=probs,
            measurements=MEASUREMENTS, guide_points={"top": (0.5, 0.2), "chin": (0.5, 0.8), "cheek_r": (0.3, 0.45),
                                                     "cheek_l": (0.7, 0.45), "jaw_r": (0.35, 0.7), "jaw_l": (0.65, 0.7),
                                                     "fore_r": (0.35, 0.28), "fore_l": (0.65, 0.28)},
            face_box=(0.3, 0.2, 0.7, 0.8), placement=Placement(0.5, 0.4, 0.4, 2.0),
            pose3d=head_pose(head_matrix(), 320, 240))

    def close(self):
        pass


@pytest.fixture(scope="session")
def rules():
    return load_rules()


@pytest.fixture(scope="session")
def catalog():
    return load_catalog(load_settings())


@pytest.fixture()
def client(catalog, rules):
    app = create_app(load_settings(), catalog=catalog, detector=FakeDetector(), rules=rules, tracker_factory=FakeTracker)
    with TestClient(app) as c:
        yield c


@pytest.fixture()
def photo_bytes():
    ok, buf = cv2.imencode(".jpg", np.full((240, 320, 3), 128, np.uint8))
    assert ok
    return buf.tobytes()
