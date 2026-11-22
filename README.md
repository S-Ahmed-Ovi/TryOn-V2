# TryOn

Sunglasses recommendations from a face photo, with a **2D try-on** and a **real 3D try-on** that runs entirely on the CPU.

A visitor uploads a selfie (or takes one with a laptop or phone camera). TryOn finds the face, works out its
shape, ranks the sunglasses frames with a **match percentage and the reasons behind it**, and puts the chosen
frame on the photo. The visitor can then switch to **Real 3D**: the glasses are drawn as a true 3D model that follows
the head's rotation and tilt, and a **Live camera** mode does the same on a moving video.

The website is called **TryOn** by default. Change it in `.env` (`TRYON_SITE_NAME`).

**No GPU anywhere.** The 3D view is drawn by a small software renderer written in JavaScript (no WebGL, no WebGPU),
and the face is tracked on the server's CPU. It is meant for low-cost machines.

---

## Quick start

You need **Python 3.10 – 3.13** (3.12 is the safest choice). Nothing else is needed to run the site.

**Windows**

1. Double-click **`install.bat`** (once; takes a few minutes).
2. Double-click **`run.bat`**. The site opens at <http://localhost:8000>.

**macOS / Linux**

```bash
./install.sh        # once
./run.sh            # opens http://localhost:8000
```

**Prefer plain pip (no scripts)?** Works too, in any terminal or VS Code:

```bash
python -m venv .venv
.venv\Scripts\activate            # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python run.py                      # also: python run.py build | doctor | analyze photo.jpg
```

Code edits in `src/` take effect on the next start; nothing needs reinstalling.

The project ships with its 24 sunglasses (3D models and their 2D pictures), so it runs straight away.

---

## What the visitor sees

1. **Upload a photo** (or *Use camera*). TryOn shows the face shape and ranked frames.
2. A **2D / Real 3D** switch appears above the picture:
   * **2D** – the flat picture of the frame, placed on the eyes and turned with the head tilt (drag it, pinch, or use the sliders).
   * **Real 3D** – the same frame as a 3D model, turned and tilted with the head, with real lens transparency and
     reflections. The same *Size* and *Height* sliders move it. *Save image* saves what is on screen.
   * **Live camera** – the 3D glasses on a live video of the visitor's face.
3. Not sure of the face shape or no photo? The visitor can pick a face shape instead. That mode is **2D only**: a 3D
   try-on needs a real face to measure, so the 3D switch and the live camera are not offered there.

## The 24 frames

Eight styles, three frames each, all built into the project (no database, no downloads, no third-party artwork):

| Style | Frames |
|---|---|
| Wayfarer | `TO-WAY-01..03` |
| Rectangle | `TO-RCT-01..03` |
| Square | `TO-SQR-01..03` |
| Round | `TO-RND-01..03` |
| Oval | `TO-OVL-01..03` |
| Cat-eye | `TO-CAT-01..03` |
| Aviator | `TO-AVI-01..03` |
| Geometric | `TO-GEO-01..03` |

The **2D pictures are renders of the 3D models**, so the 2D and 3D views always show exactly the same frame.

---

## Commands

| Windows | macOS / Linux | Does |
|---|---|---|
| `run.bat` | `./run.sh` | start the website |
| `install.bat` | `./install.sh` | one-time setup |
| `.venv\Scripts\python -m tryon doctor` | `make doctor` | check the installation |
| `.venv\Scripts\python -m tryon build` | `make build` | re-render the 2D pictures when a 3D model changed (add `--force` to redo all) |
| `.venv\Scripts\python -m tryon models3d generate` | `make models` | re-make the 24 built-in 3D frames |
| `.venv\Scripts\python -m tryon models3d add my.glb ...` | `.venv/bin/python -m tryon models3d add my.glb ...` | add your own `.glb` model ([guide](docs/ADDING_MODELS.md)) |
| `.venv\Scripts\python -m tryon analyze photo.jpg` | `.venv/bin/python -m tryon analyze photo.jpg` | face shape and top frames from the terminal |
| `.venv\Scripts\python -m pytest` | `make test` | run the tests |

