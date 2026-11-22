"""End-to-end check in a real browser (Chromium via Playwright), on a CPU-only machine.

    pip install playwright && playwright install chromium
    python tests/e2e_browser.py --photo path/to/a_front_facing_portrait.jpg [--out shots]

It starts the real app, then, as a person would: opens the page, uploads the photo, switches to Real 3D, changes frames,
moves the sliders, saves a picture, starts the live 3D camera (a fake webcam plays your photo, drifting a little), and
goes back. It fails on any console error, and saves screenshots so you can look at them. No GPU is needed anywhere.

If the `websockets` package is not installed the live camera's WebSocket is bridged into this process instead; the
server-side face tracking is still the real MediaPipe code.
"""
from __future__ import annotations

import argparse
import asyncio
import base64
import importlib.util
import socket
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def write_y4m(photo: Path, out: Path, seconds=4, fps=15, size=(640, 480)) -> None:
    """A fake webcam clip: the photo, slowly drifting and zooming like a person moving a little."""
    img = cv2.imread(str(photo))
    h, w = img.shape[:2]
    W, H = size
    scale = max(W / w, H / h) * 1.25
    base = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
    bh, bw = base.shape[:2]
    with open(out, "wb") as f:
        f.write(f"YUV4MPEG2 W{W} H{H} F{fps}:1 Ip A1:1 C420jpeg\n".encode())
        for i in range(seconds * fps):
            t = i / fps
            dx, dy = 18 * np.sin(t * 1.3), 10 * np.sin(t * 0.9)
            M = np.float32([[1, 0, (bw - W) / 2 + dx], [0, 1, (bh - H) / 2 + dy]])      # dst(x, y) = base(x + ox, y + oy)
            frame = cv2.warpAffine(base, M, (W, H), flags=cv2.INTER_LINEAR | cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REPLICATE)
            yuv = cv2.cvtColor(frame, cv2.COLOR_BGR2YUV_I420)
            f.write(b"FRAME\n" + yuv.tobytes())


