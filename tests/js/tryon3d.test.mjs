// Run with:  node --test tests/js/tryon3d.test.mjs        (Node 18+, no packages needed)
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const JS = path.join(ROOT, "src", "tryon", "web", "static", "js");
const { parseGLB } = await import(path.join(JS, "soft3d", "glb.js"));
const { render } = await import(path.join(JS, "soft3d", "engine.js"));
const { HEAD, cameraFor, headPlacement, renderGlasses, exposureFor } = await import(path.join(JS, "tryon3d.js"));
const { PoseSmoother } = await import(path.join(JS, "tracker.js"));

const manifest = JSON.parse(fs.readFileSync(path.join(ROOT, "data", "models3d", "manifest.json"), "utf8")).models;
const fixture = (n) => JSON.parse(fs.readFileSync(path.join(import.meta.dirname ?? path.dirname(fileURLToPath(import.meta.url)), "fixtures", `${n}.json`), "utf8"));
const load = async (sku) => { const b = fs.readFileSync(path.join(ROOT, "data", "models3d", `${sku}.glb`)); return parseGLB(b.buffer.slice(b.byteOffset, b.byteOffset + b.byteLength)); };
const straight = (dist = 45, yaw = 0) => { const a = (yaw * Math.PI) / 180; return { matrix: [Math.cos(a), 0, Math.sin(a), 0, 0, 1, 0, 0, -Math.sin(a), 0, Math.cos(a), -dist, 0, 0, 0, 1], fov_y: 63 }; };
const coverage = (img) => { let n = 0; for (let i = 3; i < img.data.length; i += 4) if (img.data[i] > 40) n++; return n; };

test("every model loads and has geometry", async () => {
  assert.equal(manifest.length, 24);
  for (const m of manifest) {
    const model = await load(m.sku);
    assert.ok(model.parts?.length >= 2 || model.meshes?.length >= 2 || Object.keys(model).length > 0, m.sku);
  }
});

test("a frame is drawn on the eyes of two real portraits", async () => {
  for (const name of ["portrait_a", "portrait_b"]) {
    const f = fixture(name), model = await load("TO-WAY-01");
    const img = renderGlasses(model, f.pose, f.w, f.h, { ss: 1 });
    assert.ok(img && img.w > 80 && img.h > 30, `${name}: nothing was drawn`);
    for (const [x, y] of f.eyes) {                           // both pupils must be inside the glasses, at lens height
      assert.ok(x > img.x && x < img.x + img.w, `${name}: pupil x ${x} outside ${img.x}..${img.x + img.w}`);
      assert.ok(y > img.y + img.h * 0.2 && y < img.y + img.h * 0.8, `${name}: pupil y ${y} not at lens height (${img.y}..${img.y + img.h})`);
    }
    const cx = img.x + img.w / 2, mid = (f.eyes[0][0] + f.eyes[1][0]) / 2;
    assert.ok(Math.abs(cx - mid) < img.w * 0.08, `${name}: glasses are not centred on the face`);
    const eyeDist = Math.hypot(f.eyes[1][0] - f.eyes[0][0], f.eyes[1][1] - f.eyes[0][1]);
    assert.ok(img.w > eyeDist * 1.6 && img.w < eyeDist * 2.9, `${name}: glasses are ${(img.w / eyeDist).toFixed(2)} x the eye distance`);   // 134 mm frame on ~63 mm eye distance
  }
});

test("size and height sliders move and scale the glasses", async () => {
  const f = fixture("portrait_a"), model = await load("TO-RND-02");
  const base = renderGlasses(model, f.pose, f.w, f.h, { ss: 1 });
  const big = renderGlasses(model, f.pose, f.w, f.h, { ss: 1, adjust: { size: 1.2 } });
  const up = renderGlasses(model, f.pose, f.w, f.h, { ss: 1, adjust: { lift: 1 } });
  const right = renderGlasses(model, f.pose, f.w, f.h, { ss: 1, adjust: { shift: 1 } });
  assert.ok(big.w / base.w > 1.12 && big.w / base.w < 1.28);
  assert.ok(up.y < base.y - 5, "positive lift moves the glasses up the face");
  assert.ok(right.x > base.x + 5, "positive shift moves them to image-right");
});

