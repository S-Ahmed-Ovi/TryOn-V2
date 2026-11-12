"""Draw a glasses PNG (transparent background, front view) onto a face photo using MediaPipe landmarks."""
import math
import cv2
import numpy as np

EYE_R = (33, 133, 159, 145)        # subject's right eye (left side of the picture): corners + lids
EYE_L = (362, 263, 386, 374)
CHEEK_R, CHEEK_L = 234, 454        # widest part of the face
LENS_ALPHA = 0.92                  # dark lens pixels are very slightly see-through


def decode_rgba(png_bytes):
    im = cv2.imdecode(np.frombuffer(png_bytes, np.uint8), cv2.IMREAD_UNCHANGED)
    return im if im is not None and im.ndim == 3 and im.shape[2] == 4 else None


def mirror_symmetry(rgba):
    """Left/right mirror overlap (IoU) of the glasses silhouette: 1 = perfectly symmetric front view."""
    m = (rgba[..., 3] > 40).astype(np.uint8)
    ys, xs = np.where(m > 0)
    m = m[ys.min():ys.max() + 1, xs.min():xs.max() + 1]
    k = max(3, int(0.012 * m.shape[1])) | 1                   # tolerate 1-2 px misalignment of thin wire frames
    m = cv2.dilate(m, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    f = m[:, ::-1]
    return float((m & f).sum() / max((m | f).sum(), 1))


def png_quality(rgba):
    """(ok, reason). Rejects cut-outs that are not a single pair of glasses (clip-on sets, cases, bad crops)."""
    h, w = rgba.shape[:2]
    if not 1.5 <= w / h <= 5.0:
        return False, "odd proportions (%.1f:1)" % (w / h)
    m = (rgba[..., 3] > 128).astype(np.uint8)
    if m.sum() < 0.08 * w * h:
        return False, "almost empty"
    n, _, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    areas = sorted(st[1:, 4], reverse=True)
    if len([a for a in areas if a >= 0.08 * sum(areas)]) > 2:
        return False, "several separate objects (clip-on set?)"
    sym = mirror_symmetry(rgba)
    if sym < 0.5:                                    # front views score 0.63-0.97, angled shots 0.26-0.35
        return False, "angled view, not front-facing (symmetry %.2f)" % sym
    return True, ""


def place_glasses(bgr, pts, rgba, fit=1.0):
    """bgr: face photo, pts: (468,3) normalised landmarks of that photo, rgba: glasses (BGRA).
    The glasses are scaled to the face width, rotated with the head tilt and centred on the eyes."""
    h, w = bgr.shape[:2]
    P = pts[:, :2] * [w, h]
    eye_r, eye_l = P[list(EYE_R)].mean(0), P[list(EYE_L)].mean(0)
    centre = (eye_r + eye_l) / 2
    roll = math.degrees(math.atan2(eye_l[1] - eye_r[1], eye_l[0] - eye_r[0]))
    cheek = float(np.linalg.norm(P[CHEEK_L] - P[CHEEK_R]))

    scale = fit * cheek / rgba.shape[1]
    g = cv2.resize(rgba, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_CUBIC)
    ys, xs = np.where(g[..., 3] > 128)
    ax, ay = (xs.min() + xs.max()) / 2.0, ys.mean()           # anchor = middle of the glasses, lens-level
    g = g.astype(np.float32)
    alpha = g[..., 3:4] / 255.0
    lum = g[..., :3].mean(axis=2, keepdims=True)
    alpha = np.where((lum > 165) & (alpha < 0.95), 0.0, alpha)   # faint light fringe = leftover floor shadow of the studio photo
    alpha = np.where(lum < 110, alpha * LENS_ALPHA, alpha)
    pm = np.dstack([g[..., :3] * alpha, alpha[..., 0]])        # premultiplied -> no white halo at the edges
    M = cv2.getRotationMatrix2D((float(ax), float(ay)), -roll, 1.0)
    M[:, 2] += centre - np.array([ax, ay])
    wp = cv2.warpAffine(pm, M, (w, h), flags=cv2.INTER_LINEAR, borderValue=(0, 0, 0, 0))
    A, F = wp[..., 3:4], wp[..., :3]

    shadow = cv2.GaussianBlur(A[..., 0], (0, 0), max(1.5, 0.018 * cheek))
    shadow = cv2.warpAffine(shadow, np.float32([[1, 0, 0], [0, 1, 0.025 * cheek]]), (w, h))
    base = bgr.astype(np.float32) * (1 - 0.30 * shadow[..., None])
    return np.clip(F + (1 - A) * base, 0, 255).astype(np.uint8)


def crop_face(img, pts, out_side=560):
    """Square crop around the face so the result is shown large."""
    h, w = img.shape[:2]
    P = pts[:, :2] * [w, h]
    (x0, y0), (x1, y1) = P.min(0), P.max(0)
    side = int(min(max(x1 - x0, y1 - y0) * 1.7, min(w, h)))
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    x = int(np.clip(cx - side / 2, 0, w - side)); y = int(np.clip(cy - side / 2, 0, h - side))
    c = img[y:y + side, x:x + side]
    return cv2.resize(c, (out_side, out_side), interpolation=cv2.INTER_AREA if side > out_side else cv2.INTER_CUBIC)
