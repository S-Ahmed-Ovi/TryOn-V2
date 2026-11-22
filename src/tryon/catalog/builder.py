"""Build the 2D catalogue from the 3D models.

    tryon build            # only does work when a model or the builder changed
    tryon build --force    # redo everything

Every sunglasses model in data/models3d/ is rendered from the front with the project's own CPU renderer
(tools/render_models.mjs, run with Node). Each picture is then trimmed and written as

    data/catalog/cutouts/<SKU>.webp     transparent cut-out used by the 2D try-on
    data/catalog/thumbs/<SKU>.webp      small version for cards
    data/catalog/catalog.json           one record per model

so the 2D and the 3D try-on always show exactly the same frame. The app only needs catalog.json to start; Node is
only needed when a model is added or changed.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

from tryon.config import Settings

BUILDER_VERSION = 1
FACE_REF_CM = 14.4          # a "typical" cheek-to-cheek face width; a frame as wide as this fills the face width on the 2D stage
THUMB_WIDTH = 360
ALPHA_EDGE = 6              # alpha above this counts as part of the glasses when trimming
PAD_PX = 3
Log = Callable[[str], None]


class BuildError(RuntimeError):
    pass


# ----------------------------------------------------------------------------- files
def read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def read_catalog_json(path: Path) -> dict | None:
    return read_json(path)


def read_manifest(settings: Settings) -> dict:
    manifest = read_json(settings.manifest_json)
    if not manifest or not manifest.get("models"):
        raise BuildError(f"No 3D models found. Expected {settings.manifest_json}.  Create them with:  tryon models3d generate")
    return manifest


def fingerprint(settings: Settings, manifest: dict) -> str:
    """Changes when a model file, the manifest or the builder changes."""
    h = hashlib.sha1(f"builder:{BUILDER_VERSION}:{FACE_REF_CM}".encode())
    h.update(json.dumps(manifest, sort_keys=True).encode())
    for m in manifest["models"]:
        f = settings.models_dir / m["file"]
        h.update(f.read_bytes() if f.is_file() else b"missing")
    return h.hexdigest()


def is_current(settings: Settings, manifest: dict) -> bool:
    raw = read_catalog_json(settings.catalog_json)
    if not raw or raw.get("fingerprint") != fingerprint(settings, manifest):
        return False
    return all((settings.catalog_dir / r[k]).is_file() for r in raw["products"] for k in ("cutout", "thumb"))


# ----------------------------------------------------------------------------- rendering
def _node_command(settings: Settings) -> list[str]:
    node = shutil.which("node") or shutil.which("nodejs")
    tool = settings.home / "tools" / "render_models.mjs"
    if not node:
        raise BuildError("Node.js 18+ is needed to render the 2D pictures of the 3D models (only when models change). "
                         "Install it from https://nodejs.org, or keep using the catalogue that ships with the project.")
    if not tool.is_file():
        raise BuildError(f"Missing {tool}. Run this from the project folder (or set TRYON_HOME).")
    return [node, str(tool)]


def render_cutouts(settings: Settings, out_dir: Path, log: Log) -> dict:
    """Runs tools/render_models.mjs and returns its cutouts.json (canvas size, pupil line)."""
    cmd = _node_command(settings) + ["cutouts", str(out_dir)]
    log("Rendering the 3D models to 2D pictures (CPU)...")
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(settings.home))
    if proc.returncode != 0:
        raise BuildError(f"Rendering failed:\n{proc.stderr.strip() or proc.stdout.strip()}")
    info = read_json(out_dir / "cutouts.json")
    if not info:
        raise BuildError("The renderer did not write cutouts.json.")
    return info


# ----------------------------------------------------------------------------- trimming
def trim(img: Image.Image) -> tuple[Image.Image, tuple[int, int, int, int]]:
    """Crop to the visible glasses (plus a few pixels). Returns the crop and its box in the original picture."""
    alpha = np.asarray(img.getchannel("A"))
    ys, xs = np.where(alpha > ALPHA_EDGE)
    if not len(xs):
        raise BuildError("A rendered model is empty.")
    x0, x1 = max(int(xs.min()) - PAD_PX, 0), min(int(xs.max()) + 1 + PAD_PX, img.width)
    y0, y1 = max(int(ys.min()) - PAD_PX, 0), min(int(ys.max()) + 1 + PAD_PX, img.height)
    return img.crop((x0, y0, x1, y1)), (x0, y0, x1, y1)


def build_catalog(settings: Settings, *, force: bool = False, log: Log = print) -> dict:
    manifest = read_manifest(settings)
    if not force and is_current(settings, manifest):
        return read_catalog_json(settings.catalog_json) or {}
    fp = fingerprint(settings, manifest)

    cut_dir, thumb_dir = settings.catalog_dir / "cutouts", settings.catalog_dir / "thumbs"
    with tempfile.TemporaryDirectory(prefix="tryon-render-") as tmp:
        info = render_cutouts(settings, Path(tmp), log)
        px_per_cm = float(info["px_per_cm"])
        for d in (cut_dir, thumb_dir):
            if d.exists():
                shutil.rmtree(d)
            d.mkdir(parents=True, exist_ok=True)

        products = []
        for m in manifest["models"]:
            sku = m["sku"]
            src = Path(tmp) / f"{sku}.png"
            if not src.is_file():
                raise BuildError(f"The renderer produced no picture for {sku}.")
            img = Image.open(src).convert("RGBA")
            cw, ch = img.size
            crop, (x0, y0, x1, y1) = trim(img)
            w, h = crop.size
            crop.save(cut_dir / f"{sku}.webp", "WEBP", quality=92, alpha_quality=100, method=5)
            th = crop.resize((THUMB_WIDTH, max(1, round(THUMB_WIDTH * h / w))), Image.LANCZOS)
            th.save(thumb_dir / f"{sku}.webp", "WEBP", quality=88, alpha_quality=100, method=5)
            products.append({
                "sku": sku, "name": m["name"], "frame_shape": m["frame_shape"], "audience": m["audience"],
                "material": m.get("style", ""),
                "color": m["color"], "lens": m["lens"],
                "size": {k: m[k] for k in ("frame_width_mm", "lens_width_mm", "lens_height_mm", "bridge_mm", "temple_mm") if k in m},
                "aspect": round(w / h, 4),
                "scale": round(w / px_per_cm / FACE_REF_CM, 4),         # frame width relative to a typical face width
                "anchor": {"x": round((cw / 2 - x0) / w, 4), "y": round((info["items"][sku]["pupil_y"] - y0) / h, 4)},
                "cutout": f"cutouts/{sku}.webp", "thumb": f"thumbs/{sku}.webp",
                "model": m["file"],
            })

    catalog = {"version": 1, "builder_version": BUILDER_VERSION, "fingerprint": fp, "face_ref_cm": FACE_REF_CM,
               "built_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "products": products}
    settings.catalog_dir.mkdir(parents=True, exist_ok=True)
    settings.catalog_json.write_text(json.dumps(catalog, indent=1), encoding="utf-8")
    log(f"Catalogue built: {len(products)} frames.")
    return catalog
