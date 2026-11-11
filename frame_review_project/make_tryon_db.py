"""
Makes a NEW, small database that contains ONLY the products that have a try-on PNG (rows in table tryon_images).
Your current database is not changed.

    python make_tryon_db.py                       # uses the only .db in dataset/
    python make_tryon_db.py --db dataset\\dukpion_with_shapes.db --out dataset\\dukpion_tryon.db
"""
import argparse, glob, os, shutil, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))
ap = argparse.ArgumentParser(); ap.add_argument("--db", default=None); ap.add_argument("--out", default=None)
a = ap.parse_args()
dbs = [p for p in sorted(glob.glob(os.path.join(HERE, "dataset", "*.db"))) if "tryon" not in os.path.basename(p)]
if a.db:
    src = a.db
elif len(dbs) == 1:
    src = dbs[0]
else:
    sys.exit("Need exactly one source .db in dataset/ or pass --db <path>. Found: %s" % dbs)
out = a.out or os.path.join(os.path.dirname(src), "dukpion_tryon.db")
if os.path.abspath(out) == os.path.abspath(src):
    sys.exit("--out must be a different file than the source database")
if os.path.exists(out):
    os.remove(out)
shutil.copy2(src, out)                                   # work on a copy

con = sqlite3.connect(out)
if not con.execute("SELECT 1 FROM sqlite_master WHERE name='tryon_images'").fetchone():
    sys.exit("No tryon_images table. Run store_tryon_pngs.py first.")
con.execute("CREATE TEMP TABLE keep_ids AS SELECT DISTINCT CAST(product_id AS TEXT) AS product_id FROM tryon_images")
print("products to keep:", con.execute("SELECT COUNT(*) FROM keep_ids").fetchone()[0])
tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
for t in tables:
    if "product_id" in [r[1] for r in con.execute('PRAGMA table_info("%s")' % t)]:
        n = con.execute('DELETE FROM "%s" WHERE CAST(product_id AS TEXT) NOT IN (SELECT product_id FROM keep_ids)' % t).rowcount
        print("  %-14s removed %d rows" % (t, n))
con.commit()
con.execute("VACUUM")
cols = [r[1] for r in con.execute("PRAGMA table_info(products)")]
print("\nproducts in new database:", con.execute("SELECT COUNT(*) FROM products").fetchone()[0])
if "verified_shape" in cols:
    print("verified_shape:", con.execute("SELECT COALESCE(verified_shape,'(not set)'), COUNT(*) FROM products GROUP BY 1 ORDER BY 2 DESC").fetchall())
    miss = con.execute("SELECT COUNT(*) FROM products WHERE verified_shape IS NULL").fetchone()[0]
    if miss:
        print("WARNING: %d products have no verified_shape yet (review them before recommending)" % miss)
con.close()
print("New database: %s  (%.1f MB)" % (out, os.path.getsize(out) / 1e6))