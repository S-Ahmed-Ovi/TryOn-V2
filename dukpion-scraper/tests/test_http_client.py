import pytest
import requests
from config.settings import Settings
from scraper.http_client import AccessBlocked, HttpClient, OutOfScope, RobotsDisallowed

S = Settings(request_delay_min=0, request_delay_max=0, backoff_base=0, max_retries=2)


class Resp:
    def __init__(self, code=200, text="ok", headers=None):
        self.status_code, self.text = code, text
        self.headers = headers or {"Content-Type": "text/html"}


class FakeSession:
    def __init__(self, script):
        self.script, self.headers, self.urls = list(script), {}, []

    def get(self, url, headers=None, timeout=None):
        self.urls.append(url)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def make(script, sleeps=None):
    rec = sleeps if sleeps is not None else []
    return HttpClient(S, FakeSession([Resp(404)] + script), sleep=rec.append), rec


def test_missing_robots_means_no_restrictions():
    c, _ = make([Resp(200, "hello")])
    assert c.get("https://dukpion.com.bd/x").text == "hello"


def test_robots_disallow_is_obeyed():
    robots = Resp(200, "User-agent: *\nDisallow: /category/", {"Content-Type": "text/plain"})
    c = HttpClient(S, FakeSession([robots]), sleep=lambda s: None)
    with pytest.raises(RobotsDisallowed):
        c.get("https://dukpion.com.bd/category/eyeglasses")


def test_403_stops_without_retry():
    c, _ = make([Resp(403)])
    with pytest.raises(AccessBlocked):
        c.get("https://dukpion.com.bd/x")
    assert len(c.session.urls) == 2  # robots + one attempt, no retry


def test_captcha_page_stops():
    c, _ = make([Resp(200, "<div class='g-recaptcha'></div>")])
    with pytest.raises(AccessBlocked):
        c.get("https://dukpion.com.bd/x")


def test_429_honours_retry_after_then_succeeds():
    c, sleeps = make([Resp(429, headers={"Retry-After": "7", "Content-Type": "text/html"}), Resp(200, "fine")])
    assert c.get("https://dukpion.com.bd/x").text == "fine"
    assert 7 in sleeps


def test_retry_after_is_capped():
    c, sleeps = make([Resp(429, headers={"Retry-After": "99999"}), Resp(200)])
    c.get("https://dukpion.com.bd/x")
    assert max(sleeps) <= S.max_retry_after


def test_network_error_retries_then_gives_up():
    errs = [requests.ConnectionError("boom")] * 3
    c, _ = make(errs)
    with pytest.raises(Exception) as e:
        c.get("https://dukpion.com.bd/x")
    assert "network error" in str(e.value)
    assert len(c.session.urls) == 1 + 3  # robots + (1 try + 2 retries)


def test_5xx_then_success():
    c, _ = make([Resp(503), Resp(200, "back")])
    assert c.get("https://dukpion.com.bd/x").text == "back"


def test_other_hosts_refused():
    c, _ = make([])
    with pytest.raises(OutOfScope):
        c.get("https://example.com/x")


def test_real_pages_do_not_trigger_captcha_detector():
    from conftest import FIX
    from scraper.http_client import CAPTCHA_MARKERS
    for name in ("home", "category_eyeglasses", "product_real"):
        low = (FIX / f"{name}.html").read_text(encoding="utf-8").lower()
        assert not any(m in low for m in CAPTCHA_MARKERS), name


def test_per_call_delay_override_and_robots_crawl_delay_floor():
    import random
    random.seed(1)
    c, sleeps = make([Resp(200)])
    c.get("https://dukpion.com.bd/img.jpg", delay=(1.5, 3.0))
    assert 1.5 <= sleeps[-1] <= 3.0
    c2 = HttpClient(S, FakeSession([Resp(200, "User-agent: *\nCrawl-delay: 10", {"Content-Type": "text/plain"}), Resp(200)]),
                    sleep=sleeps.append)
    c2.get("https://dukpion.com.bd/img.jpg", delay=(1.5, 3.0))
    assert sleeps[-1] >= 10            # robots.txt crawl-delay is never undercut
