"""Phase 1b: sample sitemap, one category page, one product page. Not yet run."""
import json, re, time
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://dukpion.com.bd"
UA = "DukpionResearchBot/0.1 (contact: wtsappbckup2024@gmail.com)"  # edit this
DELAY = 5
H = {"User-Agent": UA}
OUT = Path("recon/samples"); OUT.mkdir(parents=True, exist_ok=True)
report = {}

def get(url):
    time.sleep(DELAY)
    return requests.get(url, headers=H, timeout=30)

def json_blobs(soup):
    found = []
    for s in soup.find_all("script"):
        txt = (s.string or "").strip()
        if not txt:
            continue
        if s.get("type") in ("application/ld+json", "application/json") or \
           re.search(r"__NUXT__|__INITIAL_STATE__|window\.__\w+__|__NEXT_DATA__", txt[:300]):
            found.append({"type": s.get("type"), "id": s.get("id"), "preview": txt[:300]})
    return found

# 1. sitemaps (common locations)
report["sitemaps"] = {}
for p in ("/sitemap.xml", "/sitemap_index.xml"):
    r = get(BASE + p)
    report["sitemaps"][p] = {"status": r.status_code,
                             "sample": re.findall(r"<loc>(.*?)</loc>", r.text)[:15] if r.ok else None}

# 2. one category page
cat_url = f"{BASE}/category/eyeglasses"
r = get(cat_url)
(OUT / "category_eyeglasses.html").write_text(r.text, encoding="utf-8")
soup = BeautifulSoup(r.text, "lxml")
links = {urljoin(BASE, a["href"]) for a in soup.find_all("a", href=True)}
report["category"] = {
    "url": cat_url, "status": r.status_code,
    "pagination_links": sorted(l for l in links if re.search(r"[?&]page=|/page/\d+", l))[:20],
    "rel_next": [l.get("href") for l in soup.find_all("link", rel="next")],
    "non_category_links_with_img": sorted({
        urljoin(BASE, a["href"]) for a in soup.find_all("a", href=True)
        if a.find("img") and "/category/" not in a["href"]})[:30],
    "json_blobs": json_blobs(soup),
    "script_srcs": [s["src"] for s in soup.find_all("script", src=True)][:20],
}

# 3. one product page (first candidate)
cands = report["category"]["non_category_links_with_img"]
if cands:
    p_url = cands[0]
    r = get(p_url)
    (OUT / "product_sample.html").write_text(r.text, encoding="utf-8")
    ps = BeautifulSoup(r.text, "lxml")
    report["product"] = {
        "url": p_url, "status": r.status_code,
        "title": ps.title.string if ps.title else None,
        "og": {m.get("property"): m.get("content") for m in ps.find_all("meta", property=re.compile("^og:"))},
        "meta_description": (ps.find("meta", attrs={"name": "description"}) or {}).get("content"),
        "json_blobs": json_blobs(ps),
        "img_srcs": [i.get("src") or i.get("data-src") for i in ps.find_all("img")][:40],
        "headings": [h.get_text(strip=True) for h in ps.find_all(["h1", "h2", "h3"])][:20],
    }

Path("recon_report2.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
print("Saved recon_report2.json and recon/samples/*.html")