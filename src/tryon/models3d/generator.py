"""Parametric sunglasses generator.  numpy only.

Builds the 24 frames of the catalogue (8 styles x 3 variants) as real 3D meshes and writes them as .glb files:

    python -m tryon models3d generate

Coordinates (metres in the files; millimetres in this module):

    origin   middle of the bridge, at pupil height, on the lens plane
    +x       to the wearer's left / image right, +y up, +z forward (out of the face)
    temples  run towards -z

Each model has two meshes: `frame` (rims, bridge, pads, hinges, temples; opaque) and `lenses` (transparent, double sided).
Edit the `MODELS` table below to change a design, then regenerate and run `tryon build`.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from tryon.models3d.glb import model_bounds, write_glb

MM = 1e-3
SAMPLES = 96                         # points around each lens outline
IPD_HALF = 32.0                      # half the typical pupil distance, mm (only used for documentation of the fit)


# ----------------------------------------------------------------------------- small helpers
def smoothstep(a: float, b: float, x):
    t = np.clip((np.asarray(x, float) - a) / (b - a), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def srgb_to_linear(c: tuple[float, float, float]) -> np.ndarray:
    c = np.asarray(c, float)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def hex_rgb(h: str) -> tuple[float, float, float]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))


def hex_linear(h: str) -> np.ndarray:
    return srgb_to_linear(hex_rgb(h))


class Mesh:
    """Vertices (n,3) and triangles (m,3). Optional per-vertex colours (n,4)."""

    def __init__(self, v=None, f=None, c=None):
        self.v = np.zeros((0, 3)) if v is None else np.asarray(v, float)
        self.f = np.zeros((0, 3), np.int64) if f is None else np.asarray(f, np.int64)
        self.c = None if c is None else np.asarray(c, float)

    def mirrored_x(self) -> "Mesh":
        v = self.v.copy()
        v[:, 0] *= -1.0
        return Mesh(v, self.f[:, ::-1].copy(), self.c)

    def transformed(self, fn) -> "Mesh":
        return Mesh(fn(self.v.copy()), self.f, self.c)


def merge(meshes: list[Mesh]) -> Mesh:
    vs, fs, cs, off = [], [], [], 0
    use_c = any(m.c is not None for m in meshes)
    for m in meshes:
        vs.append(m.v)
        fs.append(m.f + off)
        if use_c:
            cs.append(m.c if m.c is not None else np.ones((len(m.v), 4)))
        off += len(m.v)
    return Mesh(np.vstack(vs), np.vstack(fs), np.vstack(cs) if use_c else None)


def vertex_normals(v: np.ndarray, f: np.ndarray) -> np.ndarray:
    fn = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])          # area weighted
    n = np.zeros_like(v)
    for k in range(3):
        np.add.at(n, f[:, k], fn)
    length = np.linalg.norm(n, axis=1, keepdims=True)
    length[length == 0] = 1.0
    return n / length


def normalise(a: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(a, axis=-1, keepdims=True)
    n[n == 0] = 1.0
    return a / n


# ----------------------------------------------------------------------------- 2D outlines (one lens, outer side = +x)
def resample_closed(pts: np.ndarray, n: int) -> np.ndarray:
    pts = np.asarray(pts, float)
    seg = np.linalg.norm(np.roll(pts, -1, 0) - pts, axis=1)
    s = np.concatenate([[0.0], np.cumsum(seg)])
    closed = np.vstack([pts, pts[:1]])
    u = np.linspace(0.0, s[-1], n, endpoint=False)
    return np.stack([np.interp(u, s, closed[:, 0]), np.interp(u, s, closed[:, 1])], 1)


def ensure_ccw(p: np.ndarray) -> np.ndarray:
    x, y = p[:, 0], p[:, 1]
    area = 0.5 * np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y)
    return p if area > 0 else p[::-1].copy()


def fit_box(p: np.ndarray, w: float, h: float) -> np.ndarray:
    """Scale and centre an outline so its bounding box is exactly w x h, centred on the origin."""
    lo, hi = p.min(0), p.max(0)
    p = (p - (lo + hi) / 2.0) * np.array([w / (hi[0] - lo[0]), h / (hi[1] - lo[1])])
    return p


def superellipse(w: float, h: float, n: float, count: int = 1440) -> np.ndarray:
    t = np.linspace(0.0, 2 * np.pi, count, endpoint=False)
    c, s = np.cos(t), np.sin(t)
    return np.stack([(w / 2) * np.sign(c) * np.abs(c) ** (2 / n), (h / 2) * np.sign(s) * np.abs(s) ** (2 / n)], 1)


def rounded_polygon(verts, radius, k: int = 10) -> np.ndarray:
    """A polygon with rounded corners. `radius` is one number or one per vertex (mm)."""
    verts = np.asarray(verts, float)
    radii = np.broadcast_to(np.asarray(radius, float), (len(verts),))
    out = []
    for i, p in enumerate(verts):
        a, b = verts[i - 1], verts[(i + 1) % len(verts)]
        u1, u2 = normalise(a - p), normalise(b - p)
        ang = math.acos(float(np.clip(np.dot(u1, u2), -1, 1)))
        t = radii[i] / math.tan(ang / 2.0)
        t = min(t, 0.45 * np.linalg.norm(a - p), 0.45 * np.linalg.norm(b - p))
        p1, p2 = p + u1 * t, p + u2 * t
        for s in np.linspace(0, 1, k):
            out.append((1 - s) ** 2 * p1 + 2 * (1 - s) * s * p + s ** 2 * p2)
    return np.array(out)


def _angle_gauss(theta: np.ndarray, centre_deg: float, sigma: float) -> np.ndarray:
    d = (theta - math.radians(centre_deg) + np.pi) % (2 * np.pi) - np.pi
    return np.exp(-(d / sigma) ** 2)


def outline_oval(w, h, n=2.35, **_):
    return superellipse(w, h, n)


def outline_round(w, h, **_):
    return superellipse(w, h, 2.0)


def outline_rectangle(w, h, n=6.0, **_):
    return superellipse(w, h, n)


def outline_square(w, h, n=4.6, **_):
    p = superellipse(w, h, n)
    p[:, 0] *= 1.0 + 0.04 * p[:, 1] / (h / 2)                      # a touch wider at the top
    return p


def outline_wayfarer(w, h, **_):
    """Trapezoid: wide, slightly upswept top edge; the outer side slants in towards a narrower, curved bottom."""
    return rounded_polygon([(w * 0.50, h * 0.50), (-w * 0.50, h * 0.42), (-w * 0.45, -h * 0.50), (w * 0.28, -h * 0.50), (w * 0.50, -h * 0.02)],
                           [5.0, 6.0, 11.0, 13.0, 8.0], 12)


def outline_cat_eye(w, h, **_):
    p = superellipse(w, h, 2.6)
    theta = np.arctan2(p[:, 1], p[:, 0])
    q = p * (1 + 0.27 * _angle_gauss(theta, 28, 0.42))[:, None]                # upswept outer corner
    q = q * (1 - 0.10 * _angle_gauss(theta, -150, 0.6))[:, None]               # tucked inner-lower corner
    q[:, 1] += 0.07 * h * np.clip(q[:, 0] / (w / 2), 0, 1)
    return q


def outline_aviator(w, h, **_):
    """Teardrop: broad flat-ish top, sides sweeping down to a rounded point that sits towards the nose."""
    p = superellipse(w, h, 2.0)
    x, y = p[:, 0], p[:, 1]
    low = np.clip(0.5 - 0.5 * y / (h / 2), 0, 1)                  # 0 at the top, 1 at the bottom
    return np.stack([x * (1 - 0.40 * low ** 1.3) - 0.17 * w * low ** 1.7, y], 1)


def outline_hexagon(w, h, **_):
    return rounded_polygon([(w / 2, 0), (w / 4, h / 2), (-w / 4, h / 2), (-w / 2, 0), (-w / 4, -h / 2), (w / 4, -h / 2)], 3.5)


def outline_octagon(w, h, **_):
    a = math.radians(22.5)
    return rounded_polygon([(math.cos(a + i * math.pi / 4) * w / 2 / math.cos(a), math.sin(a + i * math.pi / 4) * h / 2 / math.cos(a)) for i in range(8)], 2.6)


def outline_angular(w, h, **_):
    return rounded_polygon([(-w * 0.50, h * 0.36), (w * 0.12, h * 0.50), (w * 0.50, h * 0.30), (w * 0.50, -h * 0.14), (w * 0.20, -h * 0.50), (-w * 0.42, -h * 0.42)], 3.6)


OUTLINES = {
    "oval": outline_oval, "round": outline_round, "rectangle": outline_rectangle, "square": outline_square,
    "wayfarer": outline_wayfarer, "cat-eye": outline_cat_eye, "aviator": outline_aviator,
    "hexagon": outline_hexagon, "octagon": outline_octagon, "angular": outline_angular,
}


def lens_outline(kind: str, w: float, h: float, n: int = SAMPLES, **kw) -> np.ndarray:
    p = OUTLINES[kind](w, h, **kw)
    p = ensure_ccw(resample_closed(fit_box(p, w, h), 2 * n))
    return resample_closed(p, n)


# ----------------------------------------------------------------------------- sweeping a profile along a path
def rounded_rect(a0: float, a1: float, c0: float, c1: float, r: float, k: int = 4) -> np.ndarray:
    r = max(1e-4, min(r, (a1 - a0) / 2.0, (c1 - c0) / 2.0))
    pts = []
    for cx, cy, start in ((a1 - r, c1 - r, 0), (a0 + r, c1 - r, 90), (a0 + r, c0 + r, 180), (a1 - r, c0 + r, 270)):
        for t in np.linspace(start, start + 90, k):
            pts.append((cx + r * math.cos(math.radians(t)), cy + r * math.sin(math.radians(t))))
    return np.array(pts)


def circle_profile(r: float, k: int = 10, ra: float = 1.0, rc: float = 1.0) -> np.ndarray:
    t = np.linspace(0, 2 * np.pi, k, endpoint=False)
    return np.stack([r * ra * np.cos(t), r * rc * np.sin(t)], 1)


def sweep(path, a_axis, b_axis, profile, closed: bool, centre_ab=(0.0, 0.0), caps: bool = False) -> Mesh:
    """Extrude `profile` (M,2) or (N,M,2) along `path` (N,3). Profile x runs along a_axis, y along b_axis."""
    path, a_axis, b_axis = np.asarray(path, float), np.asarray(a_axis, float), np.asarray(b_axis, float)
    n = len(path)
    prof = np.asarray(profile, float)
    if prof.ndim == 2:
        prof = np.broadcast_to(prof, (n,) + prof.shape)
    m = prof.shape[1]
    ring = path[:, None, :] + prof[:, :, 0:1] * a_axis[:, None, :] + prof[:, :, 1:2] * b_axis[:, None, :]
    centre = path + centre_ab[0] * a_axis + centre_ab[1] * b_axis
    idx = np.arange(n * m).reshape(n, m)
    i0 = np.arange(n if closed else n - 1)
    i1 = (i0 + 1) % n
    j0 = np.arange(m)
    j1 = (j0 + 1) % m
    a, b = idx[i0[:, None], j0[None, :]], idx[i1[:, None], j0[None, :]]
    c, d = idx[i1[:, None], j1[None, :]], idx[i0[:, None], j1[None, :]]
    faces = np.concatenate([np.stack([a, b, c], -1).reshape(-1, 3), np.stack([a, c, d], -1).reshape(-1, 3)])
    verts = ring.reshape(-1, 3)
    cen = np.broadcast_to(centre[:, None, :], (n, m, 3)).reshape(-1, 3)
    fn = np.cross(verts[faces[:, 1]] - verts[faces[:, 0]], verts[faces[:, 2]] - verts[faces[:, 0]])
    out = verts[faces].mean(1) - cen[faces[:, 0]]
    faces[np.einsum("ij,ij->i", fn, out) < 0] = faces[np.einsum("ij,ij->i", fn, out) < 0][:, ::-1]
    mesh = Mesh(verts, faces)
    if caps and not closed:
        for end, ref in ((0, 1), (n - 1, n - 2)):
            base = len(mesh.v)
            cv = np.vstack([ring[end], centre[end][None, :]])
            fans = np.array([[m, j, (j + 1) % m] for j in range(m)]) + base
            nrm = np.cross(cv[fans[:, 1] - base] - cv[fans[:, 0] - base], cv[fans[:, 2] - base] - cv[fans[:, 0] - base])
            away = centre[end] - centre[ref]
            flip = nrm @ away < 0
            fans[flip] = fans[flip][:, ::-1]
            mesh = merge([mesh, Mesh(cv, fans - base)])
    return mesh


def superellipsoid(centre, radii, e: float = 1.0, nu: int = 14, nv: int = 20) -> Mesh:
    """e = 1 ellipsoid, e < 1 rounded box."""
    u = np.linspace(-np.pi / 2, np.pi / 2, nu)
    t = np.linspace(0, 2 * np.pi, nv, endpoint=False)
    U, T = np.meshgrid(u, t, indexing="ij")
    cu, su, ct, st = np.cos(U), np.sin(U), np.cos(T), np.sin(T)
    sgn = lambda a, p: np.sign(a) * np.abs(a) ** p          # noqa: E731
    v = np.stack([radii[0] * sgn(cu, e) * sgn(ct, e), radii[1] * sgn(su, e), radii[2] * sgn(cu, e) * sgn(st, e)], -1).reshape(-1, 3) + np.asarray(centre)
    idx = np.arange(nu * nv).reshape(nu, nv)
    a, b = idx[:-1, :], idx[1:, :]
    c, d = np.roll(idx[1:, :], -1, 1), np.roll(idx[:-1, :], -1, 1)
    f = np.concatenate([np.stack([a, b, c], -1).reshape(-1, 3), np.stack([a, c, d], -1).reshape(-1, 3)])
    fn = np.cross(v[f[:, 1]] - v[f[:, 0]], v[f[:, 2]] - v[f[:, 0]])
    out = v[f].mean(1) - np.asarray(centre)
    bad = np.einsum("ij,ij->i", fn, out) < 0
    f[bad] = f[bad][:, ::-1]
    keep = np.linalg.norm(fn, axis=1) > 1e-12
    return Mesh(v, f[keep])


# ----------------------------------------------------------------------------- building one model
def _value_noise(p: np.ndarray) -> np.ndarray:
    i = np.floor(p).astype(np.int64)
    f = p - i
    f = f * f * (3 - 2 * f)

    def h(ix, iy, iz):
        n = (ix * 73856093) ^ (iy * 19349663) ^ (iz * 83492791)
        n = ((n ^ (n >> 13)) * 1274126177) & 0x7FFFFFFF
        return (n % 10007) / 10007.0

    out = 0.0
    for dx in (0, 1):
        for dy in (0, 1):
            for dz in (0, 1):
                w = (f[:, 0] if dx else 1 - f[:, 0]) * (f[:, 1] if dy else 1 - f[:, 1]) * (f[:, 2] if dz else 1 - f[:, 2])
                out = out + w * h(i[:, 0] + dx, i[:, 1] + dy, i[:, 2] + dz)
    return out


def tortoise_colours(v_mm: np.ndarray, base: str = "#8a4e16") -> np.ndarray:
    """Tortoiseshell mottling from 3D noise, as per-vertex linear RGBA."""
    t = 0.6 * _value_noise(v_mm / 4.2 + 11.0) + 0.4 * _value_noise(v_mm / 1.9 + 3.0)
    amber, dark, honey = hex_linear(base), hex_linear("#1d0c05"), hex_linear("#d49a3a")
    dk = smoothstep(0.50, 0.62, t)[:, None]
    hl = smoothstep(0.40, 0.28, t)[:, None]
    rgb = amber * (1 - dk) + dark * dk
    rgb = rgb * (1 - hl * 0.8) + honey * hl * 0.8
    return np.concatenate([rgb, np.ones((len(v_mm), 1))], 1)


def build_model(spec: dict, n: int = SAMPLES) -> dict:
    """Returns {'frame': Mesh, 'lens': Mesh, 'info': {...}} with coordinates in millimetres."""
    W, H = spec["lens_w"], spec["lens_h"]
    x_in = spec["bridge"] / 2.0
    style = spec["style"]                                   # acetate | wire
    wrap = math.tan(math.radians(spec.get("wrap", 5.0)))
    rim_d = spec.get("rim_d", 6.0)
    rw = spec.get("rim_w", 4.0)
    rim_w_bottom, rim_w_top = rw if isinstance(rw, tuple) else (rw, rw)
    wire_r = spec.get("wire_r", 0.9)
    pupil_frac = spec.get("pupil_frac", 0.5)

    def bend(x):
        return -wrap * np.maximum(0.0, np.abs(x) - x_in)

    def rim_w(nx, ny):
        if style == "wire":
            return np.full_like(nx, wire_r * 1.2)
        return rim_w_bottom + (rim_w_top - rim_w_bottom) * smoothstep(-0.3, 0.8, ny) + spec.get("rim_w_outer", 0.0) * smoothstep(0.3, 1.0, nx)

    # --- outline of the right lens, placed
    o = lens_outline(spec["outline"], W, H, n, **spec.get("outline_kw", {}))
    cy = (0.5 - pupil_frac) * H
    o = o + np.array([x_in + W / 2.0, cy])
    cen = o.mean(0)
    tang = np.roll(o, -1, 0) - np.roll(o, 1, 0)
    nrm2 = normalise(np.stack([tang[:, 1], -tang[:, 0]], 1))          # outward for a CCW outline

    # --- rim
    path = np.stack([o[:, 0], o[:, 1], bend(o[:, 0])], 1)
    t3 = normalise(np.roll(path, -1, 0) - np.roll(path, 1, 0))
    a_ax = np.concatenate([nrm2, np.zeros((n, 1))], 1)
    b_ax = normalise(np.cross(a_ax, t3))
    if style == "acetate":
        prof = np.stack([rounded_rect(-0.8, float(rim_w(nrm2[i:i + 1, 0], nrm2[i:i + 1, 1])[0]), -rim_d / 2, rim_d / 2, min(2.0, rim_d / 2.5), k=4) for i in range(n)])
        rim = sweep(path, a_ax, b_ax, prof, True, centre_ab=(rim_w_bottom / 2, 0.0))
    else:
        rim = sweep(path, a_ax, b_ax, circle_profile(wire_r, 10, 1.0, 1.0) + np.array([wire_r * 0.5, 0.0]), True, centre_ab=(wire_r * 0.5, 0.0))

    # --- lens (a thin curved sheet tucked into the rim)
    rings = 6
    lens_pts = [np.array([[cen[0], cen[1]]])]
    for k in range(1, rings + 1):
        lens_pts.append(cen + (o - cen) * (1.012 * k / rings))
    L = np.vstack(lens_pts)
    r2 = ((L[:, 0] - (x_in + W / 2)) ** 2 + (L[:, 1] - cy) ** 2)
    lz = bend(L[:, 0]) - spec.get("lens_curve", 2.4) * r2 / (W / 2) ** 2          # convex: the middle sits furthest forward
    lens_v = np.stack([L[:, 0], L[:, 1], lz + 0.4], 1)
    fan = [[0, 1 + i, 1 + (i + 1) % n] for i in range(n)]
    quads = []
    for k in range(1, rings):
        base0, base1 = 1 + (k - 1) * n, 1 + k * n
        for i in range(n):
            j = (i + 1) % n
            quads.append([base0 + i, base1 + i, base1 + j])
            quads.append([base0 + i, base1 + j, base0 + j])
    lens_f = np.array(fan + quads)
    fn = np.cross(lens_v[lens_f[:, 1]] - lens_v[lens_f[:, 0]], lens_v[lens_f[:, 2]] - lens_v[lens_f[:, 0]])
    lens_f[fn[:, 2] < 0] = lens_f[fn[:, 2] < 0][:, ::-1]
    lens = spec["lens"]
    ys = (L[:, 1] - L[:, 1].min()) / (np.ptp(L[:, 1]) + 1e-9)
    alpha = lens["a_bot"] + (lens["a_top"] - lens["a_bot"]) * ys
    rgb = np.broadcast_to(hex_linear(lens["color"]), (len(L), 3))
    lens_mesh_r = Mesh(lens_v, lens_f, np.concatenate([rgb, alpha[:, None]], 1))

    # --- pieces at the outer corner: hinge block, and where the temple starts
    outer = int(np.argmax(o[:, 0]))
    xo, yo = o[outer]
    rw_out = float(rim_w(np.array([1.0]), np.array([0.0]))[0])
    xh = xo + rw_out * 0.55
    yh = yo + 1.0
    zh = float(bend(xh)) - 1.2
    parts_r = [rim]

    if style == "acetate":
        parts_r.append(superellipsoid((xh - 0.8, yh - 0.5, zh - 2.8), (rw_out * 0.62 + 0.8, spec["temple"]["h0"] * 0.55, 5.8), 0.45))
    else:
        parts_r.append(superellipsoid((xh - 0.5, yh, zh - 1.5), (1.6, 2.6, 3.4), 0.6))

    # --- temple
    tp = spec["temple"]
    s = np.linspace(0, 1, 44)
    L_t = tp["len"]
    droop = tp.get("droop", 10.0)
    tx = xh - tp.get("splay", 2.0) * s - tp.get("ear_in", 2.5) * smoothstep(0.78, 1.0, s)
    tz = zh - L_t * s
    ty = yh - tp.get("slope", 4.0) * s - droop * smoothstep(0.66, 1.0, s) ** 1.4
    tpath = np.stack([tx, ty, tz], 1)
    tt = normalise(np.gradient(tpath, axis=0))
    up = np.array([0.0, 1.0, 0.0])
    ta = normalise(up - (tt @ up)[:, None] * tt)
    tb = normalise(np.cross(tt, ta))
    h_s = tp["h0"] + (tp["h1"] - tp["h0"]) * smoothstep(0.0, 0.85, s)
    th = tp["t"] * np.ones_like(s)
    if style == "wire":
        tprof = np.stack([circle_profile(1.0, 10, h_s[i] / 2, th[i] / 2) for i in range(len(s))])
    else:
        tprof = np.stack([rounded_rect(-h_s[i] / 2, h_s[i] / 2, -th[i] / 2, th[i] / 2, th[i] * 0.45, k=3) for i in range(len(s))])
    parts_r.append(sweep(tpath, ta, tb, tprof, False, caps=True))

    # --- right half done: mirror
    right_front = merge([rim, parts_r[1]])
    frame_parts = [m for m in parts_r]
    frame = merge(frame_parts + [m.mirrored_x() for m in frame_parts])

    # --- bridge, brow bar and pads (centre pieces)
    center_parts: list[Mesh] = []
    rw_in = float(rim_w(np.array([-1.0]), np.array([0.0]))[0])
    x_end = max(0.5, x_in - rw_in * 0.45)
    xs = np.linspace(-x_end, x_end, 28)
    by = spec.get("bridge_y", 6.0)
    arch = spec.get("arch", 2.2)
    bpath = np.stack([xs, by + arch * (1 - (xs / x_end) ** 2), np.zeros_like(xs) + bend(xs)], 1)
    ones, zero = np.ones_like(xs), np.zeros_like(xs)
    if style == "acetate":
        bh = spec.get("bridge_h", 7.0)
        bprof = rounded_rect(-bh / 2, bh / 2, -rim_d * 0.45, rim_d * 0.45, 1.6, k=4)
        center_parts.append(sweep(bpath, np.stack([zero, ones, zero], 1), np.stack([zero, zero, ones], 1), bprof, False, caps=True))
    else:
        center_parts.append(sweep(bpath, np.stack([zero, ones, zero], 1), np.stack([zero, zero, ones], 1), circle_profile(wire_r * 0.95, 10), False, caps=True))
        if spec.get("brow_bar"):
            xe = x_in + 4.5
            ye = _top_at(o, xe) - 1.4
            xs2 = np.linspace(-xe, xe, 30)
            ys2 = ye + spec.get("brow_arch", 3.0) * (1 - (xs2 / xe) ** 2)
            o1, z1 = np.ones_like(xs2), np.zeros_like(xs2)
            center_parts.append(sweep(np.stack([xs2, ys2, bend(xs2)], 1), np.stack([z1, o1, z1], 1), np.stack([z1, z1, o1], 1),
                                      circle_profile(wire_r * 0.95, 8), False, caps=True))

    pad_y = spec.get("pad_y", -7.5)
    if style == "acetate":
        pad = superellipsoid((x_in - 0.2, pad_y, -5.2), (3.6, 7.5, 3.0), 0.7)
        center_parts += [pad, pad.mirrored_x()]
    else:
        px_, pz_ = x_in - 0.6, -9.0
        pad = superellipsoid((px_, pad_y, pz_), (2.2, 4.4, 1.0), 1.0)
        arm_t = np.linspace(0, 1, 12)
        a0 = np.array([x_in + 0.2, -2.0, 0.0])
        a1 = np.array([x_in - 0.2, pad_y + 2.5, -4.0])
        a2 = np.array([px_, pad_y + 1.0, pz_ + 0.6])
        arm = ((1 - arm_t) ** 2)[:, None] * a0 + (2 * (1 - arm_t) * arm_t)[:, None] * a1 + (arm_t ** 2)[:, None] * a2
        at = normalise(np.gradient(arm, axis=0))
        aa = normalise(np.cross(at, np.array([0.0, 0.0, 1.0])))
        ab = normalise(np.cross(at, aa))
        arm_m = sweep(arm, aa, ab, circle_profile(0.45, 6), False, caps=True)
        center_parts += [pad, pad.mirrored_x(), arm_m, arm_m.mirrored_x()]

    frame = merge([frame] + center_parts)
    if spec["frame"].get("pattern") == "tortoise":
        frame.c = tortoise_colours(frame.v, spec["frame"]["color"])

    lens_mesh = merge([lens_mesh_r, lens_mesh_r.mirrored_x()])
    lo = frame.v.min(0)
    hi = frame.v.max(0)
    front = merge([right_front, right_front.mirrored_x()])
    info = {
        "frame_width_mm": round(float(front.v[:, 0].max() - front.v[:, 0].min()), 1),
        "lens_width_mm": float(W), "lens_height_mm": float(H), "bridge_mm": float(spec["bridge"]),
        "temple_mm": round(float(-lo[2] + hi[2]), 1),
    }
    return {"frame": frame, "lens": lens_mesh, "info": info}


def _top_at(outline: np.ndarray, x: float) -> float:
    """y of the upper edge of a (right-lens) outline at horizontal position x."""
    above = outline[outline[:, 1] >= outline[:, 1].mean()]
    order = np.argsort(above[:, 0])
    return float(np.interp(x, above[order, 0], above[order, 1]))


def _material_for_frame(spec: dict) -> dict:
    f = spec["frame"]
    rgb = hex_linear(f["color"]) if f.get("pattern") != "tortoise" else np.ones(3)
    return {"name": "frame", "pbrMetallicRoughness": {"baseColorFactor": [*map(float, rgb), 1.0], "metallicFactor": float(f.get("metal", 0.0)),
                                                       "roughnessFactor": float(f.get("rough", 0.2))}, "doubleSided": False}


def _material_for_lens(spec: dict) -> dict:
    lens = spec["lens"]
    mirror = bool(lens.get("mirror"))
    return {"name": "lens", "pbrMetallicRoughness": {"baseColorFactor": [1.0, 1.0, 1.0, 1.0], "metallicFactor": 0.95 if mirror else 0.0,
                                                      "roughnessFactor": 0.05 if mirror else 0.08},
            "alphaMode": "BLEND", "doubleSided": True, "extras": {"role": "lens"}}


def write_model(spec: dict, out_dir: Path) -> dict:
    """Build one model, write `<sku>.glb`, return its manifest record."""
    built = build_model(spec)
    to_m = lambda m: m.v * MM                                   # noqa: E731
    frame, lens = built["frame"], built["lens"]
    parts = [
        {"name": "frame", "v": to_m(frame), "n": vertex_normals(frame.v, frame.f), "f": frame.f, "c": frame.c, "material": 0},
        {"name": "lenses", "v": to_m(lens), "n": vertex_normals(lens.v, lens.f), "f": lens.f, "c": lens.c, "material": 1},
    ]
    path = Path(out_dir) / f"{spec['sku']}.glb"
    extras = {"tryon": {"sku": spec["sku"], "unit": "m", "origin": "bridge centre at pupil height, on the lens plane", "forward": "+z"}}
    size = write_glb(path, parts, [_material_for_frame(spec), _material_for_lens(spec)], extras)
    lo, hi = model_bounds(path)
    info = built["info"]
    return {
        "sku": spec["sku"], "name": spec["name"], "frame_shape": spec["shape"], "audience": spec["audience"],
        "style": spec["style"], "file": path.name,
        "color": {"name": spec["frame"]["name"], "hex": spec["frame"]["color"] if spec["frame"].get("pattern") != "tortoise" else "#8a4e16"},
        "lens": {"name": spec["lens"]["name"], "hex": spec["lens"]["color"], "mirror": bool(spec["lens"].get("mirror"))},
        **info, "triangles": int(len(frame.f) + len(lens.f)), "bytes": size,
        "bounds_mm": {"min": [round(float(x) / MM, 1) for x in lo], "max": [round(float(x) / MM, 1) for x in hi]},
    }


# ----------------------------------------------------------------------------- the catalogue
def _spec(sku, name, shape, audience, style, outline, lens_w, lens_h, bridge, frame, lens, **kw):
    return dict(sku=sku, name=name, shape=shape, audience=audience, style=style, outline=outline, lens_w=lens_w, lens_h=lens_h,
                bridge=bridge, frame=frame, lens=lens, **kw)


ACETATE_TEMPLE = dict(len=140, h0=9.0, h1=5.5, t=3.0, droop=11, splay=2.5, slope=4)
THIN_TEMPLE = dict(len=140, h0=5.5, h1=4.0, t=2.2, droop=11, splay=2.5, slope=4)
WIRE_TEMPLE = dict(len=140, h0=2.6, h1=2.0, t=2.0, droop=12, splay=2.5, slope=5)

MODELS: list[dict] = [
    # ---- wayfarer
    _spec("TO-WAY-01", "Wayfarer Classic", "wayfarer", "unisex", "acetate", "wayfarer", 52, 42, 18,
          dict(name="Black", color="#17181c", rough=0.14), dict(name="G-15 green", color="#26382c", a_top=0.93, a_bot=0.82),
          rim_w=(4.6, 8.2), rim_d=7.0, bridge_y=8, pupil_frac=0.55, bridge_h=7.5, temple=ACETATE_TEMPLE, wrap=5),
    _spec("TO-WAY-02", "Wayfarer Havana", "wayfarer", "unisex", "acetate", "wayfarer", 53, 42, 18,
          dict(name="Tortoise", color="#8a4e16", pattern="tortoise", rough=0.14), dict(name="Brown gradient", color="#4a2f1c", a_top=0.92, a_bot=0.50),
          rim_w=(4.6, 8.0), rim_d=7.0, bridge_y=8, pupil_frac=0.55, bridge_h=7.5, temple=ACETATE_TEMPLE, wrap=5),
    _spec("TO-WAY-03", "Wayfarer Navy", "wayfarer", "unisex", "acetate", "wayfarer", 51, 41, 19,
          dict(name="Navy", color="#1f2c52", rough=0.2), dict(name="Slate", color="#394554", a_top=0.9, a_bot=0.78),
          rim_w=(4.2, 7.4), rim_d=6.6, bridge_y=8, pupil_frac=0.55, bridge_h=7.0, temple=ACETATE_TEMPLE, wrap=5),
    # ---- rectangle
    _spec("TO-RCT-01", "Slim Rectangle", "rectangle", "men", "acetate", "rectangle", 54, 34, 18,
          dict(name="Black", color="#141518", rough=0.16), dict(name="Smoke", color="#2a2d31", a_top=0.92, a_bot=0.82),
          rim_w=(3.0, 3.6), rim_d=5.2, bridge_y=7, pupil_frac=0.52, bridge_h=5.0, temple=THIN_TEMPLE, wrap=4),
    _spec("TO-RCT-02", "Gunmetal Rectangle", "rectangle", "men", "wire", "rectangle", 55, 36, 18,
          dict(name="Gunmetal", color="#585d66", metal=1.0, rough=0.28), dict(name="Blue-grey gradient", color="#2c3b4a", a_top=0.92, a_bot=0.50),
          wire_r=0.95, rim_d=3.0, bridge_y=7, pupil_frac=0.52, temple=WIRE_TEMPLE, wrap=4),
    _spec("TO-RCT-03", "Bold Rectangle", "rectangle", "unisex", "acetate", "rectangle", 53, 38, 19,
          dict(name="Brown", color="#4b2f21", rough=0.18), dict(name="Amber brown", color="#4b3420", a_top=0.9, a_bot=0.7),
          rim_w=(5.4, 6.6), rim_d=7.0, bridge_y=7, pupil_frac=0.52, bridge_h=7.0, temple=ACETATE_TEMPLE, wrap=4),
    # ---- square
    _spec("TO-SQR-01", "Bold Square", "square", "men", "acetate", "square", 50, 46, 20,
          dict(name="Black", color="#111214", rough=0.14), dict(name="Dark grey", color="#24262a", a_top=0.94, a_bot=0.86),
          rim_w=(6.0, 7.4), rim_d=7.6, bridge_y=8, pupil_frac=0.52, bridge_h=8.0, temple=ACETATE_TEMPLE, wrap=5),
    _spec("TO-SQR-02", "Square Havana", "square", "unisex", "acetate", "square", 50, 45, 20,
          dict(name="Tortoise", color="#7a4210", pattern="tortoise", rough=0.14), dict(name="Olive", color="#3a4228", a_top=0.9, a_bot=0.72),
          rim_w=(5.4, 6.8), rim_d=7.2, bridge_y=8, pupil_frac=0.52, bridge_h=7.5, temple=ACETATE_TEMPLE, wrap=5),
    _spec("TO-SQR-03", "Square Gold", "square", "unisex", "wire", "square", 52, 46, 18,
          dict(name="Gold", color="#c9a04a", metal=1.0, rough=0.2), dict(name="G-15 green", color="#26382c", a_top=0.9, a_bot=0.8),
          wire_r=0.95, rim_d=3.0, bridge_y=8, pupil_frac=0.52, temple=WIRE_TEMPLE, wrap=4),
    # ---- round
    _spec("TO-RND-01", "Round Gold Wire", "round", "unisex", "wire", "round", 48, 48, 22,
          dict(name="Gold", color="#d1ab55", metal=1.0, rough=0.2), dict(name="Brown", color="#4c3322", a_top=0.9, a_bot=0.76),
          wire_r=0.85, rim_d=3.0, bridge_y=8, pupil_frac=0.5, temple=WIRE_TEMPLE, wrap=3),
    _spec("TO-RND-02", "Round Tortoise", "round", "unisex", "acetate", "round", 49, 49, 21,
          dict(name="Tortoise", color="#8a4e16", pattern="tortoise", rough=0.14), dict(name="Green", color="#2c4030", a_top=0.9, a_bot=0.75),
          rim_w=(4.4, 4.8), rim_d=6.4, bridge_y=8, pupil_frac=0.5, bridge_h=6.0, temple=ACETATE_TEMPLE, wrap=4),
    _spec("TO-RND-03", "Round Silver Mirror", "round", "unisex", "wire", "round", 50, 50, 21,
          dict(name="Silver", color="#c5c9cf", metal=1.0, rough=0.16), dict(name="Blue mirror", color="#4a73a6", a_top=0.96, a_bot=0.92, mirror=True),
          wire_r=0.85, rim_d=3.0, bridge_y=8, pupil_frac=0.5, temple=WIRE_TEMPLE, wrap=3),
    # ---- oval
    _spec("TO-OVL-01", "Soft Oval", "oval", "women", "acetate", "oval", 52, 40, 19,
          dict(name="Black", color="#17181b", rough=0.14), dict(name="Smoke", color="#33363b", a_top=0.9, a_bot=0.72),
          rim_w=(3.6, 4.2), rim_d=5.6, bridge_y=7, pupil_frac=0.5, bridge_h=5.5, temple=THIN_TEMPLE, wrap=4),
    _spec("TO-OVL-02", "Oval Rose Gold", "oval", "women", "wire", "oval", 53, 41, 19,
          dict(name="Rose gold", color="#c98c7b", metal=1.0, rough=0.2), dict(name="Rose gradient", color="#8a4d56", a_top=0.88, a_bot=0.42),
          wire_r=0.85, rim_d=3.0, bridge_y=7, pupil_frac=0.5, temple=WIRE_TEMPLE, wrap=3),
    _spec("TO-OVL-03", "Oval Honey", "oval", "unisex", "acetate", "oval", 54, 42, 18,
          dict(name="Honey", color="#c9a24e", rough=0.12), dict(name="Amber", color="#7a4a1a", a_top=0.88, a_bot=0.66),
          rim_w=(4.2, 5.0), rim_d=6.0, bridge_y=7, pupil_frac=0.5, bridge_h=6.0, temple=ACETATE_TEMPLE, wrap=4),
    # ---- cat-eye
    _spec("TO-CAT-01", "Cat-Eye Noir", "cat-eye", "women", "acetate", "cat-eye", 54, 42, 17,
          dict(name="Black", color="#141416", rough=0.12), dict(name="Smoke", color="#2a2b30", a_top=0.92, a_bot=0.8),
          rim_w=(4.2, 7.2), rim_w_outer=1.6, rim_d=6.6, bridge_y=7, pupil_frac=0.42, bridge_h=6.0, temple=ACETATE_TEMPLE, wrap=5),
    _spec("TO-CAT-02", "Cat-Eye Burgundy", "cat-eye", "women", "acetate", "cat-eye", 54, 41, 17,
          dict(name="Burgundy", color="#591729", rough=0.12), dict(name="Plum", color="#4b2a3c", a_top=0.9, a_bot=0.58),
          rim_w=(4.0, 6.8), rim_w_outer=1.6, rim_d=6.4, bridge_y=7, pupil_frac=0.42, bridge_h=6.0, temple=ACETATE_TEMPLE, wrap=5),
    _spec("TO-CAT-03", "Cat-Eye Havana", "cat-eye", "women", "acetate", "cat-eye", 55, 42, 17,
          dict(name="Tortoise", color="#8a4e16", pattern="tortoise", rough=0.12), dict(name="Brown gradient", color="#4a2f1c", a_top=0.9, a_bot=0.5),
          rim_w=(4.2, 7.0), rim_w_outer=1.6, rim_d=6.6, bridge_y=7, pupil_frac=0.42, bridge_h=6.0, temple=ACETATE_TEMPLE, wrap=5),
    # ---- aviator
    _spec("TO-AVI-01", "Aviator Gold", "aviator", "men", "wire", "aviator", 58, 50, 17,
          dict(name="Gold", color="#d2ad58", metal=1.0, rough=0.18), dict(name="G-15 green", color="#27402f", a_top=0.92, a_bot=0.8),
          wire_r=0.9, rim_d=3.0, bridge_y=1, pupil_frac=0.58, brow_bar=True, pad_y=-9.0, temple=WIRE_TEMPLE, wrap=4),
    _spec("TO-AVI-02", "Aviator Silver Mirror", "aviator", "unisex", "wire", "aviator", 58, 50, 17,
          dict(name="Silver", color="#c8ccd2", metal=1.0, rough=0.14), dict(name="Blue mirror", color="#3f6a9c", a_top=0.97, a_bot=0.94, mirror=True),
          wire_r=0.9, rim_d=3.0, bridge_y=1, pupil_frac=0.58, brow_bar=True, pad_y=-9.0, temple=WIRE_TEMPLE, wrap=4),
    _spec("TO-AVI-03", "Aviator Gunmetal", "aviator", "men", "wire", "aviator", 60, 52, 17,
          dict(name="Gunmetal", color="#4f545d", metal=1.0, rough=0.26), dict(name="Grey gradient", color="#30343a", a_top=0.94, a_bot=0.5),
          wire_r=0.95, rim_d=3.0, bridge_y=1, pupil_frac=0.58, brow_bar=True, pad_y=-9.0, temple=WIRE_TEMPLE, wrap=4),
    # ---- geometric
    _spec("TO-GEO-01", "Hex Gold", "geometric", "unisex", "wire", "hexagon", 52, 46, 20,
          dict(name="Gold", color="#d0aa56", metal=1.0, rough=0.2), dict(name="Amber gradient", color="#7a4d1c", a_top=0.86, a_bot=0.4),
          wire_r=0.85, rim_d=3.0, bridge_y=8, pupil_frac=0.5, temple=WIRE_TEMPLE, wrap=3),
    _spec("TO-GEO-02", "Octagon Black", "geometric", "unisex", "acetate", "octagon", 50, 46, 20,
          dict(name="Black", color="#16171a", rough=0.14), dict(name="Smoke", color="#2d3034", a_top=0.92, a_bot=0.8),
          rim_w=(3.8, 4.4), rim_d=6.0, bridge_y=8, pupil_frac=0.5, bridge_h=6.0, temple=THIN_TEMPLE, wrap=4),
    _spec("TO-GEO-03", "Angular Silver", "geometric", "women", "wire", "angular", 54, 44, 18,
          dict(name="Silver", color="#bcc1c8", metal=1.0, rough=0.2), dict(name="Mint", color="#5f9a90", a_top=0.8, a_bot=0.42),
          wire_r=0.85, rim_d=3.0, bridge_y=7, pupil_frac=0.5, temple=WIRE_TEMPLE, wrap=4),
]


def generate_all(out_dir: str | Path, log=print) -> dict:
    """Write every model into `out_dir` and return the manifest (also saved as manifest.json there)."""
    import json

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    records = []
    for spec in MODELS:
        rec = write_model(spec, out)
        records.append(rec)
        log(f"  {rec['sku']:<10} {rec['name']:<24} {rec['triangles']:>6} triangles  {rec['bytes'] // 1024:>4} KB  width {rec['frame_width_mm']} mm")
    mine = {r["sku"] for r in records}
    kept = []                                           # models the owner added with `tryon models3d add` stay in the catalogue
    try:
        kept = [m for m in json.loads((out / "manifest.json").read_text(encoding="utf-8"))["models"] if m["sku"] not in mine]
    except (OSError, ValueError, KeyError):
        pass
    manifest = {"version": 1, "unit": "m", "generator": "tryon.models3d.generator", "models": records + kept}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return manifest
