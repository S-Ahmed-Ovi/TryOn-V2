"""Walk a category's pages via the site's own JSON listing and collect products."""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field

from config.settings import Settings
from processors.normalizer import ProductRecord, product_from_listing
from scraper.http_client import HttpClient

log = logging.getLogger(__name__)
AJAX = {"X-Requested-With": "XMLHttpRequest", "Accept": "application/json"}


@dataclass
class CategoryResult:
    slug: str
    pages_fetched: int = 0
    total_pages_reported: int | None = None
    listing_items: int = 0
    products: list[ProductRecord] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def parse_listing_json(text: str, base_url: str) -> tuple[list[ProductRecord], dict]:
    data = json.loads(text)
    items = data.get("products") or []
    records = [r for r in (product_from_listing(i, base_url) for i in items) if r]
    meta = {
        "page": data.get("page"),
        "total_pages": data.get("total_pages"),
        "has_more": bool(data.get("has_more")),
        "n_items": len(items),
    }
    return records, meta


def crawl_category(client: HttpClient, s: Settings, slug: str) -> CategoryResult:
    result = CategoryResult(slug=slug)
    page = 1
    while page <= s.max_pages_per_category:
        url = f"{s.base_url}/category/{slug}?page={page}"
        resp = client.get(url, headers=AJAX)
        if resp.status_code == 404:
            result.errors.append(f"404 for {url}")
            break
        resp.raise_for_status()
        try:
            records, meta = parse_listing_json(resp.text, s.base_url)
        except (json.JSONDecodeError, AttributeError) as exc:
            msg = f"page {page} of {slug}: response is not the expected JSON ({exc})"
            log.error(msg)
            result.errors.append(msg)
            break
        result.pages_fetched += 1
        result.listing_items += meta["n_items"]
        result.total_pages_reported = meta["total_pages"]
        result.products.extend(records)
        log.info("%s page %s/%s: %d products", slug, page, meta["total_pages"], len(records))
        if not meta["has_more"] or meta["n_items"] == 0:
            break
        page += 1
    else:
        result.errors.append(f"hit max_pages_per_category={s.max_pages_per_category}")
    return result


def merge_unique(results: list[CategoryResult]) -> dict[str, ProductRecord]:
    """Deduplicate by product id across categories (first seen wins)."""
    unique: dict[str, ProductRecord] = {}
    for r in results:
        for p in r.products:
            unique.setdefault(p.product_id, p)
    return unique
