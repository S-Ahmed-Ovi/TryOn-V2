"""Loading the catalogue at start-up (and building it first when the 3D models changed)."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from tryon.catalog.builder import BuildError, build_catalog, is_current, read_catalog_json, read_manifest
from tryon.config import Settings


class CatalogError(RuntimeError):
    pass


@dataclass(frozen=True)
class Product:
    sku: str
    name: str
    frame_shape: str
    audience: str            # men | women | kids | unisex
    material: str            # acetate | metal | ...
    color_name: str          # frame colour
    color_hex: str
    lens_name: str
    lens_hex: str
    aspect: float            # width / height of the 2D cut-out
    scale: float             # cut-out width relative to a typical face width (keeps real frame sizes apart on the 2D stage)
    anchor_x: float          # where the glasses sit on the eyes (fractions of the cut-out)
    anchor_y: float
    cutout: str              # media path of the 2D picture
    thumb: str
    model: str               # file name of the 3D model in data/models3d/
    size_mm: tuple[tuple[str, float], ...] = ()

    @property
    def size(self) -> dict[str, float]:
        return dict(self.size_mm)


@dataclass(frozen=True)
class Catalog:
    products: tuple[Product, ...]
    built_at: str
    version: str             # changes whenever the catalogue is rebuilt (used to refresh browser caches)

    def by_sku(self, sku: str) -> Product | None:
        return next((p for p in self.products if p.sku == sku.upper()), None)


def _parse(raw: dict) -> Catalog:
    items = tuple(
        Product(r["sku"], r["name"], r["frame_shape"], r["audience"], r.get("material", ""),
                r["color"]["name"], r["color"]["hex"], r["lens"]["name"], r["lens"]["hex"],
                r["aspect"], r.get("scale", 1.0), r["anchor"]["x"], r["anchor"]["y"], r["cutout"], r["thumb"], r["model"],
                tuple(sorted((r.get("size") or {}).items())))
        for r in raw["products"]
    )
    return Catalog(items, raw.get("built_at", ""), (raw.get("fingerprint") or "x")[:8])


def load_catalog(settings: Settings) -> Catalog:
    raw = read_catalog_json(settings.catalog_json)
    if not raw:
        raise CatalogError("The catalogue has not been built yet. Run:  tryon build")
    return _parse(raw)


def ensure_catalog(settings: Settings, log: Callable[[str], None] = print) -> Catalog:
    """Use the saved catalogue; rebuild it first when the 3D models changed (needs Node.js) and fall back to the saved one."""
    try:
        if not is_current(settings, read_manifest(settings)):
            build_catalog(settings, log=log)
    except (BuildError, OSError) as exc:
        if not settings.catalog_json.is_file():
            raise CatalogError(str(exc)) from exc
        log(f"Note: the catalogue is not up to date with the 3D models ({exc}). Using the saved one.")
    return load_catalog(settings)