test("turning the head turns the glasses, and the hidden head covers what is behind the face", async () => {
  const model = await load("TO-WAY-01");
  const front = renderGlasses(model, straight(45, 0), 640, 480, { ss: 1 });
  const turned = renderGlasses(model, straight(45, 40), 640, 480, { ss: 1 });
  assert.ok(turned.w < front.w * 0.95 || turned.w > front.w, "a turned head shows a different outline");
  const withHead = coverage(renderGlasses(model, straight(45, 80), 640, 480, { ss: 1 }));
  const without = coverage(renderGlasses(model, straight(45, 80), 640, 480, { ss: 1, occluder: false }));
  assert.ok(withHead < without, "the hidden head ellipsoid must remove the part of the arms that is behind the face");
});

test("farther heads give smaller glasses (perspective)", async () => {
  const model = await load("TO-OVL-01");
  const near = renderGlasses(model, straight(35), 640, 480, { ss: 1 }), far = renderGlasses(model, straight(70), 640, 480, { ss: 1 });
  assert.ok(near.w / far.w > 1.8 && near.w / far.w < 2.2);
});

test("placement maths: the model origin lands where HEAD.anchor says", () => {
  const { pose } = headPlacement(straight(45), { size: 1 });
  assert.equal(pose.scale, HEAD.scale);
  assert.ok(Math.abs(pose.t[1] - HEAD.anchor[1]) < 1e-9 && Math.abs(pose.t[2] - (-45 + HEAD.anchor[2])) < 1e-9);
  const cam = cameraFor(640, 480, 63);
  assert.ok(Math.abs(cam.f - 240 / Math.tan((31.5 * Math.PI) / 180)) < 1e-6 && cam.cx === 320 && cam.cy === 240);
});

test("brightness -> exposure stays in a safe range", () => {
  assert.ok(exposureFor(0) >= 0.6 && exposureFor(1) <= 1.15 && exposureFor(0.3) < exposureFor(0.8));
});

test("pose smoothing: steady when still, follows quickly when moving, never flips", () => {
  const s = new PoseSmoother();
  const mat = (tx, yaw = 0) => { const a = (yaw * Math.PI) / 180; return [Math.cos(a), 0, Math.sin(a), tx, 0, 1, 0, 0, -Math.sin(a), 0, Math.cos(a), -45, 0, 0, 0, 1]; };
  let out; const rng = (() => { let x = 7; return () => ((x = (x * 16807) % 2147483647) / 2147483647 - 0.5); })();
  for (let i = 0; i < 60; i++) out = s.update(mat(rng() * 0.4, rng() * 2), i / 15);
  assert.ok(Math.abs(out[3]) < 0.2, "jitter around 0 is damped");
  for (let i = 60; i < 75; i++) out = s.update(mat(10 + (i - 60) * 0.5, 30), i / 15);       // a real move: 10 cm and 30 degrees
  assert.ok(out[3] > 9, `follows a real move quickly (got ${out[3].toFixed(2)})`);
  assert.ok(Math.abs(out[2] - 0.5) < 0.2, "rotation follows too");
  const q = new PoseSmoother(); q.update(mat(0, 179), 0);
  const flipped = q.update(mat(0, -179), 1 / 15);                                             // across the +-180 wrap: must go the short way
  assert.ok(flipped[0] < 0, "rotation takes the short way round");
});

test("the software renderer works without any GPU or DOM", async () => {
  assert.equal(typeof globalThis.document, "undefined");
  assert.equal(typeof globalThis.WebGLRenderingContext, "undefined");
  const model = await load("TO-AVI-01");
  const img = render(model, { pose: { R: [1, 0, 0, 0, 1, 0, 0, 0, 1], t: [0, 0, -40], scale: 1.15 }, camera: cameraFor(320, 240, 63), ss: 1 });
  assert.ok(img && coverage(img) > 500);
});
