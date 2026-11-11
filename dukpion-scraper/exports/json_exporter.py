"""products.json export and DB/JSON/disk consistency verification."""
from __future__ import annotations

import json
from pathlib import Path

from database.repository import Repository
from images.deduplicator import sha256_hex


def build_export(repo: Repository, only_downloaded: bool = False) -> list[dict]:
    out = []
    for p, imgs in repo.products_with_images():
        if only_downloaded:
            imgs = [i for i in imgs if i.download_status == "downloaded"]
            if not imgs:
                continue
        out.append({
            "product_id": p.id,
            "product_name": p.product_name,
            "description": p.description,              # original text; null when unavailable
            "description_clean": p.description_clean,  # derived (additive)
            "sku": p.sku,
            "images": [{
                "image_url": i.original_url,           # original URL, preserved
                "local_path": i.local_path,            # null unless really downloaded
                "image_type": i.image_type,
                "download_status": i.download_status,  # additive
                "image_hash": i.image_hash,            # SHA-256 (additive)
            } for i in imgs],
            "source_url": p.source_url,
            "scraped_at": p.scraped_at,
        })
    return out


def export_json(repo: Repository, path: Path, only_downloaded: bool = False) -> int:
    data = build_export(repo, only_downloaded)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return len(data)


def verify(repo: Repository, data_dir: Path, json_path: Path, only_downloaded: bool = False) -> list[str]:
    """Return a list of problems (empty list = consistent)."""
    problems: list[str] = []
    exported = {p["product_id"]: p for p in json.loads(json_path.read_text(encoding="utf-8"))}
    expected = {p["product_id"]: p for p in build_export(repo, only_downloaded)}
    if set(exported) != set(expected):
        problems.append(f"product sets differ: json={len(exported)} db={len(expected)}")
    for pid, e in expected.items():
        j = exported.get(pid)
        if j is None:
            continue
        if j != e:
            problems.append(f"product {pid}: JSON differs from database")
        for img in e["images"]:
            path, status, h = img["local_path"], img["download_status"], img["image_hash"]
            if status == "downloaded":
                f = data_dir / path if path else None
                if not f or not f.exists():
                    problems.append(f"product {pid}: file missing on disk: {path}")
                elif sha256_hex(f.read_bytes()) != h:
                    problems.append(f"product {pid}: hash mismatch: {path}")
            elif path is not None or h is not None:
                problems.append(f"product {pid}: non-downloaded image has path/hash: {img['image_url']}")
    return problems
