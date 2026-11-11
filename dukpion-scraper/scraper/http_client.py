"""Polite HTTP client: robots.txt, delays, backoff, 429/403 handling, host guard.

Policy (from the project brief):
- never rotate proxies/IPs, never bypass CAPTCHA or access controls
- 429  -> pause (Retry-After if present), then retry
- 403 or CAPTCHA page -> stop and raise AccessBlocked (caller must halt)
- network errors / 5xx -> exponential backoff, limited retries
- TLS verification is always on
"""
from __future__ import annotations

import logging
import random
import time
import urllib.robotparser
from typing import Callable
from urllib.parse import urlparse

import requests
from tenacity import (
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from config.settings import Settings

log = logging.getLogger(__name__)

CAPTCHA_MARKERS = (
    "g-recaptcha",
    "h-captcha",
    "cf-challenge",
    "captcha-delivery",
    "attention required! | cloudflare",
)


class AccessBlocked(RuntimeError):
    """403 or CAPTCHA detected. Scraping of the affected process must stop."""


class RobotsDisallowed(RuntimeError):
    """robots.txt forbids fetching this URL for our user agent."""


class OutOfScope(ValueError):
    """URL is not on the configured host."""


class TransientError(Exception):
    """Temporary failure worth retrying."""


class HttpClient:
    def __init__(
        self,
        settings: Settings,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.s = settings
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = settings.user_agent
        self._sleep = sleep
        self._robots = urllib.robotparser.RobotFileParser()
        self._robots_loaded = False
        self._crawl_delay: float | None = None
        self.request_count = 0

    # ---- robots.txt -------------------------------------------------------
    def load_robots(self) -> None:
        url = f"{self.s.base_url}/robots.txt"
        resp = self._raw_get(url, check_robots=False)
        if resp.status_code == 200:
            self._robots.parse(resp.text.splitlines())
            log.info("robots.txt loaded (%d bytes)", len(resp.text))
        elif resp.status_code in (404, 410):
            self._robots.parse([])  # no file => no declared restrictions
            log.info("robots.txt not found (%s): no restrictions declared", resp.status_code)
        else:
            # Unknown state: be conservative and refuse to continue.
            raise AccessBlocked(f"robots.txt returned HTTP {resp.status_code}; refusing to continue")
        self._crawl_delay = self._robots.crawl_delay(self.s.user_agent)
        self._robots_loaded = True

    def allowed(self, url: str) -> bool:
        return self._robots.can_fetch(self.s.user_agent, url)

    # ---- public GET -------------------------------------------------------
    def get(self, url: str, headers: dict[str, str] | None = None,
            delay: tuple[float, float] | None = None) -> requests.Response:
        if not self._robots_loaded:
            self.load_robots()
        self._check_scope(url)
        if not self.allowed(url):
            raise RobotsDisallowed(url)
        retrying = Retrying(
            stop=stop_after_attempt(self.s.max_retries + 1),
            wait=wait_exponential(multiplier=self.s.backoff_base, max=60),
            retry=retry_if_exception_type(TransientError),
            sleep=self._sleep,
            reraise=True,
        )
        return retrying(self._attempt, url, headers, delay)

    # ---- internals --------------------------------------------------------
    def _check_scope(self, url: str) -> None:
        if urlparse(url).netloc.lower() != self.s.host.lower():
            raise OutOfScope(f"{url} is not on {self.s.host}")

    def _delay(self, override: tuple[float, float] | None = None) -> float:
        base_lo, base_hi = override or (self.s.request_delay_min, self.s.request_delay_max)
        lo = max(base_lo, self._crawl_delay or 0)  # robots crawl-delay is always a floor
        hi = max(base_hi, lo)
        return random.uniform(lo, hi)

    def _raw_get(self, url: str, headers=None, check_robots: bool = True, delay=None) -> requests.Response:
        self._check_scope(url)
        self._sleep(self._delay(delay))
        self.request_count += 1
        try:
            return self.session.get(url, headers=headers, timeout=self.s.request_timeout)
        except (requests.ConnectionError, requests.Timeout) as exc:
            raise TransientError(f"network error for {url}: {exc}") from exc

    def _attempt(self, url: str, headers, delay=None) -> requests.Response:
        resp = self._raw_get(url, headers, delay=delay)
        code = resp.status_code
        if code == 429:
            wait = self._retry_after(resp)
            log.warning("HTTP 429 for %s: pausing %.0fs", url, wait)
            self._sleep(wait)
            raise TransientError("429 Too Many Requests")
        if code == 403:
            raise AccessBlocked(f"HTTP 403 for {url}. Stopping; do not work around this.")
        if code >= 500:
            raise TransientError(f"HTTP {code} for {url}")
        if code == 200 and "html" in resp.headers.get("Content-Type", "").lower():
            low = resp.text[:200_000].lower()
            if any(m in low for m in CAPTCHA_MARKERS):
                raise AccessBlocked(f"CAPTCHA/challenge detected at {url}. Stopping.")
        return resp

    def _retry_after(self, resp: requests.Response) -> float:
        raw = resp.headers.get("Retry-After", "")
        try:
            secs = float(raw)
        except ValueError:
            secs = 60.0  # HTTP-date form or missing: use a safe default
        return min(max(secs, 1.0), self.s.max_retry_after)
