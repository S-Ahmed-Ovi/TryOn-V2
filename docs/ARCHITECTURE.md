# Architecture

## Request flow

```
Browser                               Server (FastAPI)
───────                               ────────────────
choose / capture photo
resize to ≤1280 px, upright JPEG
POST /api/analyze  ───────────────►   decode (never saved)
                                      vision.landmarks     478 face points + facial transformation matrix
                                      vision.face_shape    measurements → shape probabilities, photo checks
                                      vision.placement     eye centre, tilt, face width (fractions of the photo)
                                      vision.pose3d        3D head pose for the real 3D try-on
                                      recommend.engine     score + rank every frame
                                      recommend.explain    reasons, face-proportion gauges
                      ◄───────────    { face, placement, pose3d, recommendations }
draw photo + glasses on a canvas      (2D: the frame's picture;  Real 3D: the .glb drawn with pose3d)
change shape / filter:
POST /api/recommend ──────────────►   re-rank (no photo needed)

Live camera (only after a photo flow, never in the "pick a face shape" mode):
camera frame → 4-byte number + JPEG ─► WebSocket /api/track:  tracker.process → pose3d → JSON pose
draw glasses on that same frame   ◄── { seq, ok, pose: { matrix, fov_y, aspect, yaw, pitch, roll, usable } }
```

The browser keeps the photo; the server is stateless apart from the live tracker of each open camera connection.
Changing frames, size or position never calls the server.

## Packages

| Package | Responsibility | Depends on |
|---|---|---|
| `tryon.config` | paths and settings (`.env`) | – |
| `tryon.models3d` | build the 24 `.glb` frames (`generator`), read / write GLB (`glb`), import your own models (`importer`) | NumPy |
| `tryon.vision` | landmarks, face shape, 2D placement, 3D head pose, one live frame | MediaPipe, OpenCV |
| `tryon.catalog` | render the 3D models to 2D pictures (`builder`), load the catalogue at start-up (`store`) | Pillow, Node (build only) |
| `tryon.recommend` | rules, scoring, explanations | `vision.SHAPES`, `catalog.Product` |
| `tryon.api` | HTTP + WebSocket layer and JSON shaping | everything above |
| `tryon.web` | static page (no build step), the CPU 3D renderer | – |

Dependencies point one way: `api → recommend → catalog / vision`. `vision` and `catalog` do not import each other.

## The 3D models

`models3d/generator.py` builds each frame as triangle meshes with NumPy (front, rims, bridge, temples, hinges, lenses) and
writes a standard binary glTF (`data/models3d/<SKU>.glb`) plus `manifest.json`. Convention for every model, including
the ones you add:

* units: **metres**
* origin: the middle of the bridge, at pupil height, on the lens plane
* `+x` to the wearer's left, `+y` up, `+z` forward (out of the face); the temples run towards `-z`
* two meshes: `frame` (rims, bridge, pads, hinges, temples; opaque) and `lenses` (transparent, double-sided)

## Catalogue build (3D → 2D)

`catalog.builder.build_catalog` is idempotent. It computes a **fingerprint** of every `.glb`, the manifest and the builder
version; if it matches `data/catalog/catalog.json` nothing is done. `ensure_catalog` runs it at start-up. If a rebuild
fails (for example Node is not installed) the last good catalogue is used.

When something changed it runs `tools/render_models.mjs cutouts <dir>` with Node. That script uses the same renderer the
browser uses (`web/static/js/soft3d/engine.js`) to draw each model from the front on a transparent canvas, with the
camera, lighting and anti-aliasing fixed. Python then trims each picture to the visible glasses and writes:

```
data/catalog/cutouts/<SKU>.webp    transparent picture used by the 2D try-on
data/catalog/thumbs/<SKU>.webp     small version for cards
data/catalog/catalog.json          one record per frame: name, shape, colour, aspect, scale, anchor, size in mm ...
```

* `aspect` = width ÷ height of the trimmed picture.
* `scale` = the frame's real width ÷ a typical face width (`FACE_REF_CM = 14.4`). The 2D stage multiplies the face width by
  this, so a small frame looks small and a large one large.
* `anchor` = where the pupil line crosses the picture (fractions of its width and height). The 2D stage puts this point
  on the middle of the eyes.

## The CPU renderer

`web/static/js/soft3d/` is a small software rasteriser written in plain JavaScript. It runs in the browser and in Node,
needs no WebGL and no GPU, and is the single source of truth for both the 3D view and the 2D pictures.

* **Pipeline.** Vertices are transformed once per frame, triangles are rasterised into a z-buffer (depth), opaque parts first;
  see-through lens triangles are then drawn from far to near and alpha-blended over the result.
* **Shading.** Phong plus a Fresnel term and a procedural studio-like environment for reflections, so lenses and
  metal look right without any texture or environment file.
* **Hidden head.** A depth-only ellipsoid stands in for the head. It writes depth but no colour, so a temple arm that goes
  behind the cheek or ear disappears behind the face instead of floating in front of it.
* **Anti-aliasing.** Supersampling (2×2). While the user drags a slider the page draws at 1×, then at 2× after about 180 ms
  of calm; the live camera drops to 1× if a frame takes too long.
* **Cost.** Photo-size layers take roughly 50-90 ms; the live view runs at 12-15 fps on a normal laptop CPU.

