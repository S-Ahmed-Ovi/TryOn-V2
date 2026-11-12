# Sunglasses recommendation + virtual try-on

Photo of a face -> face shape -> recommended sunglasses -> the glasses drawn on the person's face.
Reuses `../face_shape_project/face_shape.py` (keep this folder next to it, as in your repo).

## Setup
    pip install -r requirements.txt            # same packages as face_shape_project
Put your try-on database in `dataset/` (the one that has the `tryon_images` table, e.g. `dukpion_tryon.db`).

## Run the web page
    python app.py                              # opens http://localhost:8000   (--port 8001 if busy)
Upload a photo -> see the detected face shape -> tap another shape if it is not right -> recommendations appear
with the glasses on your face ("Show more" for the next 6, "View product" opens the shop page).

## Or from the command line
    python tryon.py face.jpg                   # pictures + contact sheet in output/
    python tryon.py face.jpg --shape round     # force a face shape
    python tryon.py face.jpg --top 8 --offset 6

## How the recommendation works
* `rules.json`: for each face shape, a score 0-1 per frame shape (style conventions, not science - edit freely).
* Only products with a `verified_shape` and a usable try-on PNG are offered.
* The list is varied: one product per frame shape per round, best frame shapes first (so you do not get six similar pairs).
* "Great match" >= 0.9, "Good match" >= 0.7, otherwise "Worth a try".

## How the glasses are placed (overlay.py)
Eye positions from the face landmarks give the centre and the head tilt; the glasses are scaled to the face width
(234<->454 landmarks), rotated with the head, given a soft shadow, and dark lens areas are 8% see-through.
Tune: `fit` in `place_glasses` (1.0 = glasses as wide as the face; try 0.95 or 1.05) and `LENS_ALPHA`.

## Automatic checks on your try-on PNGs
At start-up each PNG is checked and skipped (with the reason printed) if it is not a single, front-facing pair:
clip-on sets/several objects, odd proportions, or angled shots (left/right symmetry below 0.5; front views score 0.63+).
Faint light "floor shadow" pixels left by the cut-out are removed while drawing, so you do not need to regenerate PNGs.

## Limits (please read)
* 2D overlay: works for straight-on photos. Turned heads (> ~12 deg) get a warning, > 25 deg are rejected. Hair or hands are not
  drawn over the glasses.
* Quality of recommendations = quality of `verified_shape`. Re-check labels in the review page: some products labelled
  "round" are visibly square/wayfarer style, and some "oval" are aviator-style (double bridge).
* Your catalogue has no `aviator` or `square` frames, and only a few `round`; square and heart faces therefore get fewer strong matches.
* No filter yet for men/women/kids, price or size.
* Face shape prototypes in `face_shape.py` are still uncalibrated - the user override is important.
* Photos are processed in memory and never saved. Say so on any public page and get consent before storing photos.
