"""The 24 built-in 3D frames and the importer for your own."""
import json

import numpy as np
import pytest

from tryon.config import load_settings
from tryon.models3d.generator import MODELS, build_model
from tryon.models3d.glb import GlbError, model_bounds, pack_glb, read_accessor, read_glb
from tryon.models3d.importer import ImportError_, import_model, world_points


def manifest():
    s = load_settings()
    return s, json.loads(s.manifest_json.read_text())["models"]


def test_the_catalogue_is_exactly_three_models_per_style():
    assert len(MODELS) == 24
    shapes = [m["shape"] for m in MODELS]
    assert {s: shapes.count(s) for s in set(shapes)} == {s: 3 for s in
            ("oval", "round", "rectangle", "square", "wayfarer", "cat-eye", "aviator", "geometric")}


def test_every_model_file_is_a_valid_glb_in_the_project_convention():
    s, models = manifest()
    for m in models:
        path = s.models_dir / m["file"]
        doc, binary = read_glb(path)
        assert doc["asset"]["version"] == "2.0" and len(binary) > 0
        lo, hi = model_bounds(path)
        mm = (hi - lo) * 1000
        assert abs(mm[0] - m["frame_width_mm"]) < 1.5, m["sku"]                    # the manifest tells the truth
        assert abs((lo[0] + hi[0]) * 1000) < 1.5, f"{m['sku']} is not centred on the bridge"
        assert hi[2] > 0.0 > lo[2] and mm[2] > 120, m["sku"]                      # front on +z, temples go back towards -z
        assert lo[1] < 0 < hi[1], m["sku"]                                         # the origin is at lens height
        for mesh in doc["meshes"]:
            for prim in mesh["primitives"]:
                pos = read_accessor(doc, binary, prim["attributes"]["POSITION"])
                nrm = read_accessor(doc, binary, prim["attributes"]["NORMAL"])
                assert np.isfinite(pos).all() and np.abs(np.linalg.norm(nrm, axis=1) - 1).max() < 0.02, m["sku"]
        assert 3_000 < m["triangles"] < 60_000 and m["bytes"] < 2_000_000, m["sku"]   # light enough for a CPU renderer


def test_lenses_are_see_through_and_frames_opaque():
    s, models = manifest()
    for m in models:
        doc, _ = read_glb(s.models_dir / m["file"])
        modes = {mat.get("alphaMode", "OPAQUE") for mat in doc["materials"]}
        assert "BLEND" in modes and "OPAQUE" in modes, m["sku"]


def test_generation_is_deterministic():
    spec = MODELS[0]
    a, b = build_model(spec, n=48), build_model(spec, n=48)
    for part in ("frame", "lens"):
        assert len(a[part].v) > 100 and np.array_equal(a[part].v, b[part].v) and np.array_equal(a[part].f, b[part].f)


def test_unreadable_files_are_reported(tmp_path):
    bad = tmp_path / "bad.glb"
    bad.write_bytes(b"not a glb")
    with pytest.raises(GlbError):
        read_glb(bad)


# ── importing your own model ───────────────────────────────────────────────
def _messy_copy(tmp_path, unit_scale=1000.0, turn=True):
    """A built-in frame re-exported the way another program might: millimetres, facing -z, origin somewhere else."""
    s, models = manifest()
    doc, binary = read_glb(s.models_dir / models[0]["file"])
    c, sn = (-1.0, 0.0) if turn else (1.0, 0.0)
    M = np.array([[c * unit_scale, 0, sn, 30.0], [0, unit_scale, 0, -12.0], [-sn, 0, c * unit_scale, 55.0], [0, 0, 0, 1]])
    doc["nodes"].append({"name": "Foreign", "matrix": [float(x) for x in M.T.reshape(-1)], "children": list(doc["scenes"][0]["nodes"])})
    doc["scenes"][0]["nodes"] = [len(doc["nodes"]) - 1]
    f = tmp_path / "foreign.glb"
    pack_glb(f, doc, binary)
    return f, models[0]


def test_import_puts_a_foreign_model_in_the_project_convention(tmp_path):
    s = load_settings()
    work = type(s)(**{**s.__dict__, "models_dir": tmp_path / "models"})
    f, original = _messy_copy(tmp_path)
    rec = import_model(work, f, sku="my-01", name="My frame", frame_shape="wayfarer", unit="mm")
    assert rec["sku"] == "MY-01" and abs(rec["frame_width_mm"] - original["frame_width_mm"]) < 2
    doc, binary = read_glb(work.models_dir / "MY-01.glb")
    pts = world_points(doc, binary)                                              # metres, project convention
    lo, hi = pts.min(0), pts.max(0)
    assert abs(lo[0] + hi[0]) < 0.002                                            # centred
    assert 0.002 < hi[2] < 0.006 and lo[2] < -0.12                               # front on +z, temples back
    saved = json.loads((work.models_dir / "manifest.json").read_text())["models"]
    assert [m["sku"] for m in saved] == ["MY-01"]
    import_model(work, f, sku="MY-01", name="Renamed", frame_shape="wayfarer", unit="mm")   # same SKU: replaced, not duplicated
    assert [m["name"] for m in json.loads((work.models_dir / "manifest.json").read_text())["models"]] == ["Renamed"]


def test_import_catches_the_wrong_unit_and_bad_input(tmp_path):
    s = load_settings()
    work = type(s)(**{**s.__dict__, "models_dir": tmp_path / "models"})
    f, _ = _messy_copy(tmp_path)
    with pytest.raises(ImportError_, match="--unit"):
        import_model(work, f, sku="X1", name="x", frame_shape="oval", unit="m")           # it is in mm, not metres
    with pytest.raises(ImportError_, match="shape"):
        import_model(work, f, sku="X1", name="x", frame_shape="triangle", unit="mm")
    with pytest.raises(ImportError_, match="SKU"):
        import_model(work, f, sku="bad sku!", name="x", frame_shape="oval", unit="mm")
    (tmp_path / "junk.glb").write_bytes(b"junk")
    with pytest.raises(ImportError_):
        import_model(work, tmp_path / "junk.glb", sku="X2", name="x", frame_shape="oval")