## 3D head pose

MediaPipe's Face Landmarker fits a metric "canonical" head to the 478 landmarks and returns a 4×4 *facial transformation
matrix* that moves that head into the camera's space (centimetres, OpenGL convention: camera looks down `-z`, `+y` up,
`+x` image right) for a virtual pinhole camera with a **63° vertical field of view**.

`vision/pose3d.py` turns it into a JSON object: `matrix` (16 numbers, row-major), `fov_y`, `aspect`, `yaw`, `pitch`, `roll`
(degrees; yaw > 0 turns the face towards image-right, pitch > 0 looks up) and `usable` (false when the head is turned
more than 55° / 40° / 45° in yaw / pitch / roll, because glasses cannot be placed convincingly then). In `/api/analyze` it is
returned as `pose3d`; when it is `null` or unusable, the 3D switch is greyed out and only the 2D try-on is offered.

In the browser `tryon3d.js` rebuilds the same virtual camera from the image size (`cameraFor`), places the model with
`headPlacement`, and calls the renderer with `renderGlasses`.

### 3D calibration

The canonical head is about **1.15×** a real head. The constants in `tryon3d.js` (`HEAD`) were fitted on real portraits:

| Constant | Value | Meaning |
|---|---|---|
| `scale` | `1.15` | canonical cm per real cm; a real 14 cm frame is drawn 1.15× bigger |
| `anchor` | `[0, 3.1, 1.9]` | where the model's origin (bridge centre, pupil height) goes, in canonical cm |
| `tilt` | `4°` | pantoscopic tilt: the bottom of the lenses is closer to the cheeks |
| `occluder` | centre `[0, 1.5, -9.8]`, radii `[8.4, 12.5, 10.5]` | the hidden-head ellipsoid |

Sliders: **Size** multiplies the frame (0.8–1.25), **Height** moves it up/down and the 2D *shift* moves it sideways, both in
real centimetres (`lift_cm = -(lift + offset.y) × 14.4`, `shift_cm = offset.x × 14.4`).

Exposure of the glasses is matched to the photo: the brightness of the face area (`exposureFor`) darkens or lightens the
shading so the glasses are not brighter than the person.

## Live camera

```
browser                                       server
getUserMedia ─ frame (640 px, mirrored)
   │ 320 px copy → JPEG → [4-byte seq][JPEG] ──► /api/track  (one FaceTracker per connection, VIDEO mode)
   │                                             ◄── { seq, ok, pose } as JSON
   └ the SAME frame is drawn with the glasses (so they never lag behind the face), pose smoothed with a One-Euro filter
```

* At most ~15 frames per second are sent; the next frame is already travelling while the current one is drawn.
* `TRYON_MAX_LIVE` (default 4) limits simultaneous cameras; extra people get a friendly "busy" message (WebSocket close
  code 1013) and can use a photo instead.
* A connection that sends nothing for 90 seconds is closed. Nothing is stored.
* Needs a secure page (`https` or `localhost`) because browsers only give the camera to those.

## Scoring

```
shape_score  = Σ P(face shape) × rules.face_shapes[face].frames[frame shape]
proportion   = exp(-½ (ln(aspect / (3.5 / L)) / 0.22)²)         L = face length ÷ cheek width
match %      = round(98 × (0.85 × shape_score + 0.15 × proportion))     (never above 98)
```

Results are strictly ordered by match %; ties alternate between frame styles. The first six are flagged `top_pick`.

## API

| Endpoint | |
|---|---|
| `GET /api/health` | status, product count |
| `GET /api/meta` | site name, face shapes (guide), frame styles, colours, `live_camera` (is the live tracker available) |
| `GET /api/catalog` | every frame (no scores) |
| `POST /api/analyze` | multipart `photo`, `audience` → face, placement, `pose3d`, recommendations (or `status: "reject"` with issues) |
| `POST /api/recommend` | JSON `{shape, overridden, probabilities?, measurements?, audience, frame_shapes[], colors[]}` |
| `WS /api/track` | live camera: binary frames in, JSON poses out (see above) |
| `GET /media/cutouts/<SKU>.webp` | 2D picture; `thumbs/` for cards |
| `GET /models3d/<SKU>.glb` | the 3D model for the browser |

`audience` is `all` (adult frames), `men`, `women` or `kids`. Live documentation: `/api/docs`.

## Frontend

Plain ES modules, no bundler. `main.js` is the controller; `stage.js` draws the try-on (2D placement maths, 3D mode,
drag, pinch, export); `tryon3d.js` holds the 3D placement maths; `models.js` loads and caches `.glb` files; `live3d.js` and
`tracker.js` run the live camera and smooth the pose; `results.js`, `collection.js`, `guide.js`, `hero.js` render
sections; `camera.js` and `photo.js` handle input. Fonts are bundled, so the page works offline.

## Tests

* `pytest` (`tests/`): API, catalogue build, model generation and import, pose maths, rules and scoring, face shape.
* `node --test tests/js/tryon3d.test.mjs`: the 3D placement and renderer on recorded poses (`tests/js/fixtures`).
* `python tests/e2e_browser.py --photo portrait.jpg`: a real Chromium on CPU only: upload, 3D, sliders, save image, live
  camera with a fake webcam, and the no-photo mode.
