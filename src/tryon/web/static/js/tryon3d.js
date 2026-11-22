// Real 3D try-on on the CPU. Pure functions (no DOM), so the same code runs in the browser and in Node tests.
//
//   headPlacement(pose3d, adjust)  ->  { pose, occluder }   what the renderer needs for one face
//   renderGlasses(model, pose3d, w, h, opts) -> { x, y, w, h, data } | null
//
// pose3d comes from the server (MediaPipe's facial transformation matrix): a 4x4 row-major matrix that moves the
// canonical head (cm, +x image right, +y up, +z out of the face) into the camera (OpenGL convention), for a virtual
// camera with a 63 degree vertical field of view. See src/tryon/vision/pose3d.py.
import { render, matMul3, rotX } from "./soft3d/engine.js";

/**
 * Where glasses sit on MediaPipe's canonical head. Measured on real portraits (see docs/ARCHITECTURE.md, "3D calibration").
 * The canonical head is ~1.15 x a real head, so a real 14 cm frame is drawn 1.15 x bigger.
 */
export const HEAD = {
  scale: 1.15,                       // canonical cm per real cm
  anchor: [0.0, 3.1, 1.9],           // where the model origin (bridge centre, pupil height, lens plane) goes, canonical cm
  tilt: 4,                           // pantoscopic tilt in degrees: the bottom of the lenses is closer to the cheeks
  occluder: { center: [0, 1.5, -9.8], radii: [8.4, 12.5, 10.5] },   // hidden head ellipsoid, canonical cm
};

export const SIZE_RANGE = [0.8, 1.25];

export function cameraFor(width, height, fovY = 63) {
  const f = (height / 2) / Math.tan((fovY * Math.PI) / 360);
  return { f, cx: width / 2, cy: height / 2, width, height };
}

const rotOf = (m) => [m[0], m[1], m[2], m[4], m[5], m[6], m[8], m[9], m[10]];
const apply = (R, v) => [R[0] * v[0] + R[1] * v[1] + R[2] * v[2], R[3] * v[0] + R[4] * v[1] + R[5] * v[2], R[6] * v[0] + R[7] * v[1] + R[8] * v[2]];

/**
 * adjust: { size = 1, lift = 0, shift = 0 }   size multiplies the frame, lift moves it up (+) or down (-) in
 * real cm, shift moves it sideways in real cm. The same three sliders the 2D try-on has.
 */
export function headPlacement(pose3d, adjust = {}) {
  const m = pose3d.matrix, Rh = rotOf(m), th = [m[3], m[7], m[11]];
  const size = adjust.size ?? 1, k = HEAD.scale;
  const a = [HEAD.anchor[0] + (adjust.shift ?? 0) * k, HEAD.anchor[1] + (adjust.lift ?? 0) * k, HEAD.anchor[2]];
  const Rg = matMul3(Rh, rotX(HEAD.tilt));
  const o = apply(Rh, a);
  return {
    pose: { R: Rg, t: [o[0] + th[0], o[1] + th[1], o[2] + th[2]], scale: k * size },
    occluder: { center: HEAD.occluder.center, radii: HEAD.occluder.radii, R: Rh, t: th },
  };
}

/** Render the glasses for one head pose into a w x h camera image. Returns the RGBA rectangle that holds them. */
export function renderGlasses(model, pose3d, w, h, opts = {}) {
  const { pose, occluder } = headPlacement(pose3d, opts.adjust);
  return render(model, {
    pose, camera: cameraFor(w, h, pose3d.fov_y), occluder: opts.occluder === false ? undefined : occluder,
    ss: opts.ss ?? 2, exposure: opts.exposure ?? 1, tint: opts.tint,
  });
}

/** Scene brightness (0-1) from RGBA pixels -> a renderer exposure that keeps the glasses from glowing in dim photos. */
export function exposureFor(luma01) {
  return Math.min(1.12, Math.max(0.62, 0.5 + 0.7 * luma01));
}