BRIDGE_JS = """
(() => {
  class FakeSocket {
    constructor() { this.readyState = 0; this.binaryType = 'arraybuffer';
      setTimeout(() => { this.readyState = 1; this.onmessage && this.onmessage({ data: JSON.stringify({ ready: true, fov_y: 63 }) }); }, 30); }
    send(buf) {
      const u8 = new Uint8Array(buf); let s = ''; for (let i = 0; i < u8.length; i += 8192) s += String.fromCharCode(...u8.subarray(i, i + 8192));
      window.__pose(btoa(s)).then((r) => this.onmessage && this.onmessage({ data: r }));
    }
    close() { this.readyState = 3; this.onclose && this.onclose({}); }
  }
  window.WebSocket = FakeSocket;
})();
"""


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--photo", required=True, type=Path, help="a clear, front-facing portrait")
    ap.add_argument("--out", type=Path, default=Path("e2e-shots"))
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    import uvicorn
    from playwright.async_api import async_playwright

    from tryon.api.app import create_app
    from tryon.config import load_settings
    from tryon.vision.landmarks import FaceTracker
    from tryon.vision.live import process_frame

    real_ws = importlib.util.find_spec("websockets") or importlib.util.find_spec("wsproto")
    port = free_port()
    app = create_app(load_settings())
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning", ws="auto" if real_ws else "none"))
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.1)
    base_url = f"http://127.0.0.1:{port}"

    clip = args.out / "fake_webcam.y4m"
    write_y4m(args.photo, clip)
    tracker = None if real_ws else FaceTracker()
    bridge_calls = []
    failures: list[str] = []

    def check(ok: bool, what: str) -> None:
        print(("  ok    " if ok else "  FAIL  ") + what)
        if not ok:
            failures.append(what)

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(args=["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
                                                 f"--use-file-for-fake-video-capture={clip}"])
        ctx = await browser.new_context(viewport={"width": 1280, "height": 900}, permissions=["camera"])
        page = await ctx.new_page()
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: errors.append(str(e)))
        if tracker:
            async def pose(b64: str) -> str:
                import json
                bridge_calls.append(time.time())
                return json.dumps(await asyncio.to_thread(process_frame, tracker, base64.b64decode(b64)))
            await page.expose_function("__pose", pose)
            await page.add_init_script(BRIDGE_JS)

        async def canvas_pixels(sel: str):
            data = await page.evaluate(f"""() => {{ const c = document.querySelector('{sel}'); const x = c.getContext('2d');
                const d = x.getImageData(0, 0, c.width, c.height).data; return {{ w: c.width, h: c.height, d: Array.from(d.filter((_, i) => i % 40 < 3)) }}; }}""")
            return np.array(data["d"], np.uint8), data["w"], data["h"]

        async def settled():
            await page.wait_for_function("() => !document.querySelector('#stage').classList.contains('is-busy')", timeout=20000)
            await page.wait_for_timeout(500)

        # 1. the page
        await page.goto(base_url)
        check("TryOn" in await page.title(), f"page title mentions the name ({await page.title()!r})")
        check(await page.inner_text("#stat-count") == "24", "hero says 24 frames")
        await page.screenshot(path=str(args.out / "1_home.png"))

        # 2. upload a photo
        await page.set_input_files("#file", str(args.photo))
        await page.wait_for_selector("#recs .rec", timeout=60000)
        await settled()
        check(not await page.is_disabled('#mode-seg [data-mode="3d"]'), "Real 3D is offered after a photo upload")
        check("shop" not in (await page.inner_text("#recs")).lower(), "no shop links in the results")
        flat, *_ = await canvas_pixels("#stage-canvas")
        await page.locator(".fit").screenshot(path=str(args.out / "2_photo_2d.png"))

        # 3. real 3D on the photo
        await page.click('#mode-seg [data-mode="3d"]')
        await settled()
        threed, *_ = await canvas_pixels("#stage-canvas")
        check(float(np.mean(np.abs(flat.astype(int) - threed.astype(int)))) > 0.3, "the 3D view differs from the 2D view")
        await page.locator(".fit").screenshot(path=str(args.out / "3_photo_3d.png"))

        # 4. another frame, in 3D
        second = page.locator("#recs .rec .rec-main").nth(1)
        await second.click()
        await settled()
        threed2, *_ = await canvas_pixels("#stage-canvas")
        check(float(np.mean(np.abs(threed.astype(int) - threed2.astype(int)))) > 0.2, "choosing another frame changes the 3D picture")
        await page.locator(".fit").screenshot(path=str(args.out / "4_photo_3d_other_frame.png"))

        # 5. sliders
        await page.fill("#ctl-size", "115")
        await page.dispatch_event("#ctl-size", "input")
        await page.fill("#ctl-lift", "-8")
        await page.dispatch_event("#ctl-lift", "input")
        await settled()
        threed3, *_ = await canvas_pixels("#stage-canvas")
        check(float(np.mean(np.abs(threed2.astype(int) - threed3.astype(int)))) > 0.2, "size/height sliders move the 3D glasses")

        # 6. save a picture
        async with page.expect_download() as dl:
            await page.click("#btn-download")
        saved = args.out / "5_saved_3d.jpg"
        await (await dl.value).save_as(str(saved))
        check(saved.stat().st_size > 20000, "the saved 3D picture is a real image")

        # 7. live 3D camera
        if await page.is_visible("#btn-live"):
            bridge_calls.clear()
            await page.click("#btn-live")
            await page.wait_for_function("() => document.querySelector('#live-canvas') && !document.querySelector('#live-canvas').hidden", timeout=15000)
            await page.wait_for_timeout(6000)
            hint = await page.inner_text("#live-hint") if await page.is_visible("#live-hint") else ""
            check(hint == "", f"the live camera is tracking a face (hint: {hint!r})")
            live_a, w, h = await canvas_pixels("#live-canvas")
            await page.wait_for_timeout(700)
            live_b, *_ = await canvas_pixels("#live-canvas")
            check(float(np.std(live_a.astype(float))) > 8, "the live picture is not blank")
            check(float(np.mean(np.abs(live_a.astype(int) - live_b.astype(int)))) > 0.05, "the live picture keeps updating")
            if bridge_calls:
                span = bridge_calls[-1] - bridge_calls[0]
                print(f"        live tracking: {len(bridge_calls) / max(span, 1e-3):.1f} frames/s through the server")
            await page.locator(".fit").screenshot(path=str(args.out / "6_live_3d.png"))
            async with page.expect_download() as dl2:
                await page.click("#btn-download")
            snap = args.out / "7_live_snapshot.jpg"
            await (await dl2.value).save_as(str(snap))
            check(snap.stat().st_size > 15000, "the live snapshot is saved")
            await page.click("#btn-live")                                  # back to the photo
            await page.wait_for_function("() => document.querySelector('#live-canvas').hidden", timeout=5000)
            check(await page.is_visible("#stage-canvas"), "back to the photo from the live camera")
        else:
            print("  info  live camera button not shown (no live tracker on this server)")

        # 8. no photo: no 3D
        await page.click('[data-action="restart"]')
        await page.click('[data-action="pick-shape"]')
        await page.click("#shape-pick-grid button >> nth=0")
        await page.wait_for_selector("#recs .rec", timeout=20000)
        check(not await page.is_visible("#mode-seg"), "3D is not offered in the no-photo (choose a face shape) mode")
        check(not await page.is_visible("#btn-live"), "the live camera is not offered in the no-photo mode")

        check(not errors, f"no console errors {errors[:3] if errors else ''}")
        await browser.close()
    if tracker:
        tracker.close()
    print("\n" + ("ALL GOOD" if not failures else f"{len(failures)} problem(s)"))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
