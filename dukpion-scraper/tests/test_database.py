import io
import json

import pytest
from PIL import Image as PILImage
from sqlalchemy.exc import IntegrityError

from config.settings import Settings
from database.connection import init_db, make_engine
from database.models import Image, Product
from database.repository import Repository
from exports.json_exporter import build_export, export_json, verify
from images.downloader import ImageResult
from pipeline.scraper_pipeline import build_index, download_all, ingest, load_discovery
from processors.normalizer import ImageRef, ProductRecord
from scraper.http_client import AccessBlocked, TransientError

B = "https://dukpion.com.bd"


def jpg(color=(9, 9, 9)):
    b = io.BytesIO(); PILImage.new("RGB", (20, 20), color).save(b, "JPEG"); return b.getvalue()


def rec(pid="1", n_gallery=2, desc="SKU: A\nSize: 1", **kw):
    imgs = [ImageRef(image_url=f"{B}/uploads/{pid}-m.jpg", image_type="main")] + \
           [ImageRef(image_url=f"{B}/uploads/{pid}-g{k}.jpg", image_type="gallery") for k in range(n_gallery)]
    base = dict(product_id=pid, slug=f"p{pid}", sku=f"S{pid}", product_name=f"Name {pid}", description=desc,
                description_raw=None, images=imgs, source_url=f"{B}/product/p{pid}", updated_at="2026-01-01")
    base.update(kw)
    return ProductRecord(**base)


@pytest.fixture
def env(tmp_path):
    s = Settings(data_dir=tmp_path)
    return s, Repository(init_db(make_engine(tmp_path / "dukpion.db")))


class Resp:
    def __init__(self, code=200, content=b"", ctype="image/jpeg"):
        self.status_code, self.content, self.headers = code, content, {"Content-Type": ctype}


class Client:
    def __init__(self, routes=None, default=None):
        self.routes, self.default, self.calls = routes or {}, default, []
        self.request_count = 0

    def get(self, url, headers=None, delay=None):
        self.calls.append(url); self.request_count += 1
        r = self.routes.get(url, self.default)
        if isinstance(r, Exception):
            raise r
        return r


def test_upsert_is_idempotent_and_detects_change(env):
    _, repo = env
    assert repo.upsert_product(rec()) == "new"
    assert repo.upsert_product(rec()) == "unchanged"
    assert repo.upsert_product(rec(desc="changed text")) == "updated"
    assert repo.upsert_product(rec(n_gallery=3)) == "updated"        # new image appears
    st = repo.stats()
    assert st["products"] == 1 and st["images"] == 4                 # no duplicate rows


def test_raw_html_is_kept_when_later_record_lacks_it(env):
    _, repo = env
    repo.upsert_product(rec(description_raw="SKU: A<br>Size: 1"))
    repo.upsert_product(rec(description_raw=None))
    with repo.sf() as s:
        assert s.get(Product, "1").description_raw == "SKU: A<br>Size: 1"


def test_foreign_key_and_unique_constraints_enforced(env):
    _, repo = env
    with pytest.raises(IntegrityError), repo.sf() as s, s.begin():
        s.add(Image(product_id="999", original_url="u", image_type="main"))   # no such product
    repo.upsert_product(rec())
    with pytest.raises(IntegrityError), repo.sf() as s, s.begin():
        s.add(Image(product_id="1", original_url=f"{B}/uploads/1-m.jpg", image_type="main"))  # duplicate


def test_status_never_downloaded_without_success(env):
    _, repo = env
    repo.upsert_product(rec(n_gallery=0))
    repo.record_result("1", ImageResult(image_url=f"{B}/uploads/1-m.jpg", image_type="main",
                                        status="failed", error="HTTP 404"))
    row = repo.products_with_images()[0][1][0]
    assert row.download_status == "failed" and row.local_path is None and row.image_hash is None


