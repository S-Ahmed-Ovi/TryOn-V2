"""The 2D catalogue is built from the 3D models: manifest -> renders -> cut-outs, thumbnails and catalog.json."""
import json
import shutil
from pathlib import Path

import pytest
from PIL import Image

from tryon.catalog import builder
from tryon.catalog.builder import BuildError, build_catalog, fingerprint, is_current, read_manifest, trim
from tryon.catalog.store import CatalogError, ensure_catalog, load_catalog
from tryon.config import load_settings

SHAPES = {"oval", "round", "rectangle", "square", "wayfarer", "cat-eye", "aviator", "geometric"}


def test_shipped_catalogue_has_three_frames_of_every_shape(catalog):
    assert len(catalog.products) == 24
    by_shape = {}
    for p in catalog.products:
        by_shape.setdefault(p.frame_shape, []).append(p)
    assert set(by_shape) == SHAPES
    assert all(len(v) == 3 for v in by_shape.values())
    assert len({p.sku for p in catalog.products}) == 24
    assert len({p.color_name for p in by_shape["wayfarer"]}) == 3          # the three frames of a style differ


def test_every_catalogue_entry_has_its_pictures_and_model():
    s = load_settings()
    cat = load_catalog(s)
    for p in cat.products:
        assert (s.catalog_dir / p.cutout).is_file() and (s.catalog_dir / p.thumb).is_file(), p.sku
        assert (s.models_dir / p.model).is_file(), p.sku
        assert 1.8 < p.aspect < 3.6 and 0.6 < p.scale < 1.3 and 0 < p.anchor_x < 1 and 0 < p.anchor_y < 1, p.sku
        with Image.open(s.catalog_dir / p.cutout) as im:
            assert im.mode == "RGBA" and im.getchannel("A").getextrema()[1] == 255
            assert abs(im.width / im.height - p.aspect) < 0.01


def test_the_shipped_catalogue_matches_the_models():
    s = load_settings()
    assert is_current(s, read_manifest(s)), "models changed: run `tryon build`"


def test_frames_have_realistic_real_world_sizes(catalog):
    for p in catalog.products:
        w = p.size["frame_width_mm"]
        assert 115 <= w <= 150, p.sku
        assert 40 <= p.size["lens_width_mm"] <= 62 and 130 <= p.size["temple_mm"] <= 155, p.sku
    wide = max(catalog.products, key=lambda p: p.scale)
    narrow = min(catalog.products, key=lambda p: p.scale)
    assert wide.scale > narrow.scale * 1.05                                # frame widths really differ on the 2D stage


def test_trim_crops_to_the_visible_glasses():
    img = Image.new("RGBA", (200, 100), (0, 0, 0, 0))
    img.paste((10, 10, 10, 255), (60, 30, 140, 70))
    crop, box = trim(img)
    assert box == (57, 27, 143, 73) and crop.size == (86, 46)
    with pytest.raises(BuildError):
        trim(Image.new("RGBA", (10, 10), (0, 0, 0, 0)))


def test_fingerprint_changes_with_the_models(tmp_path):
    s = load_settings()
    work = type(s)(**{**s.__dict__, "models_dir": tmp_path / "m", "catalog_dir": tmp_path / "c"})
    shutil.copytree(s.models_dir, work.models_dir)
    manifest = read_manifest(work)
    before = fingerprint(work, manifest)
    first = work.models_dir / manifest["models"][0]["file"]
    first.write_bytes(first.read_bytes() + b"\0\0\0\0")
    assert fingerprint(work, manifest) != before


def test_missing_manifest_gives_a_clear_message(tmp_path):
    s = load_settings()
    work = type(s)(**{**s.__dict__, "models_dir": tmp_path / "none", "catalog_dir": tmp_path / "c"})
    with pytest.raises(BuildError, match="tryon models3d generate"):
        read_manifest(work)
    with pytest.raises(CatalogError):
        ensure_catalog(work, log=lambda *_: None)


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js is needed to render the 2D pictures")
def test_full_build_from_scratch_is_reproducible(tmp_path):
    s = load_settings()
    work = type(s)(**{**s.__dict__, "catalog_dir": tmp_path / "catalog"})
    cat = build_catalog(work, log=lambda *_: None)
    assert len(cat["products"]) == 24 and is_current(work, read_manifest(work))
    shipped = json.loads(s.catalog_json.read_text())
    assert [p["sku"] for p in cat["products"]] == [p["sku"] for p in shipped["products"]]
    assert cat["fingerprint"] == shipped["fingerprint"]
    for a, b in zip(cat["products"], shipped["products"]):                  # same pixels -> same numbers
        assert abs(a["aspect"] - b["aspect"]) < 0.01 and abs(a["scale"] - b["scale"]) < 0.01, a["sku"]
    assert build_catalog(work, log=lambda *_: None)["built_at"] == cat["built_at"]      # nothing changed -> nothing redone
