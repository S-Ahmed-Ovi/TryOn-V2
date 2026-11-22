// Live camera with a face guide. Needs HTTPS or localhost (browser rule); otherwise the page falls back to
// the phone's own camera app through <input capture>.
import { fromSource } from "./photo.js";

export const cameraSupported = () => !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia) && window.isSecureContext;

export class Camera {
  constructor(video) {
    this.video = video;
    this.stream = null;
    this.facing = "user";
  }

  async start(facing = this.facing) {
    this.stop();
    this.facing = facing;
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: facing }, width: { ideal: 1280 }, height: { ideal: 960 } }, audio: false,
      });
    } catch (err) {
      throw new Error(describe(err));
    }
    this.stream = stream;
    this.video.srcObject = stream;
    this.video.classList.toggle("mirror", facing === "user");     // selfie view is mirrored, like a real mirror
    await this.video.play().catch(() => {});
    return this.hasMultiple();
  }

  async hasMultiple() {
    try { return (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === "videoinput").length > 1; }
    catch { return false; }
  }

  flip() { return this.start(this.facing === "user" ? "environment" : "user"); }

  /** The current frame, as the person saw it (mirrored for the front camera). */
  capture() {
    const v = this.video;
    return fromSource(v, v.videoWidth, v.videoHeight, this.facing === "user");
  }

  stop() {
    if (this.stream) this.stream.getTracks().forEach((t) => t.stop());
    this.stream = null;
    this.video.srcObject = null;
  }
}

function describe(err) {
  switch (err && err.name) {
    case "NotAllowedError": case "SecurityError": return "Camera access was blocked. Allow the camera in your browser's address bar, or upload a photo instead.";
    case "NotFoundError": case "OverconstrainedError": return "No camera was found on this device. You can upload a photo instead.";
    case "NotReadableError": return "The camera is being used by another app. Close it and try again.";
    default: return "We couldn't start the camera. You can upload a photo instead.";
  }
}
