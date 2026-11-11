"""
Frame-shape detection with OpenCV (CPU only). Works on one decoded image at a time:
    from detect_frames import load_image, detect
    result, lens_contours = detect(load_image(jpeg_bytes))
Finds the two lenses, measures their geometry (aspect ratio, extent, ellipse fit, corner profile, taper,
left/right symmetry) and returns a shape or "unknown" when the image is not reliable enough.
"""
import argparse, json, math, sqlite3, sys, time
import cv2
import numpy as np

SIZE = 480                      # working resolution (longest side)
SHAPES = ["aviator", "wayfarer", "round", "rectangle", "square", "cat-eye", "oval", "geometric", "unknown"]


# ----------------------------------------------------------------------------- loading
def load_image(blob):
    arr = np.frombuffer(blob, np.uint8)
    im = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if im is None:
        return None
    s = SIZE / max(im.shape[:2])
    return cv2.resize(im, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)


# ----------------------------------------------------------------------------- lens candidates
def _cells_from_mask(mask, H, W):
    """Closed regions that are NOT part of `mask` and do not leak to the image border."""
    free = cv2.bitwise_not(mask)
    n, lab, stats, cent = cv2.connectedComponentsWithStats(free, connectivity=4)
    out = []
    for i in range(1, n):
        x, y, w, h, a = stats[i]
        if a < 0.012 * H * W or a > 0.30 * H * W:
            continue
        if x <= 1 or y <= 1 or x + w >= W - 1 or y + h >= H - 1:
            continue                                  # leaks to border -> background
        m = (lab == i).astype(np.uint8) * 255
        cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if cs:
            out.append(max(cs, key=cv2.contourArea))
    return out


