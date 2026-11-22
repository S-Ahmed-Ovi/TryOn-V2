"""Add your own .glb sunglasses to the catalogue:   tryon models3d add my.glb --sku X --name "..." --shape wayfarer

The model's original data is kept as it is. A new root node with the right scale / rotation / offset is put on top, so
the file ends up in the project's convention (see docs/ADDING_MODELS.md):

    metres, origin at the middle of the bridge at pupil height on the lens plane, +x to the wearer's left, +y up, +z forward.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from tryon.config import Settings
from tryon.models3d.glb import GlbError, pack_glb, read_accessor, read_glb

UNITS = {"m": 1.0, "cm": 0.01, "mm": 0.001}
FRAME_SHAPES = ("oval", "round", "rectangle", "square", "wayfarer", "cat-eye", "aviator", "geometric")
FRONT_OFFSET_M = 0.004          # the front of the frame sits this far in front of the lens plane


class ImportError_(ValueError):
    pass


def _local(node: dict) -> np.ndarray:
    """Column-vector 4x4 matrix of a glTF node."""
    if "matrix" in node:
        return np.array(node["matrix"], float).reshape(4, 4).T
    x, y, z, w = node.get("rotation", [0, 0, 0, 1])
    sx, sy, sz = node.get("scale", [1, 1, 1])
    R = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    M = np.eye(4)
    M[:3, :3] = R * [sx, sy, sz]
    M[:3, 3] = node.get("translation", [0, 0, 0])
    return M


def world_points(doc: dict, binary: bytes) -> np.ndarray:
    """Every vertex of the scene in model space (node transforms applied)."""
    pts: list[np.ndarray] = []

    def visit(i: int, parent: np.ndarray) -> None:
        node = doc["nodes"][i]
        world = parent @ _local(node)
        if "mesh" in node:
            for prim in doc["meshes"][node["mesh"]]["primitives"]:
                p = read_accessor(doc, binary, prim["attributes"]["POSITION"]).astype(float)
                pts.append(p @ world[:3, :3].T + world[:3, 3])
        for c in node.get("children", []):
            visit(c, world)

    scene = doc["scenes"][doc.get("scene", 0)] if doc.get("scenes") else {"nodes": list(range(len(doc.get("nodes", []))))}
    for n in scene["nodes"]:
        visit(n, np.eye(4))
    if not pts:
        raise ImportError_("The model has no meshes.")
    return np.concatenate(pts)


def import_model(settings: Settings, file: str | Path, *, sku: str, name: str, frame_shape: str, audience: str = "unisex",
                 color_name: str = "Black", color_hex: str = "#1a1a1a", lens_name: str = "Grey", lens_hex: str = "#444444",
                 unit: str = "m", auto_center: bool = True) -> dict:
    sku = sku.strip().upper()
    if not sku.replace("-", "").replace("_", "").isalnum():
        raise ImportError_("The SKU may only contain letters, digits, - and _.")
    if frame_shape not in FRAME_SHAPES:
        raise ImportError_(f"--shape must be one of: {', '.join(FRAME_SHAPES)}")
    try:
        doc, binary = read_glb(file)
    except (GlbError, OSError, ValueError) as exc:
        raise ImportError_(f"Cannot read {file}: {exc}") from exc
    if any("draco" in e.lower() or "meshopt" in e.lower() for e in doc.get("extensionsRequired", [])):
        raise ImportError_("Compressed (Draco / meshopt) models are not supported. Export the model without compression.")
    pts = world_points(doc, binary) * UNITS[unit]

    # facing: the front of a pair of glasses is tall (rims), the far end is just thin temple tips
    zmin, zmax = pts[:, 2].min(), pts[:, 2].max()
    span = max(zmax - zmin, 1e-9)
    height_at = lambda sel: float(np.ptp(pts[sel, 1])) if sel.any() else 0.0   # noqa: E731
    top_end, low_end = height_at(pts[:, 2] > zmax - 0.1 * span), height_at(pts[:, 2] < zmin + 0.1 * span)
    flip = low_end > top_end
    R = np.diag([-1.0, 1.0, -1.0]) if flip else np.eye(3)         # a half-turn about the vertical axis
    pts = pts @ R.T
    zmax = pts[:, 2].max()
    front = pts[pts[:, 2] > zmax - 0.15 * span]
    width_mm = float(np.ptp(front[:, 0]) * 1000)
    if not 100 <= width_mm <= 180:
        raise ImportError_(f"The frame is {width_mm:.0f} mm wide after reading the file as '{unit}'. Real sunglasses are 120-160 mm. "
                           "Try --unit mm or --unit cm (or the other way round).")
    shift = np.zeros(3)
    if auto_center:
        shift = np.array([-(front[:, 0].min() + front[:, 0].max()) / 2, -(front[:, 1].min() + front[:, 1].max()) / 2, FRONT_OFFSET_M - zmax])

    # root node: scale -> rotate -> move, put on top of the original scene
    M = np.eye(4)
    M[:3, :3] = R * UNITS[unit]
    M[:3, 3] = shift
    doc = json.loads(json.dumps(doc))
    scene = doc["scenes"][doc.get("scene", 0)]
    doc["nodes"].append({"name": "TryOnRoot", "matrix": [float(x) for x in M.T.reshape(-1)], "children": list(scene["nodes"])})
    scene["nodes"] = [len(doc["nodes"]) - 1]
    doc.setdefault("asset", {}).setdefault("extras", {})["tryon"] = {"sku": sku, "unit": "m", "imported": True}

    settings.models_dir.mkdir(parents=True, exist_ok=True)
    out = settings.models_dir / f"{sku}.glb"
    size = pack_glb(out, doc, binary)

    moved = pts + shift
    lo, hi = moved.min(0), moved.max(0)
    mm = lambda v: round(float(v) * 1000, 1)       # noqa: E731
    f = moved[moved[:, 2] > hi[2] - 0.15 * span]
    rec = {
        "sku": sku, "name": name, "frame_shape": frame_shape, "audience": audience, "style": "imported", "file": out.name,
        "color": {"name": color_name, "hex": color_hex}, "lens": {"name": lens_name, "hex": lens_hex, "mirror": False},
        "frame_width_mm": mm(np.ptp(f[:, 0])), "lens_width_mm": mm(np.ptp(f[:, 0]) * 0.38), "lens_height_mm": mm(np.ptp(f[:, 1]) * 0.8),
        "bridge_mm": 18.0, "temple_mm": mm(hi[2] - lo[2]),
        "triangles": int(sum(len(read_accessor(doc, binary, p["indices"])) // 3 for m in doc["meshes"] for p in m["primitives"] if "indices" in p)),
        "bytes": size, "bounds_mm": {"min": [mm(x) for x in lo], "max": [mm(x) for x in hi]},
    }
    manifest_path = settings.manifest_json
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {"version": 1, "unit": "m", "models": []}
    manifest["models"] = [m for m in manifest["models"] if m["sku"] != sku] + [rec]
    manifest_path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    return rec
