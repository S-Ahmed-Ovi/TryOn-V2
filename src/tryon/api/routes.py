"""HTTP API. The browser analyses a photo once, then re-ranks / filters with cheap JSON calls."""
from __future__ import annotations

import asyncio
from collections import Counter

import cv2
import numpy as np
from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from tryon import __version__
from tryon.api import serialize as ser
from tryon.recommend.engine import make_profile, recommend
from tryon.vision.face_shape import SHAPES
from tryon.vision.live import process_frame
from tryon.vision.pose3d import FOV_Y_DEG

router = APIRouter(prefix="/api")
AUDIENCES = ("all", "men", "women", "kids")
LIVE_IDLE_SECONDS = 90          # a live-camera connection that sends nothing for this long is closed


class RecommendRequest(BaseModel):
    shape: str = Field(description="Face shape: oval, round, square, heart or oblong")
    overridden: bool = Field(False, description="True when the person picked the shape themselves")
    probabilities: dict[str, float] | None = None
    measurements: dict[str, float] | None = None
    audience: str = "all"
    frame_shapes: list[str] = []
    colors: list[str] = []


def _recommendations(request: Request, profile, audience: str, frame_shapes=None, colors=None) -> dict:
    rules, catalog = request.app.state.rules, request.app.state.catalog
    everything = recommend(rules, catalog.products, profile, audience=audience)
    shown = recommend(rules, catalog.products, profile, audience=audience, frame_shapes=set(frame_shapes or []), colors=set(colors or []))
    return ser.recommendations_json(rules, catalog, profile, shown, audience, everything)


def _audience(value: str) -> str:
    if value not in AUDIENCES:
        raise HTTPException(422, f"audience must be one of {', '.join(AUDIENCES)}")
    return value


@router.get("/health")
def health(request: Request) -> dict:
    return {"status": "ok", "version": __version__, "products": len(request.app.state.catalog.products),
            "face_model": request.app.state.detector is not None,
            "live_camera": request.app.state.tracker_factory is not None}


@router.get("/meta")
def meta(request: Request) -> dict:
    s, rules, catalog = request.app.state.settings, request.app.state.rules, request.app.state.catalog
    first_hex = {}
    for p in catalog.products:
        first_hex.setdefault(p.color_name, p.color_hex)
    names = Counter(p.color_name for p in catalog.products)
    return {
        "site_name": s.site_name, "version": __version__, "catalog_version": catalog.version,
        "product_count": len(catalog.products),
        "live_camera": request.app.state.tracker_factory is not None,
        "live_max_fps": 15,
        "face_shapes": ser.face_shapes_json(rules, {p.frame_shape for p in catalog.products}),
        "frame_shapes": [{"key": k, "label": v["label"], "summary": v["summary"],
                          "count": sum(1 for p in catalog.products if p.frame_shape == k),
                          "best_for": [{"face": f, "label": rules.face_shapes[f]["label"], "score": rules.frame_score(f, k)}
                                       for f in sorted(rules.face_shapes, key=lambda f: -rules.frame_score(f, k))[:2]]}
                         for k, v in rules.frame_shapes.items()],
        "colors": [{"name": n, "hex": first_hex[n], "count": c} for n, c in names.most_common()],
        "audiences": dict(Counter(p.audience for p in catalog.products)),
    }


@router.get("/catalog")
def catalog_listing(request: Request) -> dict:
    rules, catalog = request.app.state.rules, request.app.state.catalog
    return {"items": [ser.product_json(p, rules, catalog.version) for p in catalog.products]}


@router.post("/recommend")
def recommend_for_shape(body: RecommendRequest, request: Request) -> dict:
    """Re-rank for a face shape the person chose (or to filter) without uploading the photo again."""
    if body.shape not in SHAPES:
        raise HTTPException(422, f"shape must be one of {', '.join(SHAPES)}")
    profile = make_profile(body.shape, body.probabilities, body.measurements, body.overridden)
    return _recommendations(request, profile, _audience(body.audience), body.frame_shapes, body.colors)


@router.post("/analyze")
def analyze(request: Request, photo: UploadFile = File(...), audience: str = Form("all")) -> dict:
    """Find the face in a photo, work out its shape and recommend frames. The photo is never stored."""
    audience = _audience(audience)
    detector = request.app.state.detector
    if detector is None:
        raise HTTPException(503, "The face model could not be loaded on the server.")
    limit = request.app.state.settings.max_upload_bytes
    data = photo.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(413, f"That photo is too large (limit {limit // (1024 * 1024)} MB).")
    bgr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if bgr is None:
        raise HTTPException(400, "That file is not a photo we can read. Use a JPG, PNG or WebP image.")
    if bgr.shape[0] * bgr.shape[1] > 40_000_000:
        raise HTTPException(413, "That photo has too many pixels. Use a smaller one.")

    a = detector.analyze(bgr)
    out = {"status": a.status, "issues": [{"level": i.level, "message": i.message} for i in a.issues]}
    if a.status == "reject":
        return out
    rules = request.app.state.rules
    profile = make_profile(a.shape, a.probabilities, a.measurements)
    out["face"] = ser.face_json(a, rules)
    out["placement"] = a.placement.as_dict()
    out["pose3d"] = getattr(a, "pose3d", None)             # head pose for the real 3D try-on (null: only the 2D try-on is offered)
    out["recommendations"] = _recommendations(request, profile, audience)
    return out


@router.websocket("/track")
async def track(ws: WebSocket) -> None:
    """Live 3D try-on. The browser sends camera frames (4-byte number + JPEG); each one is answered with the head pose.

    The face is tracked on this server (CPU), one tracker per connection, and nothing is stored.
    """
    state = ws.app.state
    await ws.accept()
    factory = getattr(state, "tracker_factory", None)
    if factory is None:
        await ws.send_json({"error": "unavailable", "message": "The face model could not be loaded on the server."})
        await ws.close(code=1011)
        return
    if state.live_sessions >= state.settings.max_live_sessions:
        await ws.send_json({"error": "busy", "message": "The live camera is busy right now. Try again in a minute, or use a photo."})
        await ws.close(code=1013)
        return
    state.live_sessions += 1
    tracker = None
    try:
        tracker = await run_in_threadpool(factory)
        await ws.send_json({"ready": True, "fov_y": FOV_Y_DEG})
        while True:
            msg = await asyncio.wait_for(ws.receive(), LIVE_IDLE_SECONDS)
            if msg["type"] == "websocket.disconnect":
                break
            data = msg.get("bytes")
            if data:
                await ws.send_json(await run_in_threadpool(process_frame, tracker, data))
    except (WebSocketDisconnect, asyncio.TimeoutError):
        pass
    except RuntimeError:                                  # the socket was closed under us
        pass
    finally:
        state.live_sessions -= 1
        if tracker is not None:
            await run_in_threadpool(tracker.close)
        try:
            await ws.close()
        except RuntimeError:
            pass
