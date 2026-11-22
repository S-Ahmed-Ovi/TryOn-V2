// Live 3D try-on: your camera, with the glasses drawn on your face in real time. No GPU.
//
// How a frame travels:
//   camera -> small JPEG -> WebSocket -> server tracks the face on its CPU -> head pose back
//   -> this page draws the glasses with the software renderer onto the SAME frame the pose belongs to.
// The picture you see is the frame the pose was measured on, so the glasses never lag behind or float off the face;
// the cost is about 60-100 ms of delay, like a slightly slow mirror.
import { PoseSmoother } from "./tracker.js";
import { exposureFor, renderGlasses } from "./tryon3d.js";
import { sleep } from "./ui.js";

const FRAME_W = 640;               // frames are drawn and shown at this width
const SEND_W = 320;                // the face tracker gets a smaller copy (it only needs to find the head)
const MIN_INTERVAL = 66;           // ms between frames sent: at most ~15 per second, so a small server can serve a few people
const LOST_RESET_MS = 500;         // forget the smoothing after the face has been gone this long
const OUT_ASPECT = 4 / 5;          // the same frame shape as the photo stage

export class LiveError extends Error {}

function describeCamera(err) {
  switch (err && err.name) {
    case "NotAllowedError": case "SecurityError": return "Camera access was blocked. Allow the camera in your browser's address bar, or use your photo.";
    case "NotFoundError": case "OverconstrainedError": return "No camera was found on this device. You can keep using your photo.";
    case "NotReadableError": return "The camera is being used by another app. Close it and try again.";
    default: return "We couldn't start the camera. You can keep using your photo.";
  }
}

export class LiveTryOn {
  /** canvas: where the result is shown. onStatus(state, detail): "starting" | "tracking" | "no_face" | "unusable" | "error". */
  constructor(canvas, { onStatus = () => {} } = {}) {
    this.canvas = canvas;
    this.ctx = canvas.getContext("2d");
    this.onStatus = onStatus;
    this.video = document.createElement("video");
    this.video.playsInline = true; this.video.muted = true;
    this.frames = [0, 1].map(() => document.createElement("canvas"));       // double buffer: one is shown while the next is captured
    this.small = document.createElement("canvas");
    this.probe = Object.assign(document.createElement("canvas"), { width: 16, height: 16 });
    this.layer = document.createElement("canvas");
    this.model = null;
    this.adjust = { size: 1, lift: 0, shift: 0 };
    this.siteName = "";
    this.running = false;
    this.status = "";
    this.ss = 2;
    this.exposure = 1;
    this.smoother = new PoseSmoother();
    this.lastSeen = 0;
    this._seq = 0; this._flip = 0; this._waiter = null; this._frameNo = 0;
  }

  setModel(model) { this.model = model; }
  setAdjust(adjust) { this.adjust = { ...this.adjust, ...adjust }; }

