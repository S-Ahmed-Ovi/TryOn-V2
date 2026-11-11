"""Turn raw site data into clean, typed records. Never rewrites or invents content."""
from __future__ import annotations

import html
import json
import re
from urllib.parse import urljoin

from pydantic import BaseModel


class ImageRef(BaseModel):
    image_url: str
    image_type: str  # "main" | "gallery"


class ProductRecord(BaseModel):
    product_id: str          # site numeric id, as string
    slug: str
    sku: str | None = None
    product_name: str
    description_raw: str | None = None   # exactly as served (HTML)
    description: str | None = None       # plain text of the ORIGINAL, line breaks kept
    description_clean: str | None = None  # derived: legacy page boilerplate removed
    has_boilerplate: bool = False
    images: list[ImageRef] = []
    source_url: str
    updated_at: str | None = None


_BR = re.compile(r"<\s*br\s*/?\s*>", re.I)
_TAGS = re.compile(r"<[^>]+>")


def html_to_text(raw: str | None) -> str | None:
    """<br> -> newline, strip tags, unescape entities. Returns None if empty."""
    if raw is None:
        return None
    text = _BR.sub("\n", raw)
    text = _TAGS.sub("", text)
    text = html.unescape(text).replace("\r\n", "\n").replace("\r", "\n")
    lines = [ln.strip() for ln in text.split("\n")]
    text = "\n".join(ln for ln in lines if ln)
    return text or None


# Legacy (WordPress-era) records contain scraped page UI after the real description.
_BOILERPLATE_START = re.compile(r"^\s*(rating\s*&\s*review|question\s*&\s*answer)\b", re.I)


def strip_boilerplate(text: str | None) -> tuple[str | None, bool]:
    """Cut the text at the first legacy UI heading. Returns (clean_text, was_cut)."""
    if not text:
        return text, False
    kept: list[str] = []
    for line in text.split("\n"):
        if _BOILERPLATE_START.match(line):
            clean = "\n".join(kept).strip()
            return (clean or None), True
        kept.append(line)
    return text, False


def parse_gallery(value) -> list[str]:
    """`gallery` arrives as a JSON string inside JSON (or None/list). Never raises."""
    if value in (None, "", "null"):
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    if not isinstance(value, list):
        return []
    return [p for p in value if isinstance(p, str) and p.strip()]


def absolute_image_url(base_url: str, path: str) -> str:
    # `image` has a leading slash, `gallery` entries do not: normalise both.
    return urljoin(base_url + "/", path.strip().replace("\\/", "/").lstrip("/"))


def product_from_listing(item: dict, base_url: str) -> ProductRecord | None:
    """Build a ProductRecord from one object of the category JSON."""
    slug = (item.get("slug") or "").strip()
    name = (item.get("name") or "").strip()
    if not slug or not name or item.get("id") is None:
        return None
    images: list[ImageRef] = []
    seen: set[str] = set()

    def add(path: str | None, kind: str) -> None:
        if not path:
            return
        url = absolute_image_url(base_url, path)
        if url not in seen:
            seen.add(url)
            images.append(ImageRef(image_url=url, image_type=kind))

    add(item.get("image"), "main")
    for p in parse_gallery(item.get("gallery")):
        add(p, "gallery")

    raw = item.get("description")
    text = html_to_text(raw)
    clean, cut = strip_boilerplate(text)
    return ProductRecord(
        product_id=str(item["id"]),
        slug=slug,
        sku=item.get("sku"),
        product_name=name,
        description_raw=raw,
        description=text,
        description_clean=clean,
        has_boilerplate=cut,
        images=images,
        source_url=f"{base_url}/product/{slug}",
        updated_at=item.get("updated_at"),
    )
