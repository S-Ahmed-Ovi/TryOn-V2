// Reads a binary glTF (.glb) into flat typed arrays the CPU renderer can use. No dependencies.
//   parseGLB(arrayBuffer, { decodeImage? }) -> { parts, bounds, info }
// Supports: triangle meshes, node transforms, POSITION / NORMAL / COLOR_0 / TEXCOORD_0, pbrMetallicRoughness
// (base colour, metal, roughness, base-colour texture), alphaMode BLEND, doubleSided.
// Not supported (a clear error is thrown): Draco and meshopt compression.

const ARRAYS = { 5120: Int8Array, 5121: Uint8Array, 5122: Int16Array, 5123: Uint16Array, 5125: Uint32Array, 5126: Float32Array };
const WIDTH = { SCALAR: 1, VEC2: 2, VEC3: 3, VEC4: 4, MAT4: 16 };

function accessor(json, bin, index) {
  const a = json.accessors[index];
  const view = json.bufferViews[a.bufferView];
  const Arr = ARRAYS[a.componentType];
  const width = WIDTH[a.type];
  const base = bin.byteOffset + (view.byteOffset || 0) + (a.byteOffset || 0);
  const stride = view.byteStride || Arr.BYTES_PER_ELEMENT * width;
  let out;
  if (stride === Arr.BYTES_PER_ELEMENT * width && base % Arr.BYTES_PER_ELEMENT === 0) {
    out = new Arr(bin.buffer, base, a.count * width).slice();
  } else {
    out = new Arr(a.count * width);
    const dv = new DataView(bin.buffer);
    const get = { 5120: "getInt8", 5121: "getUint8", 5122: "getInt16", 5123: "getUint16", 5125: "getUint32", 5126: "getFloat32" }[a.componentType];
    for (let i = 0; i < a.count; i++) for (let k = 0; k < width; k++) out[i * width + k] = dv[get](base + i * stride + k * Arr.BYTES_PER_ELEMENT, true);
  }
  if (a.normalized && a.componentType !== 5126) {
    const div = { 5120: 127, 5121: 255, 5122: 32767, 5123: 65535 }[a.componentType];
    const f = new Float32Array(out.length);
    for (let i = 0; i < out.length; i++) f[i] = Math.max(-1, out[i] / div);
    return { data: f, width, count: a.count };
  }
  return { data: out, width, count: a.count };
}

const mul = (a, b) => {                                    // column-major 4x4
  const o = new Float64Array(16);
  for (let c = 0; c < 4; c++) for (let r = 0; r < 4; r++) o[c * 4 + r] = a[r] * b[c * 4] + a[4 + r] * b[c * 4 + 1] + a[8 + r] * b[c * 4 + 2] + a[12 + r] * b[c * 4 + 3];
  return o;
};
const nodeMatrix = (n) => {
  if (n.matrix) return Float64Array.from(n.matrix);
  const [x, y, z, w] = n.rotation || [0, 0, 0, 1], [sx, sy, sz] = n.scale || [1, 1, 1], [tx, ty, tz] = n.translation || [0, 0, 0];
  return Float64Array.from([
    (1 - 2 * (y * y + z * z)) * sx, 2 * (x * y + z * w) * sx, 2 * (x * z - y * w) * sx, 0,
    2 * (x * y - z * w) * sy, (1 - 2 * (x * x + z * z)) * sy, 2 * (y * z + x * w) * sy, 0,
    2 * (x * z + y * w) * sz, 2 * (y * z - x * w) * sz, (1 - 2 * (x * x + y * y)) * sz, 0,
    tx, ty, tz, 1]);
};

function smoothNormals(pos, idx) {
  const n = new Float32Array(pos.length);
  for (let t = 0; t < idx.length; t += 3) {
    const a = idx[t] * 3, b = idx[t + 1] * 3, c = idx[t + 2] * 3;
    const ux = pos[b] - pos[a], uy = pos[b + 1] - pos[a + 1], uz = pos[b + 2] - pos[a + 2];
    const vx = pos[c] - pos[a], vy = pos[c + 1] - pos[a + 1], vz = pos[c + 2] - pos[a + 2];
    const nx = uy * vz - uz * vy, ny = uz * vx - ux * vz, nz = ux * vy - uy * vx;
    for (const i of [a, b, c]) { n[i] += nx; n[i + 1] += ny; n[i + 2] += nz; }
  }
  for (let i = 0; i < n.length; i += 3) {
    const l = Math.hypot(n[i], n[i + 1], n[i + 2]) || 1;
    n[i] /= l; n[i + 1] /= l; n[i + 2] /= l;
  }
  return n;
}

