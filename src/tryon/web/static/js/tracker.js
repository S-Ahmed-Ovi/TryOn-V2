// Smoothing for a live head pose: a One-Euro filter (steady when you hold still, quick when you move).
// Rotation is smoothed as a quaternion, position as a vector.

class OneEuro {
  constructor(minCutoff, beta, dCutoff = 1.0) { this.minCutoff = minCutoff; this.beta = beta; this.dCutoff = dCutoff; this.x = null; this.dx = 0; this.t = 0; }
  static alpha(cutoff, dt) { const tau = 1 / (2 * Math.PI * cutoff); return 1 / (1 + tau / dt); }
  reset() { this.x = null; }
  filter(v, t) {
    if (this.x === null) { this.x = v; this.dx = 0; this.t = t; return v; }
    const dt = Math.max(1e-3, t - this.t);
    this.t = t;
    const dv = (v - this.x) / dt;
    this.dx += OneEuro.alpha(this.dCutoff, dt) * (dv - this.dx);
    const cutoff = this.minCutoff + this.beta * Math.abs(this.dx);
    this.x += OneEuro.alpha(cutoff, dt) * (v - this.x);
    return this.x;
  }
}

function toQuat(m) {                            // m: row-major 3x3 (rotation only)
  const t = m[0] + m[4] + m[8];
  let w, x, y, z;
  if (t > 0) { const s = Math.sqrt(t + 1) * 2; w = s / 4; x = (m[7] - m[5]) / s; y = (m[2] - m[6]) / s; z = (m[3] - m[1]) / s; }
  else if (m[0] > m[4] && m[0] > m[8]) { const s = Math.sqrt(1 + m[0] - m[4] - m[8]) * 2; w = (m[7] - m[5]) / s; x = s / 4; y = (m[1] + m[3]) / s; z = (m[2] + m[6]) / s; }
  else if (m[4] > m[8]) { const s = Math.sqrt(1 + m[4] - m[0] - m[8]) * 2; w = (m[2] - m[6]) / s; x = (m[1] + m[3]) / s; y = s / 4; z = (m[5] + m[7]) / s; }
  else { const s = Math.sqrt(1 + m[8] - m[0] - m[4]) * 2; w = (m[3] - m[1]) / s; x = (m[2] + m[6]) / s; y = (m[5] + m[7]) / s; z = s / 4; }
  return [w, x, y, z];
}

function fromQuat([w, x, y, z]) {
  const n = Math.hypot(w, x, y, z) || 1; w /= n; x /= n; y /= n; z /= n;
  return [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w),
    2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w),
    2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)];
}

export class PoseSmoother {
  constructor({ rot = [1.6, 9], pos = [1.1, 0.12] } = {}) {
    this.q = [0, 1, 2, 3].map(() => new OneEuro(rot[0], rot[1]));
    this.p = [0, 1, 2].map(() => new OneEuro(pos[0], pos[1]));
    this.last = null;
  }

  reset() { this.q.forEach((f) => f.reset()); this.p.forEach((f) => f.reset()); this.last = null; }

  /** matrix: 16 numbers, row-major 4x4 (head -> camera). t: seconds. Returns the smoothed matrix. */
  update(m, t) {
    const R = [m[0], m[1], m[2], m[4], m[5], m[6], m[8], m[9], m[10]];
    let q = toQuat(R);
    if (this.last && q[0] * this.last[0] + q[1] * this.last[1] + q[2] * this.last[2] + q[3] * this.last[3] < 0) q = q.map((v) => -v);   // same rotation, nearest sign
    const qs = q.map((v, i) => this.q[i].filter(v, t));
    this.last = qs;
    const Rs = fromQuat(qs);
    const ts = [m[3], m[7], m[11]].map((v, i) => this.p[i].filter(v, t));
    return [Rs[0], Rs[1], Rs[2], ts[0], Rs[3], Rs[4], Rs[5], ts[1], Rs[6], Rs[7], Rs[8], ts[2], 0, 0, 0, 1];
  }
}
