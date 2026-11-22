# Adding your own 3D sunglasses

TryOn ships with 24 generated frames. You can add real product models (`.glb`, binary glTF 2.0) next to them. They appear
in the results, in the 2D try-on (as a picture rendered from the model) and in Real 3D / Live camera.

```bash
.venv/bin/python -m tryon models3d add my_glasses.glb --sku TO-WAY-04 --name "Wayfarer Sky" --shape wayfarer \
        --audience unisex --color "Sky blue" --color-hex "#5a8fc2" --lens Grey --lens-hex "#444444" --unit mm
.venv/bin/python -m tryon build          # renders the 2D picture (needs Node.js 18+)
```

(On Windows use `.venv\Scripts\python`.) Restart the site afterwards. To change a model you added, run `add` again with the
same `--sku`; to remove one, delete its `.glb` and its entry in `data/models3d/manifest.json`, then run `tryon build`.

| Option | |
|---|---|
| `--sku` | unique code (letters, digits, `-`, `_`); it is also the file name |
| `--name` | the name shown on the site |
| `--shape` | `oval`, `round`, `rectangle`, `square`, `wayfarer`, `cat-eye`, `aviator` or `geometric` (decides which faces it is recommended for) |
| `--audience` | `men`, `women`, `kids` or `unisex` |
| `--color`, `--color-hex` | frame colour name and hex (used for the colour filter and labels) |
| `--lens`, `--lens-hex` | lens colour name and hex |
| `--unit` | the unit the file was modelled in: `m` (default), `cm` or `mm` |
| `--no-center` | keep the model's own origin instead of moving it to the bridge (see below) |

## What a good model looks like

* **A pair of sunglasses, open, in one piece**, with the two temple arms. A single `.glb` with the frame and lenses.
* **Real size.** A frame is normally 125–150 mm wide. The importer checks this and tells you to try `--unit mm` or `--unit cm`
  if the width looks wrong. Sizes matter: they decide how big the glasses look on the face.
* **Facing:** the front should face `+z` and the arms run backwards. If the model is backwards, the importer notices (the front
  of a pair of glasses is tall, the end of the arms is thin) and turns it around.
* **Origin:** with the default `auto-center` the importer moves the middle of the front of the frame to the origin, at the
  height of the middle of the frame (about the pupils) and puts the front of the frame slightly in front of the lens plane.
  If your model already follows the project's convention (below), use `--no-center`.
* **Lenses should be a separate material with transparency** (`alphaMode: BLEND` and an alpha below 1 in the base colour).
  Lenses without transparency look like black plastic.
* **Textures are ignored.** Only each material's base colour, metallic and roughness *factors* are used, and a material
  that relies on a texture usually has a white factor, so it would look white. Give every material a real base colour, or split the
  model into several plain-coloured materials.
* **Not supported:** Draco or meshopt compression (export without compression), animations, cameras, skins.
* **Keep it light:** the renderer is software-based. 10–30 thousand triangles is plenty; over 100 thousand will slow the
  live camera down.

## The project's convention

Every model in `data/models3d/` follows this, and the importer puts yours into it by adding a root node:

* units: **metres**
* origin: the middle of the bridge, at pupil height, on the lens plane
* `+x` to the wearer's left, `+y` up, `+z` forward (out of the face); the temples run towards `-z`

## If it does not look right

| What you see | Try |
|---|---|
| Glasses far too big or tiny | `--unit mm` or `--unit cm` |
| Glasses sit too high or too low | the model's origin is off; add `--no-center` only if it is already right, otherwise re-run without it |
| The arms point at the camera | the facing could not be detected; rotate the model by 180° about the vertical axis in your 3D tool and import again |
| Lenses opaque | give the lens material alpha blending; see above |
| `tryon build` says Node.js is needed | install Node 18+ from <https://nodejs.org> |

Check the result on a face with `tools/export_pose.py` and `tools/compose_photo.mjs` (see `docs/TUNING.md`), or just upload a
photo to the site and choose *Real 3D*.