export async function parseGLB(buffer, { decodeImage } = {}) {
  const dv = new DataView(buffer);
  if (buffer.byteLength < 20 || dv.getUint32(0, true) !== 0x46546c67) throw new Error("This file is not a .glb model.");
  let off = 12, json = null, bin = null;
  while (off + 8 <= buffer.byteLength) {
    const len = dv.getUint32(off, true), type = dv.getUint32(off + 4, true), start = off + 8;
    if (type === 0x4e4f534a) json = JSON.parse(new TextDecoder().decode(new Uint8Array(buffer, start, len)));
    else if (type === 0x004e4942 && !bin) bin = new Uint8Array(buffer, start, len);
    off = start + len;
  }
  if (!json || !bin) throw new Error("The .glb model is incomplete.");
  const required = json.extensionsRequired || [];
  if (required.some((e) => /draco|meshopt/i.test(e))) throw new Error("Compressed (Draco / meshopt) models are not supported. Export the model without compression.");

  // materials (+ textures)
  const images = new Map();
  const loadTexture = async (info) => {
    if (!info || !decodeImage) return null;
    const tex = json.textures && json.textures[info.index];
    const img = tex && json.images && json.images[tex.source];
    if (!img || img.bufferView == null) return null;
    if (!images.has(tex.source)) {
      const v = json.bufferViews[img.bufferView];
      const bytes = new Uint8Array(bin.buffer, bin.byteOffset + (v.byteOffset || 0), v.byteLength);
      images.set(tex.source, decodeImage(bytes, img.mimeType).catch(() => null));
    }
    return images.get(tex.source);
  };
  const materials = [];
  for (const m of json.materials || [{}]) {
    const p = m.pbrMetallicRoughness || {};
    const c = p.baseColorFactor || [1, 1, 1, 1];
    materials.push({
      name: m.name || "", base: [c[0], c[1], c[2]], alpha: c[3], metallic: p.metallicFactor ?? 1, roughness: p.roughnessFactor ?? 1,
      blend: m.alphaMode === "BLEND", doubleSided: !!m.doubleSided, tex: await loadTexture(p.baseColorTexture),
      emissive: m.emissiveFactor || [0, 0, 0],
    });
  }
  if (!materials.length) materials.push({ base: [1, 1, 1], alpha: 1, metallic: 0, roughness: 0.5, blend: false, doubleSided: false, tex: null, emissive: [0, 0, 0] });

  // meshes with node transforms applied
  const parts = [];
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  const visit = (ni, parent) => {
    const node = json.nodes[ni];
    const world = mul(parent, nodeMatrix(node));
    if (node.mesh != null) {
      for (const prim of json.meshes[node.mesh].primitives) {
        if ((prim.mode ?? 4) !== 4) continue;
        const pos = accessor(json, bin, prim.attributes.POSITION).data;
        const idx = prim.indices != null ? Uint32Array.from(accessor(json, bin, prim.indices).data)
          : Uint32Array.from({ length: pos.length / 3 }, (_, i) => i);
        let nrm = prim.attributes.NORMAL != null ? accessor(json, bin, prim.attributes.NORMAL).data : smoothNormals(pos, idx);
        const P = new Float32Array(pos.length), N = new Float32Array(nrm.length);
        for (let i = 0; i < pos.length; i += 3) {
          const x = pos[i], y = pos[i + 1], z = pos[i + 2];
          P[i] = world[0] * x + world[4] * y + world[8] * z + world[12];
          P[i + 1] = world[1] * x + world[5] * y + world[9] * z + world[13];
          P[i + 2] = world[2] * x + world[6] * y + world[10] * z + world[14];
          const nx = nrm[i], ny = nrm[i + 1], nz = nrm[i + 2];
          const ax = world[0] * nx + world[4] * ny + world[8] * nz, ay = world[1] * nx + world[5] * ny + world[9] * nz, az = world[2] * nx + world[6] * ny + world[10] * nz;
          const l = Math.hypot(ax, ay, az) || 1;
          N[i] = ax / l; N[i + 1] = ay / l; N[i + 2] = az / l;
          for (let k = 0; k < 3; k++) { lo[k] = Math.min(lo[k], P[i + k]); hi[k] = Math.max(hi[k], P[i + k]); }
        }
        const col = prim.attributes.COLOR_0 != null ? accessor(json, bin, prim.attributes.COLOR_0) : null;
        const uv = prim.attributes.TEXCOORD_0 != null ? accessor(json, bin, prim.attributes.TEXCOORD_0).data : null;
        parts.push({
          name: json.meshes[node.mesh].name || node.name || "", positions: P, normals: N, indices: idx,
          colors: col ? col.data : null, colorStride: col ? col.width : 0, uvs: uv,
          material: materials[prim.material ?? 0] || materials[0],
        });
      }
    }
    for (const c of node.children || []) visit(c, world);
  };
  const eye = Float64Array.from([1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]);
  const scene = (json.scenes && json.scenes[json.scene ?? 0]) || { nodes: (json.nodes || []).map((_, i) => i) };
  for (const n of scene.nodes) visit(n, eye);
  if (!parts.length) throw new Error("The .glb model has no triangle meshes.");
  const info = (json.asset && json.asset.extras && json.asset.extras.tryon) || {};
  return { parts, bounds: { min: lo, max: hi }, info };
}
