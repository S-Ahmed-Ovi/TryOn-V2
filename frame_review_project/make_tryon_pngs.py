"""
Makes transparent PNG cut-outs (tryon/<SKU>.png) of the chosen front-view image of each product
(products.tryon_image_id, set by apply_review.py). Uses rembg (CPU). First run downloads a ~170 MB model.

    pip install rembg onnxruntime      # OPTIONAL - only needed for photos with a non-plain background
    python make_tryon_pngs.py              # all products with a chosen image (skips existing PNGs)
    python make_tryon_pngs.py --limit 5    # try a few first  (--method simple | rembg | auto, default auto)
"""
import argparse, glob, io, os, sqlite3, sys
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser(); ap.add_argument("--limit", type=int, default=0); ap.add_argument("--db", default=None); ap.add_argument("--method", choices=["auto", "rembg", "simple"], default="auto")
a = ap.parse_args()
dbs = sorted(glob.glob(os.path.join(HERE, "dataset", "*.db")))
if a.db:
    db = a.db
elif len(dbs) == 1:
    db = dbs[0]
else:
    sys.exit("Need exactly one .db in dataset/ or pass --db <path>. Found: %s" % dbs)
print("Database:", db)
import cv2

def simple_cutout(img):
    """No-AI cut-out for plain (white/light) studio backgrounds. Returns RGBA or None if the background is not plain."""
    rgb = np.array(img)
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    h, w = lab.shape[:2]
    border = np.concatenate([lab[:6].reshape(-1, 3), lab[-6:].reshape(-1, 3), lab[:, :6].reshape(-1, 3), lab[:, -6:].reshape(-1, 3)])
    bg = np.median(border, axis=0)
    if np.mean(np.linalg.norm(border - bg, axis=1) > 12) > 0.05:
        return None                                           # background not plain
    dist = np.linalg.norm(lab - bg, axis=2)
    alpha = np.clip((dist - 22) / 30.0, 0, 1)                 # similar to background -> transparent (also light lenses/shadows)
    a8 = (alpha * 255).astype(np.uint8)
    a8 = cv2.morphologyEx(a8, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    n, lb, st, _ = cv2.connectedComponentsWithStats((a8 > 40).astype(np.uint8), connectivity=8)
    if n > 1:                                                 # drop specks, keep objects bigger than 3% of the largest
        big = st[1:, 4].max()
        keep = np.isin(lb, [i for i in range(1, n) if st[i, 4] >= 0.03 * big])
        a8 = np.where(keep, a8, 0).astype(np.uint8)
    return Image.fromarray(np.dstack([rgb, a8]), "RGBA")

remove = session = None
if a.method in ("auto", "rembg"):
    try:
        from rembg import remove, new_session
        session = new_session("u2net")
        print("Cut-out method: rembg")
    except Exception as e:
        if a.method == "rembg":
            sys.exit("rembg is not working in this Python: %s" % e)
        print("rembg not available (%s) -> using the simple cut-out method" % str(e).splitlines()[0][:80])
        remove = None
if remove is None:
    print("Cut-out method: simple (plain-background only)")
out_dir = os.path.join(HERE, "tryon"); os.makedirs(out_dir, exist_ok=True)
con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
rows = con.execute("SELECT p.product_id, p.sku, i.image_data FROM products p JOIN images i ON i.image_id = p.tryon_image_id "
                   "WHERE p.tryon_image_id IS NOT NULL").fetchall()
done = 0
for pid, sku, blob in rows:
    path = os.path.join(out_dir, "%s.png" % sku)
    if os.path.exists(path):
        continue
    if a.limit and done >= a.limit:
        break
    img = Image.open(io.BytesIO(blob)).convert("RGB")
    img.thumbnail((1200, 1200))
    cut = remove(img, session=session) if remove else simple_cutout(img)       # RGBA
    if cut is None:
        print("skipped (background not plain, needs rembg):", sku); continue
    alpha = np.array(cut)[..., 3]
    ys, xs = np.where(alpha > 20)
    if len(xs) == 0:
        print("no object found:", sku); continue
    cut = cut.crop((xs.min(), ys.min(), xs.max() + 1, ys.max() + 1))   # tight crop around the glasses
    cut.save(path)
    done += 1
    print(sku, cut.size)
print("created %d PNGs in %s" % (done, out_dir))