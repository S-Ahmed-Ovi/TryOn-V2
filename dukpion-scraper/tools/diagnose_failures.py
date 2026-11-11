import json
from collections import Counter
from pathlib import Path

rows = json.loads(Path("reports/image_test.json").read_text(encoding="utf-8"))
failed = [r for r in rows if r["status"] == "failed"]
ok = [r for r in rows if r["status"] == "downloaded"]

def style(u):
    return "/wp-content/" if "/wp-content/" in u else "/uploads/products/" if "/uploads/products/" in u else "other"

print("failed by path style:", dict(Counter(style(r["image_url"]) for r in failed)))
print("ok by path style:    ", dict(Counter(style(r["image_url"]) for r in ok)))
print("\nFAILED URLs:")
for r in failed:
    print(" ", r["product_id"], r["image_type"], r["image_url"], "|", r["error"])
print("\nOK gallery URLs:")
for r in ok:
    if r["image_type"] == "gallery":
        print(" ", r["product_id"], r["image_url"])