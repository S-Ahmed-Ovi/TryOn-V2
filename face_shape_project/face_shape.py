"""
Face shape detection from a photo (MediaPipe landmarks + simple geometry, CPU only).

    python face_shape.py photo.jpg                       # one photo
    python face_shape.py photos_folder                   # every .jpg/.png/.webp in a folder
    python face_shape.py --db photos.db --table users --id-col id --blob-col photo     # photos stored as BLOBs
Results: output/face_shapes.json  and annotated pictures in output/faces/  (nothing is written to your databases).

From Python:
    from face_shape import FaceShapeDetector
    result = FaceShapeDetector().analyze(bgr_image)       # dict, see analyze()
"""
import argparse, glob, json, math, os, sqlite3, sys, urllib.request
import cv2
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_URL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
MODEL_PATH = os.path.join(HERE, "models", "face_landmarker.task")
SHAPES = ["oval", "round", "square", "heart", "oblong"]

# Landmark indices of the 468-point MediaPipe face mesh
I_TOP, I_CHIN = 10, 152                 # top of forehead (mesh), chin
I_CHEEK_R, I_CHEEK_L = 234, 454         # widest part of the face (cheekbones)
I_JAW_R, I_JAW_L = 172, 397             # jaw corners
I_FORE_R, I_FORE_L = 54, 284            # upper forehead corners
I_EYE_R, I_EYE_L = 33, 263              # outer eye corners
I_NOSE = 1

# Prototype values (mean, tolerance) per face shape for: length/cheek-width, jaw/cheek-width,
# forehead/jaw-width, chin angle (deg).  FIRST GUESSES - tune with your own photos (see README).
PROTOTYPES = {
    #           length/cheek     jaw/cheek       forehead/jaw    chin angle
    "oval":   ((1.20, 0.08),  (0.74, 0.06), (1.08, 0.10), (100, 10)),
    "round":  ((1.08, 0.06),  (0.80, 0.06), (1.02, 0.10), (108, 10)),
    "square": ((1.14, 0.07),  (0.86, 0.05), (0.98, 0.08), (113, 10)),
    "heart":  ((1.20, 0.09),  (0.68, 0.06), (1.25, 0.10), (92, 10)),
    "oblong": ((1.34, 0.08),  (0.78, 0.07), (1.05, 0.10), (102, 10)),
}


# ----------------------------------------------------------------------------- landmark backends
class Landmarker:
    """Returns, for an image, a list of faces; each face = array (468+, 3) of normalised x, y, z."""

    def __init__(self):
        import mediapipe as mp
        self.mp = mp
        if hasattr(mp, "solutions") and hasattr(mp.solutions, "face_mesh"):      # older MediaPipe: model is bundled
            self.kind = "solutions"
            self.fm = mp.solutions.face_mesh.FaceMesh(static_image_mode=True, max_num_faces=2, refine_landmarks=False,
                                                      min_detection_confidence=0.5)
        else:                                                                    # newer MediaPipe: Face Landmarker task
            self.kind = "tasks"
            if not os.path.exists(MODEL_PATH):
                os.makedirs(os.path.dirname(MODEL_PATH), exist_ok=True)
                print("Downloading face model (~4 MB) ...")
                try:
                    urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
                except Exception as e:
                    sys.exit("Could not download the model: %s\nDownload it manually from\n  %s\nand save it as\n  %s"
                             % (e, MODEL_URL, MODEL_PATH))
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision
            opts = vision.FaceLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=MODEL_PATH),
                running_mode=vision.RunningMode.IMAGE, num_faces=2,
                min_face_detection_confidence=0.5, min_face_presence_confidence=0.5)
            self.lm = vision.FaceLandmarker.create_from_options(opts)

    def faces(self, bgr):
        rgb = np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        if self.kind == "solutions":
            r = self.fm.process(rgb)
            return [np.array([[p.x, p.y, p.z] for p in f.landmark]) for f in (r.multi_face_landmarks or [])]
        res = self.lm.detect(self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb))
        return [np.array([[p.x, p.y, p.z] for p in f]) for f in res.face_landmarks]


