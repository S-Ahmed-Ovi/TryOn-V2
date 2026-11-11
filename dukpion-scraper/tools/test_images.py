"""Phase 4 test: download the images of the cross-checked sample products.

    python -m tools.test_images

Uses reports/crosscheck.json (from tools.crosscheck) to pick products. Files go to
dataset/images/<product_id>/ exactly like the final run will, so they are reused later.
"""
from __future__ import annotations

import json
import sys
from collections import Counter

from rich.console import Console
from rich.table import Table

from config.logging_config import setup_logging
from config.settings import load_settings
from images.deduplicator import HashIndex
from images.downloader import download_product_images
from processors.normalizer import ImageRef
from scraper.http_client import AccessBlocked, HttpClient, RobotsDisallowed

console = Console()


def main() -> int:
    s = load_settings()
    setup_logging(s.log_dir)
    if s.has_placeholder_contact:
        console.print("[yellow]Set DUKPION_USER_AGENT in .env first.[/yellow]")
        return 1
    disc = json.loads((s.data_dir / "discovery.json").read_text(encoding="utf-8"))
    by_slug = {p["slug"]: p for p in disc["products"]}
    slugs = [r["slug"] for r in json.loads((s.report_dir / "crosscheck.json").read_text(encoding="utf-8"))]
    client, index = HttpClient(s), HashIndex()
    rows, table = [], Table(title="Image download test")
    for c in ("Product", "Type", "Status", "Fmt", "WxH", "KB", "SHA-256", "Note"):
        table.add_column(c)
    try:
        for slug in slugs:
            p = by_slug[slug]
            refs = [ImageRef(**i) for i in p["images"]]
            for r in download_product_images(client, s, p["product_id"], refs, index):
                rows.append({"slug": slug, "product_id": p["product_id"], **r.model_dump()})
                table.add_row(p["product_id"], r.image_type, r.status, r.format or "-",
                              f"{r.width}x{r.height}" if r.width else "-",
                              f"{(r.size_bytes or 0) / 1024:.0f}", (r.sha256 or "-")[:10],
                              r.error or (f"dup of {r.duplicate_of}" if r.duplicate_of else ""))
    except (AccessBlocked, RobotsDisallowed) as exc:
        console.print(f"[bold red]STOPPED:[/bold red] {exc}")
        return 2
    s.report_dir.mkdir(parents=True, exist_ok=True)
    (s.report_dir / "image_test.json").write_text(json.dumps(rows, indent=2), encoding="utf-8")
    console.print(table)
    console.print("Status counts:", dict(Counter(r["status"] for r in rows)))
    dims = [(r["width"], r["height"]) for r in rows if r["width"]]
    if dims:
        console.print(f"Smallest: {min(dims, key=lambda d: d[0]*d[1])}  Largest: {max(dims, key=lambda d: d[0]*d[1])}")
    console.print(f"Requests: {client.request_count} | files in {s.data_dir / 'images'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
