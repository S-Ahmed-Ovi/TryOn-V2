// Turning a File / camera frame into a canvas the page and the server both use.

export const MAX_SIDE = 1280;
export const ACCEPTED = /^image\/(jpeg|png|webp|gif|bmp|heic|heif)$/i;

async function decode(file) {
  if ("createImageBitmap" in window) {
    try { return await createImageBitmap(file, { imageOrientation: "from-image" }); } catch { /* fall back below */ }
  }
  const url = URL.createObjectURL(file);
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    return img;
  } finally { URL.revokeObjectURL(url); }
}

/** Resize to at most MAX_SIDE (EXIF rotation applied by the browser) and return { canvas, blob }. */
export async function prepareFile(file) {
  if (file.type && !ACCEPTED.test(file.type)) throw new Error("Please choose a photo (JPG, PNG or WebP).");
  let source;
  try { source = await decode(file); } catch { throw new Error("We couldn't open that image. Try a JPG or PNG photo."); }
  return fromSource(source, source.width, source.height);
}

export function fromSource(source, w, h, mirror = false) {
  const s = Math.min(1, MAX_SIDE / Math.max(w, h));
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(w * s);
  canvas.height = Math.round(h * s);
  const ctx = canvas.getContext("2d");
  if (mirror) { ctx.translate(canvas.width, 0); ctx.scale(-1, 1); }
  ctx.drawImage(source, 0, 0, canvas.width, canvas.height);
  return new Promise((resolve, reject) =>
    canvas.toBlob((blob) => (blob ? resolve({ canvas, blob }) : reject(new Error("Could not prepare that photo."))), "image/jpeg", 0.92));
}
