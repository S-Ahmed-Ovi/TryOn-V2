// The try-on canvas: your photo, the selected glasses placed on your eyes, and the tools to adjust them.
//
// All geometry comes from the server as fractions of the photo (so it is independent of display size):
//   placement = { cx, cy, width, angle }   centre between the eyes, face width, head tilt (degrees, clockwise)
// and each product carries its own anchor (where its lenses sit inside its cut-out), aspect ratio and `scale`
// (how wide the frame really is compared with a typical face).
//
// Two ways to draw the glasses:  "2d"  the flat picture of the frame, placed on the eyes;
//                                "3d"  the real 3D model, drawn by the CPU renderer from the head pose the server measured.
import { loadModel } from "./models.js";
import { SIZE_RANGE, exposureFor, renderGlasses } from "./tryon3d.js";

const FACE_CM = 14.4;            // a typical face width: converts the 2D "face widths" of the sliders into centimetres for 3D
const FRAME_ASPECT = 4 / 5;          // the photo is shown cropped around the face in a 4:5 frame
const MAX_OUT = 1000;                // largest on-screen canvas, in pixels

const images = new Map();            // url -> Promise<HTMLImageElement>
export function loadImage(url) {
  if (!images.has(url)) {
    images.set(url, new Promise((resolve, reject) => {
      const img = new Image();
      img.decoding = "async";
      img.onload = () => resolve(img);
      img.onerror = () => { images.delete(url); reject(new Error("Could not load a frame image.")); };
      img.src = url;
    }));
  }
  return images.get(url);
}

const ease = (t) => 1 - Math.pow(1 - t, 3);

export class TryOnStage {
  constructor(canvas, { onAdjust } = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.onAdjust = onAdjust || (() => {});
    this.photo = null;
    this.placement = null;
    this.guides = null;
    this.faceBox = null;
    this.product = null;
    this.glasses = null;
    this.fit = 1;                 // size multiplier
    this.lift = 0;                // vertical offset from the slider, in face-widths
    this.offset = { x: 0, y: 0 }; // drag offset, in face-widths
    this.showOriginal = false;
    this.showMeasure = false;
    this.pop = 1;                 // 0..1 entrance animation of the glasses
    this.measureAlpha = 0;
    this.siteName = "";
    this.mode = "2d";             // "2d" | "3d"
    this.pose3d = null;           // head pose from the server (null: 3D is not available for this photo)
    this.model = null;            // the 3D model of the selected frame
    this.exposure = 1;            // scene brightness -> how bright the 3D glasses are drawn
    this._layer = null;           // { canvas, x, y, key, ss }: the 3D glasses rendered at photo resolution
    this._hq = 0;
    this._raf = 0;
    this._pointers = new Map();
    this._bindInput();
  }

  // ── data ────────────────────────────────────────────────────────────────
  setPhoto(photoCanvas, placement, faceBox, guidePoints, pose3d = null) {
    this.photo = photoCanvas;
    this.placement = placement;
    this.faceBox = faceBox;
    this.guides = guidePoints;
    this.pose3d = pose3d && pose3d.usable ? pose3d : null;
    this.mode = "2d";
    this.model = null; this._layer = null;
    this.exposure = this._measureExposure();
    this.resetAdjustments(false);
    this._computeView();
    this.render();
  }

  get has3d() { return !!this.pose3d; }

  /** Switch between the flat picture and the real 3D model. Resolves to false if 3D could not be started. */
  async setMode(mode) {
    if (mode === "3d" && !this.pose3d) return false;
    this.mode = mode;
    if (mode === "3d" && this.product) {
      try { await this._load3d(); } catch (err) { this.mode = "2d"; this.render(); throw err; }
      this.pop = 0; this._animate();
    } else this.render();
    return true;
  }

  async setProduct(product) {
    this.product = product;
    const token = (this._token = Symbol());
    const [img] = await Promise.all([loadImage(product.cutout), this.mode === "3d" ? this._load3d(token) : null]);
    if (token !== this._token) return;          // a newer selection arrived while this one was loading
    this.glasses = img;
    this.pop = 0;
    this._animate();
  }

  async _load3d(token = this._token) {
    const model = await loadModel(this.product.model);
    if (token !== this._token) return;
    this.model = model;
    this._layer = null;
    this._sync3d(2, true);
  }