`run` accepts `--port 9000`, `--host 0.0.0.0` (to reach it from other devices) and `--no-browser`.
Interactive API documentation is at <http://localhost:8000/api/docs>.

**Node.js (optional).** Running the site does *not* need Node. It is only used by `tryon build` to render the 2D
pictures from the 3D models, which you only do after changing a model. Install Node 18+ from <https://nodejs.org> if you
plan to do that. If Node is missing the app simply keeps using the pictures that ship with the project.

---

## How it works

```
photo ─► face landmarks ─► face shape ─► score every frame ─► ranked list + reasons
        (MediaPipe, 478)   (5 shapes,     (shape rules +       (match %, why)
                            probabilities) proportions)
                    ├─► eye position, tilt, face width ─► 2D glasses drawn on the photo
                    └─► 3D head pose (rotation + position) ─► 3D glasses drawn by the CPU renderer in the browser
```

* **Face shape.** Four measurements (length ÷ cheek width, jaw ÷ cheek, forehead ÷ jaw, chin angle) are compared
  with a prototype for each of oval, round, square, heart and oblong. The result is a *probability* for each shape,
  not just a label. If the shape is uncertain the page says so and lets the visitor pick their own.
* **Match %.** `85% shape harmony + 15% proportions`. Shape harmony comes from `rules.json` (which frame shapes
  suit which face shapes), averaged by the face-shape probabilities. Proportions compare the frame's depth with the
  face's length. Frames are never shown at 100%.
* **Why.** Each pairing has a hand-written explanation in `rules.json`, plus a sentence built from the visitor's own
  measurements and a note on lens depth.
* **2D try-on.** The server returns where the eyes are, the head tilt and the face width. The browser draws the
  frame's picture on a canvas, so switching frames is instant and nothing is re-uploaded.
* **Real 3D try-on.** MediaPipe also gives the head's 3D pose. The server sends it as a 4×4 matrix and the browser
  draws the `.glb` model with that pose using its own software renderer (z-buffer, shading, see-through lenses, a
  hidden head shape so the temples disappear behind the ears). Changing frames or sliders only redraws in the browser.
* **Live camera.** The browser sends small camera frames to the server over a WebSocket (`/api/track`), the server
  answers with the head pose, and the browser draws the glasses on that same frame, smoothed so they do not jitter.
  About 12–15 frames per second on an ordinary CPU.
* **Privacy.** A photo is decoded in memory, analysed and discarded. Live frames are tracked and discarded. Nothing is
  written to disk.

