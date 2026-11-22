from tests.conftest import FakeDetector  # noqa: F401  (documented helper)


def test_health_and_meta(client):
    assert client.get("/api/health").json()["products"] > 0
    meta = client.get("/api/meta").json()
    assert {f["key"] for f in meta["face_shapes"]} == {"oval", "round", "square", "heart", "oblong"}
    assert meta["product_count"] == sum(f["count"] for f in meta["frame_shapes"])
    for f in meta["face_shapes"]:                                         # the guide only promises styles that are in stock
        in_stock = {s["key"] for s in meta["frame_shapes"] if s["count"]}
        assert {b["shape"] for b in f["best"]} <= in_stock


def test_catalog_listing_and_media(client):
    items = client.get("/api/catalog").json()["items"]
    assert len(items) == 24
    assert {"sku", "cutout", "thumb", "aspect", "scale", "anchor", "color", "lens", "size", "model"} <= set(items[0])
    assert "url" not in items[0]                                              # no shop links any more
    r = client.get(items[0]["cutout"])
    assert r.status_code == 200 and r.headers["content-type"] == "image/webp" and "max-age" in r.headers["cache-control"]
    m = client.get(items[0]["model"])                                         # the 3D model is served too
    assert m.status_code == 200 and m.content[:4] == b"glTF"


def test_index_page_uses_the_site_name(client):
    r = client.get("/")
    assert r.status_code == 200 and "{{SITE_NAME}}" not in r.text and "<title>" in r.text


def test_analyze_returns_face_placement_and_matches(client, photo_bytes):
    r = client.post("/api/analyze", files={"photo": ("p.jpg", photo_bytes, "image/jpeg")}, data={"audience": "all"})
    body = r.json()
    assert r.status_code == 200 and body["status"] == "ok"
    assert body["face"]["shape"] == "oblong" and len(body["face"]["probabilities"]) == 5 and len(body["face"]["traits"]) == 4
    assert set(body["placement"]) == {"cx", "cy", "width", "angle"}
    pose = body["pose3d"]                                                     # head pose for the real 3D try-on
    assert len(pose["matrix"]) == 16 and pose["fov_y"] == 63.0 and pose["usable"] and abs(pose["yaw"]) < 1
    recs = body["recommendations"]
    assert recs["total"] == len(recs["items"]) > 0
    first = recs["items"][0]
    assert 35 <= first["match"]["percent"] <= 98 and first["reasons"] and first["cutout"].startswith("/media/")


def test_analyze_rejection_is_reported_not_raised(client, photo_bytes):
    client.app.state.detector = FakeDetector("reject")
    body = client.post("/api/analyze", files={"photo": ("p.jpg", photo_bytes, "image/jpeg")}).json()
    assert body["status"] == "reject" and body["issues"] and "recommendations" not in body


def test_analyze_validates_input(client, photo_bytes):
    assert client.post("/api/analyze", files={"photo": ("x.txt", b"hello", "text/plain")}).status_code == 400
    assert client.post("/api/analyze", files={"photo": ("p.jpg", photo_bytes, "image/jpeg")}, data={"audience": "robots"}).status_code == 422
    client.app.state.settings = client.app.state.settings.__class__(**{**client.app.state.settings.__dict__, "max_upload_bytes": 100})
    assert client.post("/api/analyze", files={"photo": ("p.jpg", photo_bytes, "image/jpeg")}).status_code == 413


def test_recommend_for_a_chosen_shape_and_filters(client):
    body = {"shape": "round", "overridden": True, "audience": "women", "frame_shapes": ["rectangle"]}
    r = client.post("/api/recommend", json=body).json()
    assert r["overridden"] and r["face_shape"] == "round"
    assert r["items"] and {i["frame_shape"] for i in r["items"]} == {"rectangle"}
    assert {s["shape"] for s in r["styles"]} > {"rectangle"}              # style summary ignores the style filter itself
    assert client.post("/api/recommend", json={"shape": "triangle"}).status_code == 422
    assert client.post("/api/recommend", json={"shape": "oval", "audience": "x"}).status_code == 422


def test_meta_says_whether_the_live_camera_is_available(client):
    assert client.get("/api/meta").json()["live_camera"] is True
    assert client.get("/api/health").json()["live_camera"] is True


def _frame(width=320, height=240, seq=7):
    import cv2
    import numpy as np
    ok, jpg = cv2.imencode(".jpg", np.full((height, width, 3), 120, np.uint8))
    assert ok
    return seq.to_bytes(4, "big") + jpg.tobytes()


def test_live_track_answers_every_frame_with_a_pose(client):
    with client.websocket_connect("/api/track") as ws:
        assert ws.receive_json() == {"ready": True, "fov_y": 63.0}
        for seq in (1, 2, 3):
            ws.send_bytes(_frame(seq=seq))
            reply = ws.receive_json()
            assert reply["seq"] == seq and reply["ok"] and len(reply["pose"]["matrix"]) == 16 and reply["ms"] >= 0
    assert client.app.state.live_sessions == 0                               # the slot is given back


def test_live_track_rejects_garbage_frames_without_dying(client):
    with client.websocket_connect("/api/track") as ws:
        ws.receive_json()
        ws.send_bytes(b"\x00\x00\x00\x01not a jpeg at all")
        assert ws.receive_json()["reason"] == "bad_frame"
        ws.send_bytes(_frame(seq=2))
        assert ws.receive_json()["ok"]


def test_live_track_has_a_limit_on_simultaneous_cameras(client):
    state = client.app.state
    state.settings = state.settings.__class__(**{**state.settings.__dict__, "max_live_sessions": 1})
    with client.websocket_connect("/api/track") as first:
        first.receive_json()
        with client.websocket_connect("/api/track") as second:
            msg = second.receive_json()
            assert msg["error"] == "busy"
            closing = second.receive()
            assert closing["type"] == "websocket.close" and closing["code"] == 1013


def test_live_track_is_reported_unavailable_without_a_face_model(client):
    client.app.state.tracker_factory = None
    with client.websocket_connect("/api/track") as ws:
        assert ws.receive_json()["error"] == "unavailable"