def _filled_rings(mask, H, W, close_k=7):
    """Fill closed frame loops, then delete thin parts (temples, bridge, text) with an opening.
    What remains are lens-sized blobs = lens + rim outline. Internal edges seen *through* the lens no longer matter."""
    m = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (close_k, close_k)))
    pad = cv2.copyMakeBorder(m, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    ff = pad.copy(); fm = np.zeros((H + 4, W + 4), np.uint8)
    cv2.floodFill(ff, fm, (0, 0), 255)                    # background reachable from outside
    filled = (pad | cv2.bitwise_not(ff))[1:-1, 1:-1]
    k = max(9, int(0.05 * SIZE)) | 1
    op = cv2.morphologyEx(filled, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    n, lb, st, _ = cv2.connectedComponentsWithStats(op, connectivity=8)
    out = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if a < 0.012 * H * W or a > 0.45 * H * W or x <= 1 or y <= 1 or x + w >= W - 1 or y + h >= H - 1:
            continue
        mm = (lb == i).astype(np.uint8) * 255
        if w > 1.7 * h:                                    # two rims fused: skip (splitting invents wedge shapes)
            continue
        cs, _ = cv2.findContours(mm, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        if cs:
            out.append(max(cs, key=cv2.contourArea))
    return out


def lens_candidates(im):
    """Return candidate lens contours from several complementary masks."""
    H, W = im.shape[:2]
    lab = cv2.cvtColor(im, cv2.COLOR_BGR2LAB)
    gray = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
    cands = []

    # (1) thin structures of any colour/polarity: difference to a heavy median background
    bg = cv2.medianBlur(cv2.GaussianBlur(im, (5, 5), 0), 41)
    bglab = cv2.cvtColor(bg, cv2.COLOR_BGR2LAB).astype(np.int16)
    d = np.abs(lab.astype(np.int16) - bglab)
    d = (d[..., 0] + 0.5 * d[..., 1] + 0.5 * d[..., 2])
    for thr in (14, 22, 32):
        mask_raw = (d > thr).astype(np.uint8) * 255
        m = cv2.morphologyEx(mask_raw, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
        cands += [("thin%d" % thr, c) for c in _cells_from_mask(m, H, W)]
        for ck in (3, 7):
            cands += [("ring%d" % thr, c) for c in _filled_rings(mask_raw, H, W, ck)]

    # (2) big dark blobs (solid dark lenses)
    g = cv2.GaussianBlur(gray, (5, 5), 0)
    for thr in (45, 70):
        m = (g < thr).astype(np.uint8) * 255
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
        n, lb, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
        for i in range(1, n):
            x, y, w, h, a = st[i]
            if a < 0.012 * H * W or x <= 1 or y <= 1 or x + w >= W - 1 or y + h >= H - 1:
                continue
            mm = (lb == i).astype(np.uint8) * 255
            cs, _ = cv2.findContours(mm, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
            if cs:
                cands.append(("dark%d" % thr, max(cs, key=cv2.contourArea)))
            if a > 0.06 * H * W:                      # maybe two lenses fused into one blob
                cands += [("split%d" % thr, c) for c in split_blob(mm)]
    cands = [(n, cv2.convexHull(c)) for n, c in cands]
    return cands, d


def context_ratio(d, ca, cb, H, W):
    """How big is the filled rim blob around each interior cell compared with the cell itself?
    ~1.1-1.9 for a complete lens opening, >2.1 when the cell is only a fragment of the lens.
    Returns None when there is no rim evidence at all."""
    m = (d > 22).astype(np.uint8) * 255
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)))
    pad = cv2.copyMakeBorder(m, 1, 1, 1, 1, cv2.BORDER_CONSTANT, value=0)
    ff = pad.copy(); cv2.floodFill(ff, np.zeros((H + 4, W + 4), np.uint8), (0, 0), 255)
    filled = (pad | cv2.bitwise_not(ff))[1:-1, 1:-1]
    k = max(9, int(0.05 * SIZE)) | 1
    op = cv2.morphologyEx(filled, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    n, lb, st, _ = cv2.connectedComponentsWithStats(op, connectivity=8)
    ids, areas = [], []
    for c in (ca, cb):
        M = cv2.moments(c); x, y = int(M["m10"] / M["m00"]), int(M["m01"] / M["m00"])
        ids.append(lb[y, x]); areas.append(cv2.contourArea(c))
    if ids[0] == 0 or ids[1] == 0:
        return None
    if ids[0] == ids[1]:
        return float(st[ids[0]][4] / (areas[0] + areas[1]))
    return float(max(st[ids[0]][4] / areas[0], st[ids[1]][4] / areas[1]))


def split_blob(mask_u8):
    """A dark blob that holds both lenses joined by a bridge: erode until it falls into 2 parts, grow back."""
    for k in range(3, 40, 2):
        er = cv2.erode(mask_u8, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
        n, lb, st, _ = cv2.connectedComponentsWithStats(er, connectivity=8)
        parts = [i for i in range(1, n) if st[i][4] > 0.004 * mask_u8.size]
        if len(parts) >= 2:
            parts = sorted(parts, key=lambda i: -st[i][4])[:2]
            out = []
            for i in parts:
                part = cv2.dilate((lb == i).astype(np.uint8) * 255,
                                  cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k + 2, k + 2)))
                part = cv2.bitwise_and(part, mask_u8)
                cs, _ = cv2.findContours(part, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
                if cs:
                    out.append(max(cs, key=cv2.contourArea))
            return out
        if len(parts) == 0:
            return []
    return []


def solidity(c):
    a = cv2.contourArea(c); h = cv2.contourArea(cv2.convexHull(c))
    return a / h if h > 0 else 0


def clean_lens(c, H, W):
    """Remove bridge / nose-pad stubs from a lens blob (opening sized to the lens), then smooth with the hull."""
    a = cv2.contourArea(c)
    k = max(5, int(0.30 * math.sqrt(a))) | 1
    m = np.zeros((H, W), np.uint8)
    cv2.drawContours(m, [c], -1, 255, -1)
    m = cv2.morphologyEx(m, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
    cs, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not cs:
        return None
    c2 = max(cs, key=cv2.contourArea)
    if cv2.contourArea(c2) < 0.7 * a:                 # opening ate too much -> not a plain lens blob
        return None
    hull = cv2.convexHull(c2)
    if cv2.contourArea(c2) / cv2.contourArea(hull) < 0.955:   # still concave (pads, shadow, bridge): hull would invent corners
        return None
    return hull


def mirror_iou(ca, cb):
    """Overlay lens A on the mirror image of lens B (aligned by centroid, same scale). 1.0 = perfect mirror pair."""
    def mom(c):
        M = cv2.moments(c); return np.array([M["m10"] / M["m00"], M["m01"] / M["m00"]])
    pa, pb = mom(ca), mom(cb)
    if pa[0] > pb[0]:
        ca, cb, pa, pb = cb, ca, pb, pa
    ang = math.atan2(pb[1] - pa[1], pb[0] - pa[0])
    t = -ang
    R = np.array([[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]])
    A = (ca.reshape(-1, 2) - pa) @ R.T
    B = (cb.reshape(-1, 2) - pb) @ R.T
    A[:, 0] *= -1                                  # left lens mirrored -> outer side is +x for both
    sc = 60.0 / math.sqrt(max(cv2.contourArea(ca.astype(np.float32)), 1.0) / math.pi + 1e-6) / 2
    ma = np.zeros((160, 160), np.uint8); mb = np.zeros((160, 160), np.uint8)
    cv2.fillPoly(ma, [(A * sc + 80).astype(np.int32)], 1)
    cv2.fillPoly(mb, [(B * sc + 80).astype(np.int32)], 1)
    inter = np.logical_and(ma, mb).sum(); uni = np.logical_or(ma, mb).sum()
    return inter / uni if uni else 0.0


def pair_lenses(cands, H, W):
    """Pick the two contours that best look like left/right lenses. Returns (a, b, score) or None."""
    good = []
    for src, c in cands:
        a = cv2.contourArea(c)
        if a < 0.012 * H * W or solidity(c) < 0.80:
            continue
        c = clean_lens(c, H, W)
        if c is None:
            continue
        a = cv2.contourArea(c)
        (cx, cy), (rw, rh), ang = cv2.minAreaRect(c)
        if min(rw, rh) < 8 or max(rw, rh) / min(rw, rh) > 2.4:
            continue
        M = cv2.moments(c)
        good.append((src[:4], c, a, np.array([M["m10"] / M["m00"], M["m01"] / M["m00"]]), max(rw, rh)))
    pairs = []
    for i in range(len(good)):
        for j in range(i + 1, len(good)):
            sa, ca, aa, pa, la = good[i]; sb, cb, ab, pb, lb_ = good[j]
            if sa != sb and not ({sa, sb} <= {'dark', 'spli'}):
                continue                       # both lenses must come from the same kind of evidence
            ratio = min(aa, ab) / max(aa, ab)
            if ratio < 0.55:
                continue
            v = pb - pa; dist = np.linalg.norm(v)
            wmean = (la + lb_) / 2                                   # ~ lens width
            gap = dist / wmean
            if not (0.95 <= gap <= 2.0):
                continue
            tilt = abs(math.degrees(math.atan2(v[1], v[0])))
            tilt = min(tilt, 180 - tilt)
            if tilt > 40:
                continue
            iou = mirror_iou(ca, cb)
            if iou < 0.6:
                continue
            s = (0.8 if sa == 'thin' else 1.0) * iou ** 2 * ratio * (1 - 0.3 * abs(gap - 1.25)) * (1 - tilt / 120)
            s *= min(1.0, (aa + ab) / (0.10 * H * W)) ** 0.3          # mild preference for big lenses
            pairs.append((ca, cb, s, iou, sa))
    pairs.sort(key=lambda t: -t[2])
    return pairs[:14]


# ----------------------------------------------------------------------------- geometry
def _normalise(c, centre, angle_deg, mirror):
    """Rotate contour so the lens-to-lens line is horizontal; mirror so 'outer' is +x."""
    p = c.reshape(-1, 2).astype(np.float64) - centre
    t = math.radians(-angle_deg)
    R = np.array([[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]])
    p = p @ R.T
    if mirror:
        p[:, 0] *= -1
    return p


def _corner_profile(p, n=96, win=2):
    """Resample contour to n points; return (#corners, share of total turning in 6 sharpest corners)."""
    pts = p.astype(np.float32)
    seg = np.linalg.norm(np.diff(np.vstack([pts, pts[:1]]), axis=0), axis=1)
    cum = np.concatenate([[0], np.cumsum(seg)])
    t = np.linspace(0, cum[-1], n, endpoint=False)
    q = np.stack([np.interp(t, cum, np.append(pts[:, 0], pts[0, 0])),
                  np.interp(t, cum, np.append(pts[:, 1], pts[0, 1]))], 1)
    turn = np.zeros(n)
    for i in range(n):
        v1 = q[i] - q[i - win]; v2 = q[(i + win) % n] - q[i]
        c = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-9)
        turn[i] = math.degrees(math.acos(np.clip(c, -1, 1)))
    peaks = [i for i in range(n) if turn[i] > 32 and turn[i] == turn[[(i + k) % n for k in range(-5, 6)]].max()]
    share = np.sort(turn)[-6:].sum() / max(turn.sum(), 1e-6)
    return len(peaks), float(share)


def _ellipse_iou(p):
    pi = p.astype(np.float32).reshape(-1, 1, 2)
    if len(pi) < 5:
        return 0.0
    (cx, cy), (MA, ma), ang = cv2.fitEllipse(pi)
    sc = 100.0 / max(MA, ma)
    off = np.array([cx, cy])
    m1 = np.zeros((220, 220), np.uint8); m2 = np.zeros((220, 220), np.uint8)
    cv2.fillPoly(m1, [((p - off) * sc + 110).astype(np.int32)], 1)
    cv2.ellipse(m2, ((110, 110), (MA * sc, ma * sc), ang), 1, -1)
    return float(np.logical_and(m1, m2).sum() / max(np.logical_or(m1, m2).sum(), 1))


def sym_reconstruct(p):
    """Keep the outer half of a lens (x > bbox centre, outer side = +x) and mirror it.
    Removes nose-pad / bridge artifacts that live on the inner side. Returns Nx2 contour."""
    x0, y0 = p.min(0); x1, y1 = p.max(0)
    sc = 180.0 / max(x1 - x0, y1 - y0)
    q = (p - [(x0 + x1) / 2, (y0 + y1) / 2]) * sc + 200
    m = np.zeros((400, 400), np.uint8)
    cv2.fillPoly(m, [q.astype(np.int32)], 1)
    outer = m.copy(); outer[:, :200] = 0
    full = outer | outer[:, ::-1]
    cs, _ = cv2.findContours(full, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    c = max(cs, key=cv2.contourArea).reshape(-1, 2).astype(np.float64)
    return (c - 200) / sc


def lens_features(p):
    """p: Nx2 normalised contour (outer side = +x, y down). Scale-free features."""
    pi = p.astype(np.float32).reshape(-1, 1, 2)
    area = cv2.contourArea(pi); per = cv2.arcLength(pi, True)
    x0, y0 = p.min(0); x1, y1 = p.max(0); w, h = x1 - x0, y1 - y0
    f = dict(ar=w / h, extent=area / (w * h), circ=4 * math.pi * area / per ** 2,
             ell=_ellipse_iou(p))

    def band_w(lo, hi):
        sel = p[(p[:, 1] >= y0 + lo * h) & (p[:, 1] <= y0 + hi * h)]
        return (sel[:, 0].max() - sel[:, 0].min()) if len(sel) else 0
    f["taper"] = float(np.clip(band_w(0.0, 0.2) / max(band_w(0.8, 1.0), 1e-6), 0.4, 2.5))
    f["mid_taper"] = float(np.clip(band_w(0.15, 0.35) / max(band_w(0.65, 0.85), 1e-6), 0.4, 2.5))
    f["top_x"] = (p[p[:, 1].argmin(), 0] - x0) / w          # 0 = inner(nose) side, 1 = outer(temple) side
    f["cy"] = (p[:, 1].mean() - y0) / h                      # centroid height in bbox (0 top)
    f["n_corners"], f["corner_share"] = _corner_profile(p)
    # left/right balance of a single lens (a nose-pad wedge on the inner side breaks it)
    cxm = (x0 + x1) / 2
    sc = 100.0 / max(w, h)
    m1 = np.zeros((140, 140), np.uint8); m2 = np.zeros((140, 140), np.uint8)
    q = (p - [cxm, (y0 + y1) / 2]) * sc + 70
    q2 = q.copy(); q2[:, 0] = 140 - q2[:, 0]
    cv2.fillPoly(m1, [q.astype(np.int32)], 1); cv2.fillPoly(m2, [q2.astype(np.int32)], 1)
    f["self_sym"] = float(np.logical_and(m1, m2).sum() / max(np.logical_or(m1, m2).sum(), 1))
    return f


def measure(ca, cb):
    Ma, Mb = cv2.moments(ca), cv2.moments(cb)
    pa = np.array([Ma["m10"] / Ma["m00"], Ma["m01"] / Ma["m00"]])
    pb = np.array([Mb["m10"] / Mb["m00"], Mb["m01"] / Mb["m00"]])
    if pa[0] > pb[0]:
        ca, cb, pa, pb = cb, ca, pb, pa                   # ca = left lens, cb = right lens
    angle = math.degrees(math.atan2(*(pb - pa)[::-1]))
    centre = (pa + pb) / 2
    pa_n = _normalise(ca, centre, angle, mirror=True)     # left lens: outer = -x -> mirror
    pb_n = _normalise(cb, centre, angle, mirror=False)
    fa, fb = lens_features(pa_n), lens_features(pb_n)
    sa_, sb_ = lens_features(sym_reconstruct(pa_n)), lens_features(sym_reconstruct(pb_n))
    feats = {k: (fa[k] + fb[k]) / 2 for k in fa}
    feats.update({"s_" + k: (sa_[k] + sb_[k]) / 2 for k in sa_})
    feats["asym"] = abs(fa["ar"] - fb["ar"]) / max(fa["ar"], fb["ar"])
    aa, ab = cv2.contourArea(ca), cv2.contourArea(cb)
    feats["area_ratio"] = min(aa, ab) / max(aa, ab)
    return feats, ca, cb


# ----------------------------------------------------------------------------- classification
def classify(f, pair_score):
    """Rule-based on lens geometry. Symmetric shapes use the outer-half reconstruction (immune to nose-pad
    artifacts); cat-eye / aviator use the raw outline. Returns (shape, confidence, per-shape scores)."""
    ar, ext, circ = f["s_ar"], f["s_extent"], f["s_circ"]
    ell, nc, tp = f["s_ell"], f["s_n_corners"], f["s_mid_taper"]
    s = {k: 0.0 for k in SHAPES[:-1]}
    smooth = ell >= 0.93 and nc <= 2

    if smooth:                                              # elliptical outline
        s["round"] = max(0.0, 1 - abs(ar - 1.0) / 0.18)
        s["oval"] = min(max((ar - 1.12) / 0.15, 0.0), 1.0) * (ar <= 2.2)
    if ext >= 0.84 and tp < 1.10 and ell < 0.94:            # fills its bounding box: boxy outline
        s["square"] = max(0.0, 1 - abs(ar - 1.0) / 0.25)
        s["rectangle"] = min(max((ar - 1.18) / 0.2, 0.0), 1.0) * (ar <= 2.8)
    if tp >= 1.10 and ext >= 0.80 and ar <= 2.0 and ell < 0.94:   # boxy, wider on top: wayfarer-like
        s["wayfarer"] = 0.85 * min((tp - 1.06) / 0.15, 1.0)
    if ell < 0.92 and ext < 0.84 and not smooth and 0.9 <= ar <= 1.7 and 0.85 <= tp <= 1.35:   # angular, balanced
        s["geometric"] = 0.65 * min((0.93 - ell) / 0.04, 1.0)
    # raw-outline classes
    if (f["tp_raw"] if "tp_raw" in f else f["mid_taper"]) >= 1.22 and f["extent"] < 0.80 and f["ell"] >= 0.92 \
            and f["n_corners"] <= 1 and f["circ"] >= 0.92 and 1.0 <= f["ar"] <= 1.6 and f["self_sym"] >= 0.88:
        s["aviator"] = 0.85 * min((f["mid_taper"] - 1.15) / 0.2, 1.0)
    if f["top_x"] >= 0.70 and f["cy"] < 0.48 and f["extent"] < 0.84 and f["mid_taper"] >= 1.05 and f["ar"] >= 1.15 \
            and f["self_sym"] < 0.93:
        s["cat-eye"] = 0.9 * min((f["top_x"] - 0.64) / 0.2, 1.0) * min((0.50 - f["cy"]) / 0.05, 1.0)
        s["geometric"] = 0.0

    shape = max(s, key=s.get); top = s[shape]
    second = sorted(s.values())[-2]
    margin = top - second
    quality = min(f["sym"] / 0.95, 1.0) * min(pair_score / 0.7, 1.0)
    conf = min(0.75, top * (0.55 + 0.45 * min(margin / 0.4, 1.0)) * (0.5 + 0.5 * quality))
    if f["asym"] > 0.20 or f["sym"] < 0.85 or f["area_ratio"] < 0.80 or top < 0.4 or conf < 0.40:
        return "unknown", round(float(min(conf, 0.39)), 2), s     # not a clean front view / unreliable -> refuse
    return shape, round(float(conf), 2), s


def detect(im):
    """Full pipeline on one decoded image -> (result dict, (left_lens, right_lens) or None).
    Preference: a complete lens OPENING (dark lens blob, or interior cell that passes the fragment check),
    because that is what defines the frame shape; otherwise the filled rim outline."""
    H, W = im.shape[:2]
    cands, d = lens_candidates(im)
    pairs = pair_lenses(cands, H, W)
    if not pairs:
        return dict(frame_shape="unknown", confidence=0.0, reason="no lens pair found"), None
    chosen, ctx, frag = None, None, False
    for p in pairs:                                           # best opening first
        if p[4] in ("dark", "spli"):
            chosen = p; break
        if p[4] == "thin":
            r = context_ratio(d, p[0], p[1], H, W)
            if r is None or r <= 2.1:
                chosen, ctx = p, r; break
            frag = True
    if chosen is None:
        rings = [p for p in pairs if p[4] == "ring"]
        if not rings:
            return dict(frame_shape="unknown", confidence=0.0,
                        reason="only lens fragments found" if frag else "no usable lens pair"), None
        chosen = rings[0]
    feats, ca, cb = measure(chosen[0], chosen[1])
    feats["sym"] = chosen[3]
    shape, conf, scores = classify(feats, chosen[2])
    if chosen[4] == "thin" and ctx is None:
        conf = min(conf, 0.55)                                # no rim evidence -> never highly confident
    if chosen[4] == "ring":
        conf = min(conf, 0.70)                                # rim outline includes bridge/endpieces
        if shape in ("geometric", "aviator", "cat-eye"):      # these labels are produced by rim artifacts -> refuse
            shape, conf = "unknown", min(conf, 0.39)
    return dict(frame_shape=shape, confidence=conf, pair_score=round(float(chosen[2]), 3), source=chosen[4],
                features={k: round(float(v), 3) for k, v in feats.items()},
                scores={k: round(float(v), 2) for k, v in scores.items()}), (ca, cb)
