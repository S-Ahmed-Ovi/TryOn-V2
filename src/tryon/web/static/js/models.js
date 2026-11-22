// Loads and caches 3D models (.glb) for the CPU renderer.
import { parseGLB } from "./soft3d/glb.js";

const cache = new Map();                        // url -> Promise<model>

export function loadModel(url) {
  if (!cache.has(url)) {
    const p = fetch(url)
      .then((res) => {
        if (!res.ok) throw new Error("Could not load the 3D model for these frames.");
        return res.arrayBuffer();
      })
      .then((buf) => parseGLB(buf))
      .catch((err) => { cache.delete(url); throw err; });
    cache.set(url, p);
  }
  return cache.get(url);
}

/** Start downloading a model in the background (e.g. the frames the person is likely to try next). */
export function preloadModel(url) { loadModel(url).catch(() => {}); }
