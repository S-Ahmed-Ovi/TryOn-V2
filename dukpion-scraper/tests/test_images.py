import io

import pytest
from PIL import Image

from config.settings import Settings
from images.deduplicator import HashIndex
from images.downloader import download_image, download_product_images
from images.validator import validate_image_bytes
from processors.normalizer import ImageRef
from scraper.http_client import AccessBlocked, TransientError


def img_bytes(fmt="JPEG", size=(40, 30), color=(200, 10, 10)):
    buf = io.BytesIO()
    Image.new("RGB", size, color).save(buf, fmt)
    return buf.getvalue()


class Resp:
    def __init__(self, code=200, content=b"", ctype="image/jpeg"):
        self.status_code, self.content, self.headers = code, content, {"Content-Type": ctype}


class FakeClient:
    def __init__(self, routes):
        self.routes, self.calls = routes, []

    def get(self, url, headers=None, delay=None):
        self.calls.append(url)
        r = self.routes[url]
        if isinstance(r, Exception):
            raise r
        return r


@pytest.fixture
def S(tmp_path):
    return Settings(data_dir=tmp_path)


def ref(u, t="main"):
    return ImageRef(image_url=f"https://dukpion.com.bd/uploads/{u}", image_type=t)


def test_validator_accepts_three_formats_and_reports_size():
    for fmt, ext in (("JPEG", "jpg"), ("PNG", "png"), ("WEBP", "webp")):
        v = validate_image_bytes(img_bytes(fmt))
        assert v.ok and v.ext == ext and (v.width, v.height) == (40, 30)


def test_validator_rejects_bad_data():
    assert not validate_image_bytes(b"").ok
    assert not validate_image_bytes(b"<html>blocked</html>").ok
    assert not validate_image_bytes(img_bytes()[:-200]).ok               # truncated
    buf = io.BytesIO(); Image.new("RGB", (5, 5)).save(buf, "GIF")
    v = validate_image_bytes(buf.getvalue()); assert not v.ok and "unsupported" in v.error


def test_product_download_names_and_layout(S):
    a, b, c = img_bytes(color=(1, 1, 1)), img_bytes(color=(2, 2, 2)), img_bytes(color=(3, 3, 3))
    refs = [ref("m.jpg"), ref("g1.jpg", "gallery"), ref("g2.jpg", "gallery")]
    cl = FakeClient({r.image_url: Resp(content=x) for r, x in zip(refs, (a, b, c))})
    res = download_product_images(cl, S, "42", refs, HashIndex())
    assert [r.local_path for r in res] == ["images/42/main.jpg", "images/42/gallery_001.jpg", "images/42/gallery_002.jpg"]
    assert all(r.status == "downloaded" for r in res)
    assert (S.data_dir / "images/42/main.jpg").read_bytes() == a          # bytes untouched
    assert not list(S.data_dir.rglob("*.part"))


def test_failures_are_never_marked_downloaded(S):
    refs = [ref("404.jpg"), ref("html.jpg", "gallery"), ref("net.jpg", "gallery"), ref("empty.jpg", "gallery")]
    cl = FakeClient({refs[0].image_url: Resp(404), refs[1].image_url: Resp(200, b"<html>", "text/html"),
                     refs[2].image_url: TransientError("timeout"), refs[3].image_url: Resp(200, b"")})
    res = download_product_images(cl, S, "7", refs, HashIndex())
    assert [r.status for r in res] == ["failed", "invalid", "failed", "invalid"]
    assert all(r.local_path is None and r.error for r in res)
    assert not (S.data_dir / "images").exists() or not list((S.data_dir / "images").rglob("*.*"))


def test_png_content_gets_png_extension(S):
    r = ref("x.jpg"); cl = FakeClient({r.image_url: Resp(content=img_bytes("PNG"), ctype="image/png")})
    res = download_image(cl, S, r, S.data_dir / "images/1", "main", HashIndex())
    assert res.local_path == "images/1/main.png" and res.format == "PNG"


def test_existing_valid_file_is_not_redownloaded(S):
    r = ref("m.jpg"); data = img_bytes()
    cl = FakeClient({r.image_url: Resp(content=data)})
    download_product_images(cl, S, "9", [r], HashIndex())
    res = download_product_images(cl, S, "9", [r], HashIndex())
    assert res[0].status == "skipped_existing" and len(cl.calls) == 1


def test_corrupt_existing_file_is_replaced(S):
    r = ref("m.jpg"); d = S.data_dir / "images/9"; d.mkdir(parents=True)
    (d / "main.jpg").write_bytes(b"garbage")
    cl = FakeClient({r.image_url: Resp(content=img_bytes())})
    assert download_product_images(cl, S, "9", [r], HashIndex())[0].status == "downloaded"


def test_same_url_in_two_products_fetched_once_and_flagged(S):
    r = ref("shared.jpg"); cl = FakeClient({r.image_url: Resp(content=img_bytes())}); idx = HashIndex()
    a = download_product_images(cl, S, "1", [r], idx)[0]
    b = download_product_images(cl, S, "2", [r], idx)[0]
    assert len(cl.calls) == 1 and b.status == "copied_same_url"
    assert b.duplicate_of == a.local_path and (S.data_dir / b.local_path).exists()


def test_identical_bytes_at_different_urls_flagged_as_duplicate(S):
    data = img_bytes(); r1, r2 = ref("a.jpg"), ref("b.jpg", "gallery")
    cl = FakeClient({r1.image_url: Resp(content=data), r2.image_url: Resp(content=data)})
    a, b = download_product_images(cl, S, "3", [r1, r2], HashIndex())
    assert a.duplicate_of is None and b.duplicate_of == a.local_path and a.sha256 == b.sha256


def test_access_blocked_propagates_and_stops(S):
    r = ref("x.jpg"); cl = FakeClient({r.image_url: AccessBlocked("403")})
    with pytest.raises(AccessBlocked):
        download_product_images(cl, S, "1", [r], HashIndex())
