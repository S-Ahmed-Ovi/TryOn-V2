"""
Stores the PNG cut-outs from tryon/<SKU>.png inside the database, in a NEW table `tryon_images`:
    product_id | sku | png_data (BLOB) | width | height
Nothing in your existing tables is changed. Safe to re-run (existing rows are replaced).

    python store_tryon_pngs.py                      # uses the only .db in dataset/
    python store_tryon_pngs.py --db dataset\\dukpion_with_shape.db

Read one back later:   SELECT png_data FROM tryon_images WHERE product_id = '5';
"""
import argparse, glob, os, sqlite3, sys
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser(); ap.add_argument("--db", default=None); ap.add_argument("--dir", default=os.path.join(HERE, "tryon"))
a = ap.parse_args()
dbs = sorted(glob.glob(os.path.join(HERE, "dataset", "*.db")))
if a.db:
    db = a.db
elif len(dbs) == 1:
    db = dbs[0]
else:
    sys.exit("Need exactly one .db in dataset/ or pass --db <path>. Found: %s" % dbs)
pngs = sorted(glob.glob(os.path.join(a.dir, "*.png")))
if not pngs:
    sys.exit("No PNG files in %s" % a.dir)
print("Database:", db, "|", len(pngs), "PNG files")

con = sqlite3.connect(db)
con.execute("""CREATE TABLE IF NOT EXISTS tryon_images (
    product_id TEXT PRIMARY KEY, sku TEXT, png_data BLOB NOT NULL, width INTEGER, height INTEGER)""")
saved, missing = 0, []
for path in pngs:
    sku = os.path.splitext(os.path.basename(path))[0]
    prods = [r[0] for r in con.execute("SELECT product_id FROM products WHERE upper(sku) = upper(?)", (sku,))]
    if not prods:
        missing.append(sku); continue
    with Image.open(path) as im:
        w, h = im.size
    data = open(path, "rb").read()
    for pid in prods:                                   # normally exactly one product per SKU
        con.execute("INSERT OR REPLACE INTO tryon_images VALUES (?,?,?,?,?)", (str(pid), sku, data, w, h))
        saved += 1
con.commit()
print("saved %d PNGs into table tryon_images" % saved)
if missing:
    print("PNG files with no matching SKU in products (not saved):", missing)
print("total rows in tryon_images:", con.execute("SELECT COUNT(*) FROM tryon_images").fetchone()[0])
# check against the review step, if those columns exist
cols = [r[1] for r in con.execute("PRAGMA table_info(products)")]
if "tryon_image_id" in cols:
    lost = [r[0] for r in con.execute("SELECT sku FROM products WHERE tryon_image_id IS NOT NULL AND product_id NOT IN (SELECT product_id FROM tryon_images)")]
    if lost:
        print("%d products were chosen for try-on but have no PNG yet (e.g. %s)" % (len(lost), lost[:5]))