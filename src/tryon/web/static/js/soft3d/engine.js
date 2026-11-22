// A small software 3D renderer: no GPU, no WebGL, no dependencies. Runs in the browser and in Node.
//
//   render(model, { pose, camera, ss, exposure, occluder, unit }) -> { x, y, w, h, data } | null
//
//   model   parseGLB() result
//   pose    { R: [9] row-major rotation, model -> camera;  t: [x,y,z] camera space, cm;  scale }
//   camera  { f, cx, cy, width, height } in output pixels; the camera sits at the origin and looks down -z
//   ss      supersampling factor (1 fast, 2 good, 3 best)
//   unit    centimetres per model unit (the .glb files are in metres -> 100)
//   occluder  optional hidden head: { center: [x,y,z], radii: [rx,ry,rz], R?, t? } in cm; R / t default to the pose's.
//             It writes depth only, so temples vanish behind the head.
// Returns straight (non-premultiplied) 8-bit RGBA for the rectangle that holds the glasses.
//
// How it works: vertices are projected, an opaque "visibility" pass stores the nearest triangle per sample, every
// visible sample is shaded once (per-pixel lighting + a procedural studio reflection), transparent triangles
// (lenses) are then sorted far-to-near and blended, and the samples are averaged down for anti-aliasing.

const NEAR = 4;                                   // cm; nothing closer than this is drawn

// ── colour ──────────────────────────────────────────────────────────────────
const SRGB = new Uint8ClampedArray(4096);
for (let i = 0; i < 4096; i++) {
  const v = i / 4095;
  SRGB[i] = Math.round((v <= 0.0031308 ? 12.92 * v : 1.055 * Math.pow(v, 1 / 2.4) - 0.055) * 255);
}
const lin = (c) => (c <= 0.04045 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4));

// ── lighting (camera space: +x right, +y up, +z toward the viewer) ─────────
const unitVec = (x, y, z) => { const l = Math.hypot(x, y, z); return [x / l, y / l, z / l]; };
const KEY = unitVec(-0.45, 0.70, 0.55), FILL = unitVec(0.65, 0.15, 0.75), RIM = unitVec(0.25, 0.35, -0.9);
const SOFTBOX = unitVec(-0.35, 0.70, 0.62), STRIP = unitVec(0.72, 0.28, 0.63);
const smooth = (a, b, x) => { const t = Math.min(1, Math.max(0, (x - a) / (b - a))); return t * t * (3 - 2 * t); };
const E = new Float64Array(3);

/** Procedural studio reflection for a unit direction. Writes into E. */
function env(dx, dy, dz) {
  const s = smooth(0.30, 0.80, dy * 0.5 + 0.5);
  let r = 0.10 + 0.42 * s, g = 0.10 + 0.48 * s, b = 0.11 + 0.55 * s;
  const hz = Math.exp(-(dy * dy) / 0.02) * 0.22;
  r += hz; g += hz * 0.95; b += hz * 0.85;
  let k = dx * SOFTBOX[0] + dy * SOFTBOX[1] + dz * SOFTBOX[2];
  if (k > 0) { k = Math.pow(k, 28) * 3.4; r += k; g += k * 0.97; b += k * 0.92; }
  k = dx * STRIP[0] + dy * STRIP[1] + dz * STRIP[2];
  if (k > 0) { k = Math.pow(k, 16) * 1.5; r += k * 0.85; g += k * 0.95; b += k; }
  if (dz > 0.2) {                                   // a window behind the viewer
    const ux = dx / dz, uy = dy / dz;
    const w = smooth(0.95, 0.65, Math.abs(ux)) * smooth(0.85, 0.45, Math.abs(uy - 0.30));
    r += w * 1.0; g += w * 1.02; b += w * 1.05;
  }
  E[0] = r; E[1] = g; E[2] = b;
}

// ── scratch buffers, reused between frames ──────────────────────────────────
let cap = 0, depth = null, ids = null, col = null;
function ensure(n) {
  if (n > cap) { cap = n; depth = new Float32Array(n); ids = new Int32Array(n); col = new Float32Array(n * 4); }
}