# ----------------------------------------------------------------------------- geometry
def measure(pts, w, h):
    """All measurements are made after rotating the face so the eye line is horizontal (head tilt removed)."""
    P = pts[:, :2] * [w, h]
    Z = pts[:, 2] * w                                           # z has roughly the same scale as x
    roll = math.degrees(math.atan2(P[I_EYE_L, 1] - P[I_EYE_R, 1], P[I_EYE_L, 0] - P[I_EYE_R, 0]))
    t = -math.radians(roll)
    R = np.array([[math.cos(t), -math.sin(t)], [math.sin(t), math.cos(t)]])
    Q = (P - P.mean(0)) @ R.T
    width = lambda a, b: abs(Q[a, 0] - Q[b, 0])
    Wc, Wj, Wf = width(I_CHEEK_R, I_CHEEK_L), width(I_JAW_R, I_JAW_L), width(I_FORE_R, I_FORE_L)
    L = abs(Q[I_CHIN, 1] - Q[I_TOP, 1])
    v1, v2 = Q[I_JAW_R] - Q[I_CHIN], Q[I_JAW_L] - Q[I_CHIN]
    chin = math.degrees(math.acos(np.clip(v1 @ v2 / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-9), -1, 1)))
    yaw = math.degrees(math.atan2(abs(Z[I_CHEEK_L] - Z[I_CHEEK_R]), width(I_CHEEK_R, I_CHEEK_L)))
    eye_y = (Q[I_EYE_R, 1] + Q[I_EYE_L, 1]) / 2
    nose_ratio = (Q[I_NOSE, 1] - eye_y) / max(Q[I_CHIN, 1] - eye_y, 1e-6)     # ~constant for a level head
    return dict(length_cheek=L / Wc, jaw_cheek=Wj / Wc, fore_jaw=Wf / Wj, chin_angle=chin,
                yaw=yaw, roll=abs(roll), nose_ratio=nose_ratio,
                face_h_frac=(pts[:, 1].max() - pts[:, 1].min())), P


def photo_checks(m, pts, bgr):
    """Returns list of (level, message); level is 'reject' or 'warn'."""
    issues = []
    out = (pts[:, 0].min() < 0.0 or pts[:, 0].max() > 1.0 or pts[:, 1].min() < 0.0 or pts[:, 1].max() > 1.0)
    if out:
        issues.append(("reject", "Face is cut off by the edge of the photo - show the whole face."))
    if m["face_h_frac"] < 0.18:
        issues.append(("reject", "Face is too small in the photo - move closer."))
    elif m["face_h_frac"] < 0.30:
        issues.append(("warn", "Face is fairly small in the photo; a closer photo is more accurate."))
    if m["yaw"] > 25:
        issues.append(("reject", "Head is turned sideways (%.0f deg) - look straight at the camera." % m["yaw"]))
    elif m["yaw"] > 12:
        issues.append(("warn", "Head is slightly turned (%.0f deg)." % m["yaw"]))
    if m["roll"] > 35:
        issues.append(("reject", "Head is tilted too much (%.0f deg)." % m["roll"]))
    elif m["roll"] > 12:
        issues.append(("warn", "Head is tilted (%.0f deg); measurements were corrected for it." % m["roll"]))
    if not 0.28 <= m["nose_ratio"] <= 0.56:
        issues.append(("warn", "Head looks tilted up or down - keep the chin level."))
    if not out:
        h, w = bgr.shape[:2]
        x0, x1 = int(pts[:, 0].min() * w), int(pts[:, 0].max() * w)
        y0, y1 = int(pts[:, 1].min() * h), int(pts[:, 1].max() * h)
        crop = cv2.cvtColor(bgr[max(y0, 0):y1, max(x0, 0):x1], cv2.COLOR_BGR2GRAY)
        if crop.size and cv2.Laplacian(crop, cv2.CV_64F).var() < 30:
            issues.append(("warn", "Photo looks blurry."))
    return issues


def classify(m):
    """Soft scoring against the prototypes. Returns list of (shape, probability) best first."""
    x = [m["length_cheek"], m["jaw_cheek"], m["fore_jaw"], m["chin_angle"]]
    raw = {}
    for shape, protos in PROTOTYPES.items():
        raw[shape] = math.exp(-0.5 * sum(((v - mu) / sd) ** 2 for v, (mu, sd) in zip(x, protos)))
    tot = sum(raw.values()) + 1e-12
    return sorted(((s, v / tot) for s, v in raw.items()), key=lambda t: -t[1])


