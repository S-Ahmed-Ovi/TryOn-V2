import json
from conftest import FIX
from config.settings import Settings
from discovery.categories import classify
from discovery.navigation import extract_category_slugs
from discovery.products import crawl_category, merge_unique, parse_listing_json
from processors.normalizer import html_to_text, parse_gallery, product_from_listing

BASE = "https://dukpion.com.bd"


def read(name):
    return (FIX / name).read_text(encoding="utf-8")


def test_nav_finds_categories_without_duplicates():
    slugs = extract_category_slugs(read("home.html"), BASE)
    assert len(slugs) == len(set(slugs)) >= 30
    assert "eyeglasses" in slugs and "sunglasses" in slugs


def test_classify_eyewear_only():
    slugs = extract_category_slugs(read("home.html"), BASE)
    plan = classify(slugs, Settings())
    for s in ("eyeglasses", "sunglasses", "sunglass", "designer-eyewear", "50-off-eyeglass",
              "nav-sunglasses-womens", "nav-eyeglasses-kids"):
        assert s in plan.included, s
    for s in ("accessories", "box-amp-cleaner", "contact-lens", "optical-lens"):
        assert s in plan.skipped, s
    # ambiguous promo/lens categories are skipped but reported, not silently lost
    assert {"50-off", "all-offers", "free-frame", "photochromic", "blue-cut-glass"} <= set(plan.skipped)


def test_extra_and_exclude_overrides():
    s = Settings(extra_category_slugs=frozenset({"photochromic"}),
                 exclude_category_slugs=frozenset({"sunglass"}))
    plan = classify(["photochromic", "sunglass", "eyeglasses"], s)
    assert plan.included == ["photochromic", "eyeglasses"] and plan.skipped == ["sunglass"]


def test_parse_real_listing_json():
    records, meta = parse_listing_json(read("category_p2_ajax.json"), BASE)
    assert meta["page"] == 2 and meta["total_pages"] == 26 and meta["has_more"] is True
    assert len(records) == 24
    p = records[0]
    assert p.product_id == "2912" and p.sku == "DKE013118"
    assert p.source_url == f"{BASE}/product/{p.slug}"
    assert p.images[0].image_type == "main"
    assert p.images[0].image_url == f"{BASE}/uploads/products/15a84e9575d5f32c.jpg"
    assert [i.image_type for i in p.images] == ["main", "gallery", "gallery", "gallery"]
    assert p.images[1].image_url == f"{BASE}/uploads/products/64b9cfbc232daf59.jpg"
    assert p.description.splitlines()[0] == "SKU: DKE013118"
    assert "<br>" in p.description_raw          # original preserved untouched
    assert len({i.image_url for i in p.images}) == len(p.images)


def test_helpers_never_raise_on_bad_data():
    assert parse_gallery(None) == [] and parse_gallery("not json") == [] and parse_gallery("{}") == []
    assert html_to_text(None) is None and html_to_text(" <br> ") is None
    assert product_from_listing({"id": 1, "name": "", "slug": "x"}, BASE) is None
    r = product_from_listing({"id": 5, "name": "A", "slug": "a", "description": None,
                              "image": None, "gallery": None}, BASE)
    assert r.description is None and r.images == []


def test_merge_unique_dedupes_across_categories():
    records, _ = parse_listing_json(read("category_p2_ajax.json"), BASE)
    from discovery.products import CategoryResult
    a = CategoryResult("a", products=records)
    b = CategoryResult("b", products=records[:5])
    assert len(merge_unique([a, b])) == 24


class FakeClient:
    """Serves pages of the real fixture with a changing `page`/`has_more`."""
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def get(self, url, headers=None):
        self.calls.append(url)
        n = int(url.rsplit("=", 1)[1])
        data = json.loads(read("category_p2_ajax.json"))
        data.update(page=n, total_pages=self.pages, has_more=n < self.pages)
        for i, prod in enumerate(data["products"]):  # make ids unique per page
            prod["id"] = n * 1000 + i
            prod["slug"] = f"p{n}-{i}"

        class R:
            status_code = 200
            text = json.dumps(data)
            def raise_for_status(self): pass
        return R()


def test_pagination_stops_at_has_more_false():
    c = FakeClient(pages=3)
    res = crawl_category(c, Settings(), "eyeglasses")
    assert res.pages_fetched == 3 and len(c.calls) == 3
    assert len(res.products) == 72 and not res.errors
    assert c.calls[0].endswith("/category/eyeglasses?page=1")


def test_pagination_safety_cap():
    c = FakeClient(pages=999)
    s = Settings(max_pages_per_category=4)
    res = crawl_category(c, s, "eyeglasses")
    assert res.pages_fetched == 4 and res.errors