// ── an ellipsoid used as the hidden head ───────────────────────────────────
const OCC_NU = 18, OCC_NV = 28;
const OCC = (() => {
  const dirs = new Float32Array(((OCC_NU + 1) * OCC_NV) * 3);
  let k = 0;
  for (let i = 0; i <= OCC_NU; i++) {
    const a = -Math.PI / 2 + (Math.PI * i) / OCC_NU;
    for (let j = 0; j < OCC_NV; j++) {
      const t = (2 * Math.PI * j) / OCC_NV;
      dirs[k++] = Math.cos(a) * Math.cos(t); dirs[k++] = Math.sin(a); dirs[k++] = Math.cos(a) * Math.sin(t);
    }
  }
  const idx = [];
  for (let i = 0; i < OCC_NU; i++) for (let j = 0; j < OCC_NV; j++) {
    const a = i * OCC_NV + j, b = (i + 1) * OCC_NV + j, c = (i + 1) * OCC_NV + ((j + 1) % OCC_NV), d = i * OCC_NV + ((j + 1) % OCC_NV);
    idx.push(a, c, b, a, d, c);                      // outward-facing
  }
  const n = dirs.length / 3;
  return { dirs, idx: Uint32Array.from(idx), cam: new Float32Array(n * 3), scr: new Float32Array(n * 3) };
})();

// ── rasteriser ──────────────────────────────────────────────────────────────
// mode 0: depth only (hidden head)   1: nearest-triangle ids   2: shade + blend (transparent)
let SH = null;                                       // shading context for mode 2

function tri(mode, scr, i0, i1, i2, cull, bw, bh, id, bias) {
  const a = i0 * 3, b = i1 * 3, c = i2 * 3;
  const v0 = scr[a + 2], v1 = scr[b + 2], v2 = scr[c + 2];
  if (v0 <= 0 || v1 <= 0 || v2 <= 0) return;
  const x0 = scr[a], y0 = scr[a + 1], x1 = scr[b], y1 = scr[b + 1], x2 = scr[c], y2 = scr[c + 1];
  const area = (x1 - x0) * (y2 - y0) - (x2 - x0) * (y1 - y0);
  if (area === 0 || (cull && area > 0)) return;      // front faces have negative area on a y-down screen
  const minx = Math.max(0, Math.floor(Math.min(x0, x1, x2))), maxx = Math.min(bw - 1, Math.ceil(Math.max(x0, x1, x2)));
  const miny = Math.max(0, Math.floor(Math.min(y0, y1, y2))), maxy = Math.min(bh - 1, Math.ceil(Math.max(y0, y1, y2)));
  if (minx > maxx || miny > maxy) return;
  const ia = 1 / area;
  const dx0 = (y1 - y2) * ia, dy0 = (x2 - x1) * ia, dx1 = (y2 - y0) * ia, dy1 = (x0 - x2) * ia, dx2 = (y0 - y1) * ia, dy2 = (x1 - x0) * ia;
  const px = minx + 0.5, py = miny + 0.5;
  let r0 = ((x1 - px) * (y2 - py) - (x2 - px) * (y1 - py)) * ia;
  let r1 = ((x2 - px) * (y0 - py) - (x0 - px) * (y2 - py)) * ia;
  let r2 = ((x0 - px) * (y1 - py) - (x1 - px) * (y0 - py)) * ia;
  for (let y = miny; y <= maxy; y++) {
    let l0 = r0, l1 = r1, l2 = r2, idx = y * bw + minx;
    for (let x = minx; x <= maxx; x++, idx++, l0 += dx0, l1 += dx1, l2 += dx2) {
      if (l0 < 0 || l1 < 0 || l2 < 0) continue;
      const inv = (l0 * v0 + l1 * v1 + l2 * v2) * bias;
      if (inv <= depth[idx]) continue;
      if (mode === 0) { depth[idx] = inv; if (SH && SH.debug) ids[idx] = -2; }
      else if (mode === 1) { depth[idx] = inv; ids[idx] = id; }
      else blend(idx, SH.part, i0, i1, i2, l0 * v0 / inv * bias, l1 * v1 / inv * bias, l2 * v2 / inv * bias);
    }
    r0 += dy0; r1 += dy1; r2 += dy2;
  }
}

// ── shading ─────────────────────────────────────────────────────────────────
const OUT = new Float64Array(4);                      // r, g, b, a (premultiplied)

