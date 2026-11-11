"""Central, configurable settings. Values come from environment / .env."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Tiny .env loader (avoids an extra dependency). Real env vars win."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def _csv(name: str) -> frozenset[str]:
    raw = os.environ.get(name, "")
    return frozenset(s.strip().lower() for s in raw.split(",") if s.strip())


@dataclass(frozen=True)
class Settings:
    base_url: str = "https://dukpion.com.bd"  # apex host: the TLS cert does not cover www
    user_agent: str = "DukpionResearchBot/0.1 (contact: you@example.com)"
    request_delay_min: float = 3.0
    request_delay_max: float = 6.0
    max_retries: int = 3
    request_timeout: float = 30.0
    max_concurrent_requests: int = 2  # reserved; image downloading is sequential
    # Images are static files on the same host. Sequential, with its own delay range.
    image_delay_min: float = 1.5
    image_delay_max: float = 3.0
    backoff_base: float = 2.0  # seconds; exponential backoff multiplier
    max_retry_after: float = 300.0  # never sleep longer than this for Retry-After
    max_pages_per_category: int = 200  # safety stop, real limit comes from the site
    # Only these categories are scraped: slug must match this pattern ...
    eyewear_pattern: str = r"eyeglass|sunglass|eyewear"
    # ... or be listed here explicitly
    extra_category_slugs: frozenset[str] = field(default_factory=frozenset)
    exclude_category_slugs: frozenset[str] = field(default_factory=frozenset)
    data_dir: Path = ROOT / "dataset"
    log_dir: Path = ROOT / "logs"
    report_dir: Path = ROOT / "reports"

    @property
    def host(self) -> str:
        return re.sub(r"^https?://", "", self.base_url).rstrip("/")

    @property
    def has_placeholder_contact(self) -> bool:
        return "you@example.com" in self.user_agent


def load_settings() -> Settings:
    _load_dotenv(ROOT / ".env")
    e = os.environ.get
    d = Settings()
    return Settings(
        base_url=e("DUKPION_BASE_URL", d.base_url).rstrip("/"),
        user_agent=e("DUKPION_USER_AGENT", d.user_agent),
        request_delay_min=float(e("DUKPION_REQUEST_DELAY_MIN", d.request_delay_min)),
        request_delay_max=float(e("DUKPION_REQUEST_DELAY_MAX", d.request_delay_max)),
        max_retries=int(e("DUKPION_MAX_RETRIES", d.max_retries)),
        request_timeout=float(e("DUKPION_REQUEST_TIMEOUT", d.request_timeout)),
        image_delay_min=float(e("DUKPION_IMAGE_DELAY_MIN", d.image_delay_min)),
        image_delay_max=float(e("DUKPION_IMAGE_DELAY_MAX", d.image_delay_max)),
        max_concurrent_requests=int(e("DUKPION_MAX_CONCURRENT_REQUESTS", d.max_concurrent_requests)),
        extra_category_slugs=_csv("DUKPION_EXTRA_CATEGORY_SLUGS"),
        exclude_category_slugs=_csv("DUKPION_EXCLUDE_CATEGORY_SLUGS"),
    )
