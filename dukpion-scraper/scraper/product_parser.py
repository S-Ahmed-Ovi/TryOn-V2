"""Parse a /product/<slug> HTML page (used as fallback and for cross-checking the JSON).

Selectors were taken from a real saved page:
  name        -> <h1>
  main image  -> img#product-main-image
  gallery     -> button.product-gallery-thumb[data-src]   (first thumb repeats the main image)
  description -> the div right under <h2>Description</h2>
The <meta name="description"> is truncated by the site and is NOT used.
"""
from __future__ import annotations

from bs4 import BeautifulSoup
from pydantic import BaseModel

from processors.normalizer import (
    ImageRef, absolute_image_url, html_to_text, strip_boilerplate,
)


class ParsedPage(BaseModel):
    name: str | None = None
    description_raw: str | None = None
    description: str | None = None
    description_clean: str | None = None
    has_boilerplate: bool = False
    images: list[ImageRef] = []


def parse_product_page(html_text: str, base_url: str) -> ParsedPage:
    soup = BeautifulSoup(html_text, "lxml")
    h1 = soup.find("h1")
    page = ParsedPage(name=h1.get_text(" ", strip=True) if h1 else None)

    # description: container following the "Description" heading
    for h in soup.find_all(["h2", "h3"]):
        if h.get_text(strip=True).lower() == "description":
            box = h.find_next_sibling("div")
            if box:
                raw = box.decode_contents()
                page.description_raw = raw
                page.description = html_to_text(raw)
                page.description_clean, page.has_boilerplate = strip_boilerplate(page.description)
            break

    # images: main first, then thumbnails; de-duplicate keeping order
    seen: set[str] = set()

    def add(path: str | None, kind: str) -> None:
        if not path:
            return
        url = absolute_image_url(base_url, path)
        if url not in seen:
            seen.add(url)
            page.images.append(ImageRef(image_url=url, image_type=kind))

    main = soup.find("img", id="product-main-image")
    add(main.get("src") if main else None, "main")
    for btn in soup.select("button.product-gallery-thumb"):
        add(btn.get("data-src") or (btn.find("img") or {}).get("src"), "gallery")
    if page.images and page.images[0].image_type != "main":
        page.images[0].image_type = "main"
    return page