function shade(part, i0, i1, i2, w0, w1, w2) {
  const m = part.material, cam = part._cam, nrm = part._nrm;
  const a = i0 * 3, b = i1 * 3, c = i2 * 3;
  const Px = w0 * cam[a] + w1 * cam[b] + w2 * cam[c], Py = w0 * cam[a + 1] + w1 * cam[b + 1] + w2 * cam[c + 1], Pz = w0 * cam[a + 2] + w1 * cam[b + 2] + w2 * cam[c + 2];
  let Nx = w0 * nrm[a] + w1 * nrm[b] + w2 * nrm[c], Ny = w0 * nrm[a + 1] + w1 * nrm[b + 1] + w2 * nrm[c + 1], Nz = w0 * nrm[a + 2] + w1 * nrm[b + 2] + w2 * nrm[c + 2];
  let l = Math.hypot(Nx, Ny, Nz) || 1; Nx /= l; Ny /= l; Nz /= l;
  l = Math.hypot(Px, Py, Pz) || 1;
  const Vx = -Px / l, Vy = -Py / l, Vz = -Pz / l;
  let ndv = Nx * Vx + Ny * Vy + Nz * Vz;
  if (ndv < 0) { if (m.doubleSided) { Nx = -Nx; Ny = -Ny; Nz = -Nz; ndv = -ndv; } else ndv = 0; }

  // base colour, linear
  let br = m._br, bg = m._bg, bb = m._bb, alpha = m.alpha;
  const cs = part.colorStride;
  if (cs) {
    const cv = part.colors;
    br *= w0 * cv[i0 * cs] + w1 * cv[i1 * cs] + w2 * cv[i2 * cs];
    bg *= w0 * cv[i0 * cs + 1] + w1 * cv[i1 * cs + 1] + w2 * cv[i2 * cs + 1];
    bb *= w0 * cv[i0 * cs + 2] + w1 * cv[i1 * cs + 2] + w2 * cv[i2 * cs + 2];
    if (cs === 4) alpha *= w0 * cv[i0 * 4 + 3] + w1 * cv[i1 * 4 + 3] + w2 * cv[i2 * 4 + 3];
  }
  if (m.tex && part.uvs) {
    const uv = part.uvs, t = m.tex;
    let u = w0 * uv[i0 * 2] + w1 * uv[i1 * 2] + w2 * uv[i2 * 2], v = w0 * uv[i0 * 2 + 1] + w1 * uv[i1 * 2 + 1] + w2 * uv[i2 * 2 + 1];
    u -= Math.floor(u); v -= Math.floor(v);
    const o = ((Math.min(t.height - 1, (v * t.height) | 0) * t.width) + Math.min(t.width - 1, (u * t.width) | 0)) * 4;
    br *= lin(t.data[o] / 255); bg *= lin(t.data[o + 1] / 255); bb *= lin(t.data[o + 2] / 255);
    alpha *= t.data[o + 3] / 255;
  }

  const metal = m.metallic, rough = Math.min(1, Math.max(0.04, m.roughness));
  // lights
  const sky = Ny * 0.5 + 0.5;
  let amb = 0.14 + 0.34 * sky;
  let dk = Math.max(0, Nx * KEY[0] + Ny * KEY[1] + Nz * KEY[2]);
  let df = Math.max(0, Nx * FILL[0] + Ny * FILL[1] + Nz * FILL[2]);
  let dr = Math.max(0, Nx * RIM[0] + Ny * RIM[1] + Nz * RIM[2]);
  const lit = amb + dk * 1.25 + df * 0.35 + dr * 0.35;
  const dif = 1 - metal;
  let r = br * dif * lit, g = bg * dif * lit, bl = bb * dif * lit;

  // Fresnel (Schlick) with a base reflectance that follows the metalness
  const f5 = Math.pow(1 - ndv, 5);
  const F0r = 0.04 + (br - 0.04) * metal, F0g = 0.04 + (bg - 0.04) * metal, F0b = 0.04 + (bb - 0.04) * metal;
  const Fr = F0r + (1 - F0r) * f5, Fg = F0g + (1 - F0g) * f5, Fb = F0b + (1 - F0b) * f5;
  // key light highlight
  const shin = Math.min(300, Math.max(4, 2 / (rough * rough) - 2));
  let hx = KEY[0] + Vx, hy = KEY[1] + Vy, hz = KEY[2] + Vz;
  const hl = Math.hypot(hx, hy, hz) || 1;
  const nh = Math.max(0, (Nx * hx + Ny * hy + Nz * hz) / hl);
  const sp = dk > 0 ? Math.pow(nh, shin) * 1.3 : 0;
  r += Fr * sp * 1.0; g += Fg * sp * 0.97; bl += Fb * sp * 0.93;
  // reflection of the studio
  const k2 = 2 * ndv;
  const Rx = k2 * Nx - Vx, Ry = k2 * Ny - Vy, Rz = k2 * Nz - Vz;
  env(Rx, Ry, Rz);
  const blur = Math.min(1, rough * 1.1), avg = 0.30;
  const refl = 1 - 0.55 * rough;
  const er = (E[0] * (1 - blur) + avg * blur) * refl, eg = (E[1] * (1 - blur) + avg * 1.05 * blur) * refl, eb = (E[2] * (1 - blur) + avg * 1.15 * blur) * refl;
  r += Fr * er; g += Fg * eg; bl += Fb * eb;
  r += m.emissive[0]; g += m.emissive[1]; bl += m.emissive[2];

  if (m.blend) {
    // the tint scales by alpha; reflections and highlights are added on top (premultiplied alpha)
    const glints = Fr * (sp + er) * 0.6;
    const spec = Fr * sp + Fr * er, specg = Fg * sp + Fg * eg, specb = Fb * sp + Fb * eb;
    OUT[0] = (r - spec) * alpha + spec; OUT[1] = (g - specg) * alpha + specg; OUT[2] = (bl - specb) * alpha + specb;
    OUT[3] = Math.min(1, alpha + glints * 0.9 * (1 - alpha));
  } else {
    OUT[0] = r; OUT[1] = g; OUT[2] = bl; OUT[3] = 1;
  }
}

