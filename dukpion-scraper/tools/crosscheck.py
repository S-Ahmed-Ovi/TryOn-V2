"""Cross-check discovery.json (site JSON) against real product pages for a diverse sample.

    python -m tools.crosscheck --n 8

Makes ONE request per sampled product (polite delay, robots, etc. via HttpClient).
Writes reports/crosscheck.json and saves each fetched page to dataset/samples/.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from config.logging_config import setup_logging
from config.settings import load_settings
from scraper.http_client import AccessBlocked, HttpClient, RobotsDisallowed
from scraper.product_parser import parse_product_page

console = Console()


def norm(t: str | None) -> str:
    return " ".join((t or "").split())


def pick_sample(products: list[dict], n: int, seed: int = 7) -> list[tuple[str, dict]]:
    """Deterministic, diverse: each risky kind first, then random typical ones."""
    rnd = random.Random(seed)
    chosen: dict[str, tuple[str, dict]] = {}

    def take(label: str, pool: list[dict]) -> None:
        pool = [p for p in pool if p["slug"] not in chosen]
        if pool and len(chosen) < n:
            p = rnd.choice(pool)
            chosen[p["slug"]] = (label, p)

    take("no description", [p for p in products if not p.get("description")])
    take("legacy wp-content image", [p for p in products
                                     if any("/wp-content/" in i["image_url"] for i in p["images"])])
    take("boilerplate in text", [p for p in products if p.get("has_boilerplate")
                                 or "Rating & Review" in (p.get("description") or "")])
    take("single image", [p for p in products if len(p["images"]) == 1])
    take("5+ images", [p for p in products if len(p["images"]) >= 5])
    while len(chosen) < n:
        before = len(chosen)
        take("typical", products)
        if len(chosen) == before:
            break
    return list(chosen.values())


def compare(rec: dict, page) -> dict:
    json_imgs = [i["image_url"] for i in rec["images"]]
    page_imgs = [i.image_url for i in page.images]
    jd, pd_ = norm(rec.get("description")), norm(page.description)
    if jd == pd_:
        desc = "match" if jd else "both empty"
    elif not jd:
        desc = "page only"
    elif not pd_:
        desc = "json only"
    else:
        desc = "differs"
    return {
        "name_match": norm(rec["product_name"]) == norm(page.name),
        "description": desc,
        "images_json": len(json_imgs),
        "images_page": len(page_imgs),
        "images_only_in_json": sorted(set(json_imgs) - set(page_imgs)),
        "images_only_in_page": sorted(set(page_imgs) - set(json_imgs)),
        "main_match": bool(json_imgs and page_imgs and json_imgs[0] == page_imgs[0]),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=8)
    args = ap.parse_args()
    s = load_settings()
    setup_logging(s.log_dir)
    if s.has_placeholder_contact:
        console.print("[yellow]Set DUKPION_USER_AGENT in .env first.[/yellow]")
        return 1
    disc = json.loads((s.data_dir / "discovery.json").read_text(encoding="utf-8"))
    sample = pick_sample(disc["products"], args.n)
    client = HttpClient(s)
    out_dir = s.data_dir / "samples"
    out_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    try:
        for label, rec in sample:
            resp = client.get(rec["source_url"])
            (out_dir / f"{rec['slug']}.html").write_text(resp.text, encoding="utf-8")
            if resp.status_code != 200:
                rows.append({"slug": rec["slug"], "kind": label, "http": resp.status_code})
                continue
            res = compare(rec, parse_product_page(resp.text, s.base_url))
            rows.append({"slug": rec["slug"], "kind": label, "http": 200, **res})
    except (AccessBlocked, RobotsDisallowed) as exc:
        console.print(f"[bold red]STOPPED:[/bold red] {exc}")
        return 2

    s.report_dir.mkdir(parents=True, exist_ok=True)
    (s.report_dir / "crosscheck.json").write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    t = Table(title="JSON vs product page")
    for c in ("Kind", "Slug", "HTTP", "Name", "Desc", "Main img", "Imgs json/page"):
        t.add_column(c)
    for r in rows:
        if r["http"] != 200:
            t.add_row(r["kind"], r["slug"][:34], str(r["http"]), "-", "-", "-", "-")
            continue
        t.add_row(r["kind"], r["slug"][:34], "200", "ok" if r["name_match"] else "DIFF",
                  r["description"], "ok" if r["main_match"] else "DIFF",
                  f'{r["images_json"]}/{r["images_page"]}')
    console.print(t)
    console.print(f"Details: {s.report_dir / 'crosscheck.json'} | pages saved in {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
