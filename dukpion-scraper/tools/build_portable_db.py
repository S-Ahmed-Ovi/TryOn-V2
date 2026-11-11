"""Build ONE self-contained SQLite file: products + descriptions + the image bytes.

    python -m tools.build_portable_db            # writes dataset/dukpion_portable.db
    python -m tools.build_portable_db --overwrite

Reads dataset/dukpion.db and dataset/images/ (never modifies them, never uses the network).
Every image file is checked against its stored SHA-256 before it is embedded.
"""
from __future__ import annotations

import argparse
import hashlib
import sqlite3
import sys
from collections import Counter
from pathlib import Path

SCHEMA = """
CREATE TABLE products (
  product_id        TEXT PRIMARY KEY,
  product_name      TEXT NOT NULL,
  sku               TEXT,
  description       TEXT,          -- original text; NULL when the shop has none
  description_clean TEXT,          -- same text without legacy page boilerplate
  source_url        TEXT NOT NULL,
  scraped_at        TEXT NOT NULL
);
CREATE TABLE images (
  image_id        INTEGER PRIMARY KEY,
  product_id      TEXT NOT NULL REFERENCES products(product_id),
  image_type      TEXT NOT NULL,   -- main | gallery
  position        INTEGER NOT NULL,
  original_url    TEXT NOT NULL,
  download_status TEXT NOT NULL,   -- downloaded | failed | invalid | pending
  mime_type       TEXT,
  width           INTEGER,
  height          INTEGER,
  sha256          TEXT,
  image_data      BLOB,            -- NULL unless download_status = 'downloaded'
  UNIQUE (product_id, original_url)
);
CREATE INDEX ix_images_product ON images(product_id);
CREATE VIEW product_summary AS
  SELECT p.product_id, p.product_name, p.sku, p.description_clean,
         COALESCE(SUM(i.download_status = 'downloaded'), 0) AS images_ok,
         COALESCE(SUM(i.download_status <> 'downloaded'), 0) AS images_missing
  FROM products p LEFT JOIN images i ON i.product_id = p.product_id
  GROUP BY p.product_id;
"""
MIME = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


def build(data_dir: Path, out: Path, overwrite: bool = False) -> dict:
    src_path = data_dir / "dukpion.db"
    if not src_path.exists():
        raise FileNotFoundError(f"{src_path} not found. Run --mode full first.")
    if out.exists():
        if not overwrite:
            raise FileExistsError(f"{out} already exists (use --overwrite)")
        out.unlink()

    src = sqlite3.connect(src_path)
    dst = sqlite3.connect(out)
    dst.executescript(SCHEMA)
    problems: list[str] = []
    embedded = embedded_bytes = 0

    for p in src.execute("SELECT id, product_name, sku, description, description_clean, source_url, "
                         "scraped_at FROM products ORDER BY CAST(id AS INTEGER)"):
        dst.execute("INSERT INTO products VALUES (?,?,?,?,?,?,?)", p)

    rows = src.execute("SELECT product_id, image_type, position, original_url, download_status, local_path, "
                       "image_hash, format, width, height FROM images "
                       "ORDER BY CAST(product_id AS INTEGER), position").fetchall()
    for n, (pid, itype, pos, url, status, path, sha, fmt, w, h) in enumerate(rows, 1):
        blob = None
        if status == "downloaded":
            f = data_dir / path if path else None
            if not f or not f.exists():
                problems.append(f"product {pid}: file missing on disk: {path}")
                status = "failed"
            else:
                data = f.read_bytes()
                if hashlib.sha256(data).hexdigest() != sha:
                    problems.append(f"product {pid}: hash mismatch, not embedded: {path}")
                    status = "failed"
                else:
                    blob = data
                    embedded += 1
                    embedded_bytes += len(data)
        dst.execute("INSERT INTO images (product_id, image_type, position, original_url, download_status, "
                    "mime_type, width, height, sha256, image_data) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (pid, itype, pos, url, status, MIME.get(fmt) if blob else None,
                     w if blob else None, h if blob else None, sha if blob else None, blob))
        if n % 300 == 0:
            dst.commit()
    dst.commit()

    breakdown = Counter(dict(((s, e or "-"), c) for s, e, c in src.execute(
        "SELECT download_status, error, COUNT(*) FROM images GROUP BY 1, 2")))
    summary = {
        "products": dst.execute("SELECT COUNT(*) FROM products").fetchone()[0],
        "images_rows": len(rows),
        "images_embedded": embedded,
        "embedded_mb": round(embedded_bytes / 1e6, 1),
        "products_with_no_image": dst.execute(
            "SELECT COUNT(*) FROM product_summary WHERE images_ok = 0").fetchone()[0],
        "status_breakdown": {f"{s} / {e}": c for (s, e), c in sorted(breakdown.items())},
        "problems": problems,
    }
    dst.execute("VACUUM")
    summary["integrity_check"] = dst.execute("PRAGMA integrity_check").fetchone()[0]
    dst.close(); src.close()
    summary["file_mb"] = round(out.stat().st_size / 1e6, 1)
    return summary


def main() -> int:
    from config.settings import load_settings
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path)
    ap.add_argument("--overwrite", action="store_true")
    a = ap.parse_args()
    s = load_settings()
    out = a.out or s.data_dir / "dukpion_portable.db"
    try:
        r = build(s.data_dir, out, a.overwrite)
    except (FileNotFoundError, FileExistsError) as exc:
        print(exc)
        return 1
    print(f"Saved {out}  ({r['file_mb']} MB, integrity: {r['integrity_check']})")
    print(f"Products: {r['products']} | image rows: {r['images_rows']} | embedded: {r['images_embedded']} "
          f"({r['embedded_mb']} MB of image data)")
    print(f"Products with NO usable image: {r['products_with_no_image']}")
    print("Status breakdown:")
    for k, v in r["status_breakdown"].items():
        print(f"   {k}: {v}")
    if r["problems"]:
        print(f"{len(r['problems'])} problems (first 10):")
        for p in r["problems"][:10]:
            print("  -", p)
    return 0


if __name__ == "__main__":
    sys.exit(main())
