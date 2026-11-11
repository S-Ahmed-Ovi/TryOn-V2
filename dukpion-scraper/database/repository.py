"""All database reads/writes. Every write commits immediately (crash-safe progress)."""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import sessionmaker

from database.models import Image, Product
from images.downloader import ImageResult
from processors.normalizer import ImageRef, ProductRecord

PERMANENT_ERRORS = ("HTTP 404", "HTTP 410")
_OK = {"downloaded", "skipped_existing", "copied_same_url"}


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def db_status(result_status: str) -> str:
    return "downloaded" if result_status in _OK else result_status  # failed | invalid


class Repository:
    def __init__(self, sf: sessionmaker) -> None:
        self.sf = sf

    # ---- products -----------------------------------------------------------
    def upsert_product(self, rec: ProductRecord) -> str:
        """Returns 'new' | 'updated' | 'unchanged'. Never duplicates products or images."""
        fields = dict(
            product_name=rec.product_name, description=rec.description,
            description_raw=rec.description_raw, description_clean=rec.description_clean,
            has_boilerplate=rec.has_boilerplate, source_url=rec.source_url, slug=rec.slug,
            sku=rec.sku, site_updated_at=rec.updated_at,
        )
        with self.sf() as s, s.begin():
            row = s.get(Product, rec.product_id)
            if row is None:
                row = Product(id=rec.product_id, scraped_at=utcnow(), **fields)
                s.add(row)
                outcome = "new"
            else:
                changed = {}
                for k, v in fields.items():
                    if k == "description_raw" and v is None:
                        continue  # record doesn't carry raw HTML: keep what is stored
                    if getattr(row, k) != v:
                        changed[k] = v
                if changed:
                    for k, v in changed.items():
                        setattr(row, k, v)
                    row.scraped_at = utcnow()
                outcome = "updated" if changed else "unchanged"
            known = {i.original_url for i in row.images}
            for pos, img in enumerate(rec.images):
                if img.image_url not in known:
                    row.images.append(Image(original_url=img.image_url, image_type=img.image_type,
                                            position=pos, download_status="pending"))
                    if outcome == "unchanged":
                        outcome = "updated"
            return outcome

    # ---- images -------------------------------------------------------------
    def images_to_download(self, product_id: str, retry_failed: bool = False) -> list[Image]:
        """pending always; failed/invalid only when retryable (404/410 are permanent)."""
        with self.sf() as s:
            rows = s.scalars(select(Image).where(Image.product_id == product_id)
                             .order_by(Image.position)).all()
        out = []
        for r in rows:
            if r.download_status == "pending":
                out.append(r)
            elif r.download_status in ("failed", "invalid"):
                permanent = (r.error or "").startswith(PERMANENT_ERRORS) or r.download_status == "invalid"
                if retry_failed or not permanent:
                    out.append(r)
        return out

    def image_refs(self, product_id: str) -> list[ImageRef]:
        """The product's full ordered image list (used for stable file naming)."""
        with self.sf() as s:
            rows = s.scalars(select(Image).where(Image.product_id == product_id)
                             .order_by(Image.position)).all()
        return [ImageRef(image_url=r.original_url, image_type=r.image_type) for r in rows]

    def record_result(self, product_id: str, res: ImageResult) -> None:
        with self.sf() as s, s.begin():
            row = s.scalar(select(Image).where(Image.product_id == product_id,
                                               Image.original_url == res.image_url))
            if row is None:
                raise KeyError(f"unknown image {res.image_url} for product {product_id}")
            row.download_status = db_status(res.status)
            row.local_path = res.local_path
            row.image_hash = res.sha256
            row.format, row.width, row.height = res.format, res.width, res.height
            row.size_bytes, row.duplicate_of, row.error = res.size_bytes, res.duplicate_of, res.error
            row.updated_at = utcnow()

    def downloaded_rows(self) -> list[Image]:
        with self.sf() as s:
            return list(s.scalars(select(Image).where(Image.download_status == "downloaded")))

    # ---- reads --------------------------------------------------------------
    def product_ids(self) -> list[str]:
        with self.sf() as s:
            return sorted(s.scalars(select(Product.id)), key=int)

    def products_with_images(self) -> list[tuple[Product, list[Image]]]:
        with self.sf() as s:
            prods = s.scalars(select(Product)).all()
            out = [(p, list(p.images)) for p in prods]
        return sorted(out, key=lambda t: int(t[0].id))

    def stats(self) -> dict:
        with self.sf() as s:
            n_prod = s.scalar(select(func.count()).select_from(Product))
            by_status = Counter(dict(s.execute(
                select(Image.download_status, func.count()).group_by(Image.download_status)).all()))
            dups = s.scalar(select(func.count()).select_from(Image).where(Image.duplicate_of.is_not(None)))
            no_desc = s.scalar(select(func.count()).select_from(Product).where(Product.description.is_(None)))
        return {"products": n_prod, "images": sum(by_status.values()), "by_status": dict(by_status),
                "duplicate_images": dups, "products_without_description": no_desc}
