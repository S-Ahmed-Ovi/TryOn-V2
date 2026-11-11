"""
Make a NEW database that contains only products that have a detected frame shape.
Your original database is not changed.

    python export_shaped.py                      # all products whose frame_shape is not 'unknown'
    python export_shaped.py --min-conf 0.5       # also require confidence >= 0.5 (uses output/frame_shapes.json)
    python export_shaped.py --db dataset/dukpion_portable.db --out dataset/dukpion_with_shapes.db
"""
import argparse, glob, json, os, shutil, sqlite3, sys

ap = argparse.ArgumentParser()
ap.add_argument("--db", default=None)
ap.add_argument("--out", default=None)
ap.add_argument("--min-conf", type=float, default=0.0)
a = ap.parse_args()

here = os.path.dirname(os.path.abspath(__file__))
src = a.db or (sorted(p for p in glob.glob(os.path.join(here, "dataset", "*.db")) if "shapes" not in p) or [None])[0]
if not src:
    sys.exit("No .db found in dataset/")
out = a.out or os.path.join(os.path.dirname(src), "dukpion_with_shapes.db")
if os.path.exists(out):
    os.remove(out)
shutil.copy2(src, out)                                   # work on a copy

con = sqlite3.connect(out)
keep = {str(r[0]) for r in con.execute(
    "SELECT product_id FROM products WHERE frame_shape IS NOT NULL AND frame_shape NOT IN ('', 'unknown')")}
if a.min_conf > 0:
    conf = {str(r["product_id"]): r["confidence"] for r in json.load(open(os.path.join(here, "output", "frame_shapes.json")))}
    keep = {p for p in keep if conf.get(p, 0) >= a.min_conf}

con.execute("CREATE TEMP TABLE keep_ids (product_id TEXT PRIMARY KEY)")
con.executemany("INSERT INTO keep_ids VALUES (?)", [(p,) for p in keep])

tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
for t in tables:                                          # every table that has a product_id column
    if "product_id" in [r[1] for r in con.execute('PRAGMA table_info("%s")' % t)]:
        n = con.execute('DELETE FROM "%s" WHERE CAST(product_id AS TEXT) NOT IN (SELECT product_id FROM keep_ids)' % t).rowcount
        print("%-20s removed %d rows" % (t, n))
con.commit()
con.execute("VACUUM")                                     # shrink the file
print("products kept:", con.execute("SELECT COUNT(*) FROM products").fetchone()[0])
print(con.execute("SELECT frame_shape, COUNT(*) FROM products GROUP BY 1 ORDER BY 2 DESC").fetchall())
con.close()
print("New database:", out)