  // ── lifecycle ──────────────────────────────────────────────────────────
  async start() {
    if (this.running) return;
    this.running = true;
    this._setStatus("starting");
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "user" }, width: { ideal: 960 }, height: { ideal: 720 } }, audio: false,
      });
    } catch (err) {
      this.running = false;
      throw new LiveError(describeCamera(err));
    }
    this.video.srcObject = this.stream;
    await this.video.play().catch(() => {});
    try {
      await this._connect();
    } catch (err) {
      this.stop();
      throw err;
    }
    this.smoother.reset();
    this._loop();
  }

  stop() {
    this.running = false;
    if (this.ws) { try { this.ws.close(); } catch { /* already closed */ } this.ws = null; }
    if (this.stream) this.stream.getTracks().forEach((t) => t.stop());
    this.stream = null;
    this.video.srcObject = null;
    if (this._waiter) { this._waiter.resolve(null); this._waiter = null; }
  }

  _setStatus(state, detail) {
    if (state !== this.status) { this.status = state; this.onStatus(state, detail); }
  }

  _connect() {
    return new Promise((resolve, reject) => {
      const url = `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/track`;
      let ready = false;
      const ws = (this.ws = new WebSocket(url));
      ws.binaryType = "arraybuffer";
      const timer = setTimeout(() => reject(new LiveError("The live camera did not answer. Check the server and try again.")), 10000);
      ws.onmessage = (ev) => {
        let msg;
        try { msg = JSON.parse(ev.data); } catch { return; }
        if (!ready) {
          clearTimeout(timer);
          if (msg.ready) { ready = true; resolve(); } else reject(new LiveError(msg.message || "The live camera is not available right now."));
          return;
        }
        if (this._waiter && (msg.seq === this._waiter.seq || msg.seq === 0)) { const w = this._waiter; this._waiter = null; w.resolve(msg); }
      };
      ws.onerror = () => { clearTimeout(timer); if (!ready) reject(new LiveError("We can't reach the live camera on the server.")); };
      ws.onclose = () => {
        clearTimeout(timer);
        if (this._waiter) { this._waiter.resolve(null); this._waiter = null; }
        if (!ready) reject(new LiveError("The live camera closed the connection."));
        else if (this.running) { this.running = false; this._setStatus("error", "The live camera connection was lost."); }
      };
    });
  }

  // ── one frame: capture, send, wait for the pose ────────────────────────
  async _captureAndSend() {
    const v = this.video;
    if (!v.videoWidth) { await sleep(30); return { frame: null, reply: null }; }
    const idx = (this._flip ^= 1);
    const frame = this.frames[idx];
    const w = FRAME_W, h = Math.round((FRAME_W * v.videoHeight) / v.videoWidth);
    if (frame.width !== w || frame.height !== h) { frame.width = w; frame.height = h; }
    const fx = frame.getContext("2d");
    fx.save(); fx.translate(w, 0); fx.scale(-1, 1); fx.drawImage(v, 0, 0, w, h); fx.restore();      // a mirror: your left is on the left

    const sw = SEND_W, sh = Math.round((SEND_W * h) / w);
    if (this.small.width !== sw) { this.small.width = sw; this.small.height = sh; }
    this.small.getContext("2d").drawImage(frame, 0, 0, sw, sh);
    const blob = await new Promise((r) => this.small.toBlob(r, "image/jpeg", 0.72));
    if (!blob || !this.running || !this.ws || this.ws.readyState !== 1) return { frame, reply: null };

    const seq = (this._seq = (this._seq % 0x7fffffff) + 1);
    const reply = new Promise((resolve) => { this._waiter = { seq, resolve }; });
    const body = new Uint8Array(4 + blob.size);
    new DataView(body.buffer).setUint32(0, seq, false);
    body.set(new Uint8Array(await blob.arrayBuffer()), 4);
    this.ws.send(body);
    return { frame, reply: await Promise.race([reply, sleep(4000).then(() => null)]) };
  }

  async _loop() {
    let next = this._captureAndSend();
    let t0 = performance.now();
    while (this.running) {
      const cur = await next;
      if (!this.running) break;
      const wait = MIN_INTERVAL - (performance.now() - t0);
      if (wait > 0) await sleep(wait);
      t0 = performance.now();
      next = this._captureAndSend();                  // the next frame is already travelling while this one is drawn
      if (cur.frame) this._present(cur.frame, cur.reply);
    }
  }

  // ── drawing ────────────────────────────────────────────────────────────
  _present(frame, reply) {
    const now = performance.now();
    const w = frame.width, h = frame.height;
    const fx = frame.getContext("2d");
    if (++this._frameNo % 12 === 1) this.exposure = this._measureExposure(frame);

    if (reply && reply.ok && reply.pose && this.model) {
      this.lastSeen = now;
      const pose = { ...reply.pose, matrix: this.smoother.update(reply.pose.matrix, now / 1000) };
      const t = performance.now();
      const img = renderGlasses(this.model, pose, w, h, { adjust: this.adjust, ss: this.ss, exposure: this.exposure });
      const cost = performance.now() - t;
      if (cost > 38 && this.ss > 1) this.ss = 1; else if (cost < 12 && this.ss < 2) this.ss = 2;       // keep up on slow computers
      if (img) this._blit(fx, img, w);
      this._setStatus("tracking");
    } else {
      if (now - this.lastSeen > LOST_RESET_MS) this.smoother.reset();
      this._setStatus(reply && reply.reason === "unusable" ? "unusable" : "no_face");
    }
    this._show(frame);
  }

  _blit(fx, img, frameW) {
    const L = this.layer;
    if (L.width !== img.w || L.height !== img.h) { L.width = img.w; L.height = img.h; }
    L.getContext("2d").putImageData(new ImageData(img.data, img.w, img.h), 0, 0);
    fx.save();
    fx.shadowColor = "rgba(8, 10, 9, .34)";
    fx.shadowBlur = frameW * 0.012;
    fx.shadowOffsetY = frameW * 0.006;
    fx.drawImage(L, img.x, img.y);
    fx.restore();
  }

  _show(frame) {                                       // "cover" the 4:5 stage with the frame
    const c = this.canvas;
    if (c.width !== 720) { c.width = 720; c.height = Math.round(720 / OUT_ASPECT); }
    const s = Math.max(c.width / frame.width, c.height / frame.height);
    const dw = frame.width * s, dh = frame.height * s;
    this.ctx.drawImage(frame, (c.width - dw) / 2, (c.height - dh) / 2, dw, dh);
  }

  _measureExposure(frame) {
    try {
      const c = this.probe.getContext("2d", { willReadFrequently: true });
      c.drawImage(frame, frame.width * 0.3, frame.height * 0.15, frame.width * 0.4, frame.height * 0.5, 0, 0, 16, 16);
      const d = c.getImageData(0, 0, 16, 16).data;
      let sum = 0;
      for (let i = 0; i < d.length; i += 4) sum += 0.2126 * d[i] + 0.7152 * d[i + 1] + 0.0722 * d[i + 2];
      return exposureFor(sum / (16 * 16 * 255));
    } catch { return 1; }
  }

  // ── saving ─────────────────────────────────────────────────────────────
  snapshot() {
    const out = document.createElement("canvas");
    out.width = this.canvas.width; out.height = this.canvas.height;
    const x = out.getContext("2d");
    x.drawImage(this.canvas, 0, 0);
    if (this.siteName) {
      x.font = `${Math.round(out.width * 0.028)}px "Instrument Serif", Georgia, serif`;
      x.fillStyle = "rgba(255,255,255,.88)";
      x.shadowColor = "rgba(0,0,0,.5)"; x.shadowBlur = out.width * 0.01;
      x.textAlign = "left"; x.textBaseline = "bottom";
      x.fillText(this.siteName, out.width * 0.035, out.height - out.width * 0.03);
    }
    return new Promise((resolve) => out.toBlob(resolve, "image/jpeg", 0.93));
  }
}
