"""Download product images: validate, hash, never alter, never fake success."""
from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

from pydantic import BaseModel

from config.settings import Settings
from images.deduplicator import HashIndex, sha256_hex
from images.validator import ALLOWED, validate_image_bytes
from processors.normalizer import ImageRef
from scraper.http_client import (  # AccessBlocked / RobotsDisallowed deliberately not caught
    HttpClient, OutOfScope, TransientError,
)

log = logging.getLogger(__name__)
STATUSES = ("downloaded", "skipped_existing", "copied_same_url", "failed", "invalid")


class ImageResult(BaseModel):
    image_url: str
    image_type: str
    status: str                      # one of STATUSES
    local_path: str | None = None    # relative to dataset dir, forward slashes
    sha256: str | None = None
    format: str | None = None
    width: int | None = None
    height: int | None = None
    size_bytes: int | None = None
    duplicate_of: str | None = None  # local_path of an earlier byte-identical file
    error: str | None = None


def _rel(s: Settings, path: Path) -> str:
    return path.relative_to(s.data_dir).as_posix()


def _existing(dest_dir: Path, stem: str) -> Path | None:
    for ext in ALLOWED.values():
        p = dest_dir / f"{stem}.{ext}"
        if p.exists():
            return p
    return None


def download_image(client: HttpClient, s: Settings, ref: ImageRef, dest_dir: Path,
                   stem: str, index: HashIndex) -> ImageResult:
    base = dict(image_url=ref.image_url, image_type=ref.image_type)

    # 1. already on disk and valid -> do not download again
    have = _existing(dest_dir, stem)
    if have:
        data = have.read_bytes()
        v = validate_image_bytes(data)
        if v.ok:
            sha = sha256_hex(data)
            dup = index.register(ref.image_url, sha, _rel(s, have), {})
            return ImageResult(**base, status="skipped_existing", local_path=_rel(s, have), sha256=sha,
                               format=v.format, width=v.width, height=v.height,
                               size_bytes=len(data), duplicate_of=dup)
        log.warning("existing file %s is invalid; re-downloading", have)
        have.unlink()

    # 2. same URL already fetched earlier in this run -> copy, don't refetch
    cached = index.by_url.get(ref.image_url)
    if cached:
        src = s.data_dir / cached["local_path"]
        if src.exists():
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / f"{stem}{src.suffix}"
            shutil.copy2(src, dest)
            dup = index.register(ref.image_url, cached["sha256"], _rel(s, dest), {})
            return ImageResult(**base, status="copied_same_url", local_path=_rel(s, dest),
                               sha256=cached["sha256"], format=cached.get("format"),
                               width=cached.get("width"), height=cached.get("height"),
                               size_bytes=dest.stat().st_size, duplicate_of=dup)

    # 3. fetch (AccessBlocked / RobotsDisallowed propagate so the run stops)
    try:
        resp = client.get(ref.image_url, headers={"Accept": "image/*"},
                          delay=(s.image_delay_min, s.image_delay_max))
    except (TransientError, OutOfScope) as exc:
        return ImageResult(**base, status="failed", error=str(exc)[:200])
    if resp.status_code != 200:
        return ImageResult(**base, status="failed", error=f"HTTP {resp.status_code}")

    data = resp.content
    v = validate_image_bytes(data)
    if not v.ok:
        ctype = resp.headers.get("Content-Type", "?")
        return ImageResult(**base, status="invalid", error=f"{v.error} (Content-Type {ctype})")

    # 4. store atomically under the REAL format's extension; bytes untouched
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = dest_dir / f"{stem}.{v.ext}"
    part = final.with_suffix(final.suffix + ".part")
    part.write_bytes(data)
    os.replace(part, final)
    sha = sha256_hex(data)
    info = dict(format=v.format, width=v.width, height=v.height)
    dup = index.register(ref.image_url, sha, _rel(s, final), info)
    return ImageResult(**base, status="downloaded", local_path=_rel(s, final), sha256=sha,
                       format=v.format, width=v.width, height=v.height, size_bytes=len(data),
                       duplicate_of=dup)


def download_product_images(client: HttpClient, s: Settings, product_id: str,
                            images: list[ImageRef], index: HashIndex,
                            only: set[str] | None = None) -> list[ImageResult]:
    """File names come from each image's position in the FULL list, so they stay stable
    even when only a subset (`only` = set of URLs) is processed."""
    dest_dir = s.data_dir / "images" / str(product_id)
    results, n_gallery = [], 0
    for ref in images:
        if ref.image_type == "main":
            stem = "main"
        else:
            n_gallery += 1
            stem = f"gallery_{n_gallery:03d}"
        if only is None or ref.image_url in only:
            results.append(download_image(client, s, ref, dest_dir, stem, index))
    return results
