#!/usr/bin/env node
// Developer tool: draw one model onto a raw RGBA photo with its exported pose and write a PNG. Used to check the fit.
//   node tools/compose_photo.mjs <photo.rgba> <pose.json> <SKU> <out.png> [crop=x0,y0,x1,y1]
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { parseGLB } from "../src/tryon/web/static/js/soft3d/glb.js";
import { renderGlasses } from "../src/tryon/web/static/js/tryon3d.js";
import { encodePNG } from "./render_models.mjs";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const [rgbaFile, poseFile, sku, out, crop] = process.argv.slice(2);
const meta = JSON.parse(fs.readFileSync(poseFile, "utf8"));
const raw = fs.readFileSync(rgbaFile), photo = new Uint8ClampedArray(raw.buffer, raw.byteOffset, raw.length).slice();
const b = fs.readFileSync(path.join(ROOT, "data", "models3d", `${sku}.glb`));
const model = await parseGLB(b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength));
const t0 = performance.now();
const img = renderGlasses(model, meta.pose, meta.w, meta.h, { ss: 2 });
console.log(`render ${(performance.now() - t0).toFixed(0)} ms, rect ${img.w}x${img.h}`);
for (let y = 0; y < img.h; y++) for (let x = 0; x < img.w; x++) {
  const s = (y * img.w + x) * 4, d = ((img.y + y) * meta.w + img.x + x) * 4, a = img.data[s + 3] / 255;
  if (!a) continue;
  for (let k = 0; k < 3; k++) photo[d + k] = img.data[s + k] * a + photo[d + k] * (1 - a);
}
let [x0, y0, x1, y1] = crop ? crop.split(",").map(Number) : [0, 0, meta.w, meta.h];
const cw = x1 - x0, ch = y1 - y0, outBuf = new Uint8ClampedArray(cw * ch * 4);
for (let y = 0; y < ch; y++) outBuf.set(photo.subarray(((y0 + y) * meta.w + x0) * 4, ((y0 + y) * meta.w + x0 + cw) * 4), y * cw * 4);
fs.writeFileSync(out, encodePNG(cw, ch, outBuf));