  _measureExposure() {                          // brightness of the face area -> renderer exposure
    try {
      const [x0, y0, x1, y1] = this.faceBox || [0.3, 0.2, 0.7, 0.7];
      const W = this.photo.width, H = this.photo.height, c = document.createElement("canvas");
      c.width = c.height = 16;
      const g = c.getContext("2d", { willReadFrequently: true });
      g.drawImage(this.photo, x0 * W, y0 * H, (x1 - x0) * W, (y1 - y0) * H, 0, 0, 16, 16);
      const d = g.getImageData(0, 0, 16, 16).data;
      let sum = 0;
      for (let i = 0; i < d.length; i += 4) sum += 0.2126 * d[i] + 0.7152 * d[i + 1] + 0.0722 * d[i + 2];
      return exposureFor(sum / (16 * 16 * 255));
    } catch { return 1; }
  }

  /** The 3D glasses as a transparent layer in photo pixels. Re-rendered only when something changed; `ss` is the quality. */
  _sync3d(ss = 1, force = false) {
    if (this.mode !== "3d" || !this.model || !this.pose3d || !this.product) return;
    const key = [this.product.sku, this.fit, this.lift, this.offset.x.toFixed(4), this.offset.y.toFixed(4)].join("|");
    const L = this._layer;
    if (!force && L && L.key === key && L.ss >= ss) return;
    const img = renderGlasses(this.model, this.pose3d, this.photo.width, this.photo.height, {
      ss, exposure: this.exposure,
      adjust: { size: this.fit, lift: -(this.lift + this.offset.y) * FACE_CM, shift: this.offset.x * FACE_CM },
    });
    if (!img) { this._layer = null; return; }
    const canvas = (L && L.canvas) || document.createElement("canvas");
    canvas.width = img.w; canvas.height = img.h;
    canvas.getContext("2d").putImageData(new ImageData(img.data, img.w, img.h), 0, 0);
    this._layer = { canvas, x: img.x, y: img.y, key, ss };
    if (ss < 2) {                                // while dragging, draw fast; polish a moment after the hand stops
      clearTimeout(this._hq);
      this._hq = setTimeout(() => { this._sync3d(2); this.render(); }, 180);
    }
  }

  resetAdjustments(redraw = true) {
    this.fit = 1; this.lift = 0; this.offset = { x: 0, y: 0 };
    if (redraw) this.render();
  }

  set(opts) {
    Object.assign(this, opts);
    this.render();
  }

  // ── view: crop the photo around the face ───────────────────────────────
  _computeView() {
    const W = this.photo.width, H = this.photo.height;
    const [x0, y0, x1, y1] = this.faceBox || [0.25, 0.2, 0.75, 0.8];
    const faceH = (y1 - y0) * H;
    let ch = Math.min(H, faceH * 1.9);
    let cw = ch * FRAME_ASPECT;
    if (cw > W) { cw = W; ch = cw / FRAME_ASPECT; }
    if (ch > H) { ch = H; cw = ch * FRAME_ASPECT; }
    const cx = ((x0 + x1) / 2) * W, cy = ((y0 + y1) / 2) * H + faceH * 0.02;
    this.view = {
      x: Math.min(Math.max(cx - cw / 2, 0), W - cw), y: Math.min(Math.max(cy - ch / 2, 0), H - ch), w: cw, h: ch,
    };
    const outW = Math.min(MAX_OUT, Math.round(cw));
    this.canvas.width = outW;
    this.canvas.height = Math.round(outW / (cw / ch));
  }

  // ── drawing ─────────────────────────────────────────────────────────────
  render() {
    if (this._raf) return;
    this._raf = requestAnimationFrame(() => { this._raf = 0; this.draw(); });
  }

  draw() {
    if (!this.photo) return;
    if (this.mode === "3d") this._sync3d(1);                 // quick while things change; the sharp version follows (see _sync3d)
    this.paint(this.ctx, this.canvas.width, { guides: true });
  }

