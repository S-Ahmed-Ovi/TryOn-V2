"""Phase 1c: one product page + category page 2 (HTML and JSON). Not yet run."""
import json, time
from pathlib import Path
import requests

BASE = "https://dukpion.com.bd"
UA = "DukpionResearchBot/0.1 (contact: YOUR_EMAIL_HERE)"  # edit this
DELAY = 5
OUT = Path("recon/samples"); OUT.mkdir(parents=True, exist_ok=True)

def get(url, extra=None):
    time.sleep(DELAY)
    h = {"User-Agent": UA, **(extra or {})}
    r = requests.get(url, headers=h, timeout=30)
    print(r.status_code, r.headers.get("Content-Type"), url)
    return r

r = get(f"{BASE}/product/black-color-double-bridge-stylish-sunglass")
(OUT / "product_real.html").write_text(r.text, encoding="utf-8")

r = get(f"{BASE}/category/eyeglasses?page=2")
(OUT / "category_p2_plain.html").write_text(r.text, encoding="utf-8")

r = get(f"{BASE}/category/eyeglasses?page=2", {"X-Requested-With": "XMLHttpRequest"})
(OUT / "category_p2_ajax.txt").write_text(r.text, encoding="utf-8")
print("done")