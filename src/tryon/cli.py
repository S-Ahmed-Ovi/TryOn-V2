"""Command line:  tryon run | build | doctor | analyze <photo> | models3d generate|add"""
from __future__ import annotations

import argparse
import sys
import webbrowser

from tryon import __version__


def _run(args) -> int:
    import threading

    import uvicorn

    from tryon.api.app import create_app
    from tryon.config import load_settings

    s = load_settings()
    host, port = args.host or s.host, args.port or s.port
    url = f"http://{'localhost' if host in ('0.0.0.0', '127.0.0.1') else host}:{port}"
    print(f"Starting {s.site_name} at {url}   (Ctrl+C to stop)")
    if not args.no_browser:
        threading.Timer(2.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(create_app(s), host=host, port=port, log_level="warning")
    return 0


def _build(args) -> int:
    from tryon.catalog.builder import BuildError, build_catalog
    from tryon.config import load_settings

    try:
        build_catalog(load_settings(), force=args.force)
    except BuildError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


def _doctor(_args) -> int:
    import shutil

    from tryon.catalog.builder import is_current, read_catalog_json, read_manifest
    from tryon.config import FACE_MODEL_PATH, WEB_DIR, load_settings

    s = load_settings()
    ok = True

    def line(good: bool, text: str, fix: str = "") -> None:
        nonlocal ok
        ok &= good
        print(("  ok    " if good else "  FAIL  ") + text + (f"\n        -> {fix}" if not good and fix else ""))

    print(f"TryOn {__version__}   project folder: {s.home}")
    line(sys.version_info >= (3, 10), f"Python {sys.version.split()[0]}", "Use Python 3.10 - 3.12")
    line(FACE_MODEL_PATH.is_file(), "face model file", "Restore src/tryon/assets/models/face_landmarker.task")
    try:
        manifest = read_manifest(s)
        glbs = [m for m in manifest["models"] if (s.models_dir / m["file"]).is_file()]
        line(len(glbs) == len(manifest["models"]), f"3D models ({len(glbs)} of {len(manifest['models'])} files present)",
             "Run: tryon models3d generate")
        current = is_current(s, manifest)
    except Exception as exc:  # noqa: BLE001
        line(False, f"3D models: {exc}", "Run: tryon models3d generate")
        current = False
    cat = read_catalog_json(s.catalog_json)
    line(bool(cat), f"2D catalogue ({len(cat['products']) if cat else 0} frames)", "Run: tryon build")
    print(("  ok    " if current else "  info  ") + ("catalogue matches the 3D models" if current else "catalogue is older than the 3D models (run: tryon build)"))
    line((WEB_DIR / "static" / "js" / "soft3d" / "engine.js").is_file(), "3D renderer (CPU, no GPU or WebGL needed)", "Reinstall the project")
    node = shutil.which("node") or shutil.which("nodejs")
    print(("  ok    " if node else "  info  ") + ("Node.js found (only needed to re-render 2D pictures after changing models)" if node
                                                else "Node.js not found (optional: only needed to re-render 2D pictures after changing models)"))
    try:
        from tryon.vision.landmarks import FaceLandmarker
        FaceLandmarker().close()
        line(True, "face model loads")
    except Exception as exc:  # noqa: BLE001
        line(False, f"face model failed to load: {exc}", "Reinstall: pip install -e .")
    return 0 if ok else 1


def _analyze(args) -> int:
    import cv2

    from tryon.catalog.store import load_catalog
    from tryon.config import load_settings
    from tryon.recommend.engine import make_profile, recommend
    from tryon.recommend.rules import load_rules
    from tryon.vision.face_shape import FaceShapeDetector

    img = cv2.imread(args.photo)
    if img is None:
        print(f"Cannot read {args.photo}", file=sys.stderr)
        return 1
    det = FaceShapeDetector()
    a = det.analyze(img)
    det.close()
    for i in a.issues:
        print(f"[{i.level}] {i.message}")
    if a.status == "reject":
        return 1
    print(f"Face shape: {a.shape} (confidence {a.confidence:.0%}){'  - please confirm' if a.needs_confirmation else ''}")
    rules, cat = load_rules(), load_catalog(load_settings())
    for m in recommend(rules, cat.products, make_profile(a.shape, a.probabilities, a.measurements))[: args.top]:
        print(f"  {m.percent:>3}%  {m.product.sku:<11} {m.product.frame_shape:<10} {m.product.name}")
    return 0


def _models3d(args) -> int:
    from tryon.config import load_settings

    s = load_settings()
    if args.action == "generate":
        from tryon.models3d.generator import generate_all
        generate_all(s.models_dir)
        print("Now run:  tryon build   (renders the 2D pictures and refreshes the catalogue)")
        return 0
    from tryon.models3d.importer import ImportError_, import_model
    try:
        rec = import_model(s, args.file, sku=args.sku, name=args.name, frame_shape=args.shape, audience=args.audience,
                           color_name=args.color, color_hex=args.color_hex, lens_name=args.lens, lens_hex=args.lens_hex,
                           unit=args.unit, auto_center=not args.no_center)
    except ImportError_ as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(f"Added {rec['sku']} ({rec['name']}). Now run:  tryon build")
    return 0


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="tryon", description="Face-shape sunglasses recommendations with virtual try-on.")
    p.add_argument("--version", action="version", version=f"tryon {__version__}")
    sub = p.add_subparsers(dest="cmd")
    r = sub.add_parser("run", help="start the website (default)")
    r.add_argument("--host"), r.add_argument("--port", type=int)
    r.add_argument("--no-browser", action="store_true", help="do not open the browser")
    r.set_defaults(fn=_run)
    b = sub.add_parser("build", help="(re)build the 2D catalogue from the 3D models")
    b.add_argument("--force", action="store_true", help="rebuild even if nothing changed")
    b.set_defaults(fn=_build)
    m = sub.add_parser("models3d", help="make or add 3D sunglasses models")
    msub = m.add_subparsers(dest="action", required=True)
    msub.add_parser("generate", help="(re)generate the 24 built-in frames in data/models3d/")
    ad = msub.add_parser("add", help="add your own .glb model (see docs/ADDING_MODELS.md)")
    ad.add_argument("file", help="the .glb file")
    ad.add_argument("--sku", required=True), ad.add_argument("--name", required=True)
    ad.add_argument("--shape", required=True, help="oval | round | rectangle | square | wayfarer | cat-eye | aviator | geometric")
    ad.add_argument("--audience", default="unisex", choices=["men", "women", "kids", "unisex"])
    ad.add_argument("--color", default="Black", help="frame colour name"), ad.add_argument("--color-hex", default="#1a1a1a")
    ad.add_argument("--lens", default="Grey", help="lens colour name"), ad.add_argument("--lens-hex", default="#444444")
    ad.add_argument("--unit", choices=["m", "cm", "mm"], default="m", help="unit of the model file")
    ad.add_argument("--no-center", action="store_true", help="do not move the model's centre to the bridge")
    m.set_defaults(fn=_models3d)
    sub.add_parser("doctor", help="check the installation").set_defaults(fn=_doctor)
    a = sub.add_parser("analyze", help="analyse a photo from the terminal")
    a.add_argument("photo"), a.add_argument("--top", type=int, default=5)
    a.set_defaults(fn=_analyze)
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv or (argv[0].startswith("-") and argv[0] not in ("-h", "--help", "--version")):
        argv.insert(0, "run")                      # `tryon --port 9000` means `tryon run --port 9000`
    args = p.parse_args(argv)
    sys.exit(args.fn(args))
