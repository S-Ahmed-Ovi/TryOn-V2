#!/usr/bin/env node
// Renders the 3D models with the same CPU renderer the website uses. Developer tool; the finished images ship with the project.
//
//   node tools/render_models.mjs sheet <out.png> [SKU-prefix]     contact sheet: front, three-quarter and top views
//   node tools/render_models.mjs cutouts <out-dir>                2D front views for the catalogue (+ cutouts.json)
//
// Models are read from data/models3d/. Needs Node 18+ and nothing else.
import fs from "node:fs";
import path from "node:path";
import zlib from "node:zlib";
import { fileURLToPath } from "node:url";
import { parseGLB } from "../src/tryon/web/static/js/soft3d/glb.js";
import { render, rotX, rotY, matMul3 } from "../src/tryon/web/static/js/soft3d/engine.js";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const MODELS = path.join(ROOT, "data", "models3d");

// ── PNG writer ─────────────────────────────────────────────────────────────
const CRC = new Uint32Array(256).map((_, n) => { let c = n; for (let k = 0; k < 8; k++) c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1; return c >>> 0; });
const crc32 = (buf) => { let c = 0xffffffff; for (const b of buf) c = CRC[(c ^ b) & 255] ^ (c >>> 8); return (c ^ 0xffffffff) >>> 0; };
function chunk(type, data) {
  const out = Buffer.alloc(12 + data.length);
  out.writeUInt32BE(data.length, 0); out.write(type, 4, "ascii"); data.copy(out, 8);
  out.writeUInt32BE(crc32(out.subarray(4, 8 + data.length)), 8 + data.length);
  return out;
}
export function encodePNG(w, h, rgba) {
  const raw = Buffer.alloc((w * 4 + 1) * h);
  for (let y = 0; y < h; y++) { raw[y * (w * 4 + 1)] = 0; Buffer.from(rgba.buffer, rgba.byteOffset + y * w * 4, w * 4).copy(raw, y * (w * 4 + 1) + 1); }
  const ihdr = Buffer.alloc(13); ihdr.writeUInt32BE(w, 0); ihdr.writeUInt32BE(h, 4); ihdr[8] = 8; ihdr[9] = 6;
  return Buffer.concat([Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]), chunk("IHDR", ihdr), chunk("IDAT", zlib.deflateSync(raw, { level: 6 })), chunk("IEND", Buffer.alloc(0))]);
}

// ── helpers ────────────────────────────────────────────────────────────────
const manifest = () => JSON.parse(fs.readFileSync(path.join(MODELS, "manifest.json"), "utf8"));
async function load(file) {
  const b = fs.readFileSync(path.join(MODELS, file));
  return parseGLB(b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength));
}
function over(dst, dw, img, ox, oy) {                          // straight-alpha composite of img onto an opaque RGBA canvas
  for (let y = 0; y < img.h; y++) for (let x = 0; x < img.w; x++) {
    const s = (y * img.w + x) * 4, d = ((oy + img.y + y) * dw + ox + img.x + x) * 4, a = img.data[s + 3] / 255;
    if (!a) continue;
    for (let k = 0; k < 3; k++) dst[d + k] = img.data[s + k] * a + dst[d + k] * (1 - a);
  }
}

async function sheet(out, prefix = "") {
  const list = manifest().models.filter((m) => m.sku.includes(prefix));
  const cw = 330, ch = 200, cols = 3;
  const W = cw * cols, H = ch * list.length;
  const canvas = new Uint8ClampedArray(W * H * 4);
  for (let i = 0; i < canvas.length; i += 4) { canvas[i] = 214; canvas[i + 1] = 220; canvas[i + 2] = 214; canvas[i + 3] = 255; }
  const views = [
    { R: [1, 0, 0, 0, 1, 0, 0, 0, 1], t: [0, 0, -42] },                              // front
    { R: matMul3(rotY(-38), rotX(6)), t: [0, 0, -42] },                              // three-quarter
    { R: rotX(62), t: [0, 0, -40] },                                                 // from above: temples
  ];
  for (let r = 0; r < list.length; r++) {
    const model = await load(list[r].file);
    for (let c = 0; c < cols; c++) {
      const v = views[c];
      const img = render(model, { pose: { R: v.R, t: v.t }, camera: { f: 520, cx: cw / 2, cy: ch / 2, width: cw, height: ch }, ss: 2 });
      if (img) over(canvas, W, img, c * cw, r * ch);
    }
  }
  fs.writeFileSync(out, encodePNG(W, H, canvas));
  console.log(`wrote ${out} (${list.map((m) => m.sku).join(", ")})`);
}

async function grid(out, yaw = 0) {
  const list = manifest().models;
  const cw = 330, ch = 170, cols = 6, rows = Math.ceil(list.length / cols);
  const W = cw * cols, H = ch * rows;
  const canvas = new Uint8ClampedArray(W * H * 4);
  for (let i = 0; i < canvas.length; i += 4) { canvas[i] = 214; canvas[i + 1] = 220; canvas[i + 2] = 214; canvas[i + 3] = 255; }
  for (let i = 0; i < list.length; i++) {
    const model = await load(list[i].file);
    const img = render(model, { pose: { R: matMul3(rotY(yaw), rotX(0)), t: [0, 0, -40] }, camera: { f: 560, cx: cw / 2, cy: ch / 2, width: cw, height: ch }, ss: 2 });
    if (img) over(canvas, W, img, (i % cols) * cw, Math.floor(i / cols) * ch);
  }
  fs.writeFileSync(out, encodePNG(W, H, canvas));
  console.log(`wrote ${out}`);
}

// Front view, nearly orthographic, on a canvas exactly CANVAS_CM wide, with the pupil line at the vertical middle.
const CANVAS_CM = 15.2, PX_PER_CM = 64, CANVAS_H_CM = 9.0;
async function cutouts(dir) {
  fs.mkdirSync(dir, { recursive: true });
  const D = 400, f = PX_PER_CM * D;
  const W = Math.round(CANVAS_CM * PX_PER_CM), H = Math.round(CANVAS_H_CM * PX_PER_CM);
  const result = {};
  for (const m of manifest().models) {
    const model = await load(m.file);
    const img = render(model, { pose: { R: [1, 0, 0, 0, 1, 0, 0, 0, 1], t: [0, 0, -D] }, camera: { f, cx: W / 2, cy: H / 2, width: W, height: H }, ss: 3 });
    const full = new Uint8ClampedArray(W * H * 4);
    for (let y = 0; y < img.h; y++) for (let x = 0; x < img.w; x++) full.set(img.data.subarray((y * img.w + x) * 4, (y * img.w + x) * 4 + 4), ((img.y + y) * W + img.x + x) * 4);
    fs.writeFileSync(path.join(dir, `${m.sku}.png`), encodePNG(W, H, full));
    result[m.sku] = { width: W, height: H, pupil_y: H / 2 };
    console.log(`  ${m.sku}`);
  }
  fs.writeFileSync(path.join(dir, "cutouts.json"), JSON.stringify({ canvas_cm: CANVAS_CM, px_per_cm: PX_PER_CM, items: result }, null, 1));
}

if (import.meta.url === `file://${process.argv[1]}`) await main();
async function main() {
const [cmd, a, b] = process.argv.slice(2);
if (cmd === "sheet" && a) await sheet(a, b);
else if (cmd === "grid" && a) await grid(a, Number(b || 0));
else if (cmd === "cutouts" && a) await cutouts(a);
else { console.error("usage: render_models.mjs sheet <out.png> [SKU-prefix] | cutouts <out-dir>"); process.exit(2); }
}
