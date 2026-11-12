"""
Face photo -> face shape -> recommended sunglasses drawn on the face.

    python tryon.py face.jpg                       # detect face shape, recommend, draw glasses
    python tryon.py face.jpg --shape round         # override the detected face shape
    python tryon.py face.jpg --top 8 --offset 6    # more / next recommendations
Results go to output/ (one picture per product + a contact sheet). The photo is never stored anywhere else.
"""
import argparse, os, sys, threading
import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
for cand in (HERE, os.path.join(HERE, "..", "face_shape_project")):          # reuse your existing face_shape.py
    if os.path.exists(os.path.join(cand, "face_shape.py")):
        sys.path.insert(0, os.path.abspath(cand)); break
else:
    sys.exit("face_shape.py not found. Keep this folder next to face_shape_project/ or copy face_shape.py here.")
from face_shape import FaceShapeDetector, SHAPES                                # noqa: E402
import overlay, recommend                                                       # noqa: E402


class TryOnEngine:
    def __init__(self, db=None, rules=None):
        db = recommend.find_db(db)
        print("Database:", db)
        self.rules = recommend.load_rules(rules)
        self.products, self.skipped = [], []
        self.png = {}
        for p in recommend.load_products(db):
            rgba = overlay.decode_rgba(p.pop("png"))
            ok, why = overlay.png_quality(rgba) if rgba is not None else (False, "unreadable PNG")
            if ok:
                self.products.append(p); self.png[p["product_id"]] = rgba
            else:
                self.skipped.append((p["sku"], why))
        print("%d products usable for try-on, %d skipped %s" % (len(self.products), len(self.skipped), self.skipped[:6]))
        self.det = FaceShapeDetector()
        self.lock = threading.Lock()                                            # MediaPipe: one photo at a time

    def run(self, bgr, shape=None, top=6, offset=0):
        """Returns dict: face (full detector result), used_shape, why, recs[{..., image (BGR)}], total."""
        h, w = bgr.shape[:2]
        s = 1280 / max(h, w)
        if s < 1:
            bgr = cv2.resize(bgr, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        with self.lock:
            face = self.det.analyze(bgr)
            faces = self.det.lm.faces(bgr)
        out = {"face": face, "used_shape": None, "why": "", "recs": [], "total": 0}
        if face["status"] == "reject" or len(faces) != 1:
            return out
        used = shape if shape in SHAPES else face["face_shape"]
        recs, total = recommend.recommend(self.products, used, self.rules, top, offset)
        for r in recs:
            img = overlay.place_glasses(bgr, faces[0], self.png[r["product_id"]])
            r["image"] = overlay.crop_face(img, faces[0])
        out.update(used_shape=used, why=self.rules[used]["why"], recs=recs, total=total)
        return out


def contact_sheet(recs, cols=3):
    tiles = []
    for i, r in enumerate(recs, 1):
        t = cv2.copyMakeBorder(r["image"], 0, 44, 0, 0, cv2.BORDER_CONSTANT, value=(255, 255, 255))
        cv2.putText(t, "%d. %s  %s" % (i, r["sku"], r["frame_shape"]), (8, t.shape[0] - 26), 0, 0.55, (0, 0, 0), 1)
        cv2.putText(t, "%s (%.2f)" % (r["match"], r["score"]), (8, t.shape[0] - 8), 0, 0.5, (0, 120, 0), 1)
        tiles.append(t)
    while len(tiles) % cols:
        tiles.append(np.full_like(tiles[0], 255))
    return np.vstack([np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)])


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("photo"); ap.add_argument("--db"); ap.add_argument("--shape", choices=SHAPES)
    ap.add_argument("--top", type=int, default=6); ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--out", default=os.path.join(HERE, "output"))
    a = ap.parse_args()
    img = cv2.imread(a.photo)
    if img is None:
        sys.exit("Cannot read " + a.photo)
    eng = TryOnEngine(a.db)
    res = eng.run(img, a.shape, a.top, a.offset)
    f = res["face"]
    print("\nPhoto check: %s%s" % (f["status"], "  -> " + "; ".join(f["issues"]) if f["issues"] else ""))
    if not res["recs"]:
        sys.exit("No recommendation (fix the photo and try again).")
    print("Face shape: %s (detected %s, confidence %.2f)%s" % (res["used_shape"], f["face_shape"], f["confidence"],
          "   <- please confirm, or use --shape" if f["needs_confirmation"] and not a.shape else ""))
    print(res["why"], "\n")
    os.makedirs(a.out, exist_ok=True)
    stem = os.path.splitext(os.path.basename(a.photo))[0]
    for i, r in enumerate(res["recs"], 1):
        cv2.imwrite(os.path.join(a.out, "%s_%d_%s.jpg" % (stem, i, r["sku"])), r["image"])
        print("%d. %-10s %-10s %-12s %s" % (i, r["sku"], r["frame_shape"], r["match"], (r["name"] or "")[:40]))
    cv2.imwrite(os.path.join(a.out, "%s_sheet.jpg" % stem), contact_sheet(res["recs"]))
    print("\nPictures in", a.out)