More detail in [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Project layout

```
TryOn/
├── README.md
├── install.bat / install.sh        one-time setup
├── run.bat / run.sh                start the website
├── pyproject.toml                  dependencies and the `tryon` command
├── Makefile                        shortcuts for macOS / Linux
├── .env.example                    optional settings (copy to .env)
│
├── data/
│   ├── models3d/                   the 24 3D sunglasses (.glb) + manifest.json
│   └── catalog/                    2D pictures rendered from the models + catalog.json (made by `tryon build`)
│
├── src/tryon/
│   ├── cli.py                      `tryon run | build | models3d | doctor | analyze`
│   ├── config.py                   all settings in one place
│   ├── models3d/                   generator.py (builds the frames) · glb.py · importer.py (add your own .glb)
│   ├── vision/                     landmarks.py · face_shape.py · placement.py · pose3d.py · live.py
│   ├── catalog/                    builder.py (3D → 2D pictures) · store.py
│   ├── recommend/                  rules.py · engine.py · explain.py
│   ├── api/                        app.py · routes.py · serialize.py
│   ├── resources/rules.json        style rules and explanations (edit freely)
│   ├── assets/models/              MediaPipe face model (bundled, no download)
│   └── web/                        index.html + static/ (css, js, fonts)
│       └── static/js/              stage.js (2D + 3D stage) · tryon3d.js · live3d.js · soft3d/ (CPU renderer)
│
├── tools/                          render_models.mjs (Node: 3D → 2D pictures) · compose_photo.mjs (dev helper)
├── tests/                          pytest suite, Node tests (tests/js) and a real-browser check (e2e_browser.py)
└── docs/                           ARCHITECTURE.md · TUNING.md · ADDING_MODELS.md
```

---

## Adding your own 3D sunglasses

```bash
.venv/bin/python -m tryon models3d add my_glasses.glb --sku TO-WAY-04 --name "Wayfarer Sky" --shape wayfarer \
        --audience unisex --color "Sky blue" --color-hex "#5a8fc2" --unit mm
.venv/bin/python -m tryon build
```

The model is put into the project's convention automatically (scale, direction, centre on the bridge). See
[`docs/ADDING_MODELS.md`](docs/ADDING_MODELS.md) for what a good model looks like and what to do if it appears too big,
too small or backwards.

---

## Settings

Copy `.env.example` to `.env`. Every setting is optional.

| Setting | Default | |
|---|---|---|
| `TRYON_SITE_NAME` | `TryOn` | name in the header, page title and saved pictures |
| `TRYON_HOST` / `TRYON_PORT` | `127.0.0.1` / `8000` | where the server listens |
| `TRYON_MAX_UPLOAD_MB` | `12` | largest photo accepted |
| `TRYON_MAX_LIVE` | `4` | how many people can use the live 3D camera at the same time (each one is a CPU-heavy video stream) |

---

## Using it on a phone

* **Upload** always works, including Real 3D on the photo.
* **Live camera** needs a secure page (browsers insist on it). `http://localhost` counts as secure; an address like
  `http://192.168.1.20:8000` does **not**. On such an address *Use camera* opens the phone's own camera app instead
  (a photo, with Real 3D available afterwards). For the live in-page camera on a phone, serve the site over HTTPS
  (for example behind a reverse proxy or a tunnelling tool; the proxy must pass WebSockets through).

---

## Troubleshooting

Run **`tryon doctor`** first; it checks Python, the face model, the 3D models, the catalogue and the renderer.

| Problem | Fix |
|---|---|
| `install.bat` says Python not found | install Python 3.12 from python.org and tick *Add python.exe to PATH* |
| Error mentioning *Microsoft Visual C++* | install <https://aka.ms/vs/17/release/vc_redist.x64.exe> and run `install.bat` again |
| `tryon build` says Node.js is needed | install Node 18+ from <https://nodejs.org> (only needed after you change a 3D model) |
| The *Live camera* button is missing or says the camera is busy | the server could not load the face model, or `TRYON_MAX_LIVE` people are already connected; run `tryon doctor` |
| Live camera connects but never tracks | a reverse proxy is blocking WebSockets, or the page is not served over `https`/`localhost` |
| Real 3D is greyed out | it needs a photo with a clearly visible, roughly front-facing face; very strong turns of the head are refused on purpose |
| Camera button does nothing / blocked | allow the camera in the browser address bar; use `localhost` or HTTPS |
| Port already in use | `run.bat --port 9000` |
| The face shape looks wrong | the shape rules are estimates; the visitor can tap the right shape. See `docs/TUNING.md` |
| The 3D glasses sit a little high/low or look too big on a particular face | the *Size* and *Height* sliders; to change the default for everyone see `docs/TUNING.md` |

---

## Good to know

* The 3D frames are **procedurally generated, stylised models**, not scans of real products. They are meant to be a
  good-looking, correctly sized stand-in until you add your own `.glb` files.
* The 3D placement was calibrated on portrait photos and a fake-webcam test; faces and cameras vary, so use the
  sliders and see `docs/TUNING.md` if you want to adjust the default placement.
* A very slow computer can lower the quality of the live view (it drops the anti-aliasing) to keep up.

## Licences

Code: yours to choose a licence for. Bundled third-party files are listed in [`NOTICE.md`](NOTICE.md).
