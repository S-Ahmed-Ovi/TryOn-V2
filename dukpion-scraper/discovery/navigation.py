"""Find category links in navigation HTML."""
from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

_CAT = re.compile(r"^/category/([^/?#]+)/?$")


def extract_category_slugs(html_text: str, base_url: str) -> list[str]:
    """Unique category slugs (sorted) from every <a href> on the page."""
    soup = BeautifulSoup(html_text, "lxml")
    host = urlparse(base_url).netloc
    slugs: set[str] = set()
    for a in soup.find_all("a", href=True):
        parsed = urlparse(urljoin(base_url + "/", a["href"]))
        if parsed.netloc and parsed.netloc != host:
            continue
        m = _CAT.match(parsed.path)
        if m:
            slugs.add(m.group(1).lower())
    return sorted(slugs)
