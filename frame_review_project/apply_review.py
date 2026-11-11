"""
Reads review/review_results.json (downloaded from review.html) and saves it into the database:
  products.verified_shape   TEXT     the shape you confirmed/corrected  (NULL = not reviewed / unsure)
  products.tryon_image_id   INTEGER  images.image_id of the chosen front-view image (NULL = none)
Nothing else is changed. A backup (<db>.review_backup) is made once before the first change.

    python apply_review.py [path/to/review_results.json]
"""
import glob, json, os, shutil, sqlite3, sys
HERE = os.path.dirname(os.path.abspath(__file__))
import argparse
ap = argparse.ArgumentParser()
ap.add_argument("results", nargs="?", default=os.path.join(HERE, "review", "review_results.json"))
ap.add_argument("--db", default=None, help="database to update (default: the only .db in dataset/)")
a = ap.parse_args()
res_path = a.results
if not os.path.exists(res_path):
    sys.exit("Put the downloaded review_results.json in the review/ folder (or pass its path).")
dbs = sorted(glob.glob(os.path.join(HERE, "dataset", "*.db")))
if a.db:
    db = a.db
elif len(dbs) == 1:
    db = dbs[0]
elif not dbs:
    sys.exit("No .db file in the dataset/ folder.")
else:
    sys.exit("Several .db files in dataset/. Choose one:  python apply_review.py --db " + dbs[0] + "\n  " + "\n  ".join(dbs))
print("Database:", db)
bak = db + ".review_backup"
if not os.path.exists(bak):
    print("Backing up to", bak); shutil.copy2(db, bak)
con = sqlite3.connect(db)
cols = [r[1] for r in con.execute("PRAGMA table_info(products)")]
for c, t in (("verified_shape", "TEXT"), ("tryon_image_id", "INTEGER")):
    if c not in cols:
        con.execute("ALTER TABLE products ADD COLUMN %s %s" % (c, t))
n = 0
for r in json.load(open(res_path)):
    if not r.get("reviewed") and not r.get("tryon_image_id"):
        continue                                    # untouched cards are not saved
    shape = r["verified_shape"]
    if shape and shape.startswith("other"):
        shape = None
    con.execute("UPDATE products SET verified_shape=?, tryon_image_id=? WHERE product_id=?",
                (shape, r["tryon_image_id"], r["product_id"]))
    n += 1
con.commit()
print("saved %d products" % n)
print("verified shapes:", con.execute("SELECT verified_shape, COUNT(*) FROM products WHERE verified_shape IS NOT NULL GROUP BY 1 ORDER BY 2 DESC").fetchall())
print("with try-on image:", con.execute("SELECT COUNT(*) FROM products WHERE tryon_image_id IS NOT NULL").fetchone()[0])