# ----------------------------------------------------------------------------- main class
class FaceShapeDetector:
    def __init__(self):
        self.lm = Landmarker()

    def analyze(self, bgr, annotate=False):
        """Returns dict: status ('ok' | 'warn' | 'reject'), issues, face_shape, confidence (0-0.85), alternatives,
        needs_confirmation (True = show the user the 'not quite right? choose' options), measurements.
        With annotate=True also returns the annotated image as a second value."""
        h, w = bgr.shape[:2]
        s = 1280 / max(h, w)
        if s < 1:
            bgr = cv2.resize(bgr, None, fx=s, fy=s, interpolation=cv2.INTER_AREA); h, w = bgr.shape[:2]
        faces = self.lm.faces(bgr)
        res = {"status": "reject", "issues": [], "face_shape": None, "confidence": 0.0, "alternatives": [],
               "needs_confirmation": True, "measurements": {}}
        img = bgr.copy()
        if not faces:
            res["issues"].append("No face found - use a clear, front-facing photo.")
        elif len(faces) > 1:
            res["issues"].append("More than one face found - use a photo with only one person.")
        else:
            pts = faces[0]
            m, P = measure(pts, w, h)
            issues = photo_checks(m, pts, bgr)
            res["issues"] = [msg for _, msg in issues]
            res["measurements"] = {k: round(float(v), 3) for k, v in m.items()}
            if any(l == "reject" for l, _ in issues):
                res["status"] = "reject"
            else:
                ranked = classify(m)
                (top, p1), (sec, p2) = ranked[0], ranked[1]
                conf = min(0.85, p1 * (1.0 if not issues else 0.75))
                res.update(status="warn" if issues else "ok", face_shape=top, confidence=round(conf, 2),
                           alternatives=[{"shape": s_, "score": round(p, 2)} for s_, p in ranked[:3]],
                           needs_confirmation=bool(issues) or conf < 0.55 or (p1 - p2) < 0.15)
            if annotate:
                for a, b, col in ((I_CHEEK_R, I_CHEEK_L, (0, 200, 0)), (I_JAW_R, I_JAW_L, (255, 0, 0)),
                                  (I_FORE_R, I_FORE_L, (0, 160, 255)), (I_TOP, I_CHIN, (0, 0, 255))):
                    cv2.line(img, tuple(P[a].astype(int)), tuple(P[b].astype(int)), col, 2)
                for i in (I_TOP, I_CHIN, I_CHEEK_R, I_CHEEK_L, I_JAW_R, I_JAW_L, I_FORE_R, I_FORE_L):
                    cv2.circle(img, tuple(P[i].astype(int)), 4, (255, 255, 255), -1)
        if annotate:
            label = "%s %.2f [%s]" % (res["face_shape"] or "-", res["confidence"], res["status"])
            cv2.rectangle(img, (0, 0), (w, 30), (255, 255, 255), -1)
            cv2.putText(img, label, (6, 22), 0, 0.7, (0, 0, 200) if res["status"] == "reject" else (0, 120, 0), 2)
            for k, msg in enumerate(res["issues"][:3]):
                cv2.putText(img, msg[:70], (6, h - 8 - 18 * k), 0, 0.5, (0, 0, 255), 1)
            return res, img
        return res


# ----------------------------------------------------------------------------- command line
def iter_inputs(a):
    if a.db:
        con = sqlite3.connect("file:%s?mode=ro" % a.db, uri=True)               # read-only
        for pid, blob in con.execute('SELECT "%s", "%s" FROM "%s"' % (a.id_col, a.blob_col, a.table)):
            if blob:
                yield str(pid), cv2.imdecode(np.frombuffer(blob, np.uint8), cv2.IMREAD_COLOR)
        return
    for p in a.paths:
        files = sorted(f for ext in ("jpg", "jpeg", "png", "webp") for f in glob.glob(os.path.join(p, "*." + ext))) \
            if os.path.isdir(p) else [p]
        for f in files:
            yield os.path.basename(f), cv2.imread(f)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--db"); ap.add_argument("--table"); ap.add_argument("--id-col"); ap.add_argument("--blob-col")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--stats", action="store_true", help="print the spread of measurements (to tune PROTOTYPES)")
    ap.add_argument("--out", default=os.path.join(HERE, "output"))
    a = ap.parse_args()
    if not a.paths and not (a.db and a.table and a.id_col and a.blob_col):
        sys.exit(__doc__)
    det = FaceShapeDetector()
    os.makedirs(os.path.join(a.out, "faces"), exist_ok=True)
    results = []
    for n, (name, im) in enumerate(iter_inputs(a), 1):
        if a.limit and n > a.limit:
            break
        if im is None:
            r = {"status": "reject", "issues": ["Unreadable image"], "face_shape": None}
            img = None
        else:
            r, img = det.analyze(im, annotate=True)
        r["id"] = name
        results.append(r)
        if img is not None:
            cv2.imwrite(os.path.join(a.out, "faces", "%s.jpg" % os.path.splitext(name)[0].replace(os.sep, "_")), img)
        print("%-30s %-7s %-8s %s %s" % (name[:30], r["status"], r.get("face_shape"), r.get("confidence", ""), "; ".join(r["issues"])[:80]))
    json.dump(results, open(os.path.join(a.out, "face_shapes.json"), "w"), indent=2)
    if a.stats:
        good = [r for r in results if r["status"] != "reject"]
        if good:
            print("\nMeasurements over %d usable photos (10% / 50% / 90%):" % len(good))
            for k in ("length_cheek", "jaw_cheek", "fore_jaw", "chin_angle"):
                v = np.array([r["measurements"][k] for r in good])
                print("  %-13s %.2f / %.2f / %.2f" % (k, *np.quantile(v, [0.1, 0.5, 0.9])))
            from collections import Counter
            print("  shapes:", dict(Counter(r["face_shape"] for r in good)))
    ok = sum(r["status"] != "reject" for r in results)
    print("\n%d photos: %d usable, %d rejected.  JSON: %s" % (len(results), ok, len(results) - ok, os.path.join(a.out, "face_shapes.json")))
