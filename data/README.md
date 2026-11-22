# data/

Everything the app needs that is not code.

* `models3d/` - the 24 3D sunglasses (`.glb`, metres) and `manifest.json` (names, shapes, colours, sizes).
  Made by `tryon models3d generate`; add your own with `tryon models3d add` (see `docs/ADDING_MODELS.md`).
* `catalog/` - the 2D pictures (`cutouts/`, `thumbs/`) and `catalog.json`, rendered from the 3D models by `tryon build`.
  Safe to delete: `tryon build` makes them again (needs Node.js 18+).
