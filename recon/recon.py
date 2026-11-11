"""Phase 1 reconnaissance. Minimal, polite, robots.txt-first. Not yet run."""
import json
import re
import sys
import time
import urllib.robotparser as rp

import requests
from bs4 import BeautifulSoup

BASE = "https://dukpion.com.bd"
UA = "DukpionResearchBot/0.1 (contact: wtsappbckup2024@gmail.com)"  
DELAY = 5  # seconds between requests

headers = {"User-Agent": UA}
report = {"base": BASE}


def get(url):
    time.sleep(DELAY)
    return requests.get(url, headers=headers, timeout=30)


# 1. robots.txt
r = get(f"{BASE}/robots.txt")
report["robots_status"] = r.status_code
report["robots_txt"] = r.text[:5000] if r.ok else None
parser = rp.RobotFileParser()
parser.parse(r.text.splitlines() if r.ok else [])
allowed = parser.can_fetch(UA, f"{BASE}/")
report["homepage_allowed_by_robots"] = allowed
report["crawl_delay"] = parser.crawl_delay(UA)
sitemaps = parser.site_maps() or []
report["declared_sitemaps"] = sitemaps

if not allowed:
    print("robots.txt disallows this user agent. STOP. Do not scrape.")
    print("Consider contacting the site owner for permission or a data feed.")
    json.dump(report, open("recon_report.json", "w"), indent=2)
    sys.exit(0)

# 2. Homepage (one request)
h = get(BASE + "/")
report["home_status"] = h.status_code
html = h.text
soup = BeautifulSoup(html, "lxml")
report["platform_hints"] = {
    "generator_meta": (soup.find("meta", attrs={"name": "generator"}) or {}).get("content"),
    "shopify": "cdn.shopify.com" in html,
    "woocommerce": "wp-content/plugins/woocommerce" in html,
    "next_data": bool(soup.find("script", id="__NEXT_DATA__")),
    "json_ld_blocks": len(soup.find_all("script", type="application/ld+json")),
    "server_header": h.headers.get("Server"),
    "powered_by": h.headers.get("X-Powered-By"),
}
report["nav_links"] = sorted(
    {a["href"] for a in soup.select("nav a[href], header a[href]")}
)[:200]
report["category_like_links"] = sorted(
    {a["href"] for a in soup.find_all("a", href=True)
     if re.search(r"categor|collection|shop|/c/", a["href"], re.I)}
)[:200]

# 3. Sitemaps (declared ones only, first 20 URLs of each as a sample)
report["sitemap_samples"] = {}
for sm in sitemaps[:5]:
    if parser.can_fetch(UA, sm):
        s = get(sm)
        report["sitemap_samples"][sm] = re.findall(r"<loc>(.*?)</loc>", s.text)[:20]

json.dump(report, open("recon_report.json", "w"), indent=2, ensure_ascii=False)
print("Saved recon_report.json")