  /** Draw the whole scene into any 2D context `outW` pixels wide (used for the screen and for saving). */
  paint(ctx, outW, { guides = false, watermark = false } = {}) {
    const v = this.view;
    const outH = Math.round(outW * v.h / v.w);
    const s = outW / v.w;
    ctx.clearRect(0, 0, outW, outH);
    ctx.imageSmoothingQuality = "high";
    ctx.drawImage(this.photo, v.x, v.y, v.w, v.h, 0, 0, outW, outH);

    if (this.glasses && this.product && !this.showOriginal) this._drawGlasses(ctx, s, v);
    if (guides && this.measureAlpha > 0 && !this.showOriginal) this._drawMeasurements(ctx, s, v);
    if (watermark && this.siteName) {
      ctx.save();
      ctx.font = `${Math.round(outW * 0.028)}px "Instrument Serif", Georgia, serif`;
      ctx.fillStyle = "rgba(255,255,255,.88)";
      ctx.shadowColor = "rgba(0,0,0,.5)"; ctx.shadowBlur = outW * 0.01;
      ctx.textAlign = "left"; ctx.textBaseline = "bottom";
      ctx.fillText(this.siteName, outW * 0.035, outH - outW * 0.03);
      ctx.restore();
    }
  }

  _drawGlasses(ctx, s, v) {
    if (this.mode === "3d") return this._draw3d(ctx, s, v);
    const { cx, cy, width, angle } = this.placement;
    const W = this.photo.width, H = this.photo.height;
    const faceW = width * W;
    const gw = faceW * this.fit * (this.product.scale || 1);
    const gh = gw / this.product.aspect;
    const ax = this.product.anchor.x * gw, ay = this.product.anchor.y * gh;
    const px = cx * W + this.offset.x * faceW;
    const py = cy * H + (this.offset.y + this.lift) * faceW;
    const k = ease(this.pop);

    ctx.save();
    ctx.globalAlpha = k;
    ctx.shadowColor = "rgba(8, 10, 9, .34)";
    ctx.shadowBlur = faceW * s * 0.04;
    ctx.shadowOffsetY = faceW * s * 0.022;
    ctx.scale(s, s);
    ctx.translate(-v.x, -v.y);
    ctx.translate(px, py);
    ctx.rotate((angle * Math.PI) / 180);
    ctx.scale(0.97 + 0.03 * k, 0.97 + 0.03 * k);
    ctx.drawImage(this.glasses, -ax, -ay, gw, gh);
    ctx.restore();
  }

  _draw3d(ctx, s, v) {
    const L = this._layer;
    if (!L) return;
    const faceW = this.placement.width * this.photo.width;
    const k = ease(this.pop);
    ctx.save();
    ctx.globalAlpha = k;
    ctx.shadowColor = "rgba(8, 10, 9, .34)";
    ctx.shadowBlur = faceW * s * 0.03;
    ctx.shadowOffsetY = faceW * s * 0.016;
    ctx.scale(s, s);
    ctx.translate(-v.x, -v.y);
    ctx.drawImage(L.canvas, L.x, L.y);
    ctx.restore();
  }

  _drawMeasurements(ctx, s, v) {
    const g = this.guides;
    if (!g) return;
    const W = this.photo.width, H = this.photo.height;
    const P = (name) => [(g[name][0] * W - v.x) * s, (g[name][1] * H - v.y) * s];
    const lines = [
      ["Length", "top", "chin"], ["Cheekbones", "cheek_r", "cheek_l"], ["Jaw", "jaw_r", "jaw_l"], ["Forehead", "fore_r", "fore_l"],
    ];
    ctx.save();
    ctx.globalAlpha = this.measureAlpha;
    const unit = ctx.canvas.width / 600;
    ctx.lineWidth = 2 * unit; ctx.strokeStyle = "#f2c14e"; ctx.fillStyle = "#f2c14e";
    ctx.font = `600 ${12.5 * unit}px "Instrument Sans", system-ui, sans-serif`;
    ctx.textBaseline = "middle";
    ctx.shadowColor = "rgba(0,0,0,.55)"; ctx.shadowBlur = 4 * unit;
    const tags = [];
    for (const [label, a, b] of lines) {
      const [ax, ay] = P(a), [bx, by] = P(b);
      ctx.setLineDash([6 * unit, 5 * unit]);
      ctx.beginPath(); ctx.moveTo(ax, ay); ctx.lineTo(bx, by); ctx.stroke();
      ctx.setLineDash([]);
      for (const [x, y] of [[ax, ay], [bx, by]]) { ctx.beginPath(); ctx.arc(x, y, 4 * unit, 0, 7); ctx.fill(); }
      const vertical = Math.abs(by - ay) > Math.abs(bx - ax);
      tags.push([label, vertical ? ax + 40 * unit : (ax + bx) / 2, vertical ? (ay + by) / 2 : ay - 14 * unit]);
    }
    ctx.shadowBlur = 0;
    for (const [label, x, y] of tags) {                      // labels on dark pills so they read on any photo
      const w = ctx.measureText(label).width + 16 * unit, h = 21 * unit;
      ctx.fillStyle = "rgba(10, 14, 12, .78)";
      ctx.beginPath(); ctx.roundRect(x - w / 2, y - h / 2, w, h, h / 2); ctx.fill();
      ctx.fillStyle = "#f2c14e"; ctx.textAlign = "center";
      ctx.fillText(label, x, y + unit * .5);
    }
    ctx.restore();
  }

