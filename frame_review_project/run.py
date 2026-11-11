"""
Usage (from this folder):
    python run.py validate            # 24 random products -> output/validation/*.jpg  (does NOT touch the database)
    python run.py run                 # detect all unprocessed products, write JSON + update the database
    python run.py run --limit 50      # only process 50 products (for a quick trial)
    python run.py run --retry-unknown # also redo products already stored as 'unknown' (e.g. from an older main-only run)

The database is read from dataset/*.db. Only the MAIN image of each product is used.
If the main image gives no reliable shape, the product's gallery images are tried (best result wins).
A new column `frame_shape` is added to the `products` table (nothing else is changed).
Products whose frame_shape is already filled are skipped, so the script can be stopped and re-run safely.
"""
import argparse, glob, json, os, random, shutil, sqlite3, sys, time
import cv2
import numpy as np
from detect_frames import load_image, detect

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "output")
JSON_PATH = os.path.join(OUT, "frame_shapes.json")

MAIN_SQL = """
SELECT p.product_id, p.sku, i.image_data
FROM products p JOIN images i ON i.product_id = p.product_id AND i.image_type = 'main'
"""


def find_db(arg):
    if arg:
        return arg
    dbs = sorted(glob.glob(os.path.join(HERE, "dataset", "*.db")))
    if not dbs:
        sys.exit("No .db file found in the dataset/ folder. Put dukpion_portable.db there.")
    return dbs[0]


def _try(blob):
    """Never raises. Returns (result, contours, image) ; bad/missing image -> unknown."""
    try:
        if blob is None:
            return {"frame_shape": "unknown", "confidence": 0.0, "reason": "missing image"}, None, None
        im = load_image(blob)
        if im is None:
            return {"frame_shape": "unknown", "confidence": 0.0, "reason": "unreadable image"}, None, None
        r, cs = detect(im)
        return r, cs, im
    except Exception as e:                                   # keep the pipeline alive
        return {"frame_shape": "unknown", "confidence": 0.0, "reason": "error: %s" % e}, None, None


def detect_product(con, pid, main_blob):
    """Main image first. Only if it is 'unknown', try the gallery images and keep the most confident answer.
    Returns (result, contours, image, image_used)."""
    r, cs, im = _try(main_blob)
    if r["frame_shape"] != "unknown":
        return r, cs, im, "main"
    best = (r, cs, im, "main")
    gal = con.execute("SELECT position, image_data FROM images WHERE product_id = ? AND image_type = 'gallery' "
                      "AND download_status = 'downloaded' ORDER BY position", (pid,)).fetchall()
    top = 0.0
    for pos, blob in gal:
        g, gcs, gim = _try(blob)
        if g["frame_shape"] != "unknown" and g["confidence"] > top:
            top = g["confidence"]
            best = (g, gcs, gim, "gallery:%s" % pos)
    return best


def save_json(records):
    tmp = JSON_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(list(records.values()), f, indent=2)
    os.replace(tmp, JSON_PATH)                               # atomic: never leaves a half-written file


