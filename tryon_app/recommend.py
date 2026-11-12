"""Face shape -> list of products. Pure logic, no photos involved."""
import glob, json, os, sqlite3, sys

HERE = os.path.dirname(os.path.abspath(__file__))


def load_rules(path=None):
    return json.load(open(path or os.path.join(HERE, "rules.json")))["face_shapes"]


def find_db(explicit=None):
    """--db wins; otherwise the .db in dataset/ that contains a tryon_images table."""
    if explicit:
        return explicit
    found = []
    for p in sorted(glob.glob(os.path.join(HERE, "dataset", "*.db"))):
        try:
            con = sqlite3.connect("file:%s?mode=ro" % p, uri=True)
            if con.execute("SELECT 1 FROM sqlite_master WHERE name='tryon_images'").fetchone():
                found.append(p)
            con.close()
        except sqlite3.Error:
            pass
    if len(found) == 1:
        return found[0]
    if not found:
        sys.exit("No database with a tryon_images table in dataset/. Put dukpion_tryon.db there (or use --db).")
    pref = [p for p in found if "tryon" in os.path.basename(p)]
    if len(pref) == 1:
        return pref[0]
    sys.exit("Several databases found, choose one with --db: %s" % found)


def load_products(db):
    """Products that have a try-on PNG and a shape. Returns list of dicts (png as bytes)."""
    con = sqlite3.connect("file:%s?mode=ro" % db, uri=True)
    cols = [r[1] for r in con.execute("PRAGMA table_info(products)")]
    shape_col = "verified_shape" if "verified_shape" in cols else "frame_shape"
    if shape_col != "verified_shape":
        print("WARNING: products.verified_shape not found - using the detector's frame_shape (less reliable).")
    rows = con.execute(
        "SELECT p.product_id, p.sku, p.product_name, p.source_url, p.%s, t.png_data FROM products p "
        "JOIN tryon_images t ON t.product_id = p.product_id WHERE p.%s IS NOT NULL AND p.%s NOT IN ('', 'unknown')"
        % (shape_col, shape_col, shape_col)).fetchall()
    con.close()
    return [dict(product_id=str(r[0]), sku=r[1], name=r[2], url=r[3], frame_shape=r[4], png=r[5]) for r in rows]


def match_label(score):
    return "Great match" if score >= 0.9 else "Good match" if score >= 0.7 else "Worth a try"


def recommend(products, face_shape, rules, top=6, offset=0):
    """Best frame shapes first, but varied: one product per frame shape per round (round-robin),
    so the user does not get six near-identical pairs. Returns (list, total_available)."""
    scores = rules[face_shape]["frames"]
    by_shape = {}
    for p in sorted(products, key=lambda p: (p["sku"] or "")):
        by_shape.setdefault(p["frame_shape"], []).append(p)
    order = sorted(by_shape, key=lambda s: -scores.get(s, 0.3))
    strong = [s for s in order if scores.get(s, 0.3) >= 0.6] or order
    weak = [s for s in order if s not in strong]
    ranked = []
    for group in (strong, weak):
        depth = 0
        while any(len(by_shape[s]) > depth for s in group):
            for s in group:
                if len(by_shape[s]) > depth:
                    ranked.append(by_shape[s][depth])
            depth += 1
    out = []
    for p in ranked[offset:offset + top]:
        sc = scores.get(p["frame_shape"], 0.3)
        out.append({**{k: p[k] for k in ("product_id", "sku", "name", "url", "frame_shape")},
                    "score": round(sc, 2), "match": match_label(sc)})
    return out, len(ranked)
