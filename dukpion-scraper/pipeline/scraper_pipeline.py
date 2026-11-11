"""Glue: discovery.json -> database -> image downloads -> JSON export."""
from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path
from typing import Callable

from config.settings import Settings
from database.repository import Repository
from images.deduplicator import HashIndex
from images.downloader import download_product_images
from processors.normalizer import ImageRef, ProductRecord, strip_boilerplate

log = logging.getLogger(__name__)


def load_discovery(path: Path) -> list[ProductRecord]:
    data = json.loads(path.read_text(encoding="utf-8"))
    records = []
    for p in data["products"]:
        rec = ProductRecord(**p)
        # derived fields are recomputed so older discovery files work too
        rec.description_clean, rec.has_boilerplate = strip_boilerplate(rec.description)
        records.append(rec)
    return records


def ingest(repo: Repository, records: list[ProductRecord]) -> Counter:
    return Counter(repo.upsert_product(r) for r in records)


def build_index(repo: Repository) -> HashIndex:
    """Rehydrate duplicate tracking from what is already stored."""
    idx = HashIndex()
    for r in repo.downloaded_rows():
        idx.register(r.original_url, r.image_hash, r.local_path,
                     {"format": r.format, "width": r.width, "height": r.height})
    return idx


def download_all(client, s: Settings, repo: Repository, index: HashIndex, product_ids: list[str],
                 retry_failed: bool = False,
                 on_product: Callable[[str], None] | None = None) -> Counter:
    """Download what is still needed. Each result is saved to the DB immediately, so an
    interruption (or AccessBlocked) loses nothing. Exceptions from `client` propagate."""
    counts: Counter = Counter()
    for pid in product_ids:
        todo = repo.images_to_download(pid, retry_failed)
        if todo:
            full = repo.image_refs(pid)
            for res in download_product_images(client, s, pid, full, index,
                                               only={t.original_url for t in todo}):
                repo.record_result(pid, res)
                counts[res.status] += 1
        if on_product:
            on_product(pid)
    return counts