def cmd_run(a):
    db = find_db(a.db)
    os.makedirs(OUT, exist_ok=True)
    con = sqlite3.connect(db)
    cols = [r[1] for r in con.execute("PRAGMA table_info(products)")]
    if "frame_shape" not in cols:
        if not a.no_backup:
            bak = db + ".backup"
            if not os.path.exists(bak):
                print("Backing up database to", bak)
                shutil.copy2(db, bak)
        con.execute("ALTER TABLE products ADD COLUMN frame_shape TEXT")
        con.commit()
        print("Added column products.frame_shape")

    records = {}
    if os.path.exists(JSON_PATH):
        records = {str(r["product_id"]): r for r in json.load(open(JSON_PATH))}

    cond = "frame_shape IS NULL OR frame_shape = ''" + (" OR frame_shape = 'unknown'" if a.retry_unknown else "")
    ids = [r[0] for r in con.execute("SELECT product_id FROM products WHERE " + cond)]
    if a.limit:
        ids = ids[: a.limit]
    print("%d products to process" % len(ids))
    t0 = time.time()
    for n, pid in enumerate(ids, 1):
        row = con.execute(MAIN_SQL + " WHERE p.product_id = ?", (pid,)).fetchone()
        sku, blob = (row[1], row[2]) if row else (None, None)
        r, _, _, used = detect_product(con, pid, blob)
        shape = r["frame_shape"]
        rec = {"product_id": str(pid), "sku": sku, "frame_shape": shape, "confidence": round(float(r["confidence"]), 2),
               "image_used": used}
        if r.get("reason"):
            rec["note"] = r["reason"]
        records[str(pid)] = rec
        con.execute("UPDATE products SET frame_shape = ? WHERE product_id = ?", (shape, pid))
        if n % 25 == 0 or n == len(ids):
            con.commit(); save_json(records)
            print("  %d/%d  (%.0fs)" % (n, len(ids), time.time() - t0), flush=True)
    con.commit(); save_json(records); con.close()
    counts = {}
    for r in records.values():
        counts[r["frame_shape"]] = counts.get(r["frame_shape"], 0) + 1
    print("Done.", counts)
    print("JSON:", JSON_PATH)


def cmd_validate(a):
    db = find_db(a.db)
    outdir = os.path.join(OUT, "validation"); os.makedirs(outdir, exist_ok=True)
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)    # read-only: validation never changes the DB
    rows = con.execute(MAIN_SQL).fetchall()
    random.Random(a.seed).shuffle(rows)
    rows = rows[: a.n]
    tiles, report = [], []
    for pid, sku, blob in rows:
        r, cs, im, used = detect_product(con, pid, blob)
        if im is None:
            continue
        o = im.copy()
        if cs:
            cv2.drawContours(o, list(cs), -1, (0, 255, 0), 2)
        col = (0, 0, 255) if r["frame_shape"] == "unknown" else (0, 160, 0)
        cv2.rectangle(o, (0, 0), (im.shape[1], 30), (255, 255, 255), -1)
        cv2.putText(o, "%s %s %.2f [%s]" % (pid, r["frame_shape"], r["confidence"], used), (6, 22), 0, 0.6, col, 2)
        why = r.get("reason", "")
        if why:
            cv2.putText(o, why[:38], (6, im.shape[0] - 8), 0, 0.5, (255, 0, 0), 1)
        tiles.append(cv2.resize(o, (360, 360)))
        report.append({"product_id": str(pid), "sku": sku, "frame_shape": r["frame_shape"],
                       "confidence": r["confidence"], "image_used": used, "note": why})
    for k in range(0, len(tiles), 12):                          # 12 per sheet (4 x 3)
        chunk = tiles[k:k + 12]
        while len(chunk) % 4:
            chunk.append(np.full((360, 360, 3), 255, np.uint8))
        sheet = np.vstack([np.hstack(chunk[i:i + 4]) for i in range(0, len(chunk), 4)])
        cv2.imwrite(os.path.join(outdir, "sheet_%d.jpg" % (k // 12 + 1)), sheet)
    json.dump(report, open(os.path.join(outdir, "validation.json"), "w"), indent=2)
    known = sum(r["frame_shape"] != "unknown" for r in report)
    print("Validated %d images, %d classified, %d unknown. Sheets in %s" % (len(report), known, len(report) - known, outdir))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sp = ap.add_subparsers(dest="cmd", required=True)
    v = sp.add_parser("validate"); v.add_argument("--n", type=int, default=24); v.add_argument("--seed", type=int, default=1)
    r = sp.add_parser("run"); r.add_argument("--limit", type=int, default=0); r.add_argument("--retry-unknown", action="store_true"); r.add_argument("--no-backup", action="store_true")
    for p in (v, r):
        p.add_argument("--db", default=None, help="path to .db (default: first .db in dataset/)")
    a = ap.parse_args()
    {"validate": cmd_validate, "run": cmd_run}[a.cmd](a)
