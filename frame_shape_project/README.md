# Frame shape detection (OpenCV, CPU only)

## Setup
    pip install -r requirements.txt

Put your database in the `dataset/` folder (e.g. `dataset/dukpion_portable.db`).

## Run
    python run.py validate     # 24 random products -> output/validation/sheet_*.jpg (database untouched)
    python run.py run          # processes every product, writes output/frame_shapes.json, updates the database
    python run.py run --limit 50   # quick trial on 50 products
    python run.py run --retry-unknown   # also redo products already stored as 'unknown' (use this if you ran an earlier main-only version)

* The **main** image is used first. Only if it gives no reliable shape, the product's **gallery** images are tried and the
  most confident result is kept. `image_used` in the JSON shows which image decided ("main" or "gallery:<position>").
  Note: in your database only 490 products have downloaded gallery images (the other ~1,000 gallery downloads have status
  `failed`), so the fallback can only help those products.
* A new column `products.frame_shape` is added (the only change to the database). Before the first change a
  copy is saved next to it as `<name>.db.backup` (disable with `--no-backup`; needs free disk space equal to the DB size).
* Products that already have a `frame_shape` are skipped, so you can stop and re-run at any time.
* Unreadable/missing images and any errors never stop the run; the product gets `unknown`.
* `output/frame_shapes.json`: `[{"product_id": "5", "sku": "DKS012473", "frame_shape": "rectangle", "confidence": 0.75, "image_used": "main"}, ...]`
  Confidence is stored only in the JSON.
* To re-detect everything: `UPDATE products SET frame_shape = NULL;` then run again (JSON is overwritten per product).

Values: aviator, wayfarer, round, rectangle, square, cat-eye, oval, geometric, unknown.

## Known limitations (please read)
* Your main images are mostly lifestyle photos at 3/4 angles on props. Classical OpenCV cannot measure lens
  geometry reliably from those, so **most products will be `unknown`** (about 80-90% of products with no usable gallery image in my samples).
  That is deliberate: the detector refuses rather than guess.
* Confidence is a heuristic score (capped at 0.75), not a calibrated probability.
* Labels that do appear can still be wrong: the square / wayfarer / rectangle boundaries are fuzzy, and
  partial lens outlines occasionally slip through. Check `output/validation` sheets before relying on results.
* `aviator`, `cat-eye` and `geometric` are only emitted from lens-opening measurements and are rare.
* Tested on a copy of your DB; the full run takes a few minutes on CPU (~0.1 s per image).

* Gallery images include side/back/3-4 views; shapes taken from them are gated the same way but can still be wrong. Review `output/validation`.