def test_pipeline_end_to_end_resume_and_404_policy(env):
    s, repo = env
    ingest(repo, [rec("1"), rec("2", n_gallery=1)])
    routes = {f"{B}/uploads/1-m.jpg": Resp(content=jpg((1, 1, 1))),
              f"{B}/uploads/1-g0.jpg": Resp(404),                           # permanent
              f"{B}/uploads/1-g1.jpg": TransientError("timeout"),           # temporary
              f"{B}/uploads/2-m.jpg": Resp(content=jpg((2, 2, 2))),
              f"{B}/uploads/2-g0.jpg": Resp(content=jpg((3, 3, 3)))}
    c = Client(routes)
    counts = download_all(c, s, repo, build_index(repo), repo.product_ids())
    assert counts["downloaded"] == 3 and counts["failed"] == 2 and len(c.calls) == 5
    assert repo.stats()["by_status"] == {"downloaded": 3, "failed": 2}

    # rerun: downloaded skipped, 404 NOT retried, timeout IS retried
    c2 = Client({**routes, f"{B}/uploads/1-g1.jpg": Resp(content=jpg((4, 4, 4)))})
    download_all(c2, s, repo, build_index(repo), repo.product_ids())
    assert c2.calls == [f"{B}/uploads/1-g1.jpg"]
    # stable naming: failed gallery_001 leaves a gap, next file is gallery_002
    assert (s.data_dir / "images/1/gallery_002.jpg").exists() and not (s.data_dir / "images/1/gallery_001.jpg").exists()

    # --retry-failed retries the 404 as well
    c3 = Client(routes)
    download_all(c3, s, repo, build_index(repo), repo.product_ids(), retry_failed=True)
    assert c3.calls == [f"{B}/uploads/1-g0.jpg"]


def test_access_blocked_keeps_progress(env):
    s, repo = env
    ingest(repo, [rec("1", n_gallery=0), rec("2", n_gallery=0)])
    c = Client({f"{B}/uploads/1-m.jpg": Resp(content=jpg()), f"{B}/uploads/2-m.jpg": AccessBlocked("403")})
    with pytest.raises(AccessBlocked):
        download_all(c, s, repo, build_index(repo), repo.product_ids())
    assert repo.stats()["by_status"] == {"downloaded": 1, "pending": 1}


def test_export_structure_null_description_and_filter(env):
    s, repo = env
    ingest(repo, [rec("1", n_gallery=1, desc=None), rec("2", n_gallery=0)])
    c = Client({f"{B}/uploads/1-m.jpg": Resp(content=jpg()), f"{B}/uploads/1-g0.jpg": Resp(404),
                f"{B}/uploads/2-m.jpg": Resp(404)})
    download_all(c, s, repo, build_index(repo), repo.product_ids())
    data = build_export(repo)
    p1 = data[0]
    assert p1["description"] is None and p1["product_id"] == "1" and p1["scraped_at"]
    assert [i["download_status"] for i in p1["images"]] == ["downloaded", "failed"]
    assert p1["images"][0]["local_path"] == "images/1/main.jpg" and p1["images"][1]["local_path"] is None
    only = build_export(repo, only_downloaded=True)
    assert [p["product_id"] for p in only] == ["1"] and len(only[0]["images"]) == 1


def test_verify_detects_problems(env):
    s, repo = env
    ingest(repo, [rec("1", n_gallery=0)])
    download_all(Client({f"{B}/uploads/1-m.jpg": Resp(content=jpg())}), s, repo, build_index(repo), ["1"])
    out = s.data_dir / "products.json"
    export_json(repo, out)
    assert verify(repo, s.data_dir, out) == []
    (s.data_dir / "images/1/main.jpg").write_bytes(jpg((5, 5, 5)))          # tamper
    assert any("hash mismatch" in p for p in verify(repo, s.data_dir, out))
    (s.data_dir / "images/1/main.jpg").unlink()
    assert any("missing on disk" in p for p in verify(repo, s.data_dir, out))
    data = json.loads(out.read_text()); data[0]["product_name"] = "edited"; out.write_text(json.dumps(data))
    assert any("differs from database" in p for p in verify(repo, s.data_dir, out))


def test_load_discovery_recomputes_clean_description(tmp_path):
    legacy = "SKU: X\nRating & Review\nBased on 0 Reviews"
    prod = rec("5", desc=legacy).model_dump(exclude={"description_raw", "description_clean", "has_boilerplate"})
    p = tmp_path / "discovery.json"; p.write_text(json.dumps({"products": [prod]}))
    r = load_discovery(p)[0]
    assert r.has_boilerplate and r.description_clean == "SKU: X" and "Rating" in r.description