function blend(idx, part, i0, i1, i2, w0, w1, w2) {
  shade(part, i0, i1, i2, w0, w1, w2);
  const k = idx * 4, a = OUT[3];
  col[k] = OUT[0] + col[k] * (1 - a); col[k + 1] = OUT[1] + col[k + 1] * (1 - a); col[k + 2] = OUT[2] + col[k + 2] * (1 - a);
  col[k + 3] = a + col[k + 3] * (1 - a);
}

// ── public API ──────────────────────────────────────────────────────────────
export function prepare(model) {
  for (const p of model.parts) {
    const m = p.material;
    m._br = lin(m.base[0]); m._bg = lin(m.base[1]); m._bb = lin(m.base[2]);
    const n = p.positions.length / 3;
    if (!p._cam || p._cam.length !== n * 3) { p._cam = new Float32Array(n * 3); p._nrm = new Float32Array(n * 3); p._scr = new Float32Array(n * 3); }
    p._opaque = !m.blend;
  }
  return model;
}

export function render(model, opts) {
  if (!model._prepared) { prepare(model); model._prepared = true; }
  const { pose, camera } = opts;
  const ss = Math.max(1, opts.ss | 0 || 1);
  const sc = (pose.scale ?? 1) * (opts.unit ?? 100);
  const R = pose.R, T = pose.t, f = camera.f, cx = camera.cx, cy = camera.cy;
  const exposure = opts.exposure ?? 1, tint = opts.tint || [1, 1, 1];

  // 1. project every vertex
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity, nTri = 0;
  for (const p of model.parts) {
    const pos = p.positions, nrm = p.normals, cam = p._cam, nc = p._nrm, scr = p._scr, n = pos.length / 3;
    for (let i = 0, k = 0; i < n; i++, k += 3) {
      const x = pos[k] * sc, y = pos[k + 1] * sc, z = pos[k + 2] * sc;
      const X = R[0] * x + R[1] * y + R[2] * z + T[0], Y = R[3] * x + R[4] * y + R[5] * z + T[1], Z = R[6] * x + R[7] * y + R[8] * z + T[2];
      cam[k] = X; cam[k + 1] = Y; cam[k + 2] = Z;
      nc[k] = R[0] * nrm[k] + R[1] * nrm[k + 1] + R[2] * nrm[k + 2];
      nc[k + 1] = R[3] * nrm[k] + R[4] * nrm[k + 1] + R[5] * nrm[k + 2];
      nc[k + 2] = R[6] * nrm[k] + R[7] * nrm[k + 1] + R[8] * nrm[k + 2];
      const d = -Z;
      if (d < NEAR) { scr[k + 2] = 0; continue; }
      const inv = 1 / d, sx = cx + f * X * inv, sy = cy - f * Y * inv;
      scr[k] = sx; scr[k + 1] = sy; scr[k + 2] = inv;
      if (sx < minX) minX = sx; if (sx > maxX) maxX = sx; if (sy < minY) minY = sy; if (sy > maxY) maxY = sy;
    }
    nTri += p.indices.length / 3;
  }
  if (!(maxX > minX)) return null;
  const x0 = Math.max(0, Math.floor(minX) - 2), y0 = Math.max(0, Math.floor(minY) - 2);
  const x1 = Math.min(camera.width, Math.ceil(maxX) + 2), y1 = Math.min(camera.height, Math.ceil(maxY) + 2);
  const w = x1 - x0, h = y1 - y0;
  if (w <= 0 || h <= 0) return null;
  const bw = w * ss, bh = h * ss;
  for (const p of model.parts) {                      // to buffer coordinates
    const scr = p._scr;
    for (let k = 0; k < scr.length; k += 3) { scr[k] = (scr[k] - x0) * ss; scr[k + 1] = (scr[k + 1] - y0) * ss; }
  }
  ensure(bw * bh);
  depth.fill(0, 0, bw * bh); ids.fill(-1, 0, bw * bh); col.fill(0, 0, bw * bh * 4);

  // 2. hidden head: depth only
  SH = { debug: !!opts.debugOccluder, part: null };
  const oc = opts.occluder;
  if (oc) {
    const { dirs, idx, cam, scr } = OCC;
    const ot = oc.t || T, oR = oc.R || R;
    for (let i = 0, k = 0; i < dirs.length / 3; i++, k += 3) {
      const x = oc.center[0] + oc.radii[0] * dirs[k], y = oc.center[1] + oc.radii[1] * dirs[k + 1], z = oc.center[2] + oc.radii[2] * dirs[k + 2];
      const X = oR[0] * x + oR[1] * y + oR[2] * z + ot[0], Y = oR[3] * x + oR[4] * y + oR[5] * z + ot[1], Z = oR[6] * x + oR[7] * y + oR[8] * z + ot[2];
      const d = -Z;
      if (d < NEAR) { scr[k + 2] = 0; continue; }
      const inv = 1 / d;
      scr[k] = (cx + f * X * inv - x0) * ss; scr[k + 1] = (cy - f * Y * inv - y0) * ss; scr[k + 2] = inv;
    }
    for (let t = 0; t < idx.length; t += 3) tri(0, scr, idx[t], idx[t + 1], idx[t + 2], true, bw, bh, 0, 0.9985);
  }

  // 3. nearest opaque triangle per sample
  const triPart = new Int32Array(nTri), triAt = new Int32Array(nTri);
  let id = 0;
  const transparent = [];
  model.parts.forEach((p, pi) => {
    const ind = p.indices, scr = p._scr, cull = !p.material.doubleSided;
    for (let t = 0; t < ind.length; t += 3, id++) {
      triPart[id] = pi; triAt[id] = t;
      if (p._opaque) tri(1, scr, ind[t], ind[t + 1], ind[t + 2], cull, bw, bh, id, 1);
      else transparent.push(id);
    }
  });

  // 4. shade every visible sample once
  const n = bw * bh;
  for (let s = 0; s < n; s++) {
    const tid = ids[s];
    if (tid === -1) continue;
    const k = s * 4;
    if (tid === -2) { col[k] = 0.02; col[k + 1] = 0.12; col[k + 2] = 0.3; col[k + 3] = 0.35; continue; }
    const p = model.parts[triPart[tid]], t = triAt[tid];
    const i0 = p.indices[t], i1 = p.indices[t + 1], i2 = p.indices[t + 2], scr = p._scr;
    const a = i0 * 3, b = i1 * 3, c = i2 * 3;
    const x = (s % bw) + 0.5, y = ((s / bw) | 0) + 0.5;
    const ax = scr[a], ay = scr[a + 1], bx = scr[b], by = scr[b + 1], cx2 = scr[c], cy2 = scr[c + 1];
    const ia = 1 / ((bx - ax) * (cy2 - ay) - (cx2 - ax) * (by - ay));
    const l0 = ((bx - x) * (cy2 - y) - (cx2 - x) * (by - y)) * ia, l1 = ((cx2 - x) * (ay - y) - (ax - x) * (cy2 - y)) * ia, l2 = 1 - l0 - l1;
    const q0 = l0 * scr[a + 2], q1 = l1 * scr[b + 2], q2 = l2 * scr[c + 2], qs = q0 + q1 + q2 || 1e-9;
    shade(p, i0, i1, i2, q0 / qs, q1 / qs, q2 / qs);
    col[k] = OUT[0]; col[k + 1] = OUT[1]; col[k + 2] = OUT[2]; col[k + 3] = 1;
  }

  // 5. transparent triangles (lenses), far to near, tested against the opaque depth
  if (transparent.length) {
    const key = new Float32Array(transparent.length);
    transparent.forEach((tid, i) => {
      const p = model.parts[triPart[tid]], t = triAt[tid], scr = p._scr;
      key[i] = scr[p.indices[t] * 3 + 2] + scr[p.indices[t + 1] * 3 + 2] + scr[p.indices[t + 2] * 3 + 2];
    });
    const order = Array.from(transparent.keys()).sort((a, b) => key[a] - key[b]);
    for (const o of order) {
      const tid = transparent[o], p = model.parts[triPart[tid]], t = triAt[tid];
      SH.part = p;
      tri(2, p._scr, p.indices[t], p.indices[t + 1], p.indices[t + 2], false, bw, bh, tid, 1);
    }
  }

  // 6. average down, un-premultiply, encode to sRGB
  const out = new Uint8ClampedArray(w * h * 4);
  const inv = 1 / (ss * ss);
  for (let y = 0; y < h; y++) {
    for (let x = 0; x < w; x++) {
      let r = 0, g = 0, b = 0, a = 0;
      for (let sy = 0; sy < ss; sy++) {
        let s = ((y * ss + sy) * bw + x * ss) * 4;
        for (let sx = 0; sx < ss; sx++, s += 4) { r += col[s]; g += col[s + 1]; b += col[s + 2]; a += col[s + 3]; }
      }
      const o = (y * w + x) * 4;
      a *= inv;
      if (a < 0.002) continue;
      const k = inv / a * exposure;
      out[o] = SRGB[Math.min(4095, Math.max(0, (r * k * tint[0] * 4095) | 0))];
      out[o + 1] = SRGB[Math.min(4095, Math.max(0, (g * k * tint[1] * 4095) | 0))];
      out[o + 2] = SRGB[Math.min(4095, Math.max(0, (b * k * tint[2] * 4095) | 0))];
      out[o + 3] = Math.min(255, Math.round(a * 255));
    }
  }
  return { x: x0, y: y0, w, h, data: out };
}

/** Rotation matrices (row-major, 9 numbers). */
export const rotY = (deg) => { const c = Math.cos(deg * Math.PI / 180), s = Math.sin(deg * Math.PI / 180); return [c, 0, s, 0, 1, 0, -s, 0, c]; };
export const rotX = (deg) => { const c = Math.cos(deg * Math.PI / 180), s = Math.sin(deg * Math.PI / 180); return [1, 0, 0, 0, c, -s, 0, s, c]; };
export const rotZ = (deg) => { const c = Math.cos(deg * Math.PI / 180), s = Math.sin(deg * Math.PI / 180); return [c, -s, 0, s, c, 0, 0, 0, 1]; };
export const matMul3 = (a, b) => {
  const o = new Array(9);
  for (let r = 0; r < 3; r++) for (let c = 0; c < 3; c++) o[r * 3 + c] = a[r * 3] * b[c] + a[r * 3 + 1] * b[3 + c] + a[r * 3 + 2] * b[6 + c];
  return o;
};
