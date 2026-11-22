# Tuning

## The face shape is wrong for some people

The five prototypes in `src/tryon/vision/face_shape.py` (`PROTOTYPES`) are estimates. Each line is
`(mean, tolerance)` for length ÷ cheek width, jaw ÷ cheek width, forehead ÷ jaw width and chin angle.

To calibrate: collect photos whose shape you are confident of, run
`tryon analyze photo.jpg` and note the printed measurements (or call `FaceShapeDetector.analyze` and read
`.measurements`), then move each prototype's mean to the average of your photos for that shape and set the
tolerance to roughly the standard deviation. Run `pytest` afterwards; the tests check every prototype still
classifies as itself.

## Which frames suit which faces

`src/tryon/resources/rules.json`

* `face_shapes.<face>.frames.<frame>`: score 0–1.
* `pairings.<face>.<frame>`: the sentence shown as the reason. Keep it consistent with the score.
* `weights`: balance between shape harmony and proportions.
* `labels`: wording for the match bands.

The app refuses to start if a frame shape in the rules is not defined in `frame_shapes`.

## Lens-depth heuristic

`engine._IDEAL_ASPECT_K` (3.5) sets the ideal frame width ÷ height for an average face. Raise it to favour
slimmer frames, lower it to favour deeper ones. The weight of this factor is `weights.proportion`.

## Where the glasses sit (2D)

In `web/static/js/stage.js`, `_drawGlasses`: the frame is as wide as the face (cheekbone to cheekbone) × the product's
`scale` (its real width relative to a typical 14.4 cm face, set in `catalog/builder.py`, `FACE_REF_CM`) × the *Size*
slider. Each product's `anchor` (where its pupil line crosses the picture) is put on the middle of the eyes.

## Where the glasses sit (Real 3D)

`web/static/js/tryon3d.js`, the `HEAD` constants (explained in `docs/ARCHITECTURE.md`, "3D calibration"):

| If the glasses are... | change |
|---|---|
| too big / too small on everybody | `HEAD.scale` (bigger = bigger glasses) |
| too high / too low on everybody | `HEAD.anchor[1]` (bigger = higher, in canonical cm; 0.1 is about 1 mm) |
| too far out of / sunk into the face | `HEAD.anchor[2]` (bigger = further forward) |
| leaning wrong (lenses too far from / close to the cheeks) | `HEAD.tilt` (degrees) |
| arms showing through the ears, or cut off too early | `HEAD.occluder` radii and centre |

The `Size` slider range is `SIZE_RANGE` in the same file. After a change, run
`node --test tests/js/tryon3d.test.mjs` and look at the result with `python tests/e2e_browser.py --photo portrait.jpg`,
which saves screenshots.

To judge a change on your own portrait without a browser:

```bash
python tools/export_pose.py portrait.jpg out/portrait          # finds the face, saves out/portrait.rgba + .json
node tools/compose_photo.mjs out/portrait.rgba out/portrait.json TO-WAY-01 look.png      # draws the model on it (Node 18+)
```

## Live camera speed

* `MIN_INTERVAL` (`live3d.js`, default 66 ms) caps the frames per second; raise it on a small server.
* `SEND_W` (320 px) is the size of the copy the face tracker sees; smaller is faster, but a face far from the camera gets
  harder to find.
* `TRYON_MAX_LIVE` (`.env`) limits how many cameras run at once.
* The renderer drops from 2× to 1× anti-aliasing on its own when a frame takes more than about 38 ms.

## Smoothing

`web/static/js/tracker.js` (`PoseSmoother`, a One-Euro filter). Its options are `{ rot: [minCutoff, beta], pos: [minCutoff, beta] }`
(defaults `rot: [1.6, 9]`, `pos: [1.1, 0.12]`): lower `minCutoff` for a steadier but laggier picture, raise `beta` for a
quicker reaction to fast head movement.
