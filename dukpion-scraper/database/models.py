"""SQLAlchemy models. Columns beyond the brief are additive (noted inline)."""
from __future__ import annotations

from sqlalchemy import (
    Boolean, CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

STATUSES = ("pending", "downloaded", "failed", "invalid")


class Base(DeclarativeBase):
    pass


class Product(Base):
    __tablename__ = "products"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)        # site product id
    product_name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)                 # original text (tags -> text)
    source_url: Mapped[str] = mapped_column(Text, nullable=False, unique=True)
    scraped_at: Mapped[str] = mapped_column(String(40), nullable=False)   # ISO 8601 UTC
    # additive columns
    slug: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    sku: Mapped[str | None] = mapped_column(String(64))
    description_raw: Mapped[str | None] = mapped_column(Text)            # original HTML, if known
    description_clean: Mapped[str | None] = mapped_column(Text)           # derived, boilerplate removed
    has_boilerplate: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    site_updated_at: Mapped[str | None] = mapped_column(String(40))

    images: Mapped[list["Image"]] = relationship(
        back_populates="product", order_by="Image.position", cascade="all, delete-orphan")


class Image(Base):
    __tablename__ = "images"
    __table_args__ = (
        UniqueConstraint("product_id", "original_url", name="uq_image_product_url"),
        CheckConstraint("download_status IN ('pending','downloaded','failed','invalid')",
                        name="ck_image_status"),
        Index("ix_images_hash", "image_hash"),
        Index("ix_images_status", "download_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), nullable=False)
    original_url: Mapped[str] = mapped_column(Text, nullable=False)
    local_path: Mapped[str | None] = mapped_column(Text)
    image_type: Mapped[str] = mapped_column(String(16), nullable=False)   # main | gallery
    image_hash: Mapped[str | None] = mapped_column(String(64))            # SHA-256
    download_status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    # additive columns
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    format: Mapped[str | None] = mapped_column(String(16))
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    size_bytes: Mapped[int | None] = mapped_column(Integer)
    duplicate_of: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[str | None] = mapped_column(String(40))

    product: Mapped[Product] = relationship(back_populates="images")