  _animate() {
    const t0 = performance.now();
    const step = (now) => {
      this.pop = Math.min(1, (now - t0) / 280);
      this.draw();
      if (this.pop < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  toggleMeasurements(on) {
    this.showMeasure = on;
    const from = this.measureAlpha, to = on ? 1 : 0, t0 = performance.now();
    const step = (now) => {
      const k = Math.min(1, (now - t0) / 350);
      this.measureAlpha = from + (to - from) * ease(k);
      this.draw();
      if (k < 1) requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  }

  // ── export ──────────────────────────────────────────────────────────────
  toBlob() {
    if (this.mode === "3d") this._sync3d(2);
    const out = document.createElement("canvas");
    const w = Math.min(1400, Math.round(this.view.w));
    out.width = w;
    out.height = Math.round(w * this.view.h / this.view.w);
    const prev = this.showOriginal;
    this.showOriginal = false;
    this.paint(out.getContext("2d"), w, { watermark: true });
    this.showOriginal = prev;
    return new Promise((resolve) => out.toBlob(resolve, "image/jpeg", 0.93));
  }

  // ── input: drag, pinch, keyboard ────────────────────────────────────────
  _bindInput() {
    const c = this.canvas;
    c.tabIndex = 0;
    const faceWidthPx = () => this.placement.width * this.photo.width;
    const cssToSource = () => this.view.w / c.clientWidth;

    c.addEventListener("pointerdown", (e) => {
      if (!this.glasses) return;
      c.setPointerCapture(e.pointerId);
      this._pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      c.classList.add("dragging");
      if (this._pointers.size === 2) this._pinch = { d: this._dist(), fit: this.fit };
      this.onAdjust("start");
    });
    c.addEventListener("pointermove", (e) => {
      const p = this._pointers.get(e.pointerId);
      if (!p) return;
      if (this._pointers.size === 2) {
        this._pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
        this.fit = clamp(this._pinch.fit * (this._dist() / this._pinch.d), SIZE_RANGE[0], SIZE_RANGE[1]);
        this.onAdjust("fit");
      } else {
        const k = cssToSource() / faceWidthPx();
        this.offset.x = clamp(this.offset.x + (e.clientX - p.x) * k, -0.6, 0.6);
        this.offset.y = clamp(this.offset.y + (e.clientY - p.y) * k, -0.6, 0.6);
        this._pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
        this.onAdjust("move");
      }
      this.draw();
    });
    const end = (e) => {
      this._pointers.delete(e.pointerId);
      if (!this._pointers.size) c.classList.remove("dragging");
    };
    c.addEventListener("pointerup", end);
    c.addEventListener("pointercancel", end);

    c.addEventListener("keydown", (e) => {
      const step = 0.01;
      const moves = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
      if (moves[e.key]) {
        this.offset.x += moves[e.key][0]; this.offset.y += moves[e.key][1];
        this.onAdjust("move"); this.draw(); e.preventDefault();
      } else if (e.key === "+" || e.key === "=" || e.key === "-") {
        this.fit = clamp(this.fit + (e.key === "-" ? -0.02 : 0.02), SIZE_RANGE[0], SIZE_RANGE[1]);
        this.onAdjust("fit"); this.draw(); e.preventDefault();
      }
    });
  }

  _dist() {
    const [a, b] = [...this._pointers.values()];
    return Math.hypot(a.x - b.x, a.y - b.y) || 1;
  }
}

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
