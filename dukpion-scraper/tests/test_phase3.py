from conftest import FIX
from processors.normalizer import product_from_listing, strip_boilerplate
from scraper.product_parser import parse_product_page
from tools.crosscheck import compare, pick_sample

BASE = "https://dukpion.com.bd"


def test_parse_real_product_page():
    p = parse_product_page((FIX / "product_real.html").read_text(encoding="utf-8"), BASE)
    assert p.name == "Black Color Double Bridge Stylish Sunglass"
    assert [i.image_url.rsplit("/", 1)[1] for i in p.images] == [
        "b7f4642e17dffb54.jpg", "755b89b927c06ff1.jpg", "bb18140136aef8ca.jpg", "b9c82f03d2c2320c.jpg"]
    assert [i.image_type for i in p.images] == ["main", "gallery", "gallery", "gallery"]
    assert p.description.splitlines()[0] == "SKU: DKS013007"
    assert "Lens Features: Polarized & UV400" in p.description      # entity decoded
    assert "Related" not in p.description and not p.has_boilerplate


def test_related_products_images_are_excluded():
    p = parse_product_page((FIX / "product_real.html").read_text(encoding="utf-8"), BASE)
    assert len(p.images) == 4  # page lists 12 /uploads/ images, 8 belong to related products


LEGACY = ("SKU:DKECR0270\nSize:52-21-148mm\nFrame Color\nBlack, Golden, Mixed\nFrame Shape\nRound\n"
          "Rating & Review\nBased on 0 Reviews\nWrite a review\nQuestion & Answer\n0 Questions")


def test_boilerplate_cut_keeps_real_attributes():
    clean, cut = strip_boilerplate(LEGACY)
    assert cut and clean.endswith("Round") and "Review" not in clean
    assert strip_boilerplate("SKU: X\nSize: 1") == ("SKU: X\nSize: 1", False)
    assert strip_boilerplate(None) == (None, False)


def test_listing_keeps_original_and_adds_clean():
    r = product_from_listing({"id": 1, "slug": "a", "name": "A",
                              "description": LEGACY.replace("\n", "<br>")}, BASE)
    assert "Rating & Review" in r.description          # original untouched
    assert r.has_boilerplate and "Rating" not in r.description_clean


def _rec(**kw):
    base = {"slug": "s", "product_name": "N", "description": "A\nB", "has_boilerplate": False,
            "images": [{"image_url": f"{BASE}/uploads/products/a.jpg", "image_type": "main"}]}
    base.update(kw)
    return base


def test_compare_detects_differences():
    page = parse_product_page((FIX / "product_real.html").read_text(encoding="utf-8"), BASE)
    res = compare(_rec(product_name=page.name, description=page.description,
                       images=[i.model_dump() for i in page.images]), page)
    assert res["name_match"] and res["description"] == "match" and res["main_match"]
    assert not res["images_only_in_json"] and not res["images_only_in_page"]
    res = compare(_rec(product_name="Other", description="zzz"), page)
    assert not res["name_match"] and res["description"] == "differs"
    assert len(res["images_only_in_page"]) == 4 and res["images_only_in_json"]


def test_pick_sample_is_diverse_and_deterministic():
    prods = []
    for i in range(60):
        imgs = [{"image_url": f"{BASE}/uploads/products/{i}-{k}.jpg", "image_type": "gallery"} for k in range(4)]
        prods.append(_rec(slug=f"p{i}", images=imgs))
    prods[3]["description"] = None
    prods[5]["images"] = [{"image_url": f"{BASE}/wp-content/uploads/x.jpg", "image_type": "main"}]
    prods[9]["description"] = "A\nRating & Review"
    prods[11]["images"] = prods[11]["images"][:1]
    prods[13]["images"] += prods[13]["images"][:2] + [{"image_url": "u5", "image_type": "gallery"}]
    a = pick_sample(prods, 8)
    assert a == pick_sample(prods, 8) and len({s["slug"] for _, s in a}) == 8
    kinds = {k for k, _ in a}
    assert {"no description", "legacy wp-content image", "boilerplate in text", "single image"} <= kinds